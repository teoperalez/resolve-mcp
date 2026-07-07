from __future__ import annotations

"""Derive RBY Ultra Minimum Battles hold regions from RBYNewLayout events.

These regions are the visual sections where auto-editor micro-cuts should be
overridden by continuous source spans:

  - intro stats card
  - intro moveset card
  - post-battle data/tier cards
  - Champion post-battle tier card handoff into the final tierlist
  - final tierlist
  - member carousel start

The output is source-frame based so it can be applied to an auto-editor FCPXML
before Resolve import, or used as protected ranges for later cut analysis.

Example:
  python scripts/derive_rby_umb_hold_regions.py ^
    --events "%APPDATA%\\rbypc-frontend\\logs\\...\\events.json" ^
    --meta "%APPDATA%\\rbypc-frontend\\logs\\...\\meta.json" ^
    --source-video "E:\\Run\\part 2.mp4" ^
    --out "_data\\rby-umb-holds.json"
"""

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


@dataclass
class HoldRegion:
    label: str
    kind: str
    session_start_sec: float
    session_end_sec: float | None
    source_start_sec: float
    source_end_sec: float | None
    source_start_frame: int
    source_end_frame: int | None
    reason: str


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run_json(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"command failed: {cmd}")
    return json.loads(proc.stdout)


def ffprobe_format(path: Path) -> dict:
    return run_json([
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:format_tags=creation_time",
        "-of",
        "json",
        str(path),
    ]).get("format", {})


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def source_start_elapsed(meta_path: Path, source_video: Path) -> float:
    meta = load_json(meta_path)
    session_start = parse_dt(meta["startedAt"])
    tags = ffprobe_format(source_video).get("tags") or {}
    creation = tags.get("creation_time")
    if not creation:
        raise RuntimeError(f"No creation_time metadata in {source_video}")
    return (parse_dt(creation) - session_start).total_seconds()


def source_duration_sec(source_video: Path | None) -> float | None:
    if source_video is None:
        return None
    fmt = ffprobe_format(source_video)
    dur = fmt.get("duration")
    return float(dur) if dur else None


def event_sec(ev: dict) -> float:
    if "tElapsedMs" in ev:
        return float(ev["tElapsedMs"]) / 1000.0
    tc = ev.get("tc") or "00:00:00:00"
    h, m, s, f = (int(x) for x in tc.replace(";", ":").split(":"))
    return h * 3600 + m * 60 + s + f / 60.0


def is_name(ev: dict, name: str) -> bool:
    return normalized_name(ev.get("name") or "") == normalized_name(name)


def normalized_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def data_value(ev: dict, key: str):
    wanted = normalized_name(key)
    for k, v in (ev.get("data") or {}).items():
        if normalized_name(str(k)) == wanted:
            return v
    if normalized_name(ev.get("name") or "") == wanted:
        data = ev.get("data") or {}
        for k in ("value", "to", "state", "show", "shown"):
            if k in data:
                return data[k]
    return None


def is_transition(ev: dict, name: str, from_value=None, to_value=None) -> bool:
    if normalized_name(ev.get("name") or "") != normalized_name(name):
        return False
    data = ev.get("data") or {}
    if from_value is not None and data.get("from") != from_value:
        return False
    if to_value is not None and data.get("to") != to_value:
        return False
    return True


def is_tiercard_open(ev: dict) -> bool:
    if is_transition(ev, "tiercard-state-2", from_value=1, to_value=2):
        return True
    if data_value(ev, "showtierdata") is True:
        return True
    if data_value(ev, "showTierData") is True:
        return True
    value = data_value(ev, "tiercardstate")
    return value == 2 or value == "2"


def is_tiercard_close(ev: dict) -> bool:
    if is_transition(ev, "tiercard-state-1", to_value=1):
        return True
    if data_value(ev, "showtierdata") is False:
        return True
    if data_value(ev, "showTierData") is False:
        return True
    value = data_value(ev, "tiercardstate")
    return value == 1 or value == "1"


def next_event(events: list[dict], after_sec: float, predicate) -> dict | None:
    for ev in events:
        if event_sec(ev) > after_sec and predicate(ev):
            return ev
    return None


def first_event(events: Iterable[dict], predicate) -> dict | None:
    return next((ev for ev in events if predicate(ev)), None)


def event_data_sec(ev: dict, key: str) -> float | None:
    data = ev.get("data") or {}
    value = data.get(key)
    if value is None:
        return None
    return float(value) / 1000.0


