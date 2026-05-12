"""
Build a new 'edited' timeline by prepending the game intro, copying all
existing clips from the current timeline (shifted right by the intro's
duration), and appending the outro video + outro audio on A3.

The original timeline is left intact as a backup.

Strategy:
  1. Read all clip info from the current timeline.
  2. Create a new empty timeline (same project settings).
  3. Append intro → shifted original clips → outro in one batch per group.

Usage:
    python insert_intro_outro.py --game GAME_KEY [--dry-run]
"""
import sys
import os
import json
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

CATALOG_PATH  = Path('assets/catalog.json')
MANIFEST_DIR  = Path.home() / '.resolve-mcp'
MANIFEST_PATH = MANIFEST_DIR / 'manifest.json'
MIN_BATTLES_CACHE = Path('transcripts/min-battles.json')


# ── JSON helpers ───────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


# ── asset key helpers ──────────────────────────────────────────────────────────

def _find_key(assets: dict, *must: str, exclude: tuple = ()) -> str | None:
    for k in assets:
        if all(s in k for s in must) and not any(e in k for e in exclude):
            return k
    return None


def asset_keys(game_def: dict) -> tuple[str | None, str | None, str | None]:
    """Return (intro_key, outro_video_key, outro_audio_key) for this game."""
    a = game_def['assets']
    intro     = _find_key(a, 'intro',        exclude=('background',))
    outro_aud = _find_key(a, 'outro', 'audio')
    outro_vid = _find_key(a, 'outro',         exclude=('audio',))
    return intro, outro_vid, outro_aud


# ── Resolve helpers ────────────────────────────────────────────────────────────

def find_in_bin(folder, filename: str):
    """MediaPoolItem whose name matches `filename` (case-insensitive)."""
    for item in (folder.GetClipList() or []):
        if (item.GetName() or '').lower() == filename.lower():
            return item
    return None


def find_bin(root, name: str):
    for sub in (root.GetSubFolderList() or []):
        if sub.GetName() == name:
            return sub
    return None


def _mpi_clip_fps(mpi) -> float | None:
    props = mpi.GetClipProperty() or {}
    for key in ('FPS', 'Video Frame Rate', 'Frame Rate'):
        try:
            v = float(props.get(key) or 0)
            if v > 0:
                return v
        except (ValueError, TypeError):
            pass
    return None


def mpi_duration_frames(mpi, timeline_fps: float) -> int | None:
    """Duration in TIMELINE frames, accounting for clip-vs-timeline fps difference."""
    props = mpi.GetClipProperty() or {}
    clip_fps = _mpi_clip_fps(mpi) or timeline_fps

    for key in ('Video Duration', 'Audio Duration', 'Duration'):
        raw = (props.get(key) or '').strip()
        if not raw:
            continue
        parts = raw.replace(';', ':').split(':')
        if len(parts) == 4:
            h, m, s, f = (int(x) for x in parts)
            # f is expressed in clip-native fps; convert everything to seconds first
            total_sec = h * 3600 + m * 60 + s + f / clip_fps
            frames = round(total_sec * timeline_fps)
            if frames > 0:
                return frames
        try:
            native = int(raw)
            if native > 0:
                return round(native * timeline_fps / clip_fps)
        except (ValueError, TypeError):
            pass
    return None


def collect_clips(tl) -> list[dict]:
    """Return all clip info as clipInfo dicts (recordFrame is relative to tl start)."""
    tl_start = tl.GetStartFrame()
    clips = []
    for track_type, media_type in [('video', 1), ('audio', 2)]:
        count = tl.GetTrackCount(track_type)
        for idx in range(1, count + 1):
            for item in (tl.GetItemListInTrack(track_type, idx) or []):
                mpi = item.GetMediaPoolItem()
                if mpi is None:
                    continue
                left = item.GetLeftOffset()
                dur  = item.GetDuration()
                clips.append({
                    'mediaPoolItem': mpi,
                    'startFrame':   left,
                    'endFrame':     left + dur,   # exclusive end — Resolve AppendToTimeline treats endFrame as exclusive
                    'relRecord':    item.GetStart() - tl_start,
                    'trackIndex':   idx,
                    'mediaType':    media_type,
                })
    return clips


