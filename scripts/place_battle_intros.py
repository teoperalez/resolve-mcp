"""
Place battle-intro graphics on V2 over the 5 seconds leading into each
major-boss battle on the current Resolve timeline.

For Gen 1 Red/Blue/Yellow projects, pass `--gen1-insert`. Those leader intros
are discrete video + audio files (e.g. Brock.mp4 + audio/Brock.mp3), not silent
overlays. In that mode this script creates a derived timeline, splits clips at
each leader intro point, leaves an empty V1/A1 gap, inserts the intro video on
the selected Gen 1 video track (V2 by default), inserts original-speed audio on
the selected audio track, and ripples all later timeline content to the right.
`--gen1-speed` retimes only the video; matching audio starts on A3 under the
intro and can continue on A2 through the battle window.
For repeated Gen 1 leader/E4/champion attempts after a give-up or loss, the
script inserts only a one-second source-backed pre-battle gap instead of
repeating the leader intro. Only the first attempt against each trainer gets
the discrete intro.

For each battle in `transcripts/battles.json` classified as `rival` or `gym`
(in `transcripts/battle-types.json`):

  - Map the battle's source-time timestamp to a timeline frame via the
    current V1 clip layout.
  - Pick the matching intro media-pool item:
      * gym / elite4 / champion: `{trainer_lowercase}-battle-intro.mov`
        from the `battle-intros` bin (e.g. `falkner-battle-intro.mov`).
      * rival: `silver-<location>-<starter_type>-battle-intro.mov`
        from the `silver-battle-intros` bin. The location comes from
        `transcripts/rival-starter.json` (per-battle), the starter type
        from the same file (single value for the video).
  - Place the intro on V2, ending exactly at the battle's timeline frame.
    The intro's tail aligns with the battle start; its head sits at
    `battle_frame - min(5s, intro_duration)`. This puts the graphic over
    the LAST 5 seconds of the V1 clip that comes immediately before the
    battle, per the IRLPC workflow spec.

The script only places VIDEO on V2 (mediaType=1) — the intro file's audio
is dropped so it doesn't conflict with the A2 BGM / battle-audio pipeline.

Usage:
    python place_battle_intros.py [--overlap-sec 5] [--include-other]
                                  [--track-index 2] [--dry-run]

`--include-other` also places intros for battle-types classified as
`other` (route trainers, Rocket grunts) using the trainer-name slug; useful
when the user has custom intro files for named overworld trainers.
"""
import sys
import os
import json
import re
import argparse
import subprocess
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401

import DaVinciResolveScript as dvr

TRANSCRIPTS_DIR  = Path('transcripts')
BATTLES_JSON     = TRANSCRIPTS_DIR / 'battles.json'
BATTLE_TYPES     = TRANSCRIPTS_DIR / 'battle-types.json'
RIVAL_STARTER    = TRANSCRIPTS_DIR / 'rival-starter.json'

BATTLE_INTROS_BIN        = 'battle-intros'
SILVER_BATTLE_INTROS_BIN = 'silver-battle-intros'
GEN1_LEADER_INTROS_DIR   = Path(r'C:\Programming\RBYNewLayout\gymLeaders\LeaderIntros')
GEN1_RETIME_CACHE_DIR    = Path.home() / '.resolve-mcp' / 'cache' / 'retimed-gen1-intros'
GEN1_ALIASES = {
    'lt surge': 'Surge',
    'lt. surge': 'Surge',
    'surge': 'Surge',
    'blue': 'Champion',
    'champion': 'Champion',
    'rival3': 'Champion',
    'giovanni_gym': 'Giovanni',
}
GEN1_LEADER_NAMES = {
    'brock', 'misty', 'surge', 'lt surge', 'lt. surge', 'erika', 'koga',
    'sabrina', 'blaine', 'giovanni', 'lorelei', 'bruno', 'agatha', 'lance',
    'champion', 'blue',
}

# Canonical Crystal/HGSS rival encounter order, used as a fallback when
# rival-starter.json doesn't supply a location for a given battle index.
FALLBACK_CANONICAL_LOCATIONS = [
    'cherrygrove', 'azalea', 'burnedtower', 'goldenrod',
    'victoryroad', 'indigoplateau', 'mtmoon',
]


def slugify_trainer(name: str) -> str:
    """Normalize a trainer name to the form used in filenames:
    lowercased, dots/whitespace stripped, hyphens preserved. e.g.
    'Lt. Surge' -> 'ltsurge', 'Whitney' -> 'whitney'."""
    s = name.lower()
    s = re.sub(r'[^a-z0-9-]', '', s)
    return s


def build_a1_or_v1_map(timeline, fps):
    """Return a list of (tl_start_frame, tl_end_frame, src_start_frame,
    src_end_frame, name) for V1 clips. Used to map source-time to timeline."""
    v1 = sorted(timeline.GetItemListInTrack('video', 1) or [],
                key=lambda c: c.GetStart())
    out = []
    for c in v1:
        tl_s = c.GetStart()
        tl_e = tl_s + c.GetDuration()
        src_s = c.GetLeftOffset()
        src_e = src_s + c.GetDuration()
        out.append((tl_s, tl_e, src_s, src_e, c.GetName()))
    return out


def source_sec_to_tl_frame(source_sec, v1_map, fps, snap_tol_sec=1.0):
    """Map a source-time second to an absolute timeline frame. Snaps to the
    nearest V1 clip boundary if the timestamp lands in a silence-stripped gap."""
    src_frame = source_sec * fps
    # Identify the dominant (gameplay) source by name; only those clips count.
    name_counts = Counter(name for _, _, _, _, name in v1_map)
    if not name_counts:
        return None
    dominant = name_counts.most_common(1)[0][0]
    candidates = [e for e in v1_map if e[4] == dominant]

    for tl_s, tl_e, src_s, src_e, _ in candidates:
        if src_s <= src_frame <= src_e:
            return tl_s + round(src_frame - src_s)

    snap_tol_frames = snap_tol_sec * fps
    for tl_s, _, src_s, _, _ in candidates:
        if src_s - snap_tol_frames <= src_frame < src_s:
            return tl_s
    for _, tl_e, _, src_e, _ in candidates:
        if src_e < src_frame <= src_e + snap_tol_frames:
            return tl_e - 1
    return None