def event_session_sec(ev: dict) -> float:
    return event_data_sec(ev, "sessionElapsedMs") or event_sec(ev)


def slug(value: object) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "unknown"


def card_key(ev: dict) -> tuple:
    data = ev.get("data") or {}
    battle_id = data.get("battleId")
    if battle_id:
        return ("battleId", battle_id)
    return (
        "leader",
        data.get("leader") or "",
        data.get("battleType") or "",
        data.get("attempt") or "",
    )


def same_card(a: dict, b: dict) -> bool:
    return card_key(a) == card_key(b)


def make_region(
    *,
    label: str,
    kind: str,
    start_sec: float,
    end_sec: float | None,
    source_offset: float,
    fps: float,
    reason: str,
    source_dur: float | None,
    pad_start: float = 0.0,
    pad_end: float = 0.0,
) -> HoldRegion | None:
    sess_start = max(0.0, start_sec - pad_start)
    sess_end = None if end_sec is None else max(sess_start, end_sec + pad_end)
    src_start = sess_start - source_offset
    src_end = None if sess_end is None else sess_end - source_offset

    if source_dur is not None:
        if src_end is not None and src_end <= 0:
            return None
        if src_start >= source_dur:
            return None
        src_start = max(0.0, src_start)
        if src_end is not None:
            src_end = min(source_dur, src_end)

    start_frame = int(round(src_start * fps))
    end_frame = None if src_end is None else int(round(src_end * fps))
    if end_frame is not None and end_frame <= start_frame:
        return None

    return HoldRegion(
        label=label,
        kind=kind,
        session_start_sec=sess_start,
        session_end_sec=sess_end,
        source_start_sec=src_start,
        source_end_sec=src_end,
        source_start_frame=start_frame,
        source_end_frame=end_frame,
        reason=reason,
    )


def derive_post_battle_card_phase_regions(
    events: list[dict],
    *,
    source_offset: float,
    fps: float,
    source_dur: float | None,
    pad_post_battle_start: float,
    pad_post_battle_end: float,
) -> list[HoldRegion]:
    regions: list[HoldRegion] = []
    opens = [ev for ev in events if is_name(ev, "post-battle-card-visible")]
    closes = [ev for ev in events if is_name(ev, "post-battle-card-hidden")]
    changes = [ev for ev in events if is_name(ev, "post-battle-card-phase-changed")]

    for card_index, opened in enumerate(opens, start=1):
        open_s = event_session_sec(opened)
        close = next(
            (
                ev
                for ev in closes
                if event_session_sec(ev) > open_s and same_card(opened, ev)
            ),
            None,
        )
        if close is None:
            continue
        close_s = event_session_sec(close)
        open_data = opened.get("data") or {}
        leader = open_data.get("leader") or f"card_{card_index:02d}"

        boundaries: list[tuple[float, str, str]] = [
            (
                open_s,
                str(open_data.get("phase") or open_data.get("to") or "visible"),
                "open",
            )
        ]
        for change in changes:
            change_s = event_session_sec(change)
            if change_s <= open_s or change_s >= close_s:
                continue
            if not same_card(opened, change):
                continue
            data = change.get("data") or {}
            phase = str(data.get("to") or data.get("phase") or "phase")
            reason = str(data.get("reason") or "phase_changed")
            if reason == "card_visible" and change_s - open_s < 0.1:
                continue
            if boundaries and abs(change_s - boundaries[-1][0]) < 0.001:
                boundaries[-1] = (boundaries[-1][0], phase, reason)
            else:
                boundaries.append((change_s, phase, reason))

        boundaries.sort(key=lambda row: row[0])
        for phase_index, (start_s, phase, reason) in enumerate(boundaries, start=1):
            if phase_index < len(boundaries):
                end_s = boundaries[phase_index][0]
            else:
                end_s = close_s
            r = make_region(
                label=f"post_battle_card_{card_index:02d}_{slug(leader)}_{slug(phase)}",
                kind="post_battle_card_phase",
                start_sec=start_s,
                end_sec=end_s,
                source_offset=source_offset,
                fps=fps,
                reason=(
                    f"{leader} post-battle card phase '{phase}' should hold from "
                    f"{reason} to the next phase/close marker"
                ),
                source_dur=source_dur,
                pad_start=pad_post_battle_start if phase_index == 1 else 0.0,
                pad_end=pad_post_battle_end if phase_index == len(boundaries) else 0.0,
            )
            if r:
                regions.append(r)
    return regions


