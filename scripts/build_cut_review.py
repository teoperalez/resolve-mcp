"""Build the browser HTML cut-review tool for clips marked 'Pink' in clips.json.

Per Pink segment (adjacent Pinks clustered): playable [before, pink(s), after]
snippet + waveform + synced playhead; Keep/Cut toggle; drag-to-cut with
move/resize/delete/right-click-clear; Preview-result button. Saves
pink_decisions.json and a segmap (snippet-time -> source-time) for applying cuts.
Pre-loads a prior decisions file if given.

Usage:
    python build_cut_review.py --mic MIC.wav --clips clips.json --out-dir OUTDIR
        [--preload pink_decisions.json] [--categories categories.json]
        [--sr 44100] [--cap 3.0] [--tl-fps 60] [--reuse-assets]
"""
import json, subprocess, os, argparse, html
import numpy as np
from scipy.io import wavfile
from PIL import Image, ImageDraw

ap = argparse.ArgumentParser()
ap.add_argument("--mic", required=True)
ap.add_argument("--clips", required=True)
ap.add_argument("--out-dir", required=True)
ap.add_argument("--preload", default="")
ap.add_argument("--categories", default="")
ap.add_argument("--sr", type=int, default=44100)
ap.add_argument("--cap", type=float, default=3.0)
ap.add_argument("--tl-fps", type=float, default=60.0)
ap.add_argument("--reuse-assets", action="store_true")
A = ap.parse_args()
REV = A.out_dir; AST = REV + "/assets"; os.makedirs(AST, exist_ok=True)
SR, CAP = A.sr, A.cap
SKIP = A.reuse_assets and os.path.exists(AST + "/snip_0.wav")