def find_bin_by_name(folder, name):
    """Search media pool folder tree for a sub-bin with given name."""
    if folder is None:
        return None
    if folder.GetName() == name:
        return folder
    for sub in folder.GetSubFolderList() or []:
        hit = find_bin_by_name(sub, name)
        if hit is not None:
            return hit
    return None


def collect_mpi_by_name(folder):
    """Return {item_name: MediaPoolItem} for every clip directly in folder."""
    out = {}
    for item in folder.GetClipList() or []:
        out[item.GetName()] = item
    return out


def collect_mpi_by_path(folder, out=None):
    """Return {absolute_file_path: MediaPoolItem} for all clips under folder."""
    if out is None:
        out = {}
    if folder is None:
        return out
    for item in folder.GetClipList() or []:
        try:
            path = item.GetClipProperty('File Path') or ''
        except Exception:
            path = ''
        if path:
            out[str(Path(path).resolve()).lower()] = item
    for sub in folder.GetSubFolderList() or []:
        collect_mpi_by_path(sub, out)
    return out


def item_for_path(pool, path: Path, cache: dict):
    key = str(path.resolve()).lower()
    item = cache.get(key)
    if item is not None:
        return item
    imported = pool.ImportMedia([str(path)]) or []
    if not imported:
        return None
    item = imported[0]
    cache[key] = item
    return item


def media_duration_tl_frames(mpi, fps: float) -> int:
    """Best-effort MediaPoolItem duration in timeline frames."""
    props = mpi.GetClipProperty() or {}
    clip_fps = fps
    try:
        clip_fps = float(props.get('FPS') or props.get('Video Frame Rate') or fps)
    except Exception:
        clip_fps = fps
    for key in ('Frames', 'Video Frames', 'Audio Frames'):
        try:
            native = int(props.get(key) or 0)
            if native > 0:
                return max(1, int(native * fps / clip_fps))
        except Exception:
            pass
    for key in ('Video Duration', 'Audio Duration', 'Duration'):
        raw = (props.get(key) or '').strip().replace(';', ':')
        parts = raw.split(':')
        if len(parts) == 4:
            try:
                h, m, s, f = [int(x) for x in parts]
                return max(1, int(round((h * 3600 + m * 60 + s + f / clip_fps) * fps)))
            except Exception:
                pass
    return int(round(5 * fps))


def media_duration_native_frames(mpi, fallback_tl_frames: int) -> int:
    """Best-effort MediaPoolItem duration in native source frames."""
    props = mpi.GetClipProperty() or {}
    for key in ('Frames', 'Video Frames'):
        try:
            native = int(props.get(key) or 0)
            if native > 0:
                return native
        except Exception:
            pass
    return fallback_tl_frames


def media_pool_item_fps(mpi, fallback: float) -> float:
    props = mpi.GetClipProperty() or {}
    for key in ('FPS', 'Video Frame Rate', 'Frame Rate'):
        try:
            value = float(props.get(key) or 0)
            if value > 0:
                return value
        except Exception:
            pass
    return fallback


def gen1_leader_name(battle: dict) -> str | None:
    raw = (battle.get('trainer_name') or battle.get('leader') or '').strip()
    raw = re.sub(r'^(START|RESUME)\s+\d+\s+', '', raw, flags=re.IGNORECASE).strip()
    raw = re.sub(r'\bBlue$', '', raw, flags=re.IGNORECASE).strip()
    key = raw.lower().replace(' battle start', '').replace(' battle', '')
    key = re.sub(r'\s+', ' ', key).strip()
    if key in ('rival', 'rival 1', 'rival 2'):
        return None
    if key in GEN1_ALIASES:
        return GEN1_ALIASES[key]
    if raw:
        cleaned = re.sub(r'[^A-Za-z0-9. ]+', '', raw).strip()
        if cleaned:
            return GEN1_ALIASES.get(cleaned.lower(), cleaned.split()[0].title())
    return None


def gen1_intro_paths(leader: str, root: Path, prefer_blue: bool = True) -> tuple[Path | None, Path | None]:
    video = None
    if prefer_blue:
        preferred = root / f'{leader}Blue.mp4'
        if preferred.exists():
            video = preferred
    if video is None:
        fallback = root / f'{leader}.mp4'
        if fallback.exists():
            video = fallback
    audio_name = 'Giovanni 3.mp3' if leader == 'Giovanni' else f'{leader}.mp3'
    audio = root / 'audio' / audio_name
    return video, audio if audio.exists() else None


def retime_audio_filter(speed: float) -> str:
    """ffmpeg atempo only accepts 0.5..2.0, so chain filters if needed."""
    remaining = float(speed)
    chunks = []
    while remaining > 2.0:
        chunks.append('atempo=2.0')
        remaining /= 2.0
    while remaining < 0.5:
        chunks.append('atempo=0.5')
        remaining /= 0.5
    chunks.append(f'atempo={remaining:.6g}')
    return ','.join(chunks)


def retime_gen1_media(path: Path, speed: float, kind: str) -> Path:
    """Return a cached media file retimed to `speed` for Gen 1 insert mode."""
    if abs(speed - 1.0) < 0.001:
        return path
    if speed <= 0:
        raise ValueError(f'Invalid Gen 1 intro speed: {speed}')
    GEN1_RETIME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = (
        f'{speed:.3f}'.rstrip('0').rstrip('.').replace('.', 'p')
        + 'x_resolve2'
    )
    out_ext = path.suffix if kind == 'video' else '.mp3'
    out = GEN1_RETIME_CACHE_DIR / f'{path.stem}__{suffix}{out_ext}'
    if out.exists() and out.stat().st_size > 0 and out.stat().st_mtime >= path.stat().st_mtime:
        return out
    if kind == 'video':
        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
            '-i', str(path),
            '-map', '0:v:0',
            '-map_metadata', '-1',
            '-map_chapters', '-1',
            '-filter:v', f'setpts=PTS/{speed:.8g}',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            '-write_tmcd', '0',
            '-dn', '-sn',
            '-an',
            str(out),
        ]
    else:
        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
            '-i', str(path),
            '-map', '0:a:0',
            '-map_metadata', '-1',
            '-map_chapters', '-1',
            '-vn',
            '-filter:a', retime_audio_filter(speed),
            '-codec:a', 'libmp3lame',
            '-q:a', '2',
            str(out),
        ]
    subprocess.run(cmd, check=True)
    return out


