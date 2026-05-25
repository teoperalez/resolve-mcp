"""Split transcripts/4.json into ~5-min chunks with 30s overlap.

Each chunk is written as a self-contained markdown file with:
- Header (chunk index, src start/end, segment range)
- Speech segments in [src_start - src_end] "text" format
- Word-level timestamps for the FIRST and LAST 60s of the chunk (overlap region)
  so subagents can see cross-chunk-boundary words for repeat detection
"""
import json
from pathlib import Path

TRANSCRIPT = Path('transcripts/4.json')
OUT_DIR = Path('audio-checks/qa-cuts/chunks')

CHUNK_SEC = 300.0   # 5 minutes
OVERLAP_SEC = 30.0  # 30s overlap front and back

OUT_DIR.mkdir(parents=True, exist_ok=True)
t = json.loads(TRANSCRIPT.read_text(encoding='utf-8'))
segs = t['segments']
total_dur = segs[-1]['end']

print(f'Total: {len(segs)} segs, {total_dur:.1f}s')

# Build chunks
chunks = []
step = CHUNK_SEC - OVERLAP_SEC
chunk_starts = []
s = 0.0
while s < total_dur:
    chunk_starts.append(s)
    s += step

print(f'Chunk count: {len(chunk_starts)} (step={step}s)')

for ci, chunk_src_start in enumerate(chunk_starts):
    chunk_src_end = min(chunk_src_start + CHUNK_SEC, total_dur)
    # Segments whose ANY portion overlaps the chunk
    chunk_segs = [(i, s) for i, s in enumerate(segs)
                  if s['end'] >= chunk_src_start and s['start'] <= chunk_src_end]

    if not chunk_segs:
        continue

    seg_idx_first = chunk_segs[0][0]
    seg_idx_last  = chunk_segs[-1][0]

    lines = [
        f'# Transcript chunk {ci:02d}',
        '',
        f'- **Source time range:** {chunk_src_start:.2f}s — {chunk_src_end:.2f}s',
        f'- **Segment indices:** {seg_idx_first} — {seg_idx_last} (inclusive, {len(chunk_segs)} segments)',
        f'- **Overlap window:** ±{OVERLAP_SEC:.0f}s with adjacent chunks',
        '',
        '## Speech segments',
        '',
    ]

    for i, s in chunk_segs:
        text = s['text'].strip().replace('\n', ' ')
        in_overlap = (s['start'] < chunk_src_start + OVERLAP_SEC) or (s['end'] > chunk_src_end - OVERLAP_SEC)
        marker = '🔁 ' if in_overlap else '   '
        lines.append(f'{marker}**seg {i}** [{s["start"]:.2f}-{s["end"]:.2f}]  "{text}"')

    # Word-level timestamps for overlap regions (front + back)
    lines.extend([
        '',
        '## Word-level timestamps (overlap regions only)',
        '',
        '_Use these to check repeats that cross chunk boundaries with adjacent chunks._',
        '',
    ])
    for i, s in chunk_segs:
        if (s['start'] < chunk_src_start + OVERLAP_SEC) or (s['end'] > chunk_src_end - OVERLAP_SEC):
            words = s.get('words') or []
            if words:
                lines.append(f'**seg {i}** [{s["start"]:.2f}-{s["end"]:.2f}]:')
                for w in words:
                    w_text = (w.get('word') or '').strip()
                    lines.append(f'  - [{w["start"]:.3f}-{w["end"]:.3f}]  "{w_text}"')
                lines.append('')

    out = OUT_DIR / f'chunk-{ci:02d}.md'
    out.write_text('\n'.join(lines), encoding='utf-8')
    print(f'  chunk {ci:02d}: src=[{chunk_src_start:.1f}-{chunk_src_end:.1f}] segs=[{seg_idx_first}-{seg_idx_last}] -> {out}')

print(f'\nWrote {len(chunk_starts)} chunks to {OUT_DIR}/')
