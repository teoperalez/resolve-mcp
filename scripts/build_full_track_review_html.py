from __future__ import annotations

import argparse
import array
import html
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse


REPO_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resolve_mcp.orchestrator.fcpxml_review import load_fcpxml_review_model


def norm_file_path(value: str) -> str:
    if value.startswith("file://"):
        parsed = urlparse(value)
        path = unquote(parsed.path)
        if len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return path.replace("/", "\\")
    return value


def file_uri(path: str | Path) -> str:
    text = str(path)
    if text.startswith("file://"):
        return text
    return Path(text).resolve().as_uri()


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_waveform(source_video: Path, *, hz: int, sr: int) -> dict:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg was not found on PATH")

    bucket_samples = max(1, int(round(sr / hz)))
    actual_hz = sr / bucket_samples
    cmd = [
        ffmpeg,
        "-v",
        "error",
        "-i",
        str(source_video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sr),
        "-f",
        "f32le",
        "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    assert proc.stderr is not None

    peaks: list[float] = []
    carry = b""
    count = 0
    peak = 0.0
    while True:
        chunk = proc.stdout.read(1024 * 1024)
        if not chunk:
            break
        chunk = carry + chunk
        whole = (len(chunk) // 4) * 4
        carry = chunk[whole:]
        samples = array.array("f")
        samples.frombytes(chunk[:whole])
        if sys.byteorder != "little":
            samples.byteswap()
        for sample in samples:
            value = abs(float(sample))
            if value > peak:
                peak = value
            count += 1
            if count >= bucket_samples:
                peaks.append(round(min(1.0, peak), 4))
                count = 0
                peak = 0.0
    if count:
        peaks.append(round(min(1.0, peak), 4))

    stderr = proc.stderr.read().decode("utf-8", errors="replace")
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(stderr.strip() or f"ffmpeg exited with status {rc}")

    return {
        "kind": "source_peak_abs_mono",
        "source_video": str(source_video),
        "hz": actual_hz,
        "sample_rate": sr,
        "bucket_samples": bucket_samples,
        "peaks": peaks,
    }


def build_payload(args: argparse.Namespace) -> dict:
    model = load_fcpxml_review_model(args.fcpxml, fps=args.fps, video_only=True)
    segments = []
    first_source = ""
    for index, segment in enumerate(model.video_segments):
        source_path = norm_file_path(segment.source_path)
        if source_path and not first_source:
            first_source = source_path
        tl_start = segment.offset_frames / args.fps
        duration = segment.duration_frames / args.fps
        src_start = segment.source_start_frames / args.fps
        segments.append(
            {
                "idx": index,
                "label": segment.name or f"segment {index + 1}",
                "tlStart": round(tl_start, 6),
                "tlEnd": round(tl_start + duration, 6),
                "srcStart": round(src_start, 6),
                "srcEnd": round(src_start + duration, 6),
                "duration": round(duration, 6),
                "source": source_path,
            }
        )

    source_video = args.source_video or (Path(first_source) if first_source else None)
    if not source_video:
        raise SystemExit("Could not infer source video. Pass --source-video.")

    waveform = None
    if not args.no_waveform:
        print(f"Building waveform peaks from {source_video} ...", file=sys.stderr)
        waveform = build_waveform(Path(source_video), hz=args.waveform_hz, sr=args.waveform_sr)

    total_duration = max((item["tlEnd"] for item in segments), default=0.0)
    payload = {
        "schema": "minimum_battles_full_track_review_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_fcpxml": str(args.fcpxml),
        "source_video": str(source_video),
        "source_video_uri": file_uri(source_video),
        "timeline_name": args.timeline_name,
        "fps": args.fps,
        "total_duration": round(total_duration, 6),
        "segment_count": len(segments),
        "segments": segments,
        "waveform": waveform,
    }
    return payload


def render_html(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    data_script = data.replace("</", "<\\/").replace("<", "\\u003c")
    title = html.escape(str(payload.get("timeline_name") or "Full Track Review"))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  color-scheme: dark;
  --bg: #111318;
  --panel: #1b1f27;
  --panel2: #222833;
  --text: #eef2f7;
  --muted: #9aa7b6;
  --line: #313947;
  --keep: #3bb273;
  --cut: #ef5b5b;
  --manual: #f6c451;
  --accent: #74a7ff;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: Segoe UI, Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
}}
header {{
  position: sticky;
  top: 0;
  z-index: 10;
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
  background: rgba(17, 19, 24, 0.96);
}}
h1 {{
  margin: 0 0 8px;
  font-size: 18px;
  font-weight: 650;
}}
.controls {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}}
button, input {{
  border: 1px solid var(--line);
  background: var(--panel2);
  color: var(--text);
  border-radius: 6px;
  min-height: 34px;
  padding: 6px 10px;
  font: inherit;
}}
button:hover {{ border-color: var(--accent); }}
button.primary {{ background: #24466f; border-color: #3b70af; }}
label {{ color: var(--muted); font-size: 13px; display: flex; align-items: center; gap: 6px; }}
main {{ padding: 14px 16px 24px; }}
.stage {{
  display: grid;
  grid-template-columns: minmax(320px, 720px) 1fr;
  gap: 14px;
  align-items: start;
}}
video {{
  width: 100%;
  max-height: 52vh;
  background: #000;
  border: 1px solid var(--line);
  border-radius: 8px;
}}
.panel {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
}}
.status {{
  display: grid;
  gap: 7px;
  color: var(--muted);
  font-size: 13px;
}}
.status b {{ color: var(--text); font-weight: 600; }}
.timelinePanel {{ margin-top: 14px; }}
.timelineTop {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  color: var(--muted);
  font-size: 13px;
}}
#timeline {{
  position: relative;
  overflow-x: auto;
  overflow-y: hidden;
  height: 230px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #0c0f14;
  cursor: crosshair;
}}
#track {{
  position: relative;
  height: 100%;
  min-width: 100%;
}}
.seg {{
  position: absolute;
  top: 32px;
  height: 38px;
  border-left: 1px solid rgba(255,255,255,.18);
  background: linear-gradient(180deg, rgba(59,178,115,.95), rgba(37,128,79,.95));
  overflow: hidden;
  z-index: 2;
}}
.seg.cut {{
  background: linear-gradient(180deg, rgba(239,91,91,.95), rgba(156,49,49,.95));
}}
.seg:hover {{ outline: 2px solid var(--accent); z-index: 3; }}
.seg span {{
  display: block;
  padding: 5px 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 12px;
}}
.manual {{
  position: absolute;
  top: 158px;
  height: 30px;
  background: rgba(246, 196, 81, .84);
  border: 1px solid rgba(255,255,255,.45);
  border-radius: 4px;
  z-index: 4;
}}
.manual:hover {{ outline: 2px solid #fff; }}
.range {{
  position: absolute;
  top: 8px;
  height: 18px;
  background: rgba(116,167,255,.24);
  border-left: 2px solid var(--accent);
  border-right: 2px solid var(--accent);
  pointer-events: none;
}}
#playhead {{
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: #fff;
  box-shadow: 0 0 0 1px #111, 0 0 8px #fff;
  z-index: 6;
  pointer-events: none;
}}
#dragBox {{
  position: absolute;
  top: 194px;
  height: 28px;
  background: rgba(246,196,81,.35);
  border: 1px dashed var(--manual);
  display: none;
  pointer-events: none;
  z-index: 7;
}}
#waveformCanvas {{
  position: absolute;
  top: 80px;
  height: 68px;
  pointer-events: none;
  z-index: 1;
}}
.legend {{
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}}
.chip {{ display: inline-flex; align-items: center; gap: 5px; }}
.swatch {{ width: 12px; height: 12px; border-radius: 2px; display: inline-block; }}
textarea {{
  width: 100%;
  min-height: 150px;
  margin-top: 12px;
  color: var(--text);
  background: #0d1015;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  font-family: Consolas, monospace;
  font-size: 12px;
}}
@media (max-width: 900px) {{
  .stage {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="controls">
    <button id="playPreview" class="primary" type="button">Preview Result</button>
    <button id="pause" type="button">Pause</button>
    <button id="clearRange" type="button">Clear In/Out</button>
    <button id="undoManual" type="button">Undo Manual Cut</button>
    <button id="save" type="button">Save Decisions</button>
    <label>Zoom <input id="zoom" type="range" min="1" max="48" step="0.5" value="4"></label>
  </div>
</header>
<main>
  <section class="stage">
    <video id="player" preload="metadata" controls></video>
    <aside class="panel status">
      <div><b id="timeText">00:00:00.000</b></div>
      <div>In: <b id="inText">unset</b> &nbsp; Out: <b id="outText">unset</b></div>
      <div>Segments cut: <b id="cutCount">0</b> &nbsp; Manual cuts: <b id="manualCount">0</b></div>
      <div>Right-click a segment to toggle keep/cut. Drag on the track to add a manual cut. Press <b>i</b> or <b>o</b> at the playhead.</div>
      <div>Wheel over the waveform/timeline to zoom. Press <b>1</b> to zoom out or <b>2</b> to zoom in.</div>
      <div class="legend">
        <span class="chip"><span class="swatch" style="background:var(--keep)"></span>keep</span>
        <span class="chip"><span class="swatch" style="background:var(--cut)"></span>cut</span>
        <span class="chip"><span class="swatch" style="background:var(--manual)"></span>manual cut</span>
      </div>
    </aside>
  </section>
  <section class="timelinePanel panel">
    <div class="timelineTop">
      <div id="summary"></div>
      <div id="hoverText"></div>
    </div>
    <div id="timeline">
      <div id="track">
        <canvas id="waveformCanvas"></canvas>
        <div id="rangeBox" class="range"></div>
        <div id="playhead"></div>
        <div id="dragBox"></div>
      </div>
    </div>
  </section>
  <textarea id="decisionText" spellcheck="false"></textarea>
</main>
<script id="review-data" type="application/json">{data_script}</script>
<script>
const DATA = JSON.parse(document.getElementById('review-data').textContent);
const segments = DATA.segments;
const waveform = DATA.waveform || null;
const player = document.getElementById('player');
const timeline = document.getElementById('timeline');
const track = document.getElementById('track');
const waveformCanvas = document.getElementById('waveformCanvas');
const playhead = document.getElementById('playhead');
const dragBox = document.getElementById('dragBox');
const rangeBox = document.getElementById('rangeBox');
const decisionText = document.getElementById('decisionText');
const zoomInput = document.getElementById('zoom');
const state = {{
  pxPerSec: 4,
  segmentCuts: {{}},
  manualCuts: [],
  inSec: null,
  outSec: null,
  playheadSec: 0,
  previewRanges: [],
  rangeIndex: -1,
  dragging: null
}};
player.src = DATA.source_video_uri;

function fmt(sec) {{
  sec = Math.max(0, Number(sec) || 0);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  const ms = Math.floor((sec - Math.floor(sec)) * 1000);
  return String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0') + '.' + String(ms).padStart(3,'0');
}}
function clampTime(sec) {{
  return Math.max(0, Math.min(DATA.total_duration, sec));
}}
function clampZoom(value) {{
  return Math.max(1, Math.min(48, Number(value) || 4));
}}
function setStatus() {{
  document.getElementById('timeText').textContent = fmt(state.playheadSec);
  document.getElementById('inText').textContent = state.inSec == null ? 'unset' : fmt(state.inSec);
  document.getElementById('outText').textContent = state.outSec == null ? 'unset' : fmt(state.outSec);
  document.getElementById('cutCount').textContent = Object.keys(state.segmentCuts).filter(k => state.segmentCuts[k] === 'cut').length;
  document.getElementById('manualCount').textContent = state.manualCuts.length;
  document.getElementById('summary').textContent = DATA.segment_count + ' segments · ' + fmt(DATA.total_duration);
  updateDecisionText();
}}
function updateDecisionText() {{
  const payload = {{
    schema: 'minimum_battles_full_track_review_decisions_v1',
    generated_at: new Date().toISOString(),
    source_fcpxml: DATA.source_fcpxml,
    source_video: DATA.source_video,
    timeline_name: DATA.timeline_name,
    segment_decisions: state.segmentCuts,
    manual_cuts: state.manualCuts,
    in_sec: state.inSec,
    out_sec: state.outSec
  }};
  decisionText.value = JSON.stringify(payload, null, 2);
}}
function resizeTrack() {{
  const width = Math.max(timeline.clientWidth, Math.ceil(DATA.total_duration * state.pxPerSec) + 1);
  track.style.width = width + 'px';
  renderSegments();
  renderManualCuts();
  renderRange();
  movePlayhead(state.playheadSec);
  drawWaveform();
}}
function setZoom(value, anchorSec = state.playheadSec) {{
  const oldZoom = state.pxPerSec;
  const next = clampZoom(value);
  const anchor = clampTime(anchorSec);
  const anchorViewportX = anchor * oldZoom - timeline.scrollLeft;
  state.pxPerSec = next;
  zoomInput.value = String(next);
  resizeTrack();
  timeline.scrollLeft = Math.max(0, anchor * state.pxPerSec - anchorViewportX);
  drawWaveform();
}}
function renderSegments() {{
  track.querySelectorAll('.seg').forEach(el => el.remove());
  const frag = document.createDocumentFragment();
  for (const seg of segments) {{
    const el = document.createElement('div');
    el.className = 'seg' + (state.segmentCuts[seg.idx] === 'cut' ? ' cut' : '');
    el.dataset.idx = seg.idx;
    el.style.left = (seg.tlStart * state.pxPerSec) + 'px';
    el.style.width = Math.max(2, (seg.tlEnd - seg.tlStart) * state.pxPerSec) + 'px';
    const span = document.createElement('span');
    span.textContent = '#' + (seg.idx + 1) + ' ' + fmt(seg.tlStart) + ' / src ' + fmt(seg.srcStart);
    el.appendChild(span);
    el.addEventListener('contextmenu', ev => {{
      ev.preventDefault();
      state.segmentCuts[seg.idx] = state.segmentCuts[seg.idx] === 'cut' ? 'keep' : 'cut';
      if (state.segmentCuts[seg.idx] === 'keep') delete state.segmentCuts[seg.idx];
      el.classList.toggle('cut', state.segmentCuts[seg.idx] === 'cut');
      setStatus();
    }});
    el.addEventListener('mouseenter', () => {{
      document.getElementById('hoverText').textContent = '#' + (seg.idx + 1) + ' ' + fmt(seg.tlStart) + '-' + fmt(seg.tlEnd) + ' source ' + fmt(seg.srcStart) + '-' + fmt(seg.srcEnd);
    }});
    frag.appendChild(el);
  }}
  track.insertBefore(frag, dragBox);
}}
function renderManualCuts() {{
  track.querySelectorAll('.manual').forEach(el => el.remove());
  for (let i = 0; i < state.manualCuts.length; i++) {{
    const cut = state.manualCuts[i];
    const el = document.createElement('div');
    el.className = 'manual';
    el.dataset.index = i;
    el.style.left = (cut[0] * state.pxPerSec) + 'px';
    el.style.width = Math.max(2, (cut[1] - cut[0]) * state.pxPerSec) + 'px';
    el.title = 'Manual cut ' + fmt(cut[0]) + '-' + fmt(cut[1]) + '. Right-click to remove.';
    el.addEventListener('contextmenu', ev => {{
      ev.preventDefault();
      state.manualCuts.splice(i, 1);
      renderManualCuts();
      setStatus();
    }});
    track.insertBefore(el, dragBox);
  }}
}}
function renderRange() {{
  if (state.inSec == null && state.outSec == null) {{
    rangeBox.style.display = 'none';
    return;
  }}
  const start = state.inSec == null ? 0 : state.inSec;
  const end = state.outSec == null ? DATA.total_duration : state.outSec;
  rangeBox.style.display = 'block';
  rangeBox.style.left = (Math.min(start, end) * state.pxPerSec) + 'px';
  rangeBox.style.width = Math.max(2, Math.abs(end - start) * state.pxPerSec) + 'px';
}}
function movePlayhead(sec) {{
  state.playheadSec = clampTime(sec);
  playhead.style.left = (state.playheadSec * state.pxPerSec) + 'px';
  setStatus();
}}
function waveformPeak(srcStart, srcEnd) {{
  if (!waveform || !waveform.peaks || !waveform.peaks.length || !waveform.hz) return 0;
  const peaks = waveform.peaks;
  const hz = waveform.hz;
  let a = Math.max(0, Math.floor(srcStart * hz));
  let b = Math.min(peaks.length - 1, Math.ceil(srcEnd * hz));
  if (b < a) b = a;
  let peak = 0;
  for (let i = a; i <= b; i++) {{
    if (peaks[i] > peak) peak = peaks[i];
  }}
  return Math.sqrt(Math.min(1, peak * 3));
}}
function drawWaveform() {{
  const cssWidth = Math.max(1, timeline.clientWidth);
  const cssHeight = 68;
  const dpr = window.devicePixelRatio || 1;
  waveformCanvas.style.left = timeline.scrollLeft + 'px';
  waveformCanvas.style.width = cssWidth + 'px';
  waveformCanvas.style.height = cssHeight + 'px';
  waveformCanvas.width = Math.ceil(cssWidth * dpr);
  waveformCanvas.height = Math.ceil(cssHeight * dpr);
  const ctx = waveformCanvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight);
  ctx.fillStyle = '#080b10';
  ctx.fillRect(0, 0, cssWidth, cssHeight);
  const center = cssHeight / 2;
  ctx.strokeStyle = '#273141';
  ctx.beginPath();
  ctx.moveTo(0, center);
  ctx.lineTo(cssWidth, center);
  ctx.stroke();
  if (!waveform || !waveform.peaks || !waveform.peaks.length) {{
    ctx.fillStyle = '#9aa7b6';
    ctx.font = '12px Segoe UI, Arial, sans-serif';
    ctx.fillText('waveform unavailable', 10, center + 4);
    return;
  }}
  ctx.strokeStyle = 'rgba(116,167,255,.92)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = 0; x < cssWidth; x++) {{
    const tlStart = (timeline.scrollLeft + x) / state.pxPerSec;
    const tlEnd = (timeline.scrollLeft + x + 1) / state.pxPerSec;
    const seg = findSegmentAtTl((tlStart + tlEnd) / 2);
    if (!seg) continue;
    const srcStart = seg.srcStart + Math.max(0, tlStart - seg.tlStart);
    const srcEnd = seg.srcStart + Math.min(seg.duration, tlEnd - seg.tlStart);
    const amp = waveformPeak(srcStart, srcEnd);
    const half = Math.max(1, amp * (cssHeight * 0.46));
    ctx.moveTo(x + 0.5, center - half);
    ctx.lineTo(x + 0.5, center + half);
  }}
  ctx.stroke();
}}
function timeFromEvent(ev) {{
  const rect = track.getBoundingClientRect();
  return clampTime((ev.clientX - rect.left) / state.pxPerSec);
}}
function findSegmentAtTl(sec) {{
  let lo = 0, hi = segments.length - 1;
  while (lo <= hi) {{
    const mid = (lo + hi) >> 1;
    const seg = segments[mid];
    if (sec < seg.tlStart) hi = mid - 1;
    else if (sec >= seg.tlEnd) lo = mid + 1;
    else return seg;
  }}
  return null;
}}
function seekTimeline(sec) {{
  const seg = findSegmentAtTl(sec);
  movePlayhead(sec);
  if (!seg) return;
  player.currentTime = seg.srcStart + (sec - seg.tlStart);
}}
function subtractCuts(start, end, cuts) {{
  let ranges = [[start, end]];
  for (const cut of cuts) {{
    const cs = cut[0], ce = cut[1];
    const next = [];
    for (const r of ranges) {{
      const os = Math.max(r[0], cs), oe = Math.min(r[1], ce);
      if (oe <= os) next.push(r);
      else {{
        if (r[0] < os) next.push([r[0], os]);
        if (oe < r[1]) next.push([oe, r[1]]);
      }}
    }}
    ranges = next;
  }}
  return ranges.filter(r => r[1] > r[0] + 0.01);
}}
function buildPreviewRanges(startSec, endSec) {{
  const start = clampTime(startSec == null ? 0 : startSec);
  const end = clampTime(endSec == null ? DATA.total_duration : endSec);
  const lo = Math.min(start, end), hi = Math.max(start, end);
  const ranges = [];
  for (const seg of segments) {{
    if (state.segmentCuts[seg.idx] === 'cut') continue;
    const a = Math.max(seg.tlStart, lo);
    const b = Math.min(seg.tlEnd, hi);
    if (b <= a) continue;
    for (const frag of subtractCuts(a, b, state.manualCuts)) {{
      const srcStart = seg.srcStart + (frag[0] - seg.tlStart);
      const srcEnd = seg.srcStart + (frag[1] - seg.tlStart);
      ranges.push({{tlStart: frag[0], tlEnd: frag[1], srcStart, srcEnd, segIdx: seg.idx}});
    }}
  }}
  return ranges;
}}
function playRange(index) {{
  if (index < 0 || index >= state.previewRanges.length) {{
    state.rangeIndex = -1;
    player.pause();
    return;
  }}
  state.rangeIndex = index;
  const r = state.previewRanges[index];
  player.currentTime = r.srcStart;
  movePlayhead(r.tlStart);
  player.play();
}}
function startPreview() {{
  const start = state.inSec == null ? state.playheadSec : state.inSec;
  const end = state.outSec == null ? DATA.total_duration : state.outSec;
  state.previewRanges = buildPreviewRanges(start, end);
  if (!state.previewRanges.length) return;
  playRange(0);
}}
player.addEventListener('timeupdate', () => {{
  if (state.rangeIndex < 0) return;
  const r = state.previewRanges[state.rangeIndex];
  const tl = r.tlStart + (player.currentTime - r.srcStart);
  movePlayhead(Math.min(tl, r.tlEnd));
  if (player.currentTime >= r.srcEnd - 0.035 || tl >= r.tlEnd - 0.035) {{
    playRange(state.rangeIndex + 1);
  }}
}});
player.addEventListener('pause', () => {{
  if (state.rangeIndex >= 0) {{
    const r = state.previewRanges[state.rangeIndex];
    movePlayhead(r.tlStart + Math.max(0, player.currentTime - r.srcStart));
  }}
}});
timeline.addEventListener('mousedown', ev => {{
  if (ev.button !== 0) return;
  const t = timeFromEvent(ev);
  state.dragging = {{start: t, last: t, moved: false}};
  dragBox.style.display = 'block';
  dragBox.style.left = (t * state.pxPerSec) + 'px';
  dragBox.style.width = '1px';
}});
timeline.addEventListener('wheel', ev => {{
  ev.preventDefault();
  const factor = ev.deltaY < 0 ? 1.25 : 0.8;
  setZoom(state.pxPerSec * factor, timeFromEvent(ev));
}}, {{passive: false}});
timeline.addEventListener('scroll', drawWaveform);
window.addEventListener('mousemove', ev => {{
  if (!state.dragging) return;
  const t = timeFromEvent(ev);
  state.dragging.last = t;
  state.dragging.moved = state.dragging.moved || Math.abs(t - state.dragging.start) > 0.05;
  const a = Math.min(state.dragging.start, t);
  const b = Math.max(state.dragging.start, t);
  dragBox.style.left = (a * state.pxPerSec) + 'px';
  dragBox.style.width = Math.max(1, (b - a) * state.pxPerSec) + 'px';
}});
window.addEventListener('mouseup', ev => {{
  if (!state.dragging) return;
  const drag = state.dragging;
  state.dragging = null;
  dragBox.style.display = 'none';
  const a = Math.min(drag.start, drag.last);
  const b = Math.max(drag.start, drag.last);
  if (drag.moved && b - a > 0.05) {{
    state.manualCuts.push([Number(a.toFixed(3)), Number(b.toFixed(3))]);
    state.manualCuts.sort((x, y) => x[0] - y[0]);
    renderManualCuts();
    setStatus();
  }} else {{
    seekTimeline(a);
  }}
}});
document.getElementById('playPreview').onclick = startPreview;
document.getElementById('pause').onclick = () => {{ state.rangeIndex = -1; player.pause(); }};
document.getElementById('clearRange').onclick = () => {{ state.inSec = null; state.outSec = null; renderRange(); setStatus(); }};
document.getElementById('undoManual').onclick = () => {{ state.manualCuts.pop(); renderManualCuts(); setStatus(); }};
zoomInput.oninput = ev => {{ setZoom(Number(ev.target.value)); }};
document.getElementById('save').onclick = () => {{
  updateDecisionText();
  const blob = new Blob([decisionText.value], {{type: 'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'Roxanne_Minimum_full_track_review_decisions.json';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}};
document.addEventListener('keydown', ev => {{
  const tag = (ev.target && ev.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea') return;
  if (ev.key.toLowerCase() === 'i') {{
    state.inSec = state.playheadSec;
    renderRange();
    setStatus();
  }} else if (ev.key.toLowerCase() === 'o') {{
    state.outSec = state.playheadSec;
    renderRange();
    setStatus();
  }} else if (ev.key === ' ') {{
    ev.preventDefault();
    if (player.paused) startPreview(); else player.pause();
  }} else if (ev.key === '1') {{
    ev.preventDefault();
    setZoom(state.pxPerSec * 0.8);
  }} else if (ev.key === '2') {{
    ev.preventDefault();
    setZoom(state.pxPerSec * 1.25);
  }}
}});
window.addEventListener('resize', resizeTrack);
resizeTrack();
seekTimeline(0);
setStatus();
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a full-track segmented HTML cut review from an FCPXML.")
    parser.add_argument("--fcpxml", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--source-video", type=Path, default=None)
    parser.add_argument("--timeline-name", default="Full Track Review")
    parser.add_argument("--fps", type=float, default=60.0)
    parser.add_argument("--waveform-hz", type=int, default=20)
    parser.add_argument("--waveform-sr", type=int, default=1000)
    parser.add_argument("--no-waveform", action="store_true")
    args = parser.parse_args()

    payload = build_payload(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "segments.json", payload)
    (args.out_dir / "index.html").write_text(render_html(payload), encoding="utf-8")
    print(f"Wrote {args.out_dir / 'index.html'}")
    print(f"Segments: {payload['segment_count']}, duration: {payload['total_duration']:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