def battle_inputs_from_markers(tl) -> tuple[list[dict], dict]:
    """Canonical Gen 1 battle inputs from timeline ruler markers.

    RBYNewLayout projects carry battle starts as timeline markers derived from
    session logs. When those markers exist, they are more authoritative than
    transcript guesses and should drive intro placement. If no markers exist,
    callers fall back to transcripts/battles.json + battle-types.json.
    """
    starts = []
    finishes_by_ordinal = {}
    finishes = []
    for frame_rel, marker in sorted((tl.GetMarkers() or {}).items()):
        rel = int(round(float(frame_rel)))
        name = marker.get('name') or ''
        start_match = re.search(r'\b(?:START|RESUME)\s+(\d+)\s+(.+?)\s+Battle Start$', name, re.I)
        finish_match = re.search(r'\bEND\??\s+(\d+)\s+(.+?)\s+Battle Finish', name, re.I)
        if start_match:
            starts.append({
                'rel': rel,
                'ordinal': int(start_match.group(1)),
                'trainer': start_match.group(2).strip(),
                'name': name,
            })
            continue
        if finish_match:
            row = {
                'rel': rel,
                'ordinal': int(finish_match.group(1)),
                'trainer': finish_match.group(2).strip(),
                'name': name,
            }
            finishes_by_ordinal[row['ordinal']] = row
            finishes.append(row)
            continue
        if name.endswith(' Battle Start'):
            starts.append({
                'rel': rel,
                'ordinal': None,
                'trainer': name.removesuffix(' Battle Start').strip(),
                'name': name,
            })

    battles = []
    types = {}
    for idx, start in enumerate(starts):
        trainer = start['name'].removesuffix(' Battle Start')
        trainer_for_type = re.sub(r'^(START|RESUME)\s+\d+\s+', '', trainer, flags=re.IGNORECASE).strip()
        finish = finishes_by_ordinal.get(start['ordinal'])
        finish_rel = finish['rel'] if finish else None
        finish_source = finish['name'] if finish else ''
        if finish_rel is None:
            next_start = starts[idx + 1]['rel'] if idx + 1 < len(starts) else None
            if next_start and next_start > start['rel']:
                finish_rel = next_start
                finish_source = 'next Battle Start fallback'
        battles.append({
            'trainer_name': trainer,
            'description': f'from timeline marker at frame {start["rel"]}',
            'marker_frame_rel': start['rel'],
            'battle_end_marker_frame_rel': finish_rel,
            'battle_end_marker_source': finish_source,
            'first_time': True,
        })
        types[str(idx)] = {
            'type': 'rival' if trainer_for_type.lower().startswith('rival') else 'gym',
            'reasoning': 'derived from canonical timeline Battle Start marker',
        }
    return battles, types


def collect_timeline_clip_specs(tl, fps: float):
    """Collect source slices from the current timeline with exclusive endFrame."""
    tl_start = tl.GetStartFrame()
    specs = []
    for track_type, media_type in (('video', 1), ('audio', 2)):
        for track in range(1, tl.GetTrackCount(track_type) + 1):
            for item in tl.GetItemListInTrack(track_type, track) or []:
                mpi = item.GetMediaPoolItem()
                if mpi is None:
                    continue
                source_frames_per_tl_frame = 1.0
                if media_type == 1:
                    source_frames_per_tl_frame = media_pool_item_fps(mpi, fps) / fps
                source_duration = max(1, int(round(item.GetDuration() * source_frames_per_tl_frame)))
                specs.append({
                    'mediaPoolItem': mpi,
                    'name': item.GetName() or '',
                    'startFrame': item.GetLeftOffset(),
                    'endFrame': item.GetLeftOffset() + source_duration,
                    'relRecord': item.GetStart() - tl_start,
                    'duration': item.GetDuration(),
                    'trackIndex': track,
                    'mediaType': media_type,
                    'clipColor': item.GetClipColor() or '',
                    'source_frames_per_tl_frame': source_frames_per_tl_frame,
                })
    return specs


def unique_timeline_name(project, base: str) -> str:
    existing = set()
    for i in range(1, project.GetTimelineCount() + 1):
        t = project.GetTimelineByIndex(i)
        if t:
            existing.add(t.GetName())
    name, n = base, 2
    while name in existing:
        name = f'{base} {n}'
        n += 1
    return name


def cumulative_shift(frame_rel: int, insertions: list[dict]) -> int:
    return sum(p['duration_frames'] for p in insertions if frame_rel >= p['record_rel'])


def cumulative_shift_before(frame_rel: int, insertions: list[dict]) -> int:
    return sum(p['duration_frames'] for p in insertions if frame_rel > p['record_rel'])


def ranges_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return start_a < end_b and start_b < end_a


def split_shift_specs(existing: list[dict], insertions: list[dict]) -> list[dict]:
    shifted = []
    for spec in existing:
        cuts = [0, spec['duration']]
        for ins in insertions:
            if spec['relRecord'] < ins['record_rel'] < spec['relRecord'] + spec['duration']:
                cuts.append(ins['record_rel'] - spec['relRecord'])
        cuts = sorted(set(cuts))
        for a, b in zip(cuts, cuts[1:]):
            if b <= a:
                continue
            base_record = spec['relRecord'] + a
            ratio = float(spec.get('source_frames_per_tl_frame') or 1.0)
            shifted.append({
                'mediaPoolItem': spec['mediaPoolItem'],
                'startFrame': spec['startFrame'] + int(round(a * ratio)),
                'endFrame': spec['startFrame'] + int(round(b * ratio)),
                'recordRel': base_record + cumulative_shift(base_record, insertions),
                'trackIndex': spec['trackIndex'],
                'mediaType': spec['mediaType'],
                'clipColor': spec.get('clipColor', ''),
            })
    return sorted(shifted, key=lambda s: (s['mediaType'], s['trackIndex'], s['recordRel']))