raw = subprocess.run(["ffmpeg", "-v", "error", "-i", A.mic, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                     capture_output=True).stdout
audio = np.frombuffer(raw, np.float32).copy()
data = json.load(open(A.clips)); clips = data["clips"] if isinstance(data, dict) else data
source_video = data.get("source_video", "") if isinstance(data, dict) else ""
structural_reviews = data.get("structural_restart_reviews") or data.get("structural_cuts") or [] if isinstance(data, dict) else []
N = len(clips)
cats = {}
if A.categories and os.path.exists(A.categories):
    cats = {r["i"]: r for r in json.load(open(A.categories)) if "i" in r}

def tc(f):
    s = f / A.tl_fps; return "%d:%05.2f" % (int(s // 60), s % 60)
def seg2(r, side=None):
    s = r["left"] / (r["fps"] or A.tl_fps); d = r["dur"] / A.tl_fps
    a = audio[int(s * SR):int((s + d) * SR)]; ss, se = s, s + d
    if side == "before" and len(a) > CAP * SR: a = a[-int(CAP * SR):]; ss = (s + d) - CAP
    if side == "after" and len(a) > CAP * SR: a = a[:int(CAP * SR)]; se = s + CAP
    return a, ss, se

pink = [i for i, c in enumerate(clips) if c.get("color") == "Pink"]
groups, cur = [], []
for idx in pink:
    if cur and idx == cur[-1] + 1: cur.append(idx)
    else:
        if cur: groups.append(cur)
        cur = [idx]
if cur: groups.append(cur)

meta, segmap = [], {}
for g, cl in enumerate(groups):
    first, last = cl[0], cl[-1]
    parts, bounds, segs, pos = [], [], [], 0
    def add(ci, kind, side=None):
        global pos
        a, ss, se = seg2(clips[ci], side); parts.append(a); bounds.append((pos, pos + len(a), kind, ci, ss, se))
        segs.append(dict(clip_idx=ci, kind=kind, src_start=round(ss, 4), src_end=round(se, 4),
                         snip_start=round(pos / SR, 4), snip_end=round((pos + len(a)) / SR, 4))); pos += len(a)
    if first - 1 >= 0: add(first - 1, "ctx", "before")
    for idx in cl: add(idx, "pink")
    if last + 1 < N: add(last + 1, "ctx", "after")
    snip = np.concatenate(parts) if parts else np.zeros(1, np.float32); segmap[g] = segs
    if not SKIP:
        wavfile.write(AST + "/snip_%d.wav" % g, SR, (np.clip(snip, -1, 1) * 32767).astype(np.int16))
        W, H = 1100, 170; img = Image.new("RGB", (W, H), (22, 22, 28)); dr = ImageDraw.Draw(img); mid = H // 2; n = max(1, len(snip))
        for (b0, b1, k, _ci, _ss, _se) in bounds:
            if k == "pink": dr.rectangle([int(b0 / n * (W - 1)), 0, int(b1 / n * (W - 1)), H], fill=(64, 30, 38))
        for x in range(W - 1):
            a0 = x * n // (W - 1); s = snip[a0:(x + 1) * n // (W - 1) + 1]
            if len(s) == 0: continue
            col = (120, 200, 140)
            for (b0, b1, k, _ci, _ss, _se) in bounds:
                if b0 <= a0 < b1: col = (245, 110, 110) if k == "pink" else (120, 200, 140); break
            dr.line([(x, int(mid - s.max() * mid * .92)), (x, int(mid - s.min() * mid * .92))], fill=col)
        img.save(AST + "/wave_%d.png" % g)
    seg_by_clip = {int(s["clip_idx"]): s for s in segs}
    pk = [
        dict(
            idx=i,
            tc=tc(clips[i]["start"]),
            dur=round(clips[i]["dur"] / A.tl_fps, 2),
            src_start=seg_by_clip[i]["src_start"],
            src_end=seg_by_clip[i]["src_end"],
            snip_start=seg_by_clip[i]["snip_start"],
            snip_end=seg_by_clip[i]["snip_end"],
            run_vs=cats.get(i, {}).get("run_vs", "?"),
            zcr=cats.get(i, {}).get("zcr", "?"),
        )
        for i in cl
    ]
    regions = [
        dict(
            clip_idx=int(s["clip_idx"]),
            kind=s["kind"],
            left=round(float(s["snip_start"]) / max(0.001, len(snip) / SR) * 100.0, 4),
            width=round((float(s["snip_end"]) - float(s["snip_start"])) / max(0.001, len(snip) / SR) * 100.0, 4),
            src_start=s["src_start"],
            src_end=s["src_end"],
            snip_start=s["snip_start"],
            snip_end=s["snip_end"],
        )
        for s in segs
    ]
    meta.append(dict(g=g, pinks=pk, dur=round(len(snip) / SR, 3),
                     regions=regions,
                     pink_ranges=[[round(b0 / SR, 3), round(b1 / SR, 3)] for (b0, b1, k, _ci, _ss, _se) in bounds if k == "pink"],
                     before=tc(clips[first - 1]["start"]) if first - 1 >= 0 else "-",
                     after=tc(clips[last + 1]["start"]) if last + 1 < N else "-"))
json.dump(segmap, open(REV + "/segmap.json", "w"), indent=1)
total = sum(len(m["pinks"]) for m in meta)

INITIAL = {"pink": {}, "cuts": {}}
if A.preload and os.path.exists(A.preload):
    try:
        d = json.load(open(A.preload))
        INITIAL = {"pink": d.get("pink", d if "pink" not in d else {}), "cuts": d.get("cuts", {})}
    except Exception:
        pass

def card(m):
    rg = "".join((
                  '<div class="clipseg {kind}" data-idx="{idx}" title="clip {idx} {kind} | src {ss:.3f}-{se:.3f}s | snippet {ps:.3f}-{pe:.3f}s" '
                  'style="left:{left:.4f}%;width:{width:.4f}%"><span>{label}</span></div>'
                  ).format(
                      kind=r["kind"],
                      idx=r["clip_idx"],
                      ss=float(r["src_start"]),
                      se=float(r["src_end"]),
                      ps=float(r["snip_start"]),
                      pe=float(r["snip_end"]),
                      left=float(r["left"]),
                      width=float(r["width"]),
                      label=("ctx " if r["kind"] == "ctx" else "") + str(r["clip_idx"]),
                  ) for r in m["regions"])
    tg = "".join(('<div class="seg" data-idx="{i}"><span class="lab">Clip {i} &middot; src {ss:.3f}-{se:.3f}s &middot; snippet {ps:.3f}-{pe:.3f}s &middot; {d}s <span class="st">tl {tc} &middot; run {rv}/zcr {zc}</span></span>'
                  '<div class="tg"><button class="keep" data-v="keep">KEEP</button><button class="cut" data-v="cut">CUT</button></div></div>'
                  ).format(i=p["idx"], tc=p["tc"], d=p["dur"], ss=float(p["src_start"]), se=float(p["src_end"]),
                           ps=float(p["snip_start"]), pe=float(p["snip_end"]), rv=p["run_vs"], zc=p["zcr"]) for p in m["pinks"])
    starts = ", ".join("%.1fs" % pr[0] for pr in m["pink_ranges"])
    return ('<div class="card" data-g="{g}"><div class="hd">Group {g} &nbsp;&middot;&nbsp; before {bf} -> <b>PINK</b> -> after {af}</div>'
            '<div class="wavewrap"><img loading="lazy" src="assets/wave_{g}.png"><div class="clips">{rg}</div><div class="playhead"></div><div class="nowpink">&#9654; IN PINK</div></div>'
            '<div class="cap"><span style="color:#f77">&#9679;</span> red at {starts} &middot; drag=new cut &middot; drag box=move &middot; edges=resize &middot; right-click=clear</div>'
            '<div class="row"><audio controls preload="none" src="assets/snip_{g}.wav"></audio><button class="prev" type="button">&#9654; Preview result</button></div>'
            '<div class="segs">{tg}</div></div>').format(g=m["g"], bf=m["before"], af=m["after"], tg=tg, starts=starts, rg=rg)


def ffmpeg_preview(cmd):
    subprocess.run(cmd, check=True)


def maybe_build_structural_assets(row, idx):
    if not source_video or not os.path.exists(source_video) or not os.path.exists(A.mic):
        return dict(row)
    start = float(row.get("start_sec", row.get("source_start_sec", 0.0)))
    end = float(row.get("end_sec", row.get("source_end_sec", start)))
    dur = max(0.001, end - start)
    removed = AST + "/struct_removed_%d.mp4" % idx
    flow = AST + "/struct_flow_%d.mp4" % idx
    vfilter = "scale=640:-2,fps=30,setpts=PTS-STARTPTS"
    afilter = "aresample=44100,asetpts=PTS-STARTPTS"
    if (not A.reuse_assets) or (not os.path.exists(removed)):
        ffmpeg_preview([
            "ffmpeg", "-y", "-v", "error",
            "-ss", "%.3f" % start, "-t", "%.3f" % dur, "-i", source_video,
            "-ss", "%.3f" % start, "-t", "%.3f" % dur, "-i", A.mic,
            "-filter_complex", "[0:v]%s[v];[1:a]%s[a]" % (vfilter, afilter),
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32",
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
            removed,
        ])
    pre = min(8.0, start)
    post = 8.0
    pre_start = max(0.0, start - pre)
    if (not A.reuse_assets) or (not os.path.exists(flow)):
        ffmpeg_preview([
            "ffmpeg", "-y", "-v", "error",
            "-ss", "%.3f" % pre_start, "-t", "%.3f" % pre, "-i", source_video,
            "-ss", "%.3f" % pre_start, "-t", "%.3f" % pre, "-i", A.mic,
            "-ss", "%.3f" % end, "-t", "%.3f" % post, "-i", source_video,
            "-ss", "%.3f" % end, "-t", "%.3f" % post, "-i", A.mic,
            "-filter_complex",
            "[0:v]%s[v0];[1:a]%s[a0];[2:v]%s[v1];[3:a]%s[a1];"
            "[v0][a0][v1][a1]concat=n=2:v=1:a=1[outv][outa]" % (vfilter, afilter, vfilter, afilter),
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32",
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
            flow,
        ])
    return {**row, "removed_video": "assets/struct_removed_%d.mp4" % idx, "flow_video": "assets/struct_flow_%d.mp4" % idx}


def structural_card(row):
    label = html.escape(str(row.get("label") or row.get("type") or "structural_cut"))
    status = html.escape(str(row.get("status") or row.get("confidence") or "locked"))
    reason = html.escape(str(row.get("reason") or ""))
    start = float(row.get("start_sec", row.get("source_start_sec", 0.0)))
    end = float(row.get("end_sec", row.get("source_end_sec", start)))
    match = row.get("matches_locked_reference")
    match_text = "LLM confirmed" if match is True else status
    media = ""
    if row.get("removed_video"):
        media = (
            '<div class="smedia"><div><div class="vlabel">Removed section</div>'
            '<video controls preload="none" src="{removed}"></video></div>'
            '<div><div class="vlabel">Flow with cut omitted</div>'
            '<video controls preload="none" src="{flow}"></video></div></div>'
        ).format(removed=html.escape(row["removed_video"]), flow=html.escape(row["flow_video"]))
    return (
        '<div class="scut"><div><b>{label}</b> <span>{match}</span></div>'
        '<div class="stime">source {start:.3f}s -> {end:.3f}s &middot; duration {dur:.3f}s</div>'
        '<div class="sreason">{reason}</div>{media}</div>'
    ).format(label=label, match=html.escape(match_text), start=start, end=end, dur=max(0.0, end - start), reason=reason, media=media)

STRUCTURAL_HTML = ""
if structural_reviews:
    structural_reviews = [maybe_build_structural_assets(row, i) for i, row in enumerate(structural_reviews)]
    STRUCTURAL_HTML = (
        '<section class="structural"><h2>Structural Narrative Cuts Already Removed</h2>'
        '<p>These source ranges are removed before this review-base clip list is built. '
        'The cards below are only smaller candidate leads outside these structural cuts.</p>'
        + "".join(structural_card(row) for row in structural_reviews)
        + '</section>'
    )

CARDS = "".join(card(m) for m in meta)
GROUPS_JS = json.dumps({m["g"]: {"dur": m["dur"], "pink": m["pink_ranges"]} for m in meta})

T = """<!doctype html><html><head><meta charset="utf-8"><title>Cut Review</title><style>
body{background:#15151a;color:#e8e8ee;font:14px/1.4 system-ui,Arial;margin:0;padding:18px 18px 92px}
h1{font-size:20px;margin:0 0 4px}.sub{color:#9aa;margin:0 0 16px}
.structural{background:#22242b;border:1px solid #4b4b58;border-radius:10px;padding:12px;margin:0 0 16px}.structural h2{font-size:16px;margin:0 0 4px}.structural p{color:#b8b8c8;margin:0 0 10px}.scut{background:#191a20;border-left:4px solid #d29044;border-radius:6px;padding:9px 10px;margin:8px 0}.scut span{color:#ffd39b;font-size:12px;margin-left:8px}.stime{color:#eee;margin-top:2px}.sreason{color:#b8b8c8;font-size:13px;margin-top:3px}.smedia{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px;margin-top:10px}.smedia video{width:100%;max-height:260px;background:#000;border-radius:6px}.vlabel{font-size:12px;color:#d5d5e0;margin:0 0 4px}
.card{background:#1e1e26;border:1px solid #33333f;border-radius:10px;padding:12px;margin:0 0 14px}.hd{font-weight:600;margin-bottom:8px;color:#cdd}
.wavewrap{position:relative;cursor:crosshair;user-select:none;overflow:hidden}.card img{width:100%;display:block;border-radius:6px;background:#000;pointer-events:none}
.clips{position:absolute;inset:0;z-index:2;pointer-events:none}.clipseg{position:absolute;top:0;bottom:0;border-left:2px solid rgba(255,255,255,.72);border-right:1px solid rgba(255,255,255,.32);box-sizing:border-box}.clipseg span{position:absolute;z-index:2;left:3px;top:4px;background:rgba(0,0,0,.62);color:#f3f3f6;border-radius:3px;padding:1px 4px;font-size:11px;max-width:calc(100% - 6px);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.clipseg.ctx{background:rgba(190,190,210,.08)}.clipseg.pink{background:rgba(232,171,73,.18)}.clipseg.pink.keep{background:rgba(46,155,84,.38);border-left-color:#68e089}.clipseg.pink.cut{background:rgba(194,59,59,.52);border-left-color:#ff7878}.clipseg.pink.cut:after{content:"";position:absolute;inset:0;background:repeating-linear-gradient(135deg,rgba(0,0,0,.0) 0 7px,rgba(0,0,0,.24) 7px 10px)}
.playhead{position:absolute;top:0;bottom:0;width:2px;background:#fff;left:0;opacity:0;pointer-events:none;box-shadow:0 0 5px rgba(255,255,255,.8);z-index:4}.playhead.vis{opacity:.95}.playhead.red{background:#ff5252;box-shadow:0 0 8px #ff5252}
.nowpink{position:absolute;top:6px;right:8px;background:#c23b3b;color:#fff;font-weight:700;font-size:12px;padding:3px 9px;border-radius:5px;opacity:0;pointer-events:none;z-index:5}.nowpink.show{opacity:1}
.cutbox{position:absolute;top:0;bottom:0;background:rgba(255,60,60,.30);border-left:3px solid #fd0;border-right:3px solid #fd0;cursor:move;z-index:3}.cutbox.prov{background:rgba(255,210,60,.25);pointer-events:none}
.cutbox .cbx{position:absolute;top:2px;right:3px;width:16px;height:16px;line-height:14px;text-align:center;background:#000a;color:#fff;border-radius:3px;font-size:13px;cursor:pointer}
.cap{color:#9a9ab0;font-size:12px;margin:6px 2px 2px}.row{display:flex;gap:10px;align-items:center;margin:8px 0}audio{flex:1}
.prev{background:#3b6fc2;color:#fff;border:0;border-radius:7px;padding:8px 14px;font-weight:700;cursor:pointer;white-space:nowrap}
.segs{display:flex;flex-direction:column;gap:6px}.seg{display:flex;justify-content:space-between;align-items:center;background:#262630;border-radius:8px;padding:8px 10px}
.lab{color:#e6e6ee}.st{color:#8a8aa0;font-size:12px;margin-left:6px}
.tg button{border:0;border-radius:6px;padding:7px 16px;font-weight:700;cursor:pointer;color:#fff;opacity:.35;margin-left:6px}.tg .keep{background:#2e9b54}.tg .cut{background:#c23b3b}.tg button.on{opacity:1;outline:2px solid #fff}
footer{position:fixed;left:0;right:0;bottom:0;background:#0e0e12;border-top:1px solid #33333f;padding:12px 18px;display:flex;gap:14px;align-items:center}
#save{background:#3b6fc2;color:#fff;border:0;border-radius:8px;padding:10px 22px;font-weight:700;font-size:15px;cursor:pointer}#cnt{color:#bbb}#out{flex:1;height:34px;background:#1a1a22;color:#9c9;border:1px solid #333;border-radius:6px;padding:6px;font-family:monospace;font-size:11px}
</style></head><body><h1>Cut Review &nbsp;-&nbsp; __N__ segments</h1>
<p class="sub">Last saved decisions pre-loaded. Drag empty wave=new cut; drag box=move; edges=resize; right-click=clear; Preview result=hear with cuts removed; then Save.</p>
__STRUCTURAL__
__CARDS__
<footer><button id="save">Save decisions</button><span id="cnt"></span><input id="out" readonly></footer>
<script>
var GROUPS=__GROUPS__, INITIAL=__INITIAL__, dec={}, CUTS={}, boxDrag=null;
function setSegState(idx,state){document.querySelectorAll('.clipseg.pink[data-idx="'+idx+'"]').forEach(function(n){n.classList.remove('keep','cut');n.classList.add(state==='cut'?'cut':'keep');n.setAttribute('data-state',state==='cut'?'cut':'keep');});}
function upd(){var c=0,k=0,t=0;for(var i in dec){if(dec[i]==='cut')c++;else k++;}for(var g in CUTS)t+=CUTS[g].length;document.getElementById('cnt').textContent=k+' keep / '+c+' cut / '+t+' trim';}
document.querySelectorAll('.seg').forEach(function(s){var idx=s.dataset.idx;dec[idx]=(INITIAL.pink&&INITIAL.pink[idx])||'keep';
  s.querySelector('.keep').classList.toggle('on',dec[idx]==='keep');s.querySelector('.cut').classList.toggle('on',dec[idx]==='cut');
  setSegState(idx,dec[idx]);
  s.querySelectorAll('button').forEach(function(b){b.onclick=function(){dec[idx]=b.dataset.v;s.querySelector('.keep').classList.toggle('on',dec[idx]==='keep');s.querySelector('.cut').classList.toggle('on',dec[idx]==='cut');setSegState(idx,dec[idx]);upd();};});});
document.querySelectorAll('.card').forEach(function(card){var g=card.dataset.g,info=GROUPS[g]||{dur:0,pink:[]};
  var audio=card.querySelector('audio'),ph=card.querySelector('.playhead'),badge=card.querySelector('.nowpink'),ww=card.querySelector('.wavewrap');
  CUTS[g]=(INITIAL.cuts&&INITIAL.cuts[g]?INITIAL.cuts[g].map(function(c){return c.slice();}):[]);var prevMode=false,skips=[];
  function dur(){return audio.duration||info.dur||1;}
  function loop(){if(audio.paused)return;if(prevMode){for(var i=0;i<skips.length;i++){if(audio.currentTime>=skips[i][0]&&audio.currentTime<skips[i][1]-0.005){audio.currentTime=skips[i][1];break;}}}
    var f=audio.currentTime/dur();if(f>1)f=1;ph.style.left=(f*100)+'%';var inP=info.pink.some(function(r){return audio.currentTime>=r[0]&&audio.currentTime<=r[1];});ph.classList.toggle('red',inP);badge.classList.toggle('show',inP);requestAnimationFrame(loop);}
  audio.addEventListener('play',function(){ph.classList.add('vis');requestAnimationFrame(loop);});audio.addEventListener('pause',function(){prevMode=false;});
  audio.addEventListener('ended',function(){prevMode=false;badge.classList.remove('show');});audio.addEventListener('loadedmetadata',render);
  card.querySelector('.prev').onclick=function(){skips=CUTS[g].map(function(c){return c.slice();});info.pink.forEach(function(r,i){var el=card.querySelectorAll('.seg')[i];if(el&&dec[el.dataset.idx]==='cut')skips.push(r.slice());});skips.sort(function(a,b){return a[0]-b[0];});prevMode=true;audio.currentTime=0;audio.play();};
  function pxSec(px){var r=ww.getBoundingClientRect();return Math.max(0,Math.min(1,(px-r.left)/r.width))*dur();}
  function render(){ww.querySelectorAll('.cutbox:not(.prov)').forEach(function(n){n.remove();});CUTS[g].forEach(function(c,ci){var d=document.createElement('div');d.className='cutbox';d.style.left=(c[0]/dur()*100)+'%';d.style.width=(Math.max(0,c[1]-c[0])/dur()*100)+'%';
      var rm=document.createElement('div');rm.className='cbx';rm.textContent='x';d.appendChild(rm);rm.onclick=function(ev){ev.stopPropagation();CUTS[g].splice(ci,1);render();upd();};
      d.addEventListener('mousedown',function(ev){ev.stopPropagation();ev.preventDefault();var r=d.getBoundingClientRect();var off=ev.clientX-r.left;boxDrag={g:g,ci:ci,mode:off<8?'L':(off>r.width-8?'R':'M'),mx:ev.clientX,s0:c[0],e0:c[1],ww:ww,dur:dur(),render:render};});ww.appendChild(d);});}
  var down=false,sx=0,prov=null;
  ww.addEventListener('mousedown',function(e){if(e.target.classList.contains('cutbox')||e.target.classList.contains('cbx'))return;if(e.button!==0)return;down=true;sx=e.clientX;});
  ww.addEventListener('contextmenu',function(e){e.preventDefault();CUTS[g]=[];render();upd();});
  ww.addEventListener('mousemove',function(e){if(!down||boxDrag)return;if(!prov){prov=document.createElement('div');prov.className='cutbox prov';ww.appendChild(prov);}var r=ww.getBoundingClientRect();var x0=Math.min(sx,e.clientX)-r.left,x1=Math.max(sx,e.clientX)-r.left;prov.style.left=(x0/r.width*100)+'%';prov.style.width=((x1-x0)/r.width*100)+'%';});
  window.addEventListener('mouseup',function(e){if(boxDrag)return;if(!down)return;down=false;if(prov){ww.removeChild(prov);prov=null;}if(Math.abs(e.clientX-sx)<6){audio.currentTime=pxSec(e.clientX);ph.classList.add('vis');loop();return;}var a=pxSec(sx),b=pxSec(e.clientX);CUTS[g].push([+Math.min(a,b).toFixed(3),+Math.max(a,b).toFixed(3)]);render();upd();});
  render();});
window.addEventListener('mousemove',function(e){if(!boxDrag)return;var dsec=(e.clientX-boxDrag.mx)/boxDrag.ww.getBoundingClientRect().width*boxDrag.dur;var s=boxDrag.s0,en=boxDrag.e0,D=boxDrag.dur;
  if(boxDrag.mode==='M'){s+=dsec;en+=dsec;if(s<0){en-=s;s=0;}if(en>D){s-=(en-D);en=D;}}else if(boxDrag.mode==='L'){s=Math.max(0,Math.min(boxDrag.s0+dsec,en-0.02));}else{en=Math.min(D,Math.max(boxDrag.e0+dsec,s+0.02));}
  CUTS[boxDrag.g][boxDrag.ci]=[+s.toFixed(3),+en.toFixed(3)];boxDrag.render();upd();});
window.addEventListener('mouseup',function(){boxDrag=null;});upd();
document.getElementById('save').onclick=function(){var cuts={};for(var g in CUTS)if(CUTS[g].length)cuts[g]=CUTS[g];var j=JSON.stringify({pink:dec,cuts:cuts},null,1);document.getElementById('out').value=j;var b=new Blob([j],{type:'application/json'});var a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='pink_decisions.json';a.click();};
</script></body></html>"""
open(REV + "/index.html", "w", encoding="utf-8").write(
    T.replace("__STRUCTURAL__", STRUCTURAL_HTML).replace("__CARDS__", CARDS).replace("__N__", str(total)).replace("__GROUPS__", GROUPS_JS).replace("__INITIAL__", json.dumps(INITIAL)))
print("groups:", len(meta), "pink:", total, "| reused assets:", SKIP, "| wrote", REV + "/index.html + segmap.json")
