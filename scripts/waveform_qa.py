"""Waveform QA: categorize each timeline clip as speech / possible artifact /
definite artifact from the actual mic audio (NOT Whisper).

A clip is judged by its longest contiguous *voiced-speech* run — frames whose
energy is above a speech level AND whose zero-crossing rate is low (a vowel, not
a breath/fricative). Definite artifacts (no vowel, near-silent) can be auto-cut;
everything borderline should go to the HTML review tool.

Usage:
    python waveform_qa.py --mic MIC.wav --clips clips.json --out-dir OUTDIR
        [--speech-rms 0.020] [--voiced-zcr 0.25] [--tl-fps 60]

Outputs: OUTDIR/categories.json, OUTDIR/waves_candidates.png
"""
import json, subprocess, argparse, os
import numpy as np
from PIL import Image, ImageDraw

ap = argparse.ArgumentParser()
ap.add_argument("--mic", required=True, help="mic WAV (full recording, time-aligned to source)")
ap.add_argument("--clips", required=True, help="clips.json from dump_timeline_clips.py")
ap.add_argument("--out-dir", required=True)
ap.add_argument("--sr", type=int, default=16000)
ap.add_argument("--speech-rms", type=float, default=0.020)
ap.add_argument("--voiced-zcr", type=float, default=0.25)
ap.add_argument("--tl-fps", type=float, default=60.0, help="timeline fps (clip dur units)")
args = ap.parse_args()
os.makedirs(args.out_dir, exist_ok=True)
FL = int(0.02 * args.sr)

raw = subprocess.run(["ffmpeg", "-v", "error", "-i", args.mic, "-ac", "1", "-ar", str(args.sr),
                      "-f", "f32le", "-"], capture_output=True).stdout
audio = np.frombuffer(raw, np.float32)
data = json.load(open(args.clips))
clips = data["clips"] if isinstance(data, dict) else data


def frame_feats(x):
    n = len(x) // FL
    if not n:
        return np.zeros(0), np.zeros(0)
    fr = x[:n * FL].reshape(n, FL)
    return np.sqrt((fr ** 2).mean(1) + 1e-12), (np.abs(np.diff(np.sign(fr), axis=1)) > 0).mean(1)


res = []
for c in clips:
    d = c["dur"] / args.tl_fps
    if "utro" in (c.get("name") or ""):
        res.append({**c, "dur_sec": round(d, 3), "cat": "keep", "reason": "outro"}); continue
    s = c["left"] / (c["fps"] or args.tl_fps)
    a = audio[int(s * args.sr):int((s + d) * args.sr)]
    rms, zcr = frame_feats(a)
    if len(rms) == 0:
        res.append({**c, "dur_sec": round(d, 3), "rms": 0, "peak": 0, "run_vs": 0, "cat": "definite", "reason": "empty"}); continue
    voiced = (rms > args.speech_rms) & (zcr < args.voiced_zcr)
    best = run = 0
    for v in voiced:
        run = run + 1 if v else 0; best = max(best, run)
    run_vs = best * 0.02
    crms = float(np.sqrt((a ** 2).mean())); peak = float(np.abs(a).max())
    cat = "definite" if (crms < 0.012 or peak < 0.05 or run_vs < 0.06) else ("possible" if run_vs < 0.13 else "speech")
    res.append({**c, "dur_sec": round(d, 3), "rms": round(crms, 4), "peak": round(peak, 3),
                "run_vs": round(run_vs, 3), "zcr": round(float(zcr.mean()), 3), "cat": cat})

json.dump(res, open(args.out_dir + "/categories.json", "w"), indent=1)
nd = sum(r["cat"] == "definite" for r in res)
npo = sum(r["cat"] == "possible" for r in res)
ns = sum(r["cat"] == "speech" for r in res)
print("definite(auto-cut candidates):%d  possible(review):%d  speech(keep):%d" % (nd, npo, ns))
print("definite:", [r["i"] for r in res if r["cat"] == "definite"])
print("possible:", [r["i"] for r in res if r["cat"] == "possible"])

# contact sheet of the lowest-voiced clips
ranked = sorted([r for r in res if "run_vs" in r], key=lambda r: r["run_vs"])[:40]
COLS, SW, SH = 4, 470, 104
sheet = Image.new("RGB", (COLS * SW, ((len(ranked) + COLS - 1) // COLS) * SH), (12, 12, 16))
dr = ImageDraw.Draw(sheet)
COL = {"definite": (235, 90, 90), "possible": (240, 200, 90), "speech": (110, 200, 130)}
for k, r in enumerate(ranked):
    ox, oy = (k % COLS) * SW, (k // COLS) * SH
    s = r["left"] / (r["fps"] or args.tl_fps)
    a = audio[int(s * args.sr):int((s + r["dur_sec"]) * args.sr)]
    mid = oy + SH // 2 + 8
    if len(a):
        nseg = SW - 12; idx = np.linspace(0, len(a), nseg + 1).astype(int)
        for x in range(nseg):
            seg = a[idx[x]:idx[x + 1] + 1]
            if len(seg) == 0: continue
            dr.line([(ox + 6 + x, int(mid - seg.max() * (SH * .4))), (ox + 6 + x, int(mid - seg.min() * (SH * .4)))], fill=COL[r["cat"]])
    dr.text((ox + 6, oy + 4), "i=%d %.2fs rms%.3f run%.2f [%s]" % (r["i"], r["dur_sec"], r["rms"], r["run_vs"], r["cat"].upper()), fill=(240, 240, 240))
    dr.rectangle([ox, oy, ox + SW - 1, oy + SH - 1], outline=(40, 40, 48))
sheet.save(args.out_dir + "/waves_candidates.png")
print("wrote", args.out_dir + "/categories.json + waves_candidates.png")
