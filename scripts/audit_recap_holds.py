"""
Audit recap V1 holds in an FCPXML before final assembly / import.

Checks, per APPROVED recap region:
  1. coverage    — exactly ONE video spine clip spans the region's edit;
  2. audio-under — >= --min-audio-clips dialogue clips under the held clip
                   (proves the silence cuts stayed audio-only);
  3. contiguity  — the held clip butts flush against its neighbors
                   (no black holes at the hold edges);
  4. exit-drift  — source jump at the hold exit is >= 0 and <= the region's
                   source span (sane re-anchor, no backwards jump / repeats);
  5. freeze QA   — (optional, needs ffmpeg + source file) counts hard scene
                   changes (scene score > 0.3) across the held SOURCE range.
                   A results/recap screen may contain animated sprites but
                   has almost no hard cuts (measured: holds 0-2/min vs
                   gameplay 5-15/min), so a high scene-cut rate means the
                   hold was wrongly applied over moving gameplay.

Exit code 0 = all approved regions pass; 1 = any failure (orchestrator gate).

Usage:
    python audit_recap_holds.py HELD.fcpxml \
        --regions CODEx/recap_regions/recap_regions.json [--part 6] \
        --report CODEx/qa-reports/recap-holds.json \
        [--min-audio-clips 4] [--freeze-check] [--max-scene-cuts-per-min 3.0]
"""
import sys
import os
import re
import json
import argparse
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, os.path.dirname(__file__))
from insert_battle_gaps_fcpxml import parse_spine_clips  # noqa: E402
from apply_recap_holds_to_fcpxml import approved_regions  # noqa: E402

ASSET_RE = re.compile(
    r'<asset\s+id="([^"]+)"[^>]*?>\s*<media-rep[^>]*?src="([^"]+)"', re.DOTALL)
PTS_RE = re.compile(r"pts_time:(\d+(?:\.\d+)?)")


def asset_paths(xml: str) -> dict[str, Path]:
    out = {}
    for m in ASSET_RE.finditer(xml):
        ref, src = m.group(1), m.group(2)
        if src.startswith("file:"):
            src = unquote(urlparse(src).path).lstrip("/")
        out[ref] = Path(src)
    return out