def unique_tl_name(project, base: str) -> str:
    existing = set()
    for i in range(1, project.GetTimelineCount() + 1):
        tl = project.GetTimelineByIndex(i)
        if tl:
            existing.add(tl.GetName())
    name, n = base, 2
    while name in existing:
        name = f'{base} {n}'
        n += 1
    return name


def ensure_tracks(tl, video_count: int, audio_count: int) -> None:
    while tl.GetTrackCount('video') < video_count:
        tl.AddTrack('video')
    while tl.GetTrackCount('audio') < audio_count:
        tl.AddTrack('audio', 'stereo')


# ── retime helpers ─────────────────────────────────────────────────────────────

def auto_detect_intro_speed(default_fast: int = 400) -> tuple[int, str]:
    """Decide the intro speed from the cached min-battles classification.

    Returns (speed_pct, reason). If the cache is missing, defaults to 100% with
    a warning — the /import skill should run detect_minimum_battles.py first.
    """
    if not MIN_BATTLES_CACHE.exists():
        return 100, (f'no {MIN_BATTLES_CACHE} cache — defaulting to 100%; '
                     f'run scripts/detect_minimum_battles.py first to enable auto-retime')
    try:
        data = json.loads(MIN_BATTLES_CACHE.read_text(encoding='utf-8'))
    except Exception as e:
        return 100, f'could not parse {MIN_BATTLES_CACHE}: {e} — defaulting to 100%'

    if bool(data.get('is_minimum_battles')):
        return 100, (f'is_minimum_battles=true ({data.get("pokemon_count", "?")} '
                     f'Pokémon) — keeping intro at 100%')
    return default_fast, (f'is_minimum_battles=false ({data.get("pokemon_count", "?")} '
                          f'Pokémon) — retiming intro to {default_fast}%')


def retime_clip(item, speed_pct: int) -> bool:
    """Try to retime a placed TimelineItem to `speed_pct` percent.

    Tries common Resolve property name/value combos and returns True if any
    sticks (clip duration actually changed). speed_pct=100 is a no-op.
    """
    if speed_pct == 100:
        return True

    before = item.GetDuration()
    attempts = [
        ('Speed',         float(speed_pct)),
        ('Speed',         speed_pct / 100.0),
        ('Speed',         int(speed_pct)),
        ('PlaybackSpeed', float(speed_pct)),
        ('PlaybackSpeed', speed_pct / 100.0),
    ]
    for key, value in attempts:
        try:
            ok = item.SetProperty(key, value)
        except Exception:
            ok = False
        after = item.GetDuration()
        if ok and after != before:
            print(f'  Retime: SetProperty({key!r}, {value}) → '
                  f'{before} → {after} TL frames')
            return True
    print(f'  WARNING: retime to {speed_pct}% failed via SetProperty — duration '
          f'unchanged at {before} frames. Falling back to 100% speed.')
    return False


# ── main ───────────────────────────────────────────────────────────────────────

