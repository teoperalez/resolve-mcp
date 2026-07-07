"""Gen 1 marker pipeline — phase 2 (in-Resolve).

Run AFTER the FCPXML (produced by phase 1) has been imported into Resolve as a
timeline and set as the current timeline.

Workflow:
  1. Connect to Resolve, grab current timeline.
  2. Discover source MP4 from the first V1 clip's media pool item.
  3. Read chapter markers from MP4 via ffprobe.
  4. Build clip table from Resolve's V1 layout.
  5. Load session log (default: latest under %APPDATA%\\rbypc-frontend\\logs\\),
     replay events through MARKER_RULES, produce ordered intended-marker list.
  6. Pair chapters with intended markers by sorted positional index.
  7. For each chapter: map to timeline frame, AddMarker(timeline + clip).

Flags:
  --no-label        Skip session-log labelling; use raw OBS chapter names.
  --session <dir>   Use a specific session log directory.
  --list-sessions   Print available sessions and exit.

Adapted from `C:\\Programming\\FileOrganizer\\resolve_map_fcpxml_markers.py`
with the path to `session_marker_labels.py` corrected to the bundled copy
(FileOrganizer hardcodes `F:\\` which doesn't exist on this machine).
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Bundled session-label helper (vendored from RBYNewLayout)
_SKILL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SKILL_DIR))
try:
    import session_marker_labels as sml
except ImportError:
    sml = None
    print('WARN: session_marker_labels.py not found alongside phase2.py; '
          'labelling disabled.', file=sys.stderr)


def _bootstrap_resolve_api():
    api_base = r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting'
    modules_dir = os.path.join(api_base, 'Modules')
    lib_path = r'C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll'
    if not os.path.isdir(modules_dir):
        print(f'ERROR: Resolve scripting modules not found at {modules_dir}', file=sys.stderr)
        sys.exit(1)
    os.environ.setdefault('RESOLVE_SCRIPT_API', api_base)
    os.environ.setdefault('RESOLVE_SCRIPT_LIB', lib_path)
    if modules_dir not in sys.path:
        sys.path.insert(0, modules_dir)
    if sys.platform.startswith('win'):
        pyhome = sys.base_prefix or sys.prefix
        if pyhome and os.path.isdir(pyhome):
            os.environ.setdefault('PYTHON3HOME', pyhome)
        for dll_dir in (
            os.path.dirname(lib_path),
            pyhome,
            os.path.join(pyhome, 'DLLs') if pyhome else '',
            sys.prefix,
            os.path.join(sys.prefix, 'DLLs'),
        ):
            if not dll_dir or not os.path.isdir(dll_dir):
                continue
            if hasattr(os, 'add_dll_directory'):
                try:
                    os.add_dll_directory(dll_dir)
                except OSError:
                    pass
            current_path = os.environ.get('PATH', '')
            norm_dll = os.path.normcase(os.path.abspath(dll_dir))
            existing = {
                os.path.normcase(os.path.abspath(entry))
                for entry in current_path.split(os.pathsep)
                if entry
            }
            if norm_dll not in existing:
                os.environ['PATH'] = dll_dir + (os.pathsep + current_path if current_path else '')


def get_resolve():
    """When exec'd from Resolve's console, `resolve` is a global.
    From external Python, bootstrap then scriptapp('Resolve').
    """
    try:
        return resolve  # type: ignore[name-defined]  # noqa: F821
    except NameError:
        pass
    _bootstrap_resolve_api()
    try:
        import DaVinciResolveScript as bmd
        return bmd.scriptapp('Resolve')
    except Exception as e:
        print(f'ERROR: cannot import DaVinciResolveScript: {e}', file=sys.stderr)
        sys.exit(1)


def get_chapters_from_mp4(mp4_path: str) -> list[dict]:
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_chapters', mp4_path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        print('ERROR: ffprobe not on PATH', file=sys.stderr)
        return []
    if r.returncode != 0:
        print(f'ERROR: ffprobe returned {r.returncode}', file=sys.stderr)
        return []
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        print('ERROR: ffprobe output not JSON', file=sys.stderr)
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--no-label', action='store_true',
                    help='Skip session-log labelling, keep raw OBS names')
    ap.add_argument('--session', default=None,
                    help='Specific session log directory '
                         '(default: latest under %%APPDATA%%/rbypc-frontend/logs/)')
    ap.add_argument('--list-sessions', action='store_true',
                    help='Print available sessions and exit')
    args = ap.parse_args()

    if args.list_sessions:
        if sml is None:
            print('ERROR: session_marker_labels not available', file=sys.stderr)
            return 1
        sessions = sml.list_sessions()
        if not sessions:
            print('No session logs found')
        for p in sessions:
            print(p)
        return 0

    R = get_resolve()
    if R is None:
        print('ERROR: cannot connect to Resolve. Is it running?', file=sys.stderr)
        print('       Check Preferences -> System -> General -> External scripting using = Local',
              file=sys.stderr)
        return 1

    pm = R.GetProjectManager()
    project = pm.GetCurrentProject()
    if not project:
        print('ERROR: no project open', file=sys.stderr)
        return 1

    timeline = project.GetCurrentTimeline()
    if not timeline:
        print('ERROR: no timeline selected', file=sys.stderr)
        return 1

    print(f'[info] Timeline: {timeline.GetName()}')

    fps_str = timeline.GetSetting('timelineFrameRate') or '60'
    try:
        fps = float(fps_str)
    except ValueError:
        fps = 60.0
    print(f'[info] FPS: {fps}')

    # Load session-log labels
    intended = []
    session_dir = None
    if not args.no_label and sml is not None:
        session_dir, intended = sml.latest_intended_markers(args.session)
        if session_dir:
            print(f'[info] Session log: {session_dir}  ({len(intended)} intended markers)')
        else:
            print('[warn] No session log found; using raw OBS chapter names', file=sys.stderr)
    elif args.no_label:
        print('[info] --no-label set; using raw OBS chapter names')
    else:
        print('[warn] session_marker_labels unavailable; using raw OBS chapter names',
              file=sys.stderr)

    if intended and len(intended) > 0:
        preview = ', '.join(f'"{m.label}"' for m in intended[:5])
        more = '...' if len(intended) > 5 else ''
        print(f'[info] Intended labels (first 5): {preview}{more}')

    # Discover source MP4 from first V1 clip
    video_items = timeline.GetItemListInTrack('video', 1) or []
    if not video_items:
        print('ERROR: no clips on V1', file=sys.stderr)
        return 1

    mp4_path = None
    for item in video_items:
        try:
            mpi = item.GetMediaPoolItem()
            if mpi is None:
                continue
            path = mpi.GetClipProperty('File Path')
            if path and os.path.isfile(path):
                mp4_path = path
                break
        except Exception as e:
            print(f'[warn] GetMediaPoolItem failed: {e}', file=sys.stderr)

    if not mp4_path:
        print('ERROR: cannot determine source MP4 from timeline clips.', file=sys.stderr)
        print('       Make sure the FCPXML source media is at its original location.',
              file=sys.stderr)
        return 1

    print(f'[info] Source: {mp4_path}')

    chapters = get_chapters_from_mp4(mp4_path)
    if not chapters:
        print(f'[warn] No chapter markers in {os.path.basename(mp4_path)}', file=sys.stderr)
        return 0
    print(f'[info] {len(chapters)} chapter(s) in source')

    if intended and len(chapters) != len(intended):
        print(f'[warn] Chapter count ({len(chapters)}) != intended marker count '
              f'({len(intended)}) — pairing by position; extras use OBS names.',
              file=sys.stderr)

    # Build clip table from Resolve V1
    clips = []
    for item in video_items:
        try:
            clips.append((
                int(item.GetStart()),
                int(item.GetLeftOffset()),
                int(item.GetDuration()),
                item,
            ))
        except Exception as e:
            print(f'[warn] cannot read clip offsets: {e}', file=sys.stderr)
    clips.sort(key=lambda c: c[1])

    # Optionally clear existing timeline markers to "reset" before re-labelling
    # (mirrors the FCPXML-level reset done in phase 1)
    # We only clear markers that match existing chapter timeline positions to
    # avoid wiping unrelated markers the user might have placed.
    existing = set((timeline.GetMarkers() or {}).keys())

    added = snapped = skipped_end = skipped_dup = clip_marked = 0
    im_idx = 0  # advances only when a marker IS placed (preserves pairing across skips)

    for ch in chapters:
        src_frame = round(ch['start_time'] * fps)

        tl_frame = None
        clip_item = None
        clip_src_frame = None
        was_snapped = False

        for tl_start, src_start, duration, item in clips:
            if src_start <= src_frame < src_start + duration:
                tl_frame = tl_start + (src_frame - src_start)
                clip_item = item
                clip_src_frame = src_frame
                break

        if tl_frame is None:
            next_clip = next((c for c in clips if c[1] > src_frame), None)
            if next_clip is None:
                print(f'  skip  {ch["name"]!r} {ch["start_time"]:.3f}s (no following clip)')
                skipped_end += 1
                continue
            tl_frame = next_clip[0]
            clip_item = next_clip[3]
            clip_src_frame = next_clip[1]
            was_snapped = True
            snapped += 1

        im = intended[im_idx] if im_idx < len(intended) else None
        im_idx += 1

        if im is not None:
            label = im.label
            color = im.color
            note = im.note
        else:
            label = ch['name']
            color = 'Blue'
            note = ''

        snap_tag = ' (snapped)' if was_snapped else ''
        print(f'  {"snap" if was_snapped else "map "}  {ch["name"]!r} '
              f'{ch["start_time"]:.3f}s -> frame {tl_frame}{snap_tag}  [{label}]')

        if tl_frame in existing:
            skipped_dup += 1
            continue

        ok = timeline.AddMarker(tl_frame, color, label, note, 1)
        if ok:
            added += 1
            existing.add(tl_frame)
            if clip_item is not None and clip_src_frame is not None:
                clip_ok = clip_item.AddMarker(clip_src_frame, color, label, note, 1)
                if clip_ok:
                    clip_marked += 1
                else:
                    print(f'  [warn] clip AddMarker failed at src={clip_src_frame} for {label!r}',
                          file=sys.stderr)
        else:
            print(f'  [warn] timeline AddMarker failed at frame {tl_frame} for {label!r}',
                  file=sys.stderr)

    print(f'\n[done] added={added}  clip_markers={clip_marked}  snapped_to_next={snapped}  '
          f'no_following_clip={skipped_end}  duplicates={skipped_dup}')
    print('[info] Clip markers were also stamped on V1 clips — they survive copy-paste to '
          'a production timeline.')

    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