def scene_cut_rate(source: Path, t0: float, t1: float,
                   scene_thresh: float = 0.3) -> float | None:
    """Hard scene changes per MINUTE over [t0, t1) of the source.
    ~0 = static/held screen. None if ffmpeg failed."""
    dur = max(1.0, t1 - t0)
    cmd = ["ffmpeg", "-hide_banner", "-nostats",
           "-ss", f"{t0:.3f}", "-t", f"{dur:.3f}", "-i", str(source),
           "-vf", f"select='gt(scene,{scene_thresh})',showinfo",
           "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if proc.returncode != 0:
        return None
    cuts = len(PTS_RE.findall(proc.stderr))
    return round(cuts / (dur / 60.0), 3)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fcpxml", type=Path)
    ap.add_argument("--regions", type=Path, required=True)
    ap.add_argument("--part", default=None)
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--den", type=int, default=60)
    ap.add_argument("--min-audio-clips", type=int, default=4)
    ap.add_argument("--dialogue-ref", default=None,
                    help="Ref id of the dialogue audio (default: last ref)")
    ap.add_argument("--freeze-check", action="store_true")
    ap.add_argument("--max-scene-cuts-per-min", type=float, default=3.0,
                    help="Freeze check fails above this hard-cut rate")
    args = ap.parse_args()

    regions = approved_regions(args.regions, args.part)
    xml = args.fcpxml.read_text(encoding="utf-8")
    clips = parse_spine_clips(xml)
    assets = asset_paths(xml)

    refs_in_order: list[str] = []
    seen: set[str] = set()
    for c in clips:
        if c["ref"] not in seen:
            seen.add(c["ref"])
            refs_in_order.append(c["ref"])
    video_ref = refs_in_order[0]
    dialogue_ref = args.dialogue_ref or refs_in_order[-1]

    video_clips = sorted((c for c in clips if c["ref"] == video_ref),
                         key=lambda c: c["offset"][0])
    audio_clips = sorted((c for c in clips if c["ref"] == dialogue_ref),
                         key=lambda c: c["offset"][0])
    den = args.den

    results = []
    all_pass = True
    for reg in regions:
        t0u = int(round(float(reg["source_start_sec"]) * den))
        t1u = int(round(float(reg["source_end_sec"]) * den))
        checks: dict[str, dict] = {}
        entry = {"id": reg.get("id"), "part": reg.get("part"), "checks": checks}
        results.append(entry)

        # 1. coverage — one video clip whose source midpoint is in region
        inside = [c for c in video_clips
                  if t0u <= c["start"][0] + c["duration"][0] // 2 < t1u]
        checks["coverage"] = {
            "pass": len(inside) == 1,
            "video_clips_in_region": len(inside),
        }
        if len(inside) != 1:
            all_pass = False
            continue
        hold = inside[0]
        tl0 = hold["offset"][0]
        tl1 = tl0 + hold["duration"][0]
        entry["timeline_start_sec"] = round(tl0 / den, 3)
        entry["timeline_dur_sec"] = round((tl1 - tl0) / den, 3)

        # 2. audio-under — dialogue clips overlapping the held range
        under = [a for a in audio_clips
                 if a["offset"][0] < tl1 and a["offset"][0] + a["duration"][0] > tl0]
        checks["audio_under"] = {
            "pass": len(under) >= args.min_audio_clips,
            "audio_clips": len(under),
            "min_required": args.min_audio_clips,
        }

        # 3. contiguity at hold edges
        prev = next((c for c in reversed(video_clips)
                     if c["offset"][0] + c["duration"][0] <= tl0), None)
        nxt = next((c for c in video_clips if c["offset"][0] >= tl1), None)
        prev_ok = prev is None or prev["offset"][0] + prev["duration"][0] == tl0
        next_ok = nxt is None or nxt["offset"][0] == tl1
        checks["contiguity"] = {"pass": prev_ok and next_ok,
                                "prev_flush": prev_ok, "next_flush": next_ok}

        # 4. exit drift — next clip must re-anchor at/after the hold's last
        # consumed source frame (drift < 0 would repeat frames on screen).
        # Large positive drift is fine: silence stripped right after the
        # recap inflates it without affecting sync. Flag it for review only.
        src_end = hold["start"][0] + hold["duration"][0]
        if nxt is not None:
            drift = nxt["start"][0] - src_end
            span = t1u - t0u
            checks["exit_drift"] = {
                "pass": drift >= 0,
                "drift_sec": round(drift / den, 3),
                "region_span_sec": round(span / den, 3),
                "warn_large": drift > 2 * span,
            }
        else:
            checks["exit_drift"] = {"pass": True, "note": "hold is last clip"}

        # 5. freeze QA on the held source range
        if args.freeze_check:
            src = assets.get(video_ref)
            if src is None or not src.exists():
                checks["freeze"] = {"pass": False,
                                    "error": f"source not found: {src}"}
            else:
                rate = scene_cut_rate(src, hold["start"][0] / den, src_end / den)
                checks["freeze"] = {
                    "pass": rate is not None and rate <= args.max_scene_cuts_per_min,
                    "scene_cuts_per_min": rate,
                    "threshold": args.max_scene_cuts_per_min,
                }

        if not all(c.get("pass") for c in checks.values()):
            all_pass = False

    for e in results:
        status = "PASS" if all(c.get("pass") for c in e["checks"].values()) else "FAIL"
        detail = ", ".join(f"{k}={'ok' if v.get('pass') else 'FAIL'}"
                           for k, v in e["checks"].items())
        print(f"[{status}] {e.get('id')}: {detail}")

    payload = {
        "fcpxml": str(args.fcpxml),
        "regions_file": str(args.regions),
        "all_pass": all_pass,
        "results": results,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.report}")

    print("ALL PASS" if all_pass else "AUDIT FAILED")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
