"""Dump the current Resolve timeline's video-track clips to JSON.

Each clip: index, name, timeline start, duration (timeline frames), source
left-offset (source frames), source FPS, clip color, source file path.
Feeds waveform_qa.py and build_cut_review.py. Run this BEFORE any ripple edits
so the indices match the timeline you review.

Usage:
    python dump_timeline_clips.py [--out clips.json] [--track 1]
"""
import sys, os, json, argparse
sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="clips.json")
ap.add_argument("--track", type=int, default=1)
args = ap.parse_args()

resolve = dvr.scriptapp("Resolve")
tl = resolve.GetProjectManager().GetCurrentProject().GetCurrentTimeline()
items = tl.GetItemListInTrack("video", args.track) or []

rows = []
for i, c in enumerate(items):
    mp = c.GetMediaPoolItem()
    try:
        fps = float(mp.GetClipProperty("FPS")) if mp else 60.0
    except Exception:
        fps = 60.0
    rows.append(dict(
        i=i, name=c.GetName(), start=c.GetStart(), dur=c.GetDuration(),
        left=c.GetLeftOffset(), fps=fps, color=(c.GetClipColor() or ""),
        src=(mp.GetClipProperty("File Path") if mp else ""),
    ))

json.dump({"timeline": tl.GetName(), "track": args.track, "clips": rows},
          open(args.out, "w"), indent=1)
print("wrote %s | %d clips from '%s'" % (args.out, len(rows), tl.GetName()))
