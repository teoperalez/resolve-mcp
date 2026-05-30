"""Build a 1080p ffmpeg preview of the edit with saved cut decisions applied.

Reconstructs the talking-head edit from the source clip ranges (clips.json),
drops whole-cut clips, trims partial (drag) cuts via the segmap, bakes a grade
(CDL slope/offset + saturation), and muxes the mic audio. No Resolve needed.

Usage:
    python build_cut_preview.py --source SRC.mp4 --mic MIC.wav --clips clips.json
        --segmap segmap.json --decisions pink_decisions.json --out OUT.mp4
        [--slope "1.485 1.515 1.545"] [--offset -0.1896] [--sat 1.02] [--tl-fps 60]
        [--crf 18]
"""
import json, subprocess, os, argparse

ap = argparse.ArgumentParser()
ap.add_argument("--source", required=True)
ap.add_argument("--mic", required=True)
ap.add_argument("--clips", required=True)
ap.add_argument("--segmap", required=True)
ap.add_argument("--decisions", required=True)
ap.add_argument("--out", required=True)
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

def write_list(path, src):
    with open(path, "w") as f:
        f.write("ffconcat version 1.0\n")
        for (s, e) in segs:
            f.write("file '%s'\ninpoint %.3f\noutpoint %.3f\n" % (src, s, e))
write_list(OUTDIR + "/_v.txt", A.source); write_list(OUTDIR + "/_a.txt", A.mic)

sl = A.slope.split(); off255 = A.offset * 255.0
grade = ("lutrgb=r='clip(val*%s%+.1f,0,255)':g='clip(val*%s%+.1f,0,255)':b='clip(val*%s%+.1f,0,255)',eq=saturation=%s"
         % (sl[0], off255, sl[1], off255, sl[2], off255, A.sat))
tv, ta = OUTDIR + "/_pv.mp4", OUTDIR + "/_pa.aac"
print("[1/3] video concat + grade ..."); subprocess.run(["ffmpeg", "-y", "-v", "error", "-stats", "-f", "concat", "-safe", "0", "-i", OUTDIR + "/_v.txt",
    "-map", "0:v:0", "-vf", grade, "-r", str(int(A.tl_fps)), "-c:v", "libx264", "-crf", str(A.crf), "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an", tv], check=True)
print("[2/3] audio concat ..."); subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", OUTDIR + "/_a.txt", "-map", "0:a:0", "-c:a", "aac", "-b:a", "192k", ta], check=True)
print("[3/3] mux ..."); subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", tv, "-i", ta, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "copy", "-shortest", A.out], check=True)
for f in (tv, ta):
    try: os.remove(f)
    except OSError: pass
d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1", A.out], capture_output=True, text=True).stdout.strip()
print("WROTE", A.out, "| duration", d)