def source_gap_specs(existing: list[dict], record_rel: int, duration_frames: int) -> list[dict]:
    """Build V1/A1 source slices for a one-second pre-battle gap.

    Duplicate Gen 1 leader attempts should not get the full leader intro again,
    but they still need a short source-backed pre-battle gap. Use the clip at
    the battle marker when possible; when the marker is exactly on a cut, use
    the next clip's source in-point and pull the requested handle before it.
    """
    specs = []
    for media_type, track_index in ((1, 1), (2, 1)):
        candidates = sorted(
            [
                s for s in existing
                if int(s['mediaType']) == media_type and int(s['trackIndex']) == track_index
            ],
            key=lambda s: (int(s['relRecord']), int(s['startFrame'])),
        )
        hit = None
        source_at = None
        for spec in candidates:
            rel = int(spec['relRecord'])
            dur = int(spec['duration'])
            if rel <= record_rel < rel + dur:
                hit = spec
                source_at = int(spec['startFrame']) + (record_rel - rel)
                break
        if hit is None:
            next_spec = next((s for s in candidates if int(s['relRecord']) >= record_rel), None)
            if next_spec is not None:
                hit = next_spec
                source_at = int(next_spec['startFrame'])
        if hit is None:
            prev_spec = next(
                (
                    s for s in reversed(candidates)
                    if int(s['relRecord']) + int(s['duration']) <= record_rel
                ),
                None,
            )
            if prev_spec is not None:
                hit = prev_spec
                source_at = int(prev_spec['startFrame']) + int(prev_spec['duration'])
        if hit is None or source_at is None:
            raise RuntimeError(
                f'Could not find V1/A1 source clip for duplicate Gen 1 gap at rel {record_rel}'
            )
        start = source_at - int(duration_frames)
        if start < 0:
            raise RuntimeError(
                f'Not enough source handle for duplicate Gen 1 gap at rel {record_rel}: '
                f'source_at={source_at}, requested={duration_frames}'
            )
        specs.append({
            'mediaPoolItem': hit['mediaPoolItem'],
            'startFrame': start,
            'endFrame': source_at,
            'trackIndex': track_index,
            'mediaType': media_type,
            'source_clip_name': hit.get('name', ''),
        })
    return specs


def add_shifted_markers(src_tl, dst_tl, insertions: list[dict]) -> tuple[int, int]:
    markers = src_tl.GetMarkers() or {}
    used = set()
    added = 0
    for frame, marker in sorted(markers.items()):
        new_frame = int(frame) + cumulative_shift(int(frame), insertions)
        while new_frame in used:
            new_frame += 1
        used.add(new_frame)
        ok = dst_tl.AddMarker(
            new_frame,
            marker.get('color', 'Blue'),
            marker.get('name', ''),
            marker.get('note', ''),
            marker.get('duration', 1),
            marker.get('customData', ''),
        )
        added += 1 if ok else 0
    return added, len(markers)


