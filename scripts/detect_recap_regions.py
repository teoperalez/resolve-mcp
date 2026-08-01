"""
Detect recap/results sections in a Minimum Battles-style video from the
transcript, with optional ffmpeg static-screen (motion) confirmation.

Recaps are sections where the narrator talks over a static results-table
screen ("coming back to our results so far", "pass column", ...). In the
final edit these sections get a V1 HOLD: silence cuts apply to audio only
while one continuous video clip spans the whole section, so the static
screen never visibly jump-cuts.

This tool only PROPOSES regions (status="proposed"). A human review gate
must flip them to "approved" before apply_recap_holds_to_fcpxml.py will
touch them.

Times are SOURCE seconds within each part's source media, so detection can
run any time after transcription, and holds are applied later — after all
cut decisions — because the regions are anchored to source time, not to any
particular edit of the timeline.

Usage (single source):
    python detect_recap_regions.py --transcript transcripts/x/4.json \
        --source "F:/proj/part 6.mkv" --out CODEx/recap_regions/recap_regions.json

Usage (multi-part):
    python detect_recap_regions.py \
        --part 2=transcripts/roxanne/part2/4.json \
        --part 6=transcripts/roxanne/part6/4.json \
        --source-dir "F:/Roxanne Minimum Battles 19" \
        --source-pattern "Roxanne Minimum Battles 19 part {part}.mkv" \
        --out CODEx/recap_regions/recap_regions.json

Optional stills for the review gate:  --stills-dir <dir>
Disable motion scoring:               --no-motion
"""
import sys
import os
import re
import json
import argparse
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

# ── Recap-opener phrases ─────────────────────────────────────────────────────
# Derived from Roxanne Minimum Battles 19 (all confirmed manual holds opened
# with one of these). Case-insensitive regex fragments, matched against a
# sliding window of transcript text.
DEFAULT_PHRASES = [
    r"coming back to our results",
    r"results so far",
    r"(?:into|to|up in) th(?:e|at) pass column",
    r"(?:into|to|up in) th(?:e|at) struggle column",
    r"check in on our (?:other|results|member)",
    r"at the end of the day we have \d+",
    r"add(?:ing)? (?:the |those |these )?.{0,40}(?:up )?(?:in)?to the pass column",
    r"throw (?:each|those|these|them|it) .{0,40}column",
    # section-transition holds (static screen between groups)
    r"with (?:that|\w+) done,? (?:that|we|it)",
    r"that leaves only",
]

MIN_DUR_DEFAULT = 15.0    # ignore blips shorter than this
MAX_DUR_DEFAULT = 180.0   # never propose a region longer than this
MOTION_SCENE_THRESH = 0.3  # hard scene-cut threshold (calibrated: holds
                           # score 0-2 cuts/min, gameplay 5-15 cuts/min)

# Beat openers: the narration lines that start the NEXT Pokémon/section.
# Used to end a recap region when no --beats file is provided.
DEFAULT_BEAT_PHRASES = [
    r"brings? us to",
    r"that will bring us",
    r"let'?s (?:get|move on|jump) to",
    r"we'?re on to",
    r"comes? in (?:first )?with",
    r"it'?s \w+ time",
    r"first up",
    r"start(?:ing)? with our",
]