def derive_legacy_tiercard_regions(
    events: list[dict],
    *,
    source_offset: float,
    fps: float,
    source_dur: float | None,
    pad_post_battle_start: float,
    pad_post_battle_end: float,
    final_start_s: float | None,
) -> list[HoldRegion]:
    """Fallback candidates for old logs that only recorded numeric tiercard states."""
    regions: list[HoldRegion] = []
    n = 1
    for ev in events:
        if not is_tiercard_open(ev):
            continue
        start_s = event_sec(ev)
        if final_start_s is not None and start_s >= final_start_s:
            continue
        close = next_event(events, start_s, is_tiercard_close)
        if not close:
            continue
        end_s = event_sec(close)
        if final_start_s is not None and end_s >= final_start_s:
            continue
        r = make_region(
            label=f"legacy_post_battle_data_card_{n:02d}",
            kind="post_battle_card_numeric_fallback",
            start_sec=start_s,
            end_sec=end_s,
            source_offset=source_offset,
            fps=fps,
            reason=(
                "Fallback from numeric tiercard-state markers; ask for explicit "
                "hold-region approval if precise per-leader markers are unavailable"
            ),
            source_dur=source_dur,
            pad_start=pad_post_battle_start,
            pad_end=pad_post_battle_end,
        )
        if r:
            regions.append(r)
            n += 1
    return regions


def manual_override_rows_to_regions(
    rows: list[dict],
    *,
    source_offset: float,
    fps: float,
    source_dur: float | None,
) -> list[HoldRegion]:
    regions: list[HoldRegion] = []
    for index, row in enumerate(rows, start=1):
        if "session_start_sec" in row:
            start_s = float(row["session_start_sec"])
        elif "source_start_sec" in row:
            start_s = float(row["source_start_sec"]) + source_offset
        else:
            continue
        if "session_end_sec" in row:
            end_s = float(row["session_end_sec"])
        elif "source_end_sec" in row:
            end_s = float(row["source_end_sec"]) + source_offset
        else:
            continue
        label = row.get("label") or f"manual_post_battle_card_{index:02d}"
        r = make_region(
            label=str(label),
            kind="post_battle_card_manual_override",
            start_sec=start_s,
            end_sec=end_s,
            source_offset=source_offset,
            fps=fps,
            reason=str(row.get("reason") or "manual override for post-battle card hold"),
            source_dur=source_dur,
        )
        if r:
            regions.append(r)
    return regions


