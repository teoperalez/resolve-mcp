"""Gen 1 marker pipeline — phase 1 (pre-Resolve).

For each source MP4:
  1. Run auto-editor: `auto-editor <video> --margin 0.1sec --edit audio:stream=0 --export resolve`
  2. Rename audio track files: `<stem>_tracks/N.wav` -> `Stream N.wav`, patch FCPXML asset refs.
  3. Inject chapter markers: read MP4 chapters via ffprobe, remap source-time to
     timeline-time through the FCPXML's `<asset-clip>` segment table, insert
     `<marker value="<OBS name>" ...>` children of `<sequence>`.

Usage:
    python phase1.py <video.mp4> [<video2.mp4> ...]
    python phase1.py <folder>                # process every *.mp4 in folder
    python phase1.py --force-rerun <video>   # re-run auto-editor even if _ALTERED exists

Adapted from `C:\\Programming\\FileOrganizer\\organizer.py` functions:
  - run_auto_editor_on() + build_auto_editor_args()
  - rename_auto_editor_tracks_and_update_fcpxml()
  - inject_chapters_into_fcpxml() + read_mp4_chapters()
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

AUTO_EDITOR_DEFAULTS = {
    'margin': '0.1sec',
    'edit': 'audio:stream=0',
    'export': 'resolve',
}


def build_auto_editor_args(video: Path) -> list[str]:
    return [
        'auto-editor', str(video),
        '--margin', AUTO_EDITOR_DEFAULTS['margin'],
        '--edit',   AUTO_EDITOR_DEFAULTS['edit'],
        '--export', AUTO_EDITOR_DEFAULTS['export'],
    ]


def run_auto_editor(video: Path, force: bool = False) -> Path:
    """Run auto-editor on `video`. Return path to the generated FCPXML."""
    fcpxml = video.parent / f'{video.stem}_ALTERED.fcpxml'
    if fcpxml.exists() and not force:
        print(f'  [skip auto-editor] {fcpxml.name} already exists. Use --force-rerun to regenerate.')
        return fcpxml

    cmd = build_auto_editor_args(video)
    print(f'  [auto-editor] {" ".join(cmd)}')
    r = subprocess.run(cmd, cwd=str(video.parent), capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        print(f'    stderr: {r.stderr[:500]}', file=sys.stderr)
        raise RuntimeError(f'auto-editor failed for {video.name} (exit {r.returncode})')
    if not fcpxml.exists():
        raise RuntimeError(f'auto-editor finished but {fcpxml.name} not found')
    print(f'    -> {fcpxml.name}')
    return fcpxml


def rename_tracks_and_patch_fcpxml(video: Path) -> int:
    """Rename `<stem>_tracks/N.wav` to `Stream N.wav` and patch FCPXML asset refs."""
    tracks_dir = video.parent / f'{video.stem}_tracks'
    fcpxml = video.parent / f'{video.stem}_ALTERED.fcpxml'
    if not tracks_dir.is_dir():
        print(f'  [skip track rename] no {tracks_dir.name} folder')
        return 0
    if not fcpxml.is_file():
        print(f'  [skip track rename] no {fcpxml.name}')
        return 0

    # Rename files (only numeric stems like 0.wav, 1.wav)
    renames: dict[str, str] = {}  # old basename -> new basename
    for wav in sorted(tracks_dir.glob('*.wav')):
        if wav.stem.isdigit():
            new = tracks_dir / f'Stream {wav.stem}.wav'
            if new.exists():
                continue  # already renamed
            try:
                wav.rename(new)
                renames[wav.name] = new.name
                print(f'  [rename] {wav.name} -> {new.name}')
            except OSError as e:
                print(f'    WARN: could not rename {wav.name}: {e}', file=sys.stderr)

    if not renames:
        return 0

    # Patch FCPXML asset references
    text = fcpxml.read_text(encoding='utf-8')
    for old, new in renames.items():
        # URL-encoded form in src= attribute (spaces -> %20)
        old_enc = old.replace(' ', '%20')
        new_enc = new.replace(' ', '%20')
        text = text.replace(old_enc, new_enc)
        text = text.replace(old, new)  # also handle non-URL-encoded paths
    fcpxml.write_text(text, encoding='utf-8')
    print(f'  [fcpxml patched] {len(renames)} asset reference(s) updated')
    return len(renames)


# ---------- chapter injection (adapted from FileOrganizer) ----------

_TIME_RE = re.compile(r'(\d+)(?:/(\d+))?s')


def _parse_fcpxml_time(s: str | None) -> Fraction | None:
    if not s:
        return None
    m = _TIME_RE.fullmatch(s.strip())
    if not m:
        try:
            return Fraction(s.rstrip('s'))
        except (ValueError, ZeroDivisionError):
            return None
    num = int(m.group(1))
    den = int(m.group(2)) if m.group(2) else 1
    if den == 0:
        return None
    return Fraction(num, den)


def _format_fcpxml_time(t: Fraction, frame_dur: Fraction) -> str:
    """Format a Fraction as Resolve-friendly N/Ds, snapped to frame boundaries."""
    # Snap to integer multiple of frame_dur
    frames = round(t / frame_dur)
    snapped = frames * frame_dur
    if snapped.denominator == 1:
        return f'{snapped.numerator}s'
    return f'{snapped.numerator}/{snapped.denominator}s'


def read_mp4_chapters(video: Path) -> list[dict]:
    """Return [{'name': str, 'start_time': float}, ...] from ffprobe -show_chapters."""
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_chapters', str(video)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        print('  ERROR: ffprobe not on PATH', file=sys.stderr)
        return []
    if r.returncode != 0:
        print(f'  WARN: ffprobe returned {r.returncode}', file=sys.stderr)
        return []
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        print('  WARN: ffprobe output not JSON', file=sys.stderr)
        return []
    chapters = []
    for i, ch in enumerate(data.get('chapters', [])):
        name = (ch.get('tags') or {}).get('title') or f'Chapter {i + 1}'
        try:
            start_time = float(ch.get('start_time', 0))
        except (ValueError, TypeError):
            continue
        chapters.append({'name': name, 'start_time': start_time})
    return chapters


def inject_chapters_into_fcpxml(video: Path) -> int:
    """Inject MP4 chapter markers into `<stem>_ALTERED.fcpxml` as <marker> elements.

    Returns count of markers inserted.
    """
    fcpxml = video.parent / f'{video.stem}_ALTERED.fcpxml'
    if not fcpxml.is_file():
        print(f'  WARN: {fcpxml.name} not found; skipping chapter injection')
        return 0

    chapters = read_mp4_chapters(video)
    if not chapters:
        print(f'  No chapters in {video.name}; nothing to inject')
        return 0

    try:
        tree = ET.parse(fcpxml)
    except ET.ParseError as e:
        print(f'  ERROR parsing {fcpxml.name}: {e}', file=sys.stderr)
        return 0

    root = tree.getroot()

    frame_dur = Fraction(1, 60)
    for fmt in root.iter('format'):
        fd = fmt.get('frameDuration')
        if fd:
            parsed = _parse_fcpxml_time(fd)
            if parsed and parsed > 0:
                frame_dur = parsed
                break

    # Collect (src_start, src_end, tl_offset) from every asset-clip
    segments: list[tuple[Fraction, Fraction, Fraction]] = []
    for clip in root.iter('asset-clip'):
        offset = _parse_fcpxml_time(clip.get('offset', '0s'))
        start  = _parse_fcpxml_time(clip.get('start',  '0s'))
        dur    = _parse_fcpxml_time(clip.get('duration', '0s'))
        if None in (offset, start, dur) or dur == 0:
            continue
        segments.append((start, start + dur, offset))

    if not segments:
        print(f'  ERROR: no asset-clips in {fcpxml.name}', file=sys.stderr)
        return 0

    segments.sort(key=lambda x: x[0])

    # Optionally: clear any pre-existing <marker> children of <sequence> first
    # (the "reset" semantic — fresh markers from source, no stale ones)
    cleared = 0
    for seq in root.iter('sequence'):
        existing = list(seq.findall('marker'))
        for m in existing:
            seq.remove(m)
            cleared += 1
        break
    if cleared:
        print(f'  [reset] removed {cleared} pre-existing marker(s) from <sequence>')

    # Map each chapter to a new timeline position
    mapped: list[tuple[str, str, str]] = []  # (time_str, dur_str, name)
    dur_str = _format_fcpxml_time(frame_dur, frame_dur)
    skipped_end = snapped = 0
    for ch in chapters:
        src_t = Fraction(ch['start_time']).limit_denominator(100_000)
        new_t: Fraction | None = None
        for src_start, src_end, tl_offset in segments:
            if src_start <= src_t < src_end:
                new_t = tl_offset + (src_t - src_start)
                break
        if new_t is None:
            next_seg = next((seg for seg in segments if seg[0] > src_t), None)
            if next_seg is None:
                print(f'  Marker {ch["name"]!r} at {ch["start_time"]:.3f}s: no following clip, skipped')
                skipped_end += 1
                continue
            new_t = next_seg[2]
            snapped += 1
            tag = '(snapped)'
        else:
            tag = ''
        time_str = _format_fcpxml_time(new_t, frame_dur)
        mapped.append((time_str, dur_str, ch['name']))
        print(f'  {ch["name"]!r} {ch["start_time"]:.3f}s -> {float(new_t):.3f}s ({time_str}) {tag}')

    if not mapped:
        print(f'  No chapters mapped to kept segments')
        return 0

    # Insert <marker> children of <sequence>
    for seq in root.iter('sequence'):
        for time_str, dur_str, name in mapped:
            m = ET.SubElement(seq, 'marker')
            m.set('start', time_str)
            m.set('duration', dur_str)
            m.set('value', name)
            m.set('completed', '0')
        break

    tree.write(fcpxml, encoding='utf-8', xml_declaration=True)
    print(f'  [injected] {len(mapped)} marker(s); snapped={snapped}, dropped_after_last_clip={skipped_end}')
    return len(mapped)


def process_one(video: Path, force_rerun: bool = False) -> dict:
    """Process one MP4 through phase 1. Return summary dict."""
    print(f'\n=== {video.name} ===')
    summary = {'video': str(video), 'fcpxml': None, 'tracks_renamed': 0, 'markers_injected': 0}

    fcpxml = run_auto_editor(video, force=force_rerun)
    summary['fcpxml'] = str(fcpxml)
    summary['tracks_renamed'] = rename_tracks_and_patch_fcpxml(video)
    summary['markers_injected'] = inject_chapters_into_fcpxml(video)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('inputs', nargs='+', help='MP4 file(s) or a folder containing MP4s')
    ap.add_argument('--force-rerun', action='store_true',
                    help='Re-run auto-editor even if _ALTERED.fcpxml exists')
    args = ap.parse_args()

    # Resolve inputs
    videos: list[Path] = []
    for inp in args.inputs:
        p = Path(inp)
        if p.is_dir():
            for m in sorted(p.glob('*.mp4')):
                # Skip auto-editor outputs + renamed audio splits
                if '_ALTERED' in m.name or '_tracks' in m.name:
                    continue
                videos.append(m)
        elif p.is_file() and p.suffix.lower() == '.mp4':
            videos.append(p)
        else:
            print(f'WARN: skipping {p} (not an MP4 or directory)', file=sys.stderr)

    if not videos:
        print('ERROR: no MP4 inputs found', file=sys.stderr)
        return 1

    # Sanity checks
    if shutil.which('auto-editor') is None:
        print('ERROR: auto-editor not on PATH. Install via `pip install auto-editor`.', file=sys.stderr)
        return 1
    if shutil.which('ffprobe') is None:
        print('ERROR: ffprobe not on PATH. Install ffmpeg.', file=sys.stderr)
        return 1

    print(f'Processing {len(videos)} video(s):')
    for v in videos:
        print(f'  - {v}')

    summaries = []
    for v in videos:
        try:
            summaries.append(process_one(v, force_rerun=args.force_rerun))
        except Exception as e:
            print(f'  ERROR: {e}', file=sys.stderr)
            summaries.append({'video': str(v), 'error': str(e)})

    print('\n=== Phase 1 summary ===')
    for s in summaries:
        if 'error' in s:
            print(f'  FAIL  {Path(s["video"]).name}: {s["error"]}')
        else:
            print(f'  OK    {Path(s["video"]).name}: '
                  f'{s["markers_injected"]} markers, '
                  f'{s["tracks_renamed"]} tracks renamed')

    print('\nNext step: open Resolve, import each FCPXML (File > Import Timeline > Import AAF, EDL, XML).')
    print('Then for each imported timeline (set as current), run phase 2:')
    print('  python ~/.claude/skills/gen1-marker-pipeline/scripts/phase2.py')

    return 0 if all('error' not in s for s in summaries) else 1


if __name__ == '__main__':
    sys.exit(main())
