"""
_audit_state.py — capture, diff, and (de)serialize DaVinci Resolve timeline
state for the step-level audit system.

The snapshot is a plain dict (JSON-serializable). It records everything a
pipeline step might legitimately or accidentally change:

    - Timeline identity (name, fps, start frame, total clip/marker counts)
    - All clips on every video/audio track (one entry per clip)
    - Timeline-ruler markers and clip-level markers
    - Per-track lock state

Two snapshots can be diffed to detect what a step actually did. Clip
identity uses (source_path, src_left_offset, src_duration) — NOT the
track index — so a ripple delete that shifts everything left doesn't
look like "every surviving clip was modified".

This module is import-only. The CLI lives in audit_step.py.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


# ── snapshot capture ────────────────────────────────────────────────────────

def _safe(value: Any, default: Any = None) -> Any:
    """Treat a callable that errors as missing."""
    try:
        return value
    except Exception:
        return default


def _capture_clip(clip, track_kind: str, track_index: int, fps: float) -> dict:
    """One serializable record per timeline clip."""
    mpi = None
    src_path = ''
    try:
        mpi = clip.GetMediaPoolItem()
        if mpi is not None:
            src_path = mpi.GetClipProperty('File Path') or ''
    except Exception:
        pass

    rec: dict = {
        'name':         clip.GetName() or '',
        'track':        f'{"V" if track_kind == "video" else "A" if track_kind == "audio" else "S"}{track_index}',
        'track_kind':   track_kind,
        'track_index':  track_index,
        'start_abs':    clip.GetStart(),
        'end_abs':      clip.GetEnd(),
        'duration':     clip.GetDuration(),
        'src_left':     clip.GetLeftOffset(),
        'src_dur':      clip.GetDuration(),
        'src_right':    clip.GetRightOffset(),
        'clip_color':   clip.GetClipColor() or '',
        'media_type':   1 if track_kind == 'video' else 2,
        'source_path':  src_path,
    }

    # Clip-level markers
    markers = {}
    try:
        markers = clip.GetMarkers() or {}
    except Exception:
        pass
    rec['markers'] = [
        {
            'src_frame':  int(src_f),
            'color':      m.get('color', ''),
            'name':       m.get('name', ''),
            'note':       m.get('note', ''),
            'customData': m.get('customData', ''),
            'duration':   m.get('duration', 1),
        }
        for src_f, m in sorted(markers.items())
    ]

    return rec


def _capture_track(tl, kind: str, idx: int, fps: float) -> dict:
    items = tl.GetItemListInTrack(kind, idx) or []
    items_sorted = sorted(items, key=lambda c: c.GetStart())
    try:
        locked = bool(tl.GetIsTrackLocked(kind, idx))
    except Exception:
        locked = False
    try:
        enabled = bool(tl.GetIsTrackEnabled(kind, idx))
    except Exception:
        enabled = True
    return {
        'kind':    kind,
        'index':   idx,
        'locked':  locked,
        'enabled': enabled,
        'clips':   [_capture_clip(c, kind, idx, fps) for c in items_sorted],
    }


def capture_timeline_state(tl, project) -> dict:
    """Snapshot the current state of the given timeline.

    Returns a JSON-serializable dict. Callers should not mutate the result;
    it is intended to be written verbatim to disk for later diffing.
    """
    if tl is None:
        return {'timeline_name': None, 'error': 'no current timeline'}

    fps = float(project.GetSetting('timelineFrameRate'))
    tl_start = int(tl.GetStartFrame())
    tl_end = int(tl.GetEndFrame())

    tracks: dict = {'video': {}, 'audio': {}, 'subtitle': {}}
    for kind in ('video', 'audio', 'subtitle'):
        try:
            n = int(tl.GetTrackCount(kind))
        except Exception:
            n = 0
        for idx in range(1, n + 1):
            tracks[kind][str(idx)] = _capture_track(tl, kind, idx, fps)

    # Timeline-ruler markers (frames are timeline-relative)
    raw_markers = {}
    try:
        raw_markers = tl.GetMarkers() or {}
    except Exception:
        pass
    ruler_markers = [
        {
            'frame_rel':  int(f_rel),
            'color':      m.get('color', ''),
            'name':       m.get('name', ''),
            'note':       m.get('note', ''),
            'customData': m.get('customData', ''),
            'duration':   m.get('duration', 1),
        }
        for f_rel, m in sorted(raw_markers.items())
    ]

    snap: dict = {
        'timeline_name':  tl.GetName(),
        'tl_start_frame': tl_start,
        'tl_end_frame':   tl_end,
        'fps':            fps,
        'tracks':         tracks,
        'markers_ruler':  ruler_markers,
        'counts': {
            'video_tracks':    len(tracks['video']),
            'audio_tracks':    len(tracks['audio']),
            'subtitle_tracks': len(tracks['subtitle']),
            'ruler_markers':   len(ruler_markers),
            'v_clips_total':   sum(len(t['clips']) for t in tracks['video'].values()),
            'a_clips_total':   sum(len(t['clips']) for t in tracks['audio'].values()),
        },
    }
    return snap


# ── identity helpers ────────────────────────────────────────────────────────

def _clip_identity(c: dict) -> tuple:
    """Stable identity key matching the same source slice across timeline
    shifts. Includes the track so a clip moved from V1 to V2 is not
    considered identical."""
    src_left = c.get('src_left', 0)
    src_dur = c.get('src_dur', 0)
    return (c.get('track', ''),
            c.get('source_path', ''),
            int(src_left if src_left is not None else 0),
            int(src_dur if src_dur is not None else 0))


def _index_clips(snap: dict) -> dict:
    """{(track, src_path, src_left, src_dur) -> clip_dict} for all tracks."""
    idx: dict = {}
    for kind in ('video', 'audio', 'subtitle'):
        for tdata in snap.get('tracks', {}).get(kind, {}).values():
            for c in tdata.get('clips', []):
                idx[_clip_identity(c)] = c
    return idx


def _index_ruler_markers(snap: dict) -> dict:
    """{(frame_rel, color, name) -> marker_dict}"""
    return {(m['frame_rel'], m['color'], m['name']): m
            for m in snap.get('markers_ruler', [])}


def _index_clip_markers(snap: dict) -> dict:
    """{(clip_identity, src_frame, color, name) -> marker_dict}"""
    out: dict = {}
    for kind in ('video', 'audio'):
        for tdata in snap.get('tracks', {}).get(kind, {}).values():
            for c in tdata.get('clips', []):
                cid = _clip_identity(c)
                for m in c.get('markers', []):
                    key = (cid, m['src_frame'], m['color'], m['name'])
                    out[key] = m
    return out


# ── diff ────────────────────────────────────────────────────────────────────

def diff_states(pre: dict, post: dict) -> dict:
    """Return a structured delta between two snapshots.

    Always-present top-level fields:
        timeline_changed   — bool (name or start_frame differs)
        timeline_before    — str
        timeline_after     — str
        tracks_added       — list of (kind, idx)
        tracks_removed     — list of (kind, idx)
        clips_added        — list of clip dicts present in post only
        clips_removed      — list of clip dicts present in pre only
        clips_modified     — list of {before, after, fields_changed}
        markers_ruler_added/removed
        markers_clip_added/removed
        colors_changed     — list of {identity, before, after}
        locks_changed      — list of {track, before, after}
    """
    out: dict = {
        'timeline_before':   pre.get('timeline_name'),
        'timeline_after':    post.get('timeline_name'),
        'timeline_changed':  (pre.get('timeline_name') != post.get('timeline_name')
                              or pre.get('tl_start_frame') != post.get('tl_start_frame')),
        'tracks_added':      [],
        'tracks_removed':    [],
        'clips_added':       [],
        'clips_removed':     [],
        'clips_modified':    [],
        'markers_ruler_added':   [],
        'markers_ruler_removed': [],
        'markers_clip_added':    [],
        'markers_clip_removed':  [],
        'colors_changed':    [],
        'locks_changed':     [],
        'counts_before':     pre.get('counts', {}),
        'counts_after':      post.get('counts', {}),
    }

    # Tracks
    for kind in ('video', 'audio', 'subtitle'):
        before = set(pre.get('tracks', {}).get(kind, {}).keys())
        after = set(post.get('tracks', {}).get(kind, {}).keys())
        for idx in sorted(after - before, key=int):
            out['tracks_added'].append((kind, int(idx)))
        for idx in sorted(before - after, key=int):
            out['tracks_removed'].append((kind, int(idx)))

    # Locks
    for kind in ('video', 'audio', 'subtitle'):
        for idx, tdata in pre.get('tracks', {}).get(kind, {}).items():
            post_t = post.get('tracks', {}).get(kind, {}).get(idx)
            if post_t is None:
                continue
            if bool(tdata.get('locked')) != bool(post_t.get('locked')):
                out['locks_changed'].append({
                    'track':  f'{"V" if kind == "video" else "A"}{idx}',
                    'before': bool(tdata.get('locked')),
                    'after':  bool(post_t.get('locked')),
                })

    # Clips
    pre_idx = _index_clips(pre)
    post_idx = _index_clips(post)
    for key, c in post_idx.items():
        if key not in pre_idx:
            out['clips_added'].append(c)
    for key, c in pre_idx.items():
        if key not in post_idx:
            out['clips_removed'].append(c)
    for key, c_pre in pre_idx.items():
        c_post = post_idx.get(key)
        if c_post is None:
            continue
        changed = []
        for field in ('start_abs', 'end_abs', 'duration',
                      'src_left', 'src_dur', 'clip_color', 'name'):
            if c_pre.get(field) != c_post.get(field):
                changed.append(field)
        if changed:
            out['clips_modified'].append({
                'identity': list(key),
                'fields_changed': changed,
                'before': {f: c_pre.get(f) for f in changed},
                'after':  {f: c_post.get(f) for f in changed},
            })
        if c_pre.get('clip_color') != c_post.get('clip_color'):
            out['colors_changed'].append({
                'identity': list(key),
                'before':   c_pre.get('clip_color', ''),
                'after':    c_post.get('clip_color', ''),
            })

    # Ruler markers
    pre_rm = _index_ruler_markers(pre)
    post_rm = _index_ruler_markers(post)
    for key, m in post_rm.items():
        if key not in pre_rm:
            out['markers_ruler_added'].append(m)
    for key, m in pre_rm.items():
        if key not in post_rm:
            out['markers_ruler_removed'].append(m)

    # Clip-level markers
    pre_cm = _index_clip_markers(pre)
    post_cm = _index_clip_markers(post)
    for key, m in post_cm.items():
        if key not in pre_cm:
            out['markers_clip_added'].append({'identity': list(key[0]), 'marker': m})
    for key, m in pre_cm.items():
        if key not in post_cm:
            out['markers_clip_removed'].append({'identity': list(key[0]), 'marker': m})

    return out


# ── I/O ─────────────────────────────────────────────────────────────────────

def slugify_timeline_name(name: Optional[str]) -> str:
    if not name:
        return 'unknown_timeline'
    keep = []
    for ch in name:
        if ch.isalnum() or ch in ('-', '_'):
            keep.append(ch)
        elif ch in (' ', '(', ')', '[', ']', ':'):
            keep.append('_')
    s = ''.join(keep).strip('_')
    return s or 'unknown_timeline'


def audits_dir(repo_root: Optional[Path] = None) -> Path:
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parent.parent
    d = root / '_data' / 'audits'
    d.mkdir(parents=True, exist_ok=True)
    return d


def snapshot_path(step_id: str, label: str = 'pre',
                  repo_root: Optional[Path] = None) -> Path:
    return audits_dir(repo_root) / f'{step_id}_{label}.json'


def report_path(step_id: str, repo_root: Optional[Path] = None) -> Path:
    return audits_dir(repo_root) / f'{step_id}_report.json'


def write_snapshot(snap: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, indent=2, ensure_ascii=False, default=str),
                    encoding='utf-8')


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))