def load_transcript(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_phrase_hits(transcript: dict, patterns: list[re.Pattern]) -> list[dict]:
    """Scan segments; return [{time, phrase, text}] anchored at the word
    where the match begins. Matches are only accepted when they START inside
    the segment (the straddle window into the next segment is context only),
    so a phrase living in segment N+1 is anchored there — not at N's start."""
    hits = []
    segs = transcript.get("segments", [])
    for i, seg in enumerate(segs):
        window_text = seg["text"] + (segs[i + 1]["text"] if i + 1 < len(segs) else "")
        for pat in patterns:
            m = pat.search(window_text)
            if not m or m.start() >= len(seg["text"]):
                continue  # phrase starts in the next segment; anchor it there
            anchor = seg["start"]
            char_pos = m.start()
            consumed = 0
            for w in seg.get("words", []):
                if consumed >= char_pos:
                    anchor = w["start"]
                    break
                consumed += len(w["word"])
            hits.append({
                "time": round(float(anchor), 3),
                "phrase": pat.pattern,
                "text": (seg["text"] + "").strip()[:160],
            })
            break  # one hit per segment is enough
    # de-duplicate hits closer than 20s (same recap mentioned repeatedly)
    hits.sort(key=lambda h: h["time"])
    merged = []
    for h in hits:
        if merged and h["time"] - merged[-1]["time"] < 20.0:
            continue
        merged.append(h)
    return merged


# ── Motion probe (ffmpeg) ────────────────────────────────────────────────────

_SHOWINFO_PTS = re.compile(r"pts_time:(\d+(?:\.\d+)?)")


def motion_events(source: Path, t0: float, t1: float,
                  scene_thresh: float) -> list[float] | None:
    """Return pts times (relative to t0) of HARD scene changes over [t0, t1),
    full frame rate, downscaled for speed. None if ffmpeg failed."""
    dur = max(0.5, t1 - t0)
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-ss", f"{t0:.3f}", "-t", f"{dur:.3f}", "-i", str(source),
        "-vf", f"scale=480:-1,select='gt(scene,{scene_thresh})',showinfo",
        "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if proc.returncode != 0:
        return None
    return [float(m.group(1)) for m in _SHOWINFO_PTS.finditer(proc.stderr)]


def refine_with_motion(source: Path, start: float, max_end: float,
                       min_dur: float, scene_thresh: float,
                       refine_end: bool) -> tuple[float, float | None]:
    """Score motion over the span; optionally refine end to the first
    sustained motion burst after start+min_dur. Returns (end, motion_score)
    where motion_score is exceed-frames per second (lower = more static).

    NOTE: game capture results screens often contain animated sprites, so
    end refinement is OPT-IN; by default the score is advisory only and the
    end comes from beats / the next phrase hit / max-dur."""
    events = motion_events(source, start, max_end, scene_thresh)
    if events is None:
        return max_end, None
    end_rel = max_end - start
    if refine_end:
        # sustained burst = >=3 exceeding frames within 2 seconds
        after = [t for t in events if t >= min_dur]
        for i in range(len(after) - 2):
            if after[i + 2] - after[i] <= 2.0:
                end_rel = after[i]
                break
    span = max(1.0, end_rel)
    inside = sum(1 for t in events if t < end_rel)
    # score = hard scene-cuts per minute (comparable with audit threshold)
    return start + end_rel, round(inside / (span / 60.0), 3)


def extract_stills(source: Path, t0: float, t1: float, out_dir: Path,
                   label: str) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stills = []
    for tag, t in (("start", t0 + 0.5), ("mid", (t0 + t1) / 2), ("end", t1 - 0.5)):
        out = out_dir / f"{label}_{tag}.jpg"
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-ss", f"{max(0, t):.3f}", "-i", str(source),
               "-frames:v", "1", "-vf", "scale=640:-1", str(out)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=120)
            if out.exists():
                stills.append(str(out))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return stills


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--transcript", type=Path, default=None,
                    help="Single transcript JSON (word timestamps)")
    ap.add_argument("--source", type=Path, default=None,
                    help="Source video for the single transcript")
    ap.add_argument("--part", action="append", default=[],
                    metavar="N=transcript.json",
                    help="Multi-part: part number = transcript path (repeatable)")
    ap.add_argument("--source-dir", type=Path, default=None)
    ap.add_argument("--source-pattern", default=None,
                    help="e.g. 'My Video part {part}.mkv' inside --source-dir")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--stills-dir", type=Path, default=None)
    ap.add_argument("--phrases-file", type=Path, default=None,
                    help="JSON list of extra regex phrases (added to defaults)")
    ap.add_argument("--min-dur", type=float, default=MIN_DUR_DEFAULT)
    ap.add_argument("--max-dur", type=float, default=MAX_DUR_DEFAULT)
    ap.add_argument("--scene-thresh", type=float, default=MOTION_SCENE_THRESH)
    ap.add_argument("--no-motion", action="store_true")
    ap.add_argument("--motion-refine-end", action="store_true",
                    help="Refine region end at first sustained motion burst "
                         "(off by default: game screens can be animated)")
    ap.add_argument("--beats", type=Path, default=None,
                    help="JSON with beat times to snap region ends to: either "
                         "a list of source-seconds or [{part, timestamp_sec}] "
                         "(e.g. from the minimum-battles/beat detector)")
    args = ap.parse_args()

    phrases = list(DEFAULT_PHRASES)
    if args.phrases_file:
        phrases += json.loads(args.phrases_file.read_text(encoding="utf-8"))
    patterns = [re.compile(p, re.IGNORECASE) for p in phrases]
    beat_patterns = [re.compile(p, re.IGNORECASE) for p in DEFAULT_BEAT_PHRASES]

    # Build (part_label, transcript_path, source_path) list
    jobs: list[tuple[str, Path, Path | None]] = []
    if args.transcript:
        jobs.append(("1", args.transcript, args.source))
    for spec in args.part:
        label, _, tpath = spec.partition("=")
        if not tpath:
            ap.error(f"--part needs N=path, got {spec!r}")
        src = None
        if args.source_dir and args.source_pattern:
            src = args.source_dir / args.source_pattern.format(part=label)
        jobs.append((label, Path(tpath), src))
    if not jobs:
        ap.error("Provide --transcript or at least one --part")

    # optional beat times for end snapping, per part label
    beats_by_part: dict[str, list[float]] = {}
    if args.beats:
        raw = json.loads(args.beats.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("battles") or raw.get("beats") or []
        for b in raw:
            if isinstance(b, (int, float)):
                beats_by_part.setdefault("1", []).append(float(b))
            else:
                beats_by_part.setdefault(str(b.get("part", "1")), []).append(
                    float(b.get("timestamp_sec") or b.get("time") or 0))
        for v in beats_by_part.values():
            v.sort()

    regions = []
    for label, tpath, src in jobs:
        tx = load_transcript(tpath)
        tx_dur = float(tx.get("duration") or 0)
        hits = find_phrase_hits(tx, patterns)
        print(f"part {label}: {len(hits)} recap-opener hit(s)")
        beats = beats_by_part.get(label, [])
        if not beats:
            # derive beat-end candidates from the transcript itself
            beats = [h["time"] for h in find_phrase_hits(tx, beat_patterns)]
        for k, h in enumerate(hits):
            start = h["time"]
            # provisional end: next beat, next hit, max-dur, transcript end
            nxt = hits[k + 1]["time"] if k + 1 < len(hits) else float("inf")
            end = min(start + args.max_dur, nxt, tx_dur or float("inf"))
            next_beat = next((b for b in beats if b >= start + args.min_dur),
                             None)
            if next_beat is not None:
                end = min(end, next_beat)
            motion_score = None
            if src and src.exists() and not args.no_motion:
                end, motion_score = refine_with_motion(
                    src, start, end, args.min_dur, args.scene_thresh,
                    args.motion_refine_end)
            if end - start < args.min_dur:
                print(f"  skip @{start:.1f}s: refined span {end - start:.1f}s "
                      f"< min-dur {args.min_dur}")
                continue
            rid = f"p{label}-recap-{k}"
            entry = {
                "id": rid,
                "part": label,
                "source": str(src) if src else None,
                "source_start_sec": round(start, 3),
                "source_end_sec": round(end, 3),
                "status": "proposed",
                "exit_strategy": "beat_gap",
                "detection": {
                    "phrase": h["phrase"],
                    "transcript_text": h["text"],
                    "motion_score": motion_score,
                },
            }
            if args.stills_dir and src and src.exists():
                entry["stills"] = extract_stills(src, start, end,
                                                 args.stills_dir, rid)
            regions.append(entry)
            ms = f"{motion_score}" if motion_score is not None else "n/a"
            print(f"  [{rid}] {start:8.1f}s -> {end:8.1f}s "
                  f"({end - start:6.1f}s) motion={ms} | {h['text'][:70]}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "recap_regions_v1",
        "phrases_used": phrases,
        "regions": regions,
    }
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"\nwrote {args.out} ({len(regions)} proposed region(s))")
    print("Next: review each region (stills + text), set status to "
          "'approved' or 'rejected', then run apply_recap_holds_to_fcpxml.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