def derive_regions(
    events: list[dict],
    *,
    source_offset: float,
    fps: float,
    source_dur: float | None,
    pad_post_battle_start: float,
    pad_post_battle_end: float,
    manual_override_rows: list[dict] | None = None,
) -> list[HoldRegion]:
    events = sorted(events, key=event_sec)
    regions: list[HoldRegion] = []

    # Intro cards: stats until the first card-state-2, then moveset until hidden.
    pregame = first_event(events, lambda e: is_name(e, "pregame-card-shown"))
    if pregame:
        pregame_s = event_sec(pregame)
        hidden = next_event(events, pregame_s, lambda e: is_name(e, "pregame-card-hidden"))
        state2 = next_event(
            events,
            pregame_s,
            lambda e: is_transition(e, "card-state-2", to_value=2),
        )
        if hidden:
            hidden_s = event_sec(hidden)
            if state2 and event_sec(state2) < hidden_s:
                state2_s = event_sec(state2)
                for spec in (
                    ("intro_stats_card", "intro_stats", pregame_s, state2_s,
                     "stats card shown while intro narration discusses stats"),
                    ("intro_moveset_card", "intro_moveset", state2_s, hidden_s,
                     "moveset card shown while intro narration discusses moves"),
                ):
                    r = make_region(
                        label=spec[0],
                        kind=spec[1],
                        start_sec=spec[2],
                        end_sec=spec[3],
                        source_offset=source_offset,
                        fps=fps,
                        reason=spec[4],
                        source_dur=source_dur,
                    )
                    if r:
                        regions.append(r)
            else:
                r = make_region(
                    label="intro_pregame_card",
                    kind="intro_card",
                    start_sec=pregame_s,
                    end_sec=hidden_s,
                    source_offset=source_offset,
                    fps=fps,
                    reason="pregame card shown; no stats/moveset split found",
                    source_dur=source_dur,
                )
                if r:
                    regions.append(r)

    final_start = first_event(
        events,
        lambda e: e.get("name") in {
            "final-tierlist-podium-shown",
            "final-tierlist-traditional-shown",
        },
    )
    final_start_s = event_sec(final_start) if final_start else None

    post_battle_regions = derive_post_battle_card_phase_regions(
        events,
        source_offset=source_offset,
        fps=fps,
        source_dur=source_dur,
        pad_post_battle_start=pad_post_battle_start,
        pad_post_battle_end=pad_post_battle_end,
    )
    if post_battle_regions:
        regions.extend(post_battle_regions)
    elif manual_override_rows:
        regions.extend(
            manual_override_rows_to_regions(
                manual_override_rows,
                source_offset=source_offset,
                fps=fps,
                source_dur=source_dur,
            )
        )
    else:
        regions.extend(
            derive_legacy_tiercard_regions(
                events,
                source_offset=source_offset,
                fps=fps,
                source_dur=source_dur,
                pad_post_battle_start=pad_post_battle_start,
                pad_post_battle_end=pad_post_battle_end,
                final_start_s=final_start_s,
            )
        )

    if final_start:
        final_end = next_event(events, event_sec(final_start), lambda e: is_name(e, "final-tierlist-hidden"))
        if final_end:
            r = make_region(
                label="final_tierlist",
                kind="final_tierlist",
                start_sec=event_sec(final_start),
                end_sec=event_sec(final_end),
                source_offset=source_offset,
                fps=fps,
                reason="final podium/traditional tierlist views should stay visually continuous",
                source_dur=source_dur,
            )
            if r:
                regions.append(r)

    carousel_starts = [e for e in events if is_name(e, "member-carousel-started")]
    if carousel_starts:
        # Prefer the first carousel start after the final tierlist is hidden. If
        # the app emits a short warm-up start/end and then a second start, this
        # still protects the earliest point where the lower roll may appear.
        final_hidden = first_event(events, lambda e: is_name(e, "final-tierlist-hidden"))
        min_s = event_sec(final_hidden) if final_hidden else -1
        candidates = [e for e in carousel_starts if event_sec(e) >= min_s] or carousel_starts
        start = candidates[0]
        r = make_region(
            label="member_carousel",
            kind="member_carousel",
            start_sec=event_sec(start),
            end_sec=None,
            source_offset=source_offset,
            fps=fps,
            reason="carousel lower member-name roll should remain continuous under tight V2 cuts",
            source_dur=source_dur,
        )
        if r:
            regions.append(r)

    return regions


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", type=Path, required=True)
    ap.add_argument("--meta", type=Path, help="session meta.json, used with --source-video to compute source offset")
    ap.add_argument("--source-video", type=Path, help="MP4/MOV whose creation_time maps session elapsed to source time")
    ap.add_argument("--source-offset-sec", type=float, help="override: session elapsed seconds at source frame 0")
    ap.add_argument("--fps", type=float, default=60.0)
    ap.add_argument("--pad-post-battle-start-sec", type=float, default=0.0)
    ap.add_argument("--pad-post-battle-end-sec", type=float, default=0.0)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    if args.source_offset_sec is not None:
        source_offset = args.source_offset_sec
    elif args.meta and args.source_video:
        source_offset = source_start_elapsed(args.meta, args.source_video)
    else:
        raise SystemExit("Provide either --source-offset-sec or both --meta and --source-video")

    src_dur = source_duration_sec(args.source_video) if args.source_video else None
    events = load_json(args.events)
    regions = derive_regions(
        events,
        source_offset=source_offset,
        fps=args.fps,
        source_dur=src_dur,
        pad_post_battle_start=args.pad_post_battle_start_sec,
        pad_post_battle_end=args.pad_post_battle_end_sec,
    )

    payload = {
        "events": str(args.events),
        "source_video": str(args.source_video) if args.source_video else None,
        "fps": args.fps,
        "source_offset_sec": source_offset,
        "source_duration_sec": src_dur,
        "regions": [asdict(r) for r in regions],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Wrote {len(regions)} hold regions -> {args.out}")
    for r in regions:
        end = "open" if r.source_end_sec is None else f"{r.source_end_sec:.2f}s"
        print(f"  {r.label:26s} {r.source_start_sec:8.2f}s -> {end}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
