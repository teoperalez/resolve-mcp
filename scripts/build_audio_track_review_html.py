from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def render_audio_html(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    data_script = data.replace("</", "<\\/").replace("<", "\\u003c")
    title = html.escape(str(payload.get("timeline_name") or "Audio Review"))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{
  color-scheme: dark;
  --bg: #101217;
  --panel: #191e26;
  --panel2: #222936;
  --text: #eef2f7;
  --muted: #98a6b7;
  --line: #313a49;
  --keep: #36aa72;
  --cut: #e76060;
  --manual: #f4c14f;
  --accent: #79aefc;
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
  z-index: 20;
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
  background: rgba(16, 18, 23, .97);
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
button.primary {{ background: #254a74; border-color: #3b75b5; }}
button.active {{ background: #315f38; border-color: #55a764; }}
label {{ color: var(--muted); font-size: 13px; display: inline-flex; align-items: center; gap: 6px; }}
main {{ padding: 14px 16px 24px; }}
.transport {{
  display: grid;
  grid-template-columns: minmax(280px, 1fr) minmax(280px, 420px);
  gap: 14px;
  align-items: stretch;
}}
.readout, .panel {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
}}
.clock {{
  font-size: 34px;
  font-weight: 700;
  line-height: 1.1;
}}
.subclock {{
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 9px;
  color: var(--muted);
  font-size: 13px;
}}
.subclock b {{ color: var(--text); font-weight: 600; }}
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
  height: 250px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #090c11;
  cursor: crosshair;
}}
#track {{
  position: relative;
  height: 100%;
  min-width: 100%;
}}
#waveformCanvas {{
  position: absolute;
  top: 54px;
  height: 104px;
  pointer-events: none;
  z-index: 1;
}}
.seg {{
  position: absolute;
  top: 18px;
  height: 24px;
  border-left: 1px solid rgba(255,255,255,.16);
  background: rgba(54,170,114,.92);
  overflow: hidden;
  z-index: 2;
}}
.seg.cut {{ background: rgba(231,96,96,.94); }}
.seg:hover {{ outline: 2px solid var(--accent); z-index: 4; }}
.seg span {{
  display: block;
  padding: 4px 5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 11px;
}}
.manual {{
  position: absolute;
  top: 172px;
  height: 28px;
  background: rgba(244,193,79,.85);
  border: 1px solid rgba(255,255,255,.45);
  border-radius: 4px;
  z-index: 5;
}}
.manual:hover {{ outline: 2px solid #fff; }}
.range {{
  position: absolute;
  top: 208px;
  height: 18px;
  background: rgba(121,174,252,.24);
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
  z-index: 8;
  pointer-events: none;
}}
#dragBox {{
  position: absolute;
  top: 172px;
  height: 28px;
  background: rgba(244,193,79,.35);
  border: 1px dashed var(--manual);
  display: none;
  pointer-events: none;
  z-index: 7;
}}
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
.hiddenMedia {{
  position: fixed;
  width: 1px;
  height: 1px;
  left: -10px;
  top: -10px;
  opacity: .01;
  pointer-events: none;
}}
@media (max-width: 860px) {{
  .transport {{ grid-template-columns: 1fr; }}
  .clock {{ font-size: 28px; }}
}}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="controls">
    <button id="playPause" class="primary" type="button">Play</button>
    <button id="playRange" type="button">Play In/Out</button>
    <button id="back10" type="button">-10s</button>
    <button id="fwd10" type="button">+10s</button>
    <button id="clearRange" type="button">Clear In/Out</button>
    <button id="undoManual" type="button">Undo Manual Cut</button>
    <button id="save" type="button">Save Decisions</button>
    <button class="rate active" data-rate="1" type="button">1x</button>
    <button class="rate" data-rate="1.5" type="button">1.5x</button>
    <button class="rate" data-rate="2" type="button">2x</button>
    <button class="rate" data-rate="3" type="button">3x</button>
    <button class="rate" data-rate="4" type="button">4x</button>
    <label>Zoom <input id="zoom" type="range" min="1" max="64" step="0.5" value="5"></label>
  </div>
