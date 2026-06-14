"""Build a 1080p ffmpeg preview of the edit with saved cut decisions applied.

Reconstructs the talking-head edit from the source clip ranges (clips.json),
drops whole-cut clips, trims partial (drag) cuts via the segmap, bakes a grade
(CDL slope/offset + saturation). Uses a SINGLE concat pass mapping the video and
its OWN embedded mic audio stream so video+audio stay locked (no drift). No
Resolve needed.

Usage:
    python build_cut_preview.py --source SRC.mp4 --clips clips.json
        --segmap segmap.json --decisions pink_decisions.json --out OUT.mp4
        [--mic-stream 0] [--slope "1.485 1.515 1.545"] [--offset -0.1896]
        [--sat 1.02] [--tl-fps 60] [--crf 18]

--mic-stream is the 0-based embedded audio stream index in --source to use as
the dialogue track (verify with: ffprobe -select_streams a SRC.mp4).
"""
import json, subprocess, os, argparse

ap = argparse.ArgumentParser()
ap.add_argument("--source", required=True)
ap.add_argument("--clips", required=True)
ap.add_argument("--segmap", required=True)
ap.add_argument("--decisions", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--mic-stream", type=int, default=0, help="0-based embedded audio stream index (the mic)")
ap.add_argument("--slope", default="1.0 1.0 1.0")
ap.add_argument("--offset", type=float, default=0.0)
ap.add_argument("--sat", type=float, default=1.0)
ap.add_argument("--tl-fps", type=float, default=60.0)
ap.add_argument("--crf", type=int, default=18)
A = ap.parse_args()
OUTDIR = os.path.dirname(os.path.abspath(A.out)); os.makedirs(OUTDIR, exist_ok=True)

data = json.load(open(A.clips)); clips = data["clips"] if isinstance(data, dict) else data
segmap = json.load(open(A.segmap))
dec = json.load(open(A.decisions))
pink = dec.get("pink", {}); cuts = dec.get("cuts", {})
whole_cuts = {int(i) for i, v in pink.items() if v == "cut"}

# snippet-time drag cuts -> source-time cuts per clip index
source_cuts = {}
for g, ranges in cuts.items():
    for (cs, ce) in ranges:
        for p in segmap.get(str(g), []):
            ov_s = max(cs, p["snip_start"]); ov_e = min(ce, p["snip_end"])
            if ov_e - ov_s <= 0: continue
            a = p["src_start"] + (ov_s - p["snip_start"]); b = p["src_start"] + (ov_e - p["snip_start"])
            source_cuts.setdefault(p["clip_idx"], []).append((round(a, 4), round(b, 4)))

def subtract(rng, cc):
    kept = [rng]
    for (cs, ce) in sorted(cc):
        nw = []
        for (s, e) in kept:
            if ce <= s or cs >= e: nw.append((s, e)); continue
            if cs > s: nw.append((s, cs))
            if ce < e: nw.append((ce, e))
        kept = [(s, e) for (s, e) in nw if e - s > 0.02]
    return kept

segs = []
for i, c in enumerate(clips):
    if "utro" in (c.get("name") or ""): continue          # outro = different source
    if i in whole_cuts: continue
    s = c["left"] / (c["fps"] or A.tl_fps); e = s + c["dur"] / A.tl_fps
    for (ks, ke) in subtract((s, e), source_cuts.get(i, [])):
        segs.append((ks, ke))

total = sum(e - s for s, e in segs)
print("kept segments:", len(segs), "| total %.2fs (%d:%02d)" % (total, total // 60, total % 60))
print("whole-cut:", sorted(whole_cuts), "| partial-cut clips:", dict(source_cuts))

listf = OUTDIR + "/_concat.txt"
with open(listf, "w") as f:
    f.write("ffconcat version 1.0\n")
    for (s, e) in segs:
        f.write("file '%s'\ninpoint %.3f\noutpoint %.3f\n" % (A.source, s, e))

sl = A.slope.split(); off255 = A.offset * 255.0
grade = ("lutrgb=r='clip(val*%s%+.1f,0,255)':g='clip(val*%s%+.1f,0,255)':b='clip(val*%s%+.1f,0,255)',eq=saturation=%s"
         % (sl[0], off255, sl[1], off255, sl[2], off255, A.sat))

# SINGLE pass: video + its own embedded mic audio, trimmed together -> stay in sync.
print("encoding (single pass: video + embedded a:%d) ..." % A.mic_stream)
subprocess.run(["ffmpeg", "-y", "-v", "error", "-stats", "-f", "concat", "-safe", "0", "-i", listf,
                "-map", "0:v:0", "-map", "0:a:%d" % A.mic_stream, "-vf", grade,
                "-r", str(int(A.tl_fps)), "-vsync", "cfr",
                "-c:v", "libx264", "-crf", str(A.crf), "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", A.out], check=True)
try: os.remove(listf)
except OSError: pass

probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
                        "-of", "default=nw=1", A.out], capture_output=True, text=True).stdout
print("WROTE", A.out)
print(probe.strip())