def run(game_key: str, dry_run: bool, source_timeline: str | None = None,
        intro_speed: int | None = None) -> int:
    # Resolve intro speed: explicit CLI value wins, otherwise auto-detect from
    # transcripts/min-battles.json (default 100% if no cache).
    if intro_speed is None:
        intro_speed, speed_reason = auto_detect_intro_speed()
    else:
        speed_reason = f'explicit CLI override --intro-speed {intro_speed}'

    import DaVinciResolveScript as dvr

    catalog  = load_json(CATALOG_PATH)
    manifest = load_json(MANIFEST_PATH) if MANIFEST_PATH.exists() else {}

    if game_key not in catalog:
        print(f'ERROR: "{game_key}" not in catalog.', file=sys.stderr)
        return 1

    game_def  = catalog[game_key]
    group_key = game_def.get('asset_group', game_key)
    intro_k, outro_vid_k, outro_aud_k = asset_keys(game_def)

    resolve = dvr.scriptapp('Resolve')
    if resolve is None:
        print('ERROR: Could not connect to Resolve.', file=sys.stderr)
        return 1

    project  = resolve.GetProjectManager().GetCurrentProject()
    pool     = project.GetMediaPool()
    orig_tl  = project.GetCurrentTimeline()

    if orig_tl is None:
        print('ERROR: No current timeline.', file=sys.stderr)
        return 1

    if source_timeline:
        found = None
        for i in range(1, project.GetTimelineCount() + 1):
            t = project.GetTimelineByIndex(i)
            if t and t.GetName() == source_timeline:
                found = t
                break
        if found is None:
            print(f'ERROR: Source timeline "{source_timeline}" not found.', file=sys.stderr)
            return 1
        orig_tl = found

    fps          = float(project.GetSetting('timelineFrameRate'))
    orig_start   = orig_tl.GetStartFrame()
    orig_end     = orig_tl.GetEndFrame()
    orig_name    = orig_tl.GetName()
    max_vid_idx  = orig_tl.GetTrackCount('video')
    max_aud_idx  = orig_tl.GetTrackCount('audio')

    # ── Find "assets" bin ────────────────────────────────────────────────────
    root       = pool.GetRootFolder()
    assets_bin = find_bin(root, 'assets')
    if assets_bin is None:
        print('ERROR: "assets" bin not found. Run --do-import first.', file=sys.stderr)
        return 1

    # ── Resolve MPIs from manifest filenames ─────────────────────────────────
    group_paths   = manifest.get(group_key, {})

    def mpi_for_key(key):
        path = group_paths.get(key)
        if not path:
            return None
        return find_in_bin(assets_bin, Path(path).name)

    intro_mpi     = mpi_for_key(intro_k)
    outro_vid_mpi = mpi_for_key(outro_vid_k)
    outro_aud_mpi = mpi_for_key(outro_aud_k) or outro_vid_mpi  # fallback

    if intro_mpi is None:
        print(f'ERROR: Intro not found in "assets" bin (key={intro_k}).', file=sys.stderr)
        return 1

    # mpi_duration_frames used only for the dry-run estimate; actual run reads
    # the placed item's GetDuration() to get the true timeline-frame count.
    intro_tl_frames_est = mpi_duration_frames(intro_mpi, fps)
    if not intro_tl_frames_est:
        print('ERROR: Could not estimate intro duration.', file=sys.stderr)
        return 1

    # ── Collect existing clips ────────────────────────────────────────────────
    existing = collect_clips(orig_tl)

    print(f'Game:         {game_def["display_name"]}')
    print(f'Intro:        {intro_mpi.GetName()} (~{intro_tl_frames_est} TL frames est.)')
    print(f'Intro speed:  {intro_speed}%  ({speed_reason})')
    print(f'Outro video:  {outro_vid_mpi.GetName() if outro_vid_mpi else "none"}')
    print(f'Outro audio:  {outro_aud_mpi.GetName() if outro_aud_mpi else "none"}')
    print(f'Clips found:  {len(existing)}')
    print(f'Original TL:  frames {orig_start}–{orig_end}')

    if dry_run:
        # Estimate the retimed intro duration. Resolve rounds to whole frames,
        # so this may be off by ±1 vs the actual placed-then-retimed result.
        intro_tl  = max(1, round(intro_tl_frames_est * 100 / intro_speed))
        outro_rel = (orig_end - orig_start) + intro_tl
        print('\n── DRY RUN (shift estimate) ──')
        print(f'  Intro  → recordFrame={orig_start}  '
              f'(~{intro_tl} TL frames after {intro_speed}% retime; '
              f'native ~{intro_tl_frames_est})')
        for c in sorted(existing, key=lambda x: (x['mediaType'], x['trackIndex'], x['relRecord'])):
            new_rf = orig_start + c['relRecord'] + intro_tl
            print(f'  type={c["mediaType"]} track={c["trackIndex"]:2d}  '
                  f'src=[{c["startFrame"]},{c["endFrame"]}]  '
                  f'record {c["relRecord"]} → {new_rf}  '
                  f'{c["mediaPoolItem"].GetName()}')
        if outro_vid_mpi:
            print(f'  Outro video → recordFrame={orig_start + outro_rel}')
        if outro_aud_mpi:
            print(f'  Outro audio → recordFrame={orig_start + outro_rel} (A3)')
        return 0

    # ── Create new timeline ───────────────────────────────────────────────────
    new_name = unique_tl_name(project, orig_name + ' (edit)')
    new_tl   = pool.CreateEmptyTimeline(new_name)
    if new_tl is None:
        print('ERROR: Failed to create new timeline.', file=sys.stderr)
        return 1

    project.SetCurrentTimeline(new_tl)
    new_start = new_tl.GetStartFrame()

    # Ensure enough tracks (at least as many as original, and at least 3 audio)
    needed_audio = max(max_aud_idx, 3)
    ensure_tracks(new_tl, max_vid_idx, needed_audio)

    # ── Place intro (no startFrame/endFrame → Resolve uses full clip) ─────────
    pool.AppendToTimeline([{
        'mediaPoolItem': intro_mpi,
        'recordFrame':  new_start,
        'trackIndex':   1,
        'mediaType':    1,
    }])

    # Read back actual timeline-frame duration — this handles any fps conversion
    intro_items = new_tl.GetItemListInTrack('video', 1) or []
    if not intro_items:
        print('ERROR: Intro was not placed on V1.', file=sys.stderr)
        return 1
    intro_item = intro_items[0]

    # Apply retime (no-op if speed=100). After SetProperty, re-read GetDuration
    # so the gameplay shift uses the post-retime length.
    retime_clip(intro_item, intro_speed)

    intro_tl_frames = intro_item.GetDuration()
    print(f'Intro placed: {intro_tl_frames} TL frames '
          f'({intro_tl_frames/fps:.2f}s @ {intro_speed}%)')

    # ── Re-place all original clips shifted by the actual intro TL duration ───
    outro_rel = (orig_end - orig_start) + intro_tl_frames
    if existing:
        shifted = []
        for c in existing:
            shifted.append({
                'mediaPoolItem': c['mediaPoolItem'],
                'startFrame':   c['startFrame'],
                'endFrame':     c['endFrame'],
                'recordFrame':  new_start + c['relRecord'] + intro_tl_frames,
                'trackIndex':   c['trackIndex'],
                'mediaType':    c['mediaType'],
            })
        placed = pool.AppendToTimeline(shifted) or []
        print(f'Re-placed {len(placed)}/{len(shifted)} original clips.')

    # ── Append outro video on V1 (full clip, no startFrame/endFrame) ──────────
    outro_abs = new_start + outro_rel
    if outro_vid_mpi:
        pool.AppendToTimeline([{
            'mediaPoolItem': outro_vid_mpi,
            'recordFrame':  outro_abs,
            'trackIndex':   1,
            'mediaType':    1,
        }])
        print(f'Outro video placed at frame {outro_abs}.')

    # ── Append outro audio on A3 (full clip, no startFrame/endFrame) ──────────
    if outro_aud_mpi:
        pool.AppendToTimeline([{
            'mediaPoolItem': outro_aud_mpi,
            'recordFrame':  outro_abs,
            'trackIndex':   3,
            'mediaType':    2,
        }])
        print(f'Outro audio placed on A3 at frame {outro_abs}.')

    print(f'\nDone. New timeline: "{new_name}"  (original "{orig_name}" preserved)')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--game', required=True, help='Game catalog key (e.g. pokemon_crystal)')
    parser.add_argument('--source-timeline', metavar='NAME',
                        help='Name of source timeline to use (default: current timeline)')
    parser.add_argument('--intro-speed', type=int, metavar='PCT',
                        help='Retime intro to this percent (e.g. 400 for 4x). '
                             'Default: auto-detect from transcripts/min-battles.json — '
                             '100%% for Minimum Battles Series, 400%% otherwise.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print what would happen without touching Resolve')
    args = parser.parse_args()
    return run(args.game, args.dry_run, args.source_timeline,
               intro_speed=args.intro_speed)


if __name__ == '__main__':
    sys.exit(main())