def run_gen1_insert(project, pool, tl, fps: float, placements: list[dict],
                    video_track: int, audio_track: int, battle_audio_track: int,
                    dry_run: bool, report_path: Path) -> int:
    existing = collect_timeline_clip_specs(tl, fps)
    insertions = sorted(placements, key=lambda p: p['record_rel'])
    for p in insertions:
        if p.get('kind') == 'repeat_gap':
            try:
                p['gap_specs'] = source_gap_specs(
                    existing,
                    int(p['record_rel']),
                    int(p['duration_frames']),
                )
            except Exception as exc:
                print(
                    f'ERROR: failed to prepare duplicate Gen 1 pre-battle gap '
                    f'for {p.get("leader", "?")}: {exc}',
                    file=sys.stderr,
                )
                return 1
    shifted = split_shift_specs(existing, insertions)
    new_name = unique_timeline_name(project, tl.GetName() + ' (gen1 intros)')

    print(f'\nGen 1 insert mode: derived timeline {new_name!r}')
    print(f'  Existing timeline clips: {len(existing)}')
    print(f'  Shifted/split clips:    {len(shifted)}')
    print(f'  Insertions:             {len(insertions)}')
    if dry_run:
        print('\nDRY RUN — no timeline created.')
        return 0

    new_tl = pool.CreateEmptyTimeline(new_name)
    if new_tl is None:
        print('ERROR: failed to create derived Gen 1 intro timeline', file=sys.stderr)
        return 1
    project.SetCurrentTimeline(new_tl)
    while new_tl.GetTrackCount('video') < max(tl.GetTrackCount('video'), video_track):
        new_tl.AddTrack('video')
    while new_tl.GetTrackCount('audio') < max(tl.GetTrackCount('audio'), audio_track, battle_audio_track):
        new_tl.AddTrack('audio', 'stereo')
    new_start = new_tl.GetStartFrame()

    payload = []
    colors = []
    for spec in shifted:
        payload.append({
            'mediaPoolItem': spec['mediaPoolItem'],
            'startFrame': spec['startFrame'],
            'endFrame': spec['endFrame'],
            'recordFrame': new_start + spec['recordRel'],
            'trackIndex': spec['trackIndex'],
            'mediaType': spec['mediaType'],
        })
        colors.append(spec.get('clipColor', ''))
    for p in insertions:
        record = new_start + p['record_rel'] + cumulative_shift(p['record_rel'], [i for i in insertions if i is not p])
        if p.get('kind') == 'repeat_gap':
            for gap_spec in p.get('gap_specs') or []:
                payload.append({
                    'mediaPoolItem': gap_spec['mediaPoolItem'],
                    'startFrame': gap_spec['startFrame'],
                    'endFrame': gap_spec['endFrame'],
                    'recordFrame': record,
                    'trackIndex': gap_spec['trackIndex'],
                    'mediaType': gap_spec['mediaType'],
                })
                colors.append('')
            continue
        payload.append({
            'mediaPoolItem': p['video_mpi'],
            'startFrame': 0,
            'endFrame': p.get('duration_native_frames') or p['duration_frames'],
            'recordFrame': record,
            'trackIndex': video_track,
            'mediaType': 1,
        })
        colors.append('')
        if p.get('audio_mpi') is not None:
            audio_dur = p.get('audio_duration_frames') or p['duration_frames']
            intro_audio_dur = min(audio_dur, p['duration_frames'])
            payload.append({
                'mediaPoolItem': p['audio_mpi'],
                'startFrame': 0,
                'endFrame': intro_audio_dur,
                'recordFrame': record,
                'trackIndex': audio_track,
                'mediaType': 2,
            })
            colors.append('')
            p['intro_audio_duration_frames'] = intro_audio_dur

            battle_end_rel = p.get('battle_end_marker_frame_rel')
            if battle_end_rel is not None:
                battle_start_record = record + p['duration_frames']
                battle_end_record = new_start + int(battle_end_rel) + cumulative_shift_before(int(battle_end_rel), insertions)
                battle_audio_needed = max(0, battle_end_record - battle_start_record)
                source_start = intro_audio_dur
                remaining = battle_audio_needed
                chunk_record = battle_start_record
                chunks = []
                while remaining > 0 and audio_dur > 0:
                    if source_start >= audio_dur:
                        source_start = 0
                    chunk = min(remaining, audio_dur - source_start)
                    if chunk <= 0:
                        break
                    payload.append({
                        'mediaPoolItem': p['audio_mpi'],
                        'startFrame': source_start,
                        'endFrame': source_start + chunk,
                        'recordFrame': chunk_record,
                        'trackIndex': battle_audio_track,
                        'mediaType': 2,
                    })
                    colors.append('')
                    chunks.append({
                        'record_frame': chunk_record,
                        'start_frame': source_start,
                        'end_frame': source_start + chunk,
                        'duration_frames': chunk,
                    })
                    remaining -= chunk
                    chunk_record += chunk
                    source_start = 0
                p['battle_audio_track'] = battle_audio_track
                p['battle_audio_duration_frames'] = battle_audio_needed - remaining
                p['battle_audio_requested_frames'] = battle_audio_needed
                p['battle_audio_chunks'] = chunks

    payload.sort(key=lambda s: (s['mediaType'], s['trackIndex'], s['recordFrame']))
    placed = []
    for i in range(0, len(payload), 100):
        placed.extend(pool.AppendToTimeline(payload[i:i + 100]) or [])
    print(f'Placed: {len(placed)}/{len(payload)} clips')
    if len(placed) != len(payload):
        print('ERROR: not all Gen 1 intro timeline clips placed', file=sys.stderr)
        return 1

    added_markers, expected_markers = add_shifted_markers(tl, new_tl, insertions)
    print(f'Reapplied ruler markers: {added_markers}/{expected_markers}')

    track_after = new_tl.GetItemListInTrack('video', video_track) or []
    a1_after = new_tl.GetItemListInTrack('audio', 1) or []
    missing = []
    a1_overlaps = []
    intro_insertions = [p for p in insertions if p.get('kind') != 'repeat_gap']
    for p in intro_insertions:
        shifted_rel = p['record_rel'] + cumulative_shift(p['record_rel'], [i for i in insertions if i is not p])
        expected_start = new_start + shifted_rel
        expected_end = expected_start + p['duration_frames']
        hit = next((c for c in track_after
                    if c.GetName() == p['video_mpi'].GetName()
                    and abs(c.GetStart() - expected_start) <= 1
                    and abs(c.GetEnd() - expected_end) <= 1), None)
        if hit is None:
            missing.append(p)
            continue
        for a1 in a1_after:
            a_start = a1.GetStart()
            a_end = a_start + a1.GetDuration()
            if ranges_overlap(hit.GetStart(), hit.GetEnd(), a_start, a_end):
                a1_overlaps.append({
                    'leader': p['leader'],
                    'video': hit.GetName() or '',
                    'video_start': hit.GetStart(),
                    'video_end': hit.GetEnd(),
                    'audio': a1.GetName() or '',
                    'audio_start': a_start,
                    'audio_end': a_end,
                })
    if missing:
        print('ERROR: API verification failed for Gen 1 inserted intros:', file=sys.stderr)
        for p in missing:
            print(f'  - {p["leader"]} at rel {p["record_rel"]}', file=sys.stderr)
        return 1
    if a1_overlaps:
        print('ERROR: Gen 1 intro video overlaps A1 source audio:', file=sys.stderr)
        for row in a1_overlaps:
            print(
                f'  - {row["leader"]}: {row["video"]} '
                f'[{row["video_start"]},{row["video_end"]}) overlaps '
                f'{row["audio"]} [{row["audio_start"]},{row["audio_end"]})',
                file=sys.stderr,
            )
        return 1

    manifest = report_path
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        'timeline': new_tl.GetName(),
        'mode': 'gen1_insert',
        'video_track': video_track,
        'audio_track': audio_track,
        'battle_audio_track': battle_audio_track,
        'intro_a1_overlap_count': len(a1_overlaps),
        'placements': [
            {
                'kind': p.get('kind', 'intro'),
                'battle_index': p['battle_index'],
                'leader': p['leader'],
                'video': p['video_mpi'].GetName() if p.get('video_mpi') else None,
                'audio': p['audio_mpi'].GetName() if p.get('audio_mpi') else None,
                'record_frame_rel': p['record_rel'],
                'duration_frames': p['duration_frames'],
                'battle_end_marker_frame_rel': p.get('battle_end_marker_frame_rel'),
                'battle_end_marker_source': p.get('battle_end_marker_source'),
                'intro_audio_duration_frames': p.get('intro_audio_duration_frames'),
                'battle_audio_duration_frames': p.get('battle_audio_duration_frames'),
                'battle_audio_requested_frames': p.get('battle_audio_requested_frames'),
                'battle_audio_chunks': p.get('battle_audio_chunks') or [],
                'gap_sources': [
                    {
                        'name': spec.get('source_clip_name', ''),
                        'start_frame': spec.get('startFrame'),
                        'end_frame': spec.get('endFrame'),
                        'track_index': spec.get('trackIndex'),
                        'media_type': spec.get('mediaType'),
                    }
                    for spec in (p.get('gap_specs') or [])
                ],
            }
            for p in insertions
        ],
    }, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'API verification passed: {len(intro_insertions)}/{len(intro_insertions)} Gen 1 intro clips found.')
    print(f'Wrote placement manifest: {manifest}')
    return 0