</header>
<main>
  <video id="player" class="hiddenMedia" preload="metadata"></video>
  <section class="transport">
    <div class="readout">
      <div id="timeText" class="clock">00:00:00.000</div>
      <div class="subclock">
        <span>Final timeline <b id="durationText">00:00:00.000</b></span>
        <span>Source media <b id="sourceText">not loaded</b></span>
        <span>Rate <b id="rateText">1x</b></span>
      </div>
    </div>
    <aside class="panel status">
      <div>In: <b id="inText">unset</b> &nbsp; Out: <b id="outText">unset</b></div>
      <div>Segments cut: <b id="cutCount">0</b> &nbsp; Manual cuts: <b id="manualCount">0</b></div>
      <div>Right-click a segment to toggle keep/cut. Drag on the waveform to add a manual cut.</div>
      <div>Wheel over the waveform to zoom. Keys: <b>i</b>/<b>o</b> in-out, <b>1</b>/<b>2</b> zoom, <b>3</b>/<b>4</b> speed.</div>
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
  pxPerSec: 5,
  rate: 1,
  segmentCuts: {{}},
  manualCuts: [],
  inSec: null,
  outSec: null,
  playheadSec: 0,
  previewRanges: [],
  rangeIndex: -1,
  dragging: null,
  playing: false,
  raf: 0
}};
player.src = DATA.source_video_uri;
player.playbackRate = state.rate;
player.defaultPlaybackRate = state.rate;
try {{ player.preservesPitch = true; player.mozPreservesPitch = true; player.webkitPreservesPitch = true; }} catch (_err) {{}}

function fmt(sec) {{
  sec = Math.max(0, Number(sec) || 0);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  const ms = Math.floor((sec - Math.floor(sec)) * 1000);
  return String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0') + '.' + String(ms).padStart(3,'0');
}}
function clampTime(sec) {{ return Math.max(0, Math.min(DATA.total_duration, Number(sec) || 0)); }}
function clampZoom(value) {{ return Math.max(1, Math.min(64, Number(value) || 5)); }}
function setStatus() {{
  document.getElementById('timeText').textContent = fmt(state.playheadSec);
  document.getElementById('durationText').textContent = fmt(DATA.total_duration);
  document.getElementById('sourceText').textContent = findSegmentAtTl(state.playheadSec) ? fmt(player.currentTime || 0) : 'between segments';
  document.getElementById('rateText').textContent = state.rate + 'x';
  document.getElementById('inText').textContent = state.inSec == null ? 'unset' : fmt(state.inSec);
  document.getElementById('outText').textContent = state.outSec == null ? 'unset' : fmt(state.outSec);
  document.getElementById('cutCount').textContent = Object.keys(state.segmentCuts).filter(k => state.segmentCuts[k] === 'cut').length;
  document.getElementById('manualCount').textContent = state.manualCuts.length;
  document.getElementById('summary').textContent = DATA.segment_count + ' segments - final audio timeline ' + fmt(DATA.total_duration);
  document.getElementById('playPause').textContent = state.playing ? 'Pause' : 'Play';
  updateDecisionText();
}}
function updateDecisionText() {{
  const payload = {{
    schema: 'minimum_battles_audio_track_review_decisions_v1',
    generated_at: new Date().toISOString(),
    source_fcpxml: DATA.source_fcpxml,
    source_video: DATA.source_video,
    timeline_name: DATA.timeline_name,
    segment_decisions: state.segmentCuts,
    manual_cuts: state.manualCuts,
    in_sec: state.inSec,
    out_sec: state.outSec,
    playback_rate: state.rate
  }};
  decisionText.value = JSON.stringify(payload, null, 2);
}}
function resizeTrack() {{
  const width = Math.max(timeline.clientWidth, Math.ceil(DATA.total_duration * state.pxPerSec) + 1);
  track.style.width = width + 'px';
  renderSegments();
  renderManualCuts();
  renderRange();
  movePlayhead(state.playheadSec, false);
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
function setRate(rate) {{
  state.rate = Number(rate);
  player.playbackRate = state.rate;
  player.defaultPlaybackRate = state.rate;
  document.querySelectorAll('.rate').forEach(btn => btn.classList.toggle('active', Number(btn.dataset.rate) === state.rate));
  setStatus();
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
    span.textContent = '#' + (seg.idx + 1);
    el.appendChild(span);
    el.addEventListener('contextmenu', ev => {{
      ev.preventDefault();
      state.segmentCuts[seg.idx] = state.segmentCuts[seg.idx] === 'cut' ? 'keep' : 'cut';
      if (state.segmentCuts[seg.idx] === 'keep') delete state.segmentCuts[seg.idx];
      el.classList.toggle('cut', state.segmentCuts[seg.idx] === 'cut');
      setStatus();
      drawWaveform();
    }});
    el.addEventListener('mouseenter', () => {{
      document.getElementById('hoverText').textContent = '#' + (seg.idx + 1) + ' final ' + fmt(seg.tlStart) + '-' + fmt(seg.tlEnd) + ' source ' + fmt(seg.srcStart) + '-' + fmt(seg.srcEnd);
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
    el.style.left = (cut[0] * state.pxPerSec) + 'px';
    el.style.width = Math.max(2, (cut[1] - cut[0]) * state.pxPerSec) + 'px';
    el.title = 'Manual cut ' + fmt(cut[0]) + '-' + fmt(cut[1]) + '. Right-click to remove.';
    el.addEventListener('contextmenu', ev => {{
      ev.preventDefault();
      state.manualCuts.splice(i, 1);
      renderManualCuts();
      setStatus();
      drawWaveform();
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
function movePlayhead(sec, scroll = true) {{
  state.playheadSec = clampTime(sec);
  playhead.style.left = (state.playheadSec * state.pxPerSec) + 'px';
  if (scroll) {{
    const x = state.playheadSec * state.pxPerSec;
    const pad = timeline.clientWidth * 0.25;
    if (x < timeline.scrollLeft + pad) timeline.scrollLeft = Math.max(0, x - pad);
    if (x > timeline.scrollLeft + timeline.clientWidth - pad) timeline.scrollLeft = Math.max(0, x - timeline.clientWidth + pad);
  }}
  setStatus();
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
  const t = clampTime(sec);
  const seg = findSegmentAtTl(t);
  movePlayhead(t);
  if (seg) player.currentTime = seg.srcStart + (t - seg.tlStart);
}}
function waveformPeak(srcStart, srcEnd) {{
  if (!waveform || !waveform.peaks || !waveform.peaks.length || !waveform.hz) return 0;
  const peaks = waveform.peaks;
  const hz = waveform.hz;
  let a = Math.max(0, Math.floor(srcStart * hz));
  let b = Math.min(peaks.length - 1, Math.ceil(srcEnd * hz));
  if (b < a) b = a;
  let peak = 0;
  for (let i = a; i <= b; i++) if (peaks[i] > peak) peak = peaks[i];
  return Math.sqrt(Math.min(1, peak * 3));
}}
function isManualCutAt(sec) {{
  return state.manualCuts.some(cut => sec >= cut[0] && sec < cut[1]);
}}
function drawWaveform() {{
  const cssWidth = Math.max(1, timeline.clientWidth);
  const cssHeight = 104;
  const dpr = window.devicePixelRatio || 1;
  waveformCanvas.style.left = timeline.scrollLeft + 'px';
  waveformCanvas.style.width = cssWidth + 'px';
  waveformCanvas.style.height = cssHeight + 'px';
  waveformCanvas.width = Math.ceil(cssWidth * dpr);
  waveformCanvas.height = Math.ceil(cssHeight * dpr);
  const ctx = waveformCanvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight);
  ctx.fillStyle = '#070a0f';
  ctx.fillRect(0, 0, cssWidth, cssHeight);
  const center = cssHeight / 2;
  ctx.strokeStyle = '#273141';
  ctx.beginPath(); ctx.moveTo(0, center); ctx.lineTo(cssWidth, center); ctx.stroke();
  if (!waveform || !waveform.peaks || !waveform.peaks.length) {{
    ctx.fillStyle = '#9aa7b6';
    ctx.font = '12px Segoe UI, Arial, sans-serif';
    ctx.fillText('waveform unavailable', 10, center + 4);
    return;
  }}
  for (let x = 0; x < cssWidth; x++) {{
    const tlStart = (timeline.scrollLeft + x) / state.pxPerSec;
    const tlEnd = (timeline.scrollLeft + x + 1) / state.pxPerSec;
    const tlMid = (tlStart + tlEnd) / 2;
    const seg = findSegmentAtTl(tlMid);
    if (!seg) continue;
    const cut = state.segmentCuts[seg.idx] === 'cut' || isManualCutAt(tlMid);
    const srcStart = seg.srcStart + Math.max(0, tlStart - seg.tlStart);
    const srcEnd = seg.srcStart + Math.min(seg.duration, tlEnd - seg.tlStart);
    const amp = waveformPeak(srcStart, srcEnd);
    const half = Math.max(1, amp * (cssHeight * 0.46));
    ctx.strokeStyle = cut ? 'rgba(231,96,96,.72)' : 'rgba(121,174,252,.94)';
    ctx.beginPath();
    ctx.moveTo(x + 0.5, center - half);
    ctx.lineTo(x + 0.5, center + half);
    ctx.stroke();
  }}
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
      ranges.push({{
        tlStart: frag[0],
        tlEnd: frag[1],
        srcStart: seg.srcStart + (frag[0] - seg.tlStart),
        srcEnd: seg.srcStart + (frag[1] - seg.tlStart),
        segIdx: seg.idx
      }});
    }}
  }}
  return ranges;
}}
function playRange(index) {{
  if (index < 0 || index >= state.previewRanges.length) {{
    state.rangeIndex = -1;
    state.playing = false;
    player.pause();
    if (state.raf) cancelAnimationFrame(state.raf);
    state.raf = 0;
    setStatus();
    return;
  }}
  state.rangeIndex = index;
  const r = state.previewRanges[index];
  player.playbackRate = state.rate;
  player.currentTime = r.srcStart;
  movePlayhead(r.tlStart);
  state.playing = true;
  player.play();
  scheduleMonitor();
  setStatus();
}}
function playFrom(startSec, endSec = null) {{
  const end = endSec == null ? (state.outSec == null ? DATA.total_duration : state.outSec) : endSec;
  state.previewRanges = buildPreviewRanges(startSec, end);
  if (state.previewRanges.length) playRange(0);
}}
function togglePlay() {{
  if (state.playing) {{
    state.playing = false;
    state.rangeIndex = -1;
    player.pause();
    if (state.raf) cancelAnimationFrame(state.raf);
    state.raf = 0;
    setStatus();
    return;
  }}
  playFrom(state.playheadSec);
}}
player.addEventListener('timeupdate', () => {{
  if (state.rangeIndex < 0) return;
  const r = state.previewRanges[state.rangeIndex];
  const tl = r.tlStart + (player.currentTime - r.srcStart);
  movePlayhead(Math.min(tl, r.tlEnd));
  const margin = Math.max(0.04, 0.08 * state.rate);
  if (player.currentTime >= r.srcEnd - margin || tl >= r.tlEnd - margin) playRange(state.rangeIndex + 1);
}});
function scheduleMonitor() {{
  if (!state.raf) state.raf = requestAnimationFrame(monitorPlayback);
}}
function monitorPlayback() {{
  state.raf = 0;
  if (!state.playing || state.rangeIndex < 0) return;
  const r = state.previewRanges[state.rangeIndex];
  const tl = r.tlStart + (player.currentTime - r.srcStart);
  movePlayhead(Math.min(tl, r.tlEnd));
  const margin = Math.max(0.035, 0.035 * state.rate);
  if (player.currentTime >= r.srcEnd - margin || tl >= r.tlEnd - margin) {{
    playRange(state.rangeIndex + 1);
    return;
  }}
  scheduleMonitor();
}}
player.addEventListener('ended', () => {{
  state.playing = false;
  state.rangeIndex = -1;
  if (state.raf) cancelAnimationFrame(state.raf);
  state.raf = 0;
  setStatus();
}});
player.addEventListener('pause', () => {{
  if (state.rangeIndex >= 0 && !state.playing) {{
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
window.addEventListener('mouseup', () => {{
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
    drawWaveform();
    setStatus();
  }} else {{
    seekTimeline(a);
  }}
}});
document.getElementById('playPause').onclick = togglePlay;
document.getElementById('playRange').onclick = () => playFrom(state.inSec == null ? state.playheadSec : state.inSec, state.outSec);
document.getElementById('back10').onclick = () => seekTimeline(state.playheadSec - 10);
document.getElementById('fwd10').onclick = () => seekTimeline(state.playheadSec + 10);
document.getElementById('clearRange').onclick = () => {{ state.inSec = null; state.outSec = null; renderRange(); setStatus(); }};
document.getElementById('undoManual').onclick = () => {{ state.manualCuts.pop(); renderManualCuts(); drawWaveform(); setStatus(); }};
zoomInput.oninput = ev => setZoom(Number(ev.target.value));
document.querySelectorAll('.rate').forEach(btn => btn.addEventListener('click', () => setRate(Number(btn.dataset.rate))));
document.getElementById('save').onclick = () => {{
  updateDecisionText();
  const blob = new Blob([decisionText.value], {{type: 'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'Roxanne_Minimum_audio_review_decisions.json';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}};
document.addEventListener('keydown', ev => {{
  const tag = (ev.target && ev.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea') return;
  const key = ev.key.toLowerCase();
  if (key === 'i') {{
    state.inSec = state.playheadSec; renderRange(); setStatus();
  }} else if (key === 'o') {{
    state.outSec = state.playheadSec; renderRange(); setStatus();
  }} else if (ev.key === ' ') {{
    ev.preventDefault(); togglePlay();
  }} else if (ev.key === '1') {{
    ev.preventDefault(); setZoom(state.pxPerSec * 0.8);
  }} else if (ev.key === '2') {{
    ev.preventDefault(); setZoom(state.pxPerSec * 1.25);
  }} else if (ev.key === '3') {{
    ev.preventDefault(); setRate(3);
  }} else if (ev.key === '4') {{
    ev.preventDefault(); setRate(4);
  }} else if (key === 'j') {{
    seekTimeline(state.playheadSec - 10);
  }} else if (key === 'l') {{
    seekTimeline(state.playheadSec + 10);
  }} else if (key === 'k') {{
    ev.preventDefault(); togglePlay();
  }}
}});
window.addEventListener('resize', resizeTrack);
resizeTrack();
seekTimeline(0);
setRate(1);
setStatus();
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an audio-first final timeline review page from full-track segments.json.")
    parser.add_argument("--segments-json", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--title", default="")
    args = parser.parse_args()

    payload = json.loads(args.segments_json.read_text(encoding="utf-8-sig"))
    if args.title:
        payload["timeline_name"] = args.title
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "segments.json", payload)
    (args.out_dir / "index.html").write_text(render_audio_html(payload), encoding="utf-8")
    print(f"Wrote {args.out_dir / 'index.html'}")
    print(f"Timeline duration: {float(payload.get('total_duration') or 0):.3f}s")
    print(f"Source media: {payload.get('source_video')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