def pick_intro_filename(battle_index: int,
                        battle: dict,
                        battle_type: str,
                        rival_starter_data: dict | None) -> tuple[str | None, str]:
    """Return (filename_with_extension, debug_explanation).

    For gym/other: f'{slug}-battle-intro.mov' in battle-intros bin.
    For rival:     f'silver-{location}-{type}-battle-intro.mov' in silver-battle-intros.
    Returns (None, reason) when the intro can't be determined."""
    if battle_type == 'rival':
        if not rival_starter_data:
            return None, 'rival battle but no rival-starter.json data'
        starter = rival_starter_data.get('rival_starter_type')
        if starter not in ('fire', 'water', 'grass'):
            return None, f'rival_starter_type={starter!r} — need fire/water/grass'
        # Per-battle location lookup
        rivals_by_idx = rival_starter_data.get('rivals_by_battle_index') or {}
        loc = rivals_by_idx.get(str(battle_index)) or rivals_by_idx.get(battle_index)
        if not loc:
            # Fallback: canonical encounter order. Count rival ordinal.
            return None, (f'no location for battle_index={battle_index} in '
                          f'rival-starter.json, and fallback would need ordinal info')
        return (f'silver-{loc}-{starter}-battle-intro.mov',
                f'rival @ {loc!r} with {starter!r} starter')

    # gym (or other if --include-other is enabled)
    slug = slugify_trainer(battle.get('trainer_name', ''))
    if not slug:
        return None, f'cannot slugify trainer_name {battle.get("trainer_name")!r}'
    return f'{slug}-battle-intro.mov', f'{battle_type} → {slug!r}'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--overlap-sec', type=float, default=5.0,
                    help='Target overlap on the previous V1 clip (default: 5s). '
                         'Intros shorter than this are placed at their natural length.')
    ap.add_argument('--include-other', action='store_true',
                    help='Also place intros for battles classified as `other` '
                         '(route trainers, Rocket grunts) if a matching '
                         '<slug>-battle-intro.mov is available.')
    ap.add_argument('--track-index', type=int, default=2,
                    help='V-track to place intros on (default: 2 = V2)')
    ap.add_argument('--gen1-insert', action='store_true',
                    help='Gen 1 Red/Blue/Yellow mode: insert discrete leader '
                         'intro video/audio as real timeline time, creating a '
                         'derived timeline and rippling later clips/markers.')
    ap.add_argument('--gen1-root', default=str(GEN1_LEADER_INTROS_DIR),
                    help='Folder containing Gen 1 leader intro MP4s and audio/ '
                         f'(default: {GEN1_LEADER_INTROS_DIR})')
    ap.add_argument('--gen1-video-track', type=int, default=2,
                    help='Video track for Gen 1 leader intro videos (default: V2)')
    ap.add_argument('--gen1-audio-track', type=int, default=3,
                    help='Audio track for Gen 1 leader intro audio (default: A3)')
    ap.add_argument('--gen1-battle-audio-track', type=int, default=2,
                    help='Audio track for Gen 1 leader audio continuation after the intro (default: A2)')
    ap.add_argument('--gen1-speed', type=float, default=2.0,
                    help='Playback speed for Gen 1 discrete leader intro video only; audio stays 1x (default: 2.0)')
    ap.add_argument('--gen1-repeat-gap-frames', type=int, default=60,
                    help='For repeated Gen 1 leader/champion attempts, insert this many source-backed pre-battle frames instead of another intro (default: 60).')
    ap.add_argument('--no-blue-variants', action='store_true',
                    help='In --gen1-insert mode, do not prefer LeaderBlue.mp4 variants.')
    ap.add_argument('--dry-run', action='store_true',
                    help='Report what would be placed without modifying Resolve')
    ap.add_argument('--report', type=Path,
                    default=Path('_data') / 'qa-reports' / 'battle-intros-placements.json',
                    help='Write a JSON placement report (default: _data/qa-reports/battle-intros-placements.json)')
    args = ap.parse_args()

    if not BATTLES_JSON.exists() and not args.gen1_insert:
        print(f'ERROR: {BATTLES_JSON} not found', file=sys.stderr)
        return 1
    if not BATTLE_TYPES.exists() and not args.gen1_insert:
        print(f'ERROR: {BATTLE_TYPES} not found — run classify_battles.py first',
              file=sys.stderr)
        return 1

    battles = json.loads(BATTLES_JSON.read_text(encoding='utf-8')) if BATTLES_JSON.exists() else []
    types   = json.loads(BATTLE_TYPES.read_text(encoding='utf-8')) if BATTLE_TYPES.exists() else {}
    rival_data = None
    if RIVAL_STARTER.exists():
        rival_data = json.loads(RIVAL_STARTER.read_text(encoding='utf-8'))

    resolve = dvr.scriptapp('Resolve')
    if resolve is None:
        print('ERROR: Could not connect to DaVinci Resolve.', file=sys.stderr)
        return 1
    project = resolve.GetProjectManager().GetCurrentProject()
    tl      = project.GetCurrentTimeline()
    pool    = project.GetMediaPool()
    fps     = float(project.GetSetting('timelineFrameRate'))
    print(f'Timeline: {tl.GetName()!r}  fps={fps:.2f}')

    if args.gen1_insert:
        marker_battles, marker_types = battle_inputs_from_markers(tl)
        if marker_battles:
            battles = marker_battles
            types = marker_types
            print(f'  Gen 1 mode: using {len(battles)} canonical timeline Battle Start markers for placement')
        else:
            print('  Gen 1 mode: no Battle Start markers found; falling back to transcript battles')

    root = pool.GetRootFolder()
    mpi_by_path = collect_mpi_by_path(root)

    # Locate the two overlay intro bins. Gen 1 insert mode does not require
    # these bins, because its assets are discrete files on disk.
    gym_bin    = find_bin_by_name(root, BATTLE_INTROS_BIN)
    silver_bin = find_bin_by_name(root, SILVER_BATTLE_INTROS_BIN)
    if gym_bin is None and not args.gen1_insert:
        print(f'WARN: bin {BATTLE_INTROS_BIN!r} not found — gym intros will be skipped')
    if silver_bin is None and not args.gen1_insert:
        print(f'WARN: bin {SILVER_BATTLE_INTROS_BIN!r} not found — rival intros will be skipped')
    gym_items    = collect_mpi_by_name(gym_bin) if gym_bin else {}
    silver_items = collect_mpi_by_name(silver_bin) if silver_bin else {}
    if args.gen1_insert:
        print(f'  Gen 1 leader intro root: {args.gen1_root}')
    else:
        print(f'  battle-intros bin: {len(gym_items)} files')
        print(f'  silver-battle-intros bin: {len(silver_items)} files')

    v1_map = build_a1_or_v1_map(tl, fps)
    overlap_frames_target = int(round(args.overlap_sec * fps))

    placements = []
    skipped    = []
    gen1_intro_leaders_seen = set()

    for battle_index, b in enumerate(battles):
        t_entry = types.get(str(battle_index)) or types.get(battle_index)
        if not t_entry:
            skipped.append((b, 'no battle-type classification'))
            continue
        btype = t_entry.get('type')
        if btype not in ('rival', 'gym') and not (args.include_other and btype == 'other'):
            continue  # silently skip; only major-boss types get intros by default

        # Map source-time to timeline frame. Gen 1 RBY log rebuilds prefer
        # existing Battle Start ruler markers because transcript guesses are
        # less reliable than the session log.
        if args.gen1_insert and 'marker_frame_rel' in b:
            tl_frame = tl.GetStartFrame() + int(b['marker_frame_rel'])
        else:
            tl_frame = source_sec_to_tl_frame(b['timestamp_sec'], v1_map, fps)
            if tl_frame is None:
                skipped.append((b, f'cannot map source_sec={b["timestamp_sec"]} to timeline'))
                continue

        if args.gen1_insert:
            leader = gen1_leader_name(b)
            if not leader:
                skipped.append((b, f'[{btype}] no Gen 1 discrete intro for this trainer'))
                continue
            leader_key = leader.lower()
            if leader_key in gen1_intro_leaders_seen:
                gap_frames = max(0, int(args.gen1_repeat_gap_frames))
                if gap_frames <= 0:
                    skipped.append((b, f'[{btype}] duplicate Gen 1 attempt for {leader}; repeat gap disabled'))
                    continue
                placements.append({
                    'kind': 'repeat_gap',
                    'battle': b,
                    'battle_index': battle_index,
                    'type': btype,
                    'leader': leader,
                    'tl_frame': tl_frame,
                    'record_rel': int(tl_frame - tl.GetStartFrame()),
                    'duration_frames': gap_frames,
                    'reason': (
                        f'Duplicate Gen 1 {leader} attempt: no repeated leader intro; '
                        f'insert {gap_frames} source-backed pre-battle frames'
                    ),
                })
                continue
            gen1_intro_leaders_seen.add(leader_key)
            video_path, audio_path = gen1_intro_paths(
                leader,
                Path(args.gen1_root),
                prefer_blue=not args.no_blue_variants,
            )
            if video_path is None:
                skipped.append((b, f'[{btype}] Gen 1 video intro missing for {leader}'))
                continue
            if audio_path is None:
                skipped.append((b, f'[{btype}] Gen 1 audio intro missing for {leader}'))
                continue
            if abs(args.gen1_speed - 1.0) >= 0.001:
                try:
                    video_path = retime_gen1_media(video_path, args.gen1_speed, 'video')
                except Exception as exc:
                    skipped.append((b, f'[{btype}] failed to retime Gen 1 intro video for {leader}: {exc}'))
                    continue
            video_mpi = item_for_path(pool, video_path, mpi_by_path)
            audio_mpi = item_for_path(pool, audio_path, mpi_by_path)
            if video_mpi is None or audio_mpi is None:
                skipped.append((b, f'[{btype}] could not import Gen 1 intro media for {leader}'))
                continue
            duration_frames = media_duration_tl_frames(video_mpi, fps)
            duration_native_frames = media_duration_native_frames(video_mpi, duration_frames)
            audio_duration_frames = media_duration_tl_frames(audio_mpi, fps)
            placements.append({
                'kind': 'intro',
                'battle': b,
                'battle_index': battle_index,
                'type': btype,
                'leader': leader,
                'video_mpi': video_mpi,
                'audio_mpi': audio_mpi,
                'tl_frame': tl_frame,
                'record_rel': int(tl_frame - tl.GetStartFrame()),
                'battle_end_marker_frame_rel': b.get('battle_end_marker_frame_rel'),
                'battle_end_marker_source': b.get('battle_end_marker_source'),
                'duration_frames': duration_frames,
                'duration_native_frames': duration_native_frames,
                'audio_duration_frames': audio_duration_frames,
                'reason': (
                    f'Gen 1 insert video @ {args.gen1_speed:g}x, audio @ 1x → '
                    f'{video_path.name} + {audio_path.name}'
                ),
            })
            continue

        fname, why = pick_intro_filename(battle_index, b, btype, rival_data)
        if fname is None:
            skipped.append((b, f'[{btype}] {why}'))
            continue

        # Look up media-pool item
        if btype == 'rival':
            mpi = silver_items.get(fname)
        else:
            mpi = gym_items.get(fname)
        if mpi is None:
            skipped.append((b, f'[{btype}] media-pool item {fname!r} not found ({why})'))
            continue

        # Intro duration in TIMELINE frames (Resolve handles fps conversion via
        # GetClipProperty 'Frames' — but for the simple "use last N seconds"
        # approach we just place a fixed `overlap_frames_target` slice). To
        # support intros shorter than 5s, we read the property and clamp.
        try:
            intro_frames_native = int(mpi.GetClipProperty('Frames') or 0)
        except Exception:
            intro_frames_native = 0
        try:
            intro_fps_native = float(mpi.GetClipProperty('FPS') or fps)
        except Exception:
            intro_fps_native = fps
        # Native frames * (timeline_fps / native_fps) → timeline-frame count
        intro_frames_tl = int(round(intro_frames_native * fps / intro_fps_native)) \
                          if intro_frames_native else overlap_frames_target

        clip_dur_tl = min(intro_frames_tl, overlap_frames_target)
        record_frame = tl_frame - clip_dur_tl

        # Source startFrame/endFrame are in NATIVE frames. We want the LAST
        # clip_dur_tl timeline-frames of the intro, i.e. native_end - native_dur_of_clip.
        native_clip_dur = int(round(clip_dur_tl * intro_fps_native / fps)) \
                           if intro_frames_native else 0
        if intro_frames_native:
            src_end_native   = intro_frames_native - 1
            src_start_native = max(0, src_end_native - native_clip_dur + 1)
        else:
            src_start_native = 0
            src_end_native   = max(0, clip_dur_tl - 1)

        placements.append({
            'battle':        b,
            'battle_index':  battle_index,
            'type':          btype,
            'reason':        why,
            'filename':      fname,
            'mpi':           mpi,
            'tl_frame':      tl_frame,
            'record_frame':  record_frame,
            'clip_dur_tl':   clip_dur_tl,
            'src_start':     src_start_native,
            'src_end':       src_end_native,
        })

    # Report
    print(f'\nPlanned placements: {len(placements)}')
    for p in placements:
        if args.gen1_insert:
            kind = 'gap' if p.get('kind') == 'repeat_gap' else 'intro'
            print(f'  battle[{p["battle_index"]}] {p["type"]:5s}  {kind:5s} '
                  f'tl={p["record_rel"]/fps:7.1f}s  dur={p["duration_frames"]/fps:4.1f}s  '
                  f'{p["leader"]}  ({p["reason"]})')
        else:
            rel_record = (p['record_frame'] - tl.GetStartFrame()) / fps
            print(f'  battle[{p["battle_index"]}] {p["type"]:5s}  '
                  f'tl={rel_record:7.1f}s  dur={p["clip_dur_tl"]/fps:4.1f}s  '
                  f'{p["filename"]}  ({p["reason"]})')
    if skipped:
        print(f'\nSkipped ({len(skipped)}):')
        for b, why in skipped:
            loc = (f'@ {b["timestamp_sec"]:.1f}s'
                   if 'timestamp_sec' in b else f'@ marker {b.get("marker_frame_rel", "?")}')
            print(f'  {b.get("trainer_name", "?")!r} {loc} — {why}')

    if args.dry_run:
        print('\nDRY RUN — no clips placed.')
        return 0

    if not placements:
        print('\nNothing to place.')
        return 0

    if args.gen1_insert:
        return run_gen1_insert(project, pool, tl, fps, placements,
                               args.gen1_video_track,
                               args.gen1_audio_track,
                               args.gen1_battle_audio_track,
                               args.dry_run,
                               args.report)

    while tl.GetTrackCount('video') < args.track_index:
        tl.AddTrack('video')

    # Idempotency: clear any prior battle-intro V2 clips before placing new
    # ones. We identify them by source-name suffix '-battle-intro.mov' which
    # is unique to the two intro bins. This way re-running with corrected
    # rival-starter.json data does the right thing without manual cleanup.
    track = tl.GetItemListInTrack('video', args.track_index) or []
    stale = [c for c in track
             if (c.GetName() or '').endswith('-battle-intro.mov')]
    if stale:
        print(f'\nClearing {len(stale)} stale battle-intro clip(s) from '
              f'V{args.track_index}:')
        for c in stale:
            print(f'  - {c.GetName()}')
        ok = tl.DeleteClips(stale, False)
        if not ok:
            print(f'  WARN: DeleteClips returned {ok!r}; some stale clips may remain')

    # Build the AppendToTimeline payload — video only, V<track_index>
    payload = []
    for p in placements:
        payload.append({
            'mediaPoolItem': p['mpi'],
            'startFrame':    p['src_start'],
            'endFrame':      p['src_end'],
            'recordFrame':   p['record_frame'],
            'trackIndex':    args.track_index,
            'mediaType':     1,  # video only
        })

    placed = pool.AppendToTimeline(payload) or []
    print(f'\nPlaced: {len(placed)}/{len(payload)} clips on V{args.track_index}')
    if len(placed) < len(payload):
        print(f'  WARN: {len(payload) - len(placed)} placement(s) failed — likely '
              f'V{args.track_index} is occupied at one of the record positions, '
              f'or the source range was outside the media. Review with --dry-run.')
    track_after = tl.GetItemListInTrack('video', args.track_index) or []
    missing = []
    for p in placements:
        expected_end = p['record_frame'] + p['clip_dur_tl']
        hit = None
        for c in track_after:
            if (c.GetName() == p['filename']
                    and abs(c.GetStart() - p['record_frame']) <= 1
                    and abs(c.GetEnd() - expected_end) <= 2):
                hit = c
                break
        if hit is None:
            missing.append(p)
    if missing:
        print(f'\nERROR: API verification failed; missing expected '
              f'V{args.track_index} battle intro clip(s):')
        for p in missing:
            print(f'  - {p["filename"]} at {p["record_frame"]}'
                  f'..{p["record_frame"] + p["clip_dur_tl"]}')
        return 1

    manifest = Path('_data') / 'qa-reports' / 'battle-intros-placements.json'
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        'timeline': tl.GetName(),
        'track_index': args.track_index,
        'placements': [
            {
                'battle_index': p['battle_index'],
                'type': p['type'],
                'filename': p['filename'],
                'record_frame': p['record_frame'],
                'end_frame': p['record_frame'] + p['clip_dur_tl'],
                'duration_frames': p['clip_dur_tl'],
                'reason': p['reason'],
            }
            for p in placements
        ],
    }, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'API verification passed: {len(placements)}/{len(placements)} '
          f'expected V{args.track_index} intro clips found.')
    print(f'Wrote placement manifest: {manifest}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
