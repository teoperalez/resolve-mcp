"""
audit_step.py — step-level audit driver for the /edittimeline pipeline.

Two subcommands:

    audit_step.py snapshot --step STEP_ID
        Capture current timeline state and write _data/audits/<step>_pre.json.
        Call this BEFORE running a pipeline step.

    audit_step.py audit --step STEP_ID [--strict]
        Capture current state into _data/audits/<step>_post.json.
        Load <step>_pre.json. Diff. Validate diff against the step's
        declared scope in audit_scopes.py. Run verify_pipeline.py's
        audio/structure checks against the post-state. Write a report to
        _data/audits/<step>_report.json. If the audit passes, export a
        Resolve-native DRT checkpoint to _data/drt-checkpoints/ and record it
        in the report. Exit with violation count.

        --strict   also fails if expected changes were not observed.
        --no-drt   skips the post-pass DRT checkpoint export.

A non-zero exit code means the pipeline should STOP and the user should
inspect the report before continuing.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# Bootstrap Resolve env (sets sys.path so DaVinciResolveScript imports)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

import _audit_state as S
from audit_scopes import get_scope
import verify_pipeline as VP


# ── validators ──────────────────────────────────────────────────────────────

def _track_tuple(rule_or_track):
    """Extract (kind, idx) tuple from either a rule dict or a clip dict."""
    if isinstance(rule_or_track, dict):
        t = rule_or_track.get('track')
        if isinstance(t, (list, tuple)) and len(t) == 2:
            return (t[0], int(t[1]))
        return None
    return None


def _clip_track_tuple(c: dict):
    """Get (kind, idx) for a clip record."""
    return (c.get('track_kind', ''), int(c.get('track_index', 0)))


def _matches_predicate(clip: dict, predicate: str, arg, fps: float) -> bool:
    """Evaluate a named predicate against a clip dict. Keep this small."""
    if not predicate:
        return True
    if predicate == 'dur_lt_frames':
        return int(clip.get('duration', 0)) < int(arg)
    if predicate == 'dur_lt_sec':
        return (int(clip.get('duration', 0)) / fps) < float(arg)
    return True


def _allowed(diff_entry_kind: str, item, allowed_changes: list, fps: float) -> bool:
    """True iff the item is permitted by at least one allowed_changes rule."""
    for rule in allowed_changes:
        if rule.get('kind') != diff_entry_kind:
            continue
        # track filter
        rt = rule.get('track')
        if rt is not None:
            rt_t = (rt[0], int(rt[1]))
            if diff_entry_kind in ('clips_added', 'clips_removed', 'clips_modified',
                                   'clips_shifted'):
                clip = item if isinstance(item, dict) and 'track_kind' in item else None
                if clip is None and isinstance(item, dict) and 'before' in item:
                    clip = item.get('before') or item.get('after')
                if clip and _clip_track_tuple(clip) != rt_t:
                    continue
            elif diff_entry_kind in ('colors_changed',):
                clip = item.get('before') if isinstance(item, dict) else None
                if clip and _clip_track_tuple(clip) != rt_t:
                    continue
            elif diff_entry_kind in ('locks_changed',):
                tr = item.get('track', '')
                rt_str = f'{"V" if rt[0] == "video" else "A"}{rt[1]}'
                if tr != rt_str:
                    continue
            elif diff_entry_kind in ('markers_clip_added', 'markers_clip_removed'):
                # item['identity'] = [track, src_path, src_left, src_dur]
                ident = item.get('identity', [])
                if not ident:
                    continue
                tr_str = ident[0]
                rt_str = f'{"V" if rt[0] == "video" else "A"}{rt[1]}'
                if tr_str != rt_str:
                    continue
        # color filter
        colors = rule.get('colors')
        if colors is not None:
            if diff_entry_kind in ('markers_ruler_added', 'markers_ruler_removed'):
                if (item.get('color') or '') not in colors:
                    continue
            elif diff_entry_kind in ('markers_clip_added', 'markers_clip_removed'):
                if (item.get('marker', {}).get('color') or '') not in colors:
                    continue
            elif diff_entry_kind == 'colors_changed':
                # to_colors filter (rule.to_colors says "color may change TO X")
                pass
        to_colors = rule.get('to_colors')
        if to_colors is not None and diff_entry_kind == 'colors_changed':
            if (item.get('after') or '') not in to_colors:
                continue
        to_value = rule.get('to_value')
        if to_value is not None and diff_entry_kind == 'locks_changed':
            if bool(item.get('after')) != bool(to_value):
                continue
        # predicate
        pred = rule.get('predicate')
        if pred and diff_entry_kind == 'clips_removed':
            if not _matches_predicate(item, pred, rule.get('predicate_arg'), fps):
                continue
        return True
    return False


def _clip_color_change_allowed(cm: dict, allowed_changes: list) -> bool:
    """True when a clips_modified entry only reflects an allowed color flag."""
    if set(cm.get('fields_changed', [])) != {'clip_color'}:
        return False
    ident = cm.get('identity', [])
    track_name = ident[0] if ident else ''
    after_color = (cm.get('after') or {}).get('clip_color') or ''
    for rule in allowed_changes:
        if rule.get('kind') != 'colors_changed':
            continue
        rt = rule.get('track')
        if rt is not None:
            rt_str = f'{"V" if rt[0] == "video" else "A"}{rt[1]}'
            if track_name != rt_str:
                continue
        to_colors = rule.get('to_colors')
        if to_colors is not None and after_color not in to_colors:
            continue
        return True
    return False


def _check_must_preserve(diff: dict, must_preserve: list, fps: float,
                         allowed_changes: list | None = None) -> list[dict]:
    """Return a list of violations for must_preserve rules that diff broke."""
    allowed_changes = allowed_changes or []
    violations: list[dict] = []
    for rule in must_preserve:
        kind = rule.get('kind')

        if kind == 'clips':
            # No clips removed/modified on the given track (if track specified)
            rt = rule.get('track')
            for c in diff.get('clips_removed', []):
                if rt is None or _clip_track_tuple(c) == (rt[0], int(rt[1])):
                    if _allowed('clips_removed', c, allowed_changes, fps):
                        continue
                    violations.append({
                        'rule': rule,
                        'reason': 'clip removed on must-preserve track',
                        'item': c,
                    })
            for cm in diff.get('clips_modified', []):
                ident = cm.get('identity', [])
                if not ident:
                    continue
                tr = ident[0]
                if rt is not None:
                    rt_str = f'{"V" if rt[0] == "video" else "A"}{rt[1]}'
                    if tr != rt_str:
                        continue
                if _allowed('clips_modified', cm, allowed_changes, fps):
                    continue
                if _clip_color_change_allowed(cm, allowed_changes):
                    continue
                violations.append({
                    'rule': rule,
                    'reason': f'clip modified on must-preserve track ({", ".join(cm.get("fields_changed", []))})',
                    'item': cm,
                })

        elif kind == 'clips_count':
            removed = len(diff.get('clips_removed', []))
            added = len(diff.get('clips_added', []))
            if removed != 0 or added != 0:
                violations.append({
                    'rule': rule,
                    'reason': f'clip count changed (added={added}, removed={removed})',
                    'item': None,
                })

        elif kind == 'markers':
            where = rule.get('where')
            colors = rule.get('colors')
            except_colors = rule.get('except_colors')

            def _color_matches(c):
                if colors is not None:
                    return c in colors
                if except_colors is not None:
                    return c not in except_colors
                return True  # all markers must be preserved

            if where in (None, 'ruler'):
                for m in diff.get('markers_ruler_removed', []):
                    if _color_matches(m.get('color', '')):
                        violations.append({
                            'rule': rule,
                            'reason': f'ruler marker removed (color={m.get("color")}, name={m.get("name")!r})',
                            'item': m,
                        })
            if where in (None, 'clip_level'):
                for entry in diff.get('markers_clip_removed', []):
                    m = entry.get('marker', {})
                    if _color_matches(m.get('color', '')):
                        violations.append({
                            'rule': rule,
                            'reason': f'clip-level marker removed (color={m.get("color")}, name={m.get("name")!r})',
                            'item': entry,
                        })

        elif kind == 'locks':
            for lc in diff.get('locks_changed', []):
                violations.append({
                    'rule': rule, 'reason': 'lock state changed', 'item': lc,
                })

        elif kind == 'no_a2_overlaps':
            # Validated separately at audit time (needs current snapshot, not diff)
            pass

        elif kind == 'no_a2_clip_removed_before_first_battle':
            # Validated separately
            pass

        elif kind == 'a2_total_coverage_unchanged':
            # Validated separately
            pass

        elif kind in ('battle_intros_present', 'gen1_battle_intros_present'):
            # Validated separately
            pass

    return violations


def _check_no_a2_overlaps(post: dict, fps: float) -> list[dict]:
    """Detect overlapping clips on A2 — any pair of clips whose TL ranges
    intersect by more than 1 frame is a violation."""
    a2 = post.get('tracks', {}).get('audio', {}).get('2', {}).get('clips', [])
    a2 = sorted(a2, key=lambda c: int(c.get('start_abs', 0)))
    violations = []
    for i in range(len(a2) - 1):
        a, b = a2[i], a2[i + 1]
        a_end = int(a.get('end_abs', 0))
        b_start = int(b.get('start_abs', 0))
        if a_end - b_start > 1:
            violations.append({
                'rule': {'kind': 'no_a2_overlaps'},
                'reason': f'A2 clips overlap: {a.get("name")!r} ends at frame '
                          f'{a_end}, next ({b.get("name")!r}) starts at {b_start} '
                          f'({(a_end - b_start) / fps:.2f}s overlap)',
                'item': {'a': a.get('name'), 'b': b.get('name'),
                         'overlap_frames': a_end - b_start},
            })
    return violations


def _check_battle_intros_present(post: dict, rule: dict) -> list[dict]:
    track = rule.get('track', ('video', 2))
    kind, idx = track[0], str(track[1])
    min_count = int(rule.get('min_count', 1))
    clips = post.get('tracks', {}).get(kind, {}).get(idx, {}).get('clips', [])
    intros = [c for c in clips if (c.get('name') or '').endswith('-battle-intro.mov')]
    if len(intros) >= min_count:
        return []
    return [{
        'rule': rule,
        'reason': f'expected at least {min_count} battle-intro clip(s) on '
                  f'{kind.upper()}{idx}, found {len(intros)}',
        'item': {'found': [c.get('name') for c in intros]},
    }]


def _check_gen1_battle_intros_present(post: dict, rule: dict) -> list[dict]:
    track = rule.get('track', ('video', 1))
    kind, idx = track[0], str(track[1])
    min_count = int(rule.get('min_count', 1))
    clips = post.get('tracks', {}).get(kind, {}).get(idx, {}).get('clips', [])
    intros = [
        c for c in clips
        if 'leaderintros' in (c.get('source_path') or '').replace('\\', '').lower()
    ]
    if len(intros) >= min_count:
        return []
    return [{
        'rule': rule,
        'reason': f'expected at least {min_count} Gen 1 LeaderIntros clip(s) on '
                  f'{kind.upper()}{idx}, found {len(intros)}',
        'item': {'found': [c.get('name') for c in intros]},
    }]


def _is_gen1_leader_intro_clip(c: dict) -> bool:
    source = (c.get('source_path') or '').replace('\\', '/').lower()
    name = (c.get('name') or '').lower()
    return (
        '/gymleaders/leaderintros/' in source
        or '/leaderintros/' in source
        or 'leader intro' in name
    )


def _gen1_intro_identity(c: dict) -> tuple:
    return (
        c.get('track_kind', ''),
        int(c.get('track_index', 0)),
        c.get('source_path') or '',
        int(c.get('src_left', 0)),
        int(c.get('src_dur', 0)),
        c.get('name') or '',
    )


def _check_gen1_leader_intros_preserved(pre: dict, post: dict) -> list[dict]:
    """Once Gen 1 discrete leader intros exist, every later audit protects them.

    These clips are structural editorial sections like the channel intro/outro:
    downstream steps may ripple-shift them, but must not delete, trim, or swap
    either the video intro or its paired audio.
    """
    pre_counts: Counter = Counter()
    for kind in ('video', 'audio'):
        for tdata in pre.get('tracks', {}).get(kind, {}).values():
            for c in tdata.get('clips', []):
                if _is_gen1_leader_intro_clip(c):
                    pre_counts[_gen1_intro_identity(c)] += 1

    if not pre_counts:
        return []

    post_counts: Counter = Counter()
    for kind in ('video', 'audio'):
        for tdata in post.get('tracks', {}).get(kind, {}).values():
            for c in tdata.get('clips', []):
                if _is_gen1_leader_intro_clip(c):
                    post_counts[_gen1_intro_identity(c)] += 1

    missing = []
    for key, pre_n in pre_counts.items():
        post_n = post_counts.get(key, 0)
        if post_n < pre_n:
            missing.append({
                'identity': list(key),
                'pre': pre_n,
                'post': post_n,
            })

    if not missing:
        return []

    return [{
        'rule': {'kind': 'gen1_leader_intros_preserved'},
        'kind': 'gen1_leader_intros_preserved',
        'reason': f'{len(missing)} Gen 1 leader intro clip identity/count(s) '
                  f'were lost or altered after placement',
        'item': {'missing': missing[:30]},
    }]


def _check_v1_has_a1_coverage(post: dict) -> list[dict]:
    """Flag gameplay V1 clips with no corresponding aligned A1 audio.

    This catches Resolve scripting mistakes where appending/replacing a video
    clip silently drops its linked dialogue audio. The check requires at least
    one timeline/source-aligned A1 overlap for each V1 gameplay clip. It does
    not require exact clip boundaries, so layouts like the carousel's extended
    V1 bed can coexist with the original A1 edit underneath it.
    """
    tracks = post.get('tracks', {})
    v1 = tracks.get('video', {}).get('1', {}).get('clips', [])
    a1 = tracks.get('audio', {}).get('1', {}).get('clips', [])
    violations = []

    def exempt(c: dict) -> bool:
        name = (c.get('name') or '').lower()
        source = (c.get('source_path') or '').replace('\\', '').lower()
        return 'intro' in name or 'outro' in name or 'leaderintros' in source

    def same_dialogue_family(video_clip: dict, audio_clip: dict) -> bool:
        v_name = (video_clip.get('name') or '').lower()
        a_name = (audio_clip.get('name') or '').lower()
        v_src = (video_clip.get('source_path') or '').lower()
        a_src = (audio_clip.get('source_path') or '').lower()
        if (audio_clip.get('name') or '') == (video_clip.get('name') or '') and a_src == v_src:
            return True
        if not a_src.endswith('.wav'):
            return False
        # FileOrganizer/Resolve split-track WAVs are named from the source
        # video stem, e.g. "<part 1>_3.wav". Treat those as the dialogue mate
        # for the matching MP4 when source frames line up.
        v_stem = Path(v_src).stem.lower()
        a_stem = Path(a_src).stem.lower()
        if v_stem and a_stem.startswith(v_stem) and a_stem.endswith(('_1', '_2', '_3', '_4', '_5')):
            return True
        return bool(v_name and v_name.replace('.mp4', '') in a_name)

    for vc in v1:
        if exempt(vc):
            continue
        v_name = vc.get('name') or ''
        v_src = vc.get('source_path') or ''
        v_start = int(vc.get('start_abs', 0))
        v_end = int(vc.get('end_abs', 0))
        v_src_left = int(vc.get('src_left', 0))

        has_match = False
        for ac in a1:
            if not same_dialogue_family(vc, ac):
                continue
            a_start = int(ac.get('start_abs', 0))
            a_end = int(ac.get('end_abs', 0))
            ov_start = max(v_start, a_start)
            ov_end = min(v_end, a_end)
            if ov_start >= ov_end:
                continue
            a_src_at_overlap = int(ac.get('src_left', 0)) + (ov_start - a_start)
            v_src_at_overlap = v_src_left + (ov_start - v_start)
            if a_src_at_overlap == v_src_at_overlap:
                has_match = True
                break

        if not has_match:
            violations.append({
                'rule': {'kind': 'v1_has_a1_coverage'},
                'kind': 'v1_has_a1_coverage',
                'reason': 'V1 gameplay clip has no corresponding aligned A1 audio coverage',
                'item': {
                    'name': v_name,
                    'start_abs': v_start,
                    'end_abs': v_end,
                    'src_left': v_src_left,
                    'src_dur': int(vc.get('src_dur', 0)),
                    'clip_color': vc.get('clip_color', ''),
                },
            })

    return violations


def _dominant_gameplay_source(post: dict) -> tuple[str, str]:
    """Return (source_path, name) for the dominant A1 gameplay source."""
    a1 = post.get('tracks', {}).get('audio', {}).get('1', {}).get('clips', [])
    candidates = [
        ((c.get('source_path') or ''), (c.get('name') or ''))
        for c in a1
        if c.get('source_path')
    ]
    if not candidates:
        return '', ''
    (src, name), _count = Counter(candidates).most_common(1)[0]
    return src, name


def _check_no_gameplay_audio_outside_a1(post: dict) -> list[dict]:
    """Fail if the dominant gameplay source appears on A2+.

    A1 is the only valid home for gameplay/dialogue audio. A2 is reserved for
    music/battle audio, A3 for intentional outro audio, and A4+ should not
    receive gameplay audio. This catches Resolve auto-expanding embedded MP4
    audio when scripts append video MediaPoolItems.
    """
    gameplay_src, gameplay_name = _dominant_gameplay_source(post)
    if not gameplay_src:
        return []

    violations = []
    audio_tracks = post.get('tracks', {}).get('audio', {})
    for idx, tdata in audio_tracks.items():
        if int(idx) == 1:
            continue
        dupes = [
            c for c in tdata.get('clips', [])
            if (c.get('source_path') or '') == gameplay_src
        ]
        if dupes:
            violations.append({
                'rule': {'kind': 'no_gameplay_audio_outside_a1'},
                'reason': f'A{idx} contains {len(dupes)} gameplay-source audio '
                          f'clip(s) from {gameplay_name!r}; A1 is the only '
                          f'valid gameplay/dialogue audio track',
                'item': {
                    'track': f'A{idx}',
                    'source_path': gameplay_src,
                    'first_clips': [
                        {
                            'name': c.get('name'),
                            'start_abs': c.get('start_abs'),
                            'duration': c.get('duration'),
                        }
                        for c in dupes[:10]
                    ],
                },
            })
    return violations


def _check_no_raw_gameplay_audio_on_a2(post: dict) -> list[dict]:
    """Stronger A2-specific gate for the music bed."""
    gameplay_src, gameplay_name = _dominant_gameplay_source(post)
    if not gameplay_src:
        return []
    a2 = post.get('tracks', {}).get('audio', {}).get('2', {}).get('clips', [])
    dupes = [c for c in a2 if (c.get('source_path') or '') == gameplay_src]
    if not dupes:
        return []
    return [{
        'rule': {'kind': 'no_raw_gameplay_audio_on_a2'},
        'reason': f'A2 music bed contains {len(dupes)} raw gameplay-source '
                  f'audio clip(s) from {gameplay_name!r}',
        'item': {'first_clips': [c.get('name') for c in dupes[:10]]},
    }]


def _check_creates_new_timeline(pre: dict, post: dict, scope: dict) -> list[dict]:
    """Validate derived expectations when a step produced a new timeline."""
    violations = []
    exp = scope.get('derived_expectations', {}) or {}

    needle = exp.get('new_timeline_name_contains')
    if needle and needle not in (post.get('timeline_name') or ''):
        violations.append({
            'rule': {'kind': 'new_timeline_name_contains', 'value': needle},
            'reason': f'new timeline name {post.get("timeline_name")!r} '
                      f'does not contain {needle!r}',
            'item': None,
        })

    delta_gte = exp.get('v1_clip_count_delta_gte')
    if delta_gte is not None:
        pre_v1 = len(pre.get('tracks', {}).get('video', {}).get('1', {}).get('clips', []))
        post_v1 = len(post.get('tracks', {}).get('video', {}).get('1', {}).get('clips', []))
        if post_v1 - pre_v1 < int(delta_gte):
            violations.append({
                'rule': {'kind': 'v1_clip_count_delta_gte', 'value': delta_gte},
                'reason': f'V1 clip count delta {post_v1 - pre_v1} < {delta_gte} '
                          f'(pre={pre_v1}, post={post_v1})',
                'item': None,
            })

    for kind_idx in exp.get('must_be_empty_tracks', []):
        kind, idx = kind_idx[0], str(kind_idx[1])
        clips = post.get('tracks', {}).get(kind, {}).get(idx, {}).get('clips', [])
        if clips:
            violations.append({
                'rule': {'kind': 'must_be_empty_tracks', 'value': kind_idx},
                'reason': f'{kind.upper()}{idx} expected empty on new timeline but '
                          f'has {len(clips)} clip(s)',
                'item': {'first_clips': [c.get('name') for c in clips[:3]]},
            })

    if exp.get('preserve_ruler_marker_count'):
        pre_count = pre.get('counts', {}).get('ruler_markers', 0)
        post_count = post.get('counts', {}).get('ruler_markers', 0)
        if post_count < pre_count:
            violations.append({
                'rule': {'kind': 'preserve_ruler_marker_count'},
                'reason': f'ruler marker count decreased on derived timeline '
                          f'(pre={pre_count}, post={post_count})',
                'item': None,
            })

    if exp.get('preserve_clip_colors'):
        ignored_colors = set(exp.get('preserve_clip_colors_except', []))

        def colored_counter(snap: dict) -> Counter:
            out = Counter()
            for kind in ('video', 'audio', 'subtitle'):
                for _idx, tdata in snap.get('tracks', {}).get(kind, {}).items():
                    for clip in tdata.get('clips', []):
                        color = clip.get('clip_color') or ''
                        if not color:
                            continue
                        if color in ignored_colors:
                            continue
                        key = (
                            clip.get('track', ''),
                            clip.get('source_path', ''),
                            clip.get('name', ''),
                            int(clip.get('src_left', 0)),
                            int(clip.get('src_dur', 0)),
                            color,
                        )
                        out[key] += 1
            return out

        pre_colors = colored_counter(pre)
        post_colors = colored_counter(post)
        missing = []
        for key, n_pre in pre_colors.items():
            n_post = post_colors.get(key, 0)
            if n_post < n_pre:
                missing.append({'identity': list(key), 'pre': n_pre, 'post': n_post})
        if missing:
            violations.append({
                'rule': {'kind': 'preserve_clip_colors'},
                'reason': f'{len(missing)} colored clip identity/count(s) missing '
                          f'on derived timeline',
                'item': {'missing': missing[:20]},
            })

    duplicate_tracks = exp.get('no_duplicate_source_audio_tracks', [])
    if duplicate_tracks:
        a1_clips = post.get('tracks', {}).get('audio', {}).get('1', {}).get('clips', [])
        names = [c.get('name') for c in a1_clips if c.get('name')]
        if names:
            gameplay_name = Counter(names).most_common(1)[0][0]
            for kind_idx in duplicate_tracks:
                kind, idx = kind_idx[0], str(kind_idx[1])
                clips = post.get('tracks', {}).get(kind, {}).get(idx, {}).get('clips', [])
                dupes = [c for c in clips if c.get('name') == gameplay_name]
                if dupes:
                    violations.append({
                        'rule': {'kind': 'no_duplicate_source_audio_tracks',
                                 'value': kind_idx},
                        'reason': f'{kind.upper()}{idx} contains {len(dupes)} '
                                  f'duplicate gameplay-source clip(s) '
                                  f'{gameplay_name!r}; only intro/outro/music '
                                  f'assets may remain on A2-A5',
                        'item': {'first_clips': [c.get('name') for c in dupes[:3]]},
                    })

    return violations


# ── unexpected-change scan ──────────────────────────────────────────────────

DIFF_KIND_FIELDS = {
    'clips_added':          'clips_added',
    'clips_removed':        'clips_removed',
    'clips_modified':       'clips_modified',
    'markers_ruler_added':  'markers_ruler_added',
    'markers_ruler_removed':'markers_ruler_removed',
    'markers_clip_added':   'markers_clip_added',
    'markers_clip_removed': 'markers_clip_removed',
    'colors_changed':       'colors_changed',
    'locks_changed':        'locks_changed',
}


def _scan_unexpected(diff: dict, scope: dict, fps: float) -> list[dict]:
    """For every entry in the diff, check if it's covered by an allowed rule.
    Return a list of violations for entries that are NOT covered."""
    violations = []
    allowed = scope.get('allowed_changes', []) or []
    # Also tolerate the must_preserve checks above — those already produced
    # violations; we don't double-flag those same items here.
    for kind, field in DIFF_KIND_FIELDS.items():
        for item in diff.get(field, []):
            # clips_modified items are diff-shaped {identity, fields_changed,...}
            # Map them to a clip dict for the rule matcher.
            if kind == 'clips_modified':
                # Use original-shaped fallback for matcher
                if (
                    not _allowed(kind, item, allowed, fps)
                    and not _clip_color_change_allowed(item, allowed)
                ):
                    violations.append({
                        'rule': None,
                        'reason': f'unexpected {kind}: {item}',
                        'item': item,
                    })
                continue
            if not _allowed(kind, item, allowed, fps):
                violations.append({
                    'rule': None,
                    'reason': f'unexpected {kind}',
                    'item': item,
                })
    return violations


# ── audio checks ────────────────────────────────────────────────────────────

def _run_audio_checks(tl, project) -> dict:
    """Run the verify_pipeline checks against the current timeline state.
    Returns {'pink': N, 'yellow': N, ...} and a flags list."""
    fps = float(project.GetSetting('timelineFrameRate'))
    tl_start = int(tl.GetStartFrame())
    VP.set_tl_start(tl_start)

    v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
    if not v1:
        return {'counts': {'pink': 0, 'yellow': 0, 'lime': 0,
                           'teal': 0, 'brown': 0, 'total': 0}, 'flags': []}

    v1_map = VP.build_v1_source_map(v1, fps)
    source_path = VP.get_source_path(v1_map)
    from collections import Counter
    dominant = Counter(c.GetName() for c in v1).most_common(1)[0][0]

    battles = []
    bpath = Path('transcripts/battles.json')
    if bpath.exists():
        try:
            battles = json.loads(bpath.read_text(encoding='utf-8'))
        except Exception:
            battles = []

    do_audio = source_path is not None
    full_audio = VP.load_full_audio_if_needed(source_path) if do_audio else None

    pink   = VP.check_pink_cuts(v1, fps, source_path, do_audio,
                                 dominant_name=dominant, full_audio=full_audio)
    yellow = VP.check_yellow_repetitions(v1, fps, source_path, do_audio,
                                          full_audio=full_audio,
                                          dominant_name=dominant)
    lime   = VP.check_lime_missing_preroll(v1, fps, source_path, battles, do_audio,
                                            full_audio=full_audio)
    teal   = VP.check_teal_extra_preroll(v1, fps, source_path, battles, do_audio,
                                          full_audio=full_audio,
                                          dominant_name=dominant)
    brown  = VP.check_brown_bgm_under_battle(tl, fps, battles, tl_start)
    flags = pink + yellow + lime + teal + brown
    return {
        'counts': {'pink': len(pink), 'yellow': len(yellow), 'lime': len(lime),
                   'teal': len(teal), 'brown': len(brown), 'total': len(flags)},
        'flags': flags,
    }


# ── subcommands ─────────────────────────────────────────────────────────────

def _connect():
    r = dvr.scriptapp('Resolve')
    if r is None:
        print('ERROR: Resolve not connected', file=sys.stderr)
        sys.exit(99)
    proj = r.GetProjectManager().GetCurrentProject()
    tl = proj.GetCurrentTimeline()
    return r, proj, tl


def _export_drt_checkpoint(resolve, tl, step_id: str) -> dict:
    """Export a Resolve-native DRT checkpoint for a passed audit."""
    if tl is None:
        return {
            'exported': False,
            'reason': 'no current timeline',
        }
    repo_root = Path(__file__).resolve().parent.parent
    out_dir = repo_root / '_data' / 'drt-checkpoints'
    out_dir.mkdir(parents=True, exist_ok=True)
    timeline_name = tl.GetName() or 'unknown_timeline'
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = out_dir / (
        f'{step_id}__{timestamp}__{S.slugify_timeline_name(timeline_name)}.drt'
    )
    try:
        ok = bool(tl.Export(str(out_path), resolve.EXPORT_DRT, resolve.EXPORT_NONE))
    except Exception as exc:
        return {
            'exported': False,
            'path': str(out_path),
            'reason': f'{type(exc).__name__}: {exc}',
        }
    return {
        'exported': ok,
        'path': str(out_path),
        'timeline': timeline_name,
        'size_bytes': out_path.stat().st_size if ok and out_path.exists() else 0,
        'reason': '' if ok else 'Timeline.Export returned false',
    }


def cmd_snapshot(args) -> int:
    _r, proj, tl = _connect()
    snap = S.capture_timeline_state(tl, proj)
    path = S.snapshot_path(args.step, 'pre')
    S.write_snapshot(snap, path)
    print(f'[audit/snapshot] step={args.step}')
    print(f'  timeline:  {snap.get("timeline_name")!r}')
    print(f'  v_clips:   {snap.get("counts", {}).get("v_clips_total")}')
    print(f'  a_clips:   {snap.get("counts", {}).get("a_clips_total")}')
    print(f'  ruler markers: {snap.get("counts", {}).get("ruler_markers")}')
    print(f'  written:   {path}')
    return 0


def cmd_audit(args) -> int:
    resolve, proj, tl = _connect()
    pre_path = S.snapshot_path(args.step, 'pre')
    if not pre_path.exists():
        print(f'ERROR: pre-snapshot not found at {pre_path}', file=sys.stderr)
        print(f'       run `audit_step.py snapshot --step {args.step}` BEFORE the step',
              file=sys.stderr)
        return 99
    pre = S.load_snapshot(pre_path)

    post = S.capture_timeline_state(tl, proj)
    S.write_snapshot(post, S.snapshot_path(args.step, 'post'))

    diff = S.diff_states(pre, post)
    scope = get_scope(args.step)
    fps = float(proj.GetSetting('timelineFrameRate'))

    print(f'[audit/audit] step={args.step}  ({scope.get("description", "")})')
    if scope.get('unknown_step'):
        print(f'  WARN: no scope declared for {args.step!r} — running permissive audit')

    print(f'  timeline:  {pre.get("timeline_name")!r}  ->  {post.get("timeline_name")!r}')
    print(f'  diff: +{len(diff["clips_added"])}/-{len(diff["clips_removed"])} clips,  '
          f'+{len(diff["markers_ruler_added"])}/-{len(diff["markers_ruler_removed"])} ruler markers,  '
          f'colors_changed={len(diff["colors_changed"])},  locks_changed={len(diff["locks_changed"])}')

    violations: list[dict] = []
    regressions: list[dict] = []

    if scope.get('unknown_step'):
        # Unknown/ad-hoc checkpoints are intentionally permissive: capture the
        # diff and run audio checks, but do not enforce a declared scope.
        pass
    elif scope.get('creates_new_timeline'):
        # In new-timeline mode the diff would be "everything different" —
        # skip diff/preserve checks; validate derived expectations only.
        violations.extend(_check_creates_new_timeline(pre, post, scope))
    else:
        # Standard mode: preserve + unexpected-change scan
        violations.extend(_check_must_preserve(
            diff,
            scope.get('must_preserve', []),
            fps,
            scope.get('allowed_changes', []),
        ))
        violations.extend(_scan_unexpected(diff, scope, fps))

    # Special-case checks that need the post snapshot, including creates-new-
    # timeline scopes where the normal diff-based preservation scan is skipped.
    for rule in scope.get('must_preserve', []):
        if rule.get('kind') == 'no_a2_overlaps':
            violations.extend(_check_no_a2_overlaps(post, fps))
        elif rule.get('kind') == 'battle_intros_present':
            violations.extend(_check_battle_intros_present(post, rule))
        elif rule.get('kind') == 'gen1_battle_intros_present':
            violations.extend(_check_gen1_battle_intros_present(post, rule))

    # Global integrity gate: every gameplay V1 clip should have aligned A1
    # dialogue coverage. Keep this independent of step scopes because any
    # append/replace operation can accidentally drop linked audio.
    violations.extend(_check_v1_has_a1_coverage(post))
    violations.extend(_check_no_gameplay_audio_outside_a1(post))
    violations.extend(_check_no_raw_gameplay_audio_on_a2(post))
    violations.extend(_check_gen1_leader_intros_preserved(pre, post))

    if not scope.get('creates_new_timeline'):
        # Mark any "must_preserve" violations whose lost item carries the
        # signature of a prior pipeline step's output as REGRESSIONS.
        for v in violations:
            r = v.get('rule') or {}
            item = v.get('item') or {}
            if r.get('kind') == 'markers':
                col = (item.get('marker', {}).get('color') if 'marker' in item
                       else item.get('color', ''))
                if col == 'Green':
                    regressions.append({**v, 'from_step': 'step2_mark_battle_ends_rough or step8a/8b'})
                elif col == 'Magenta':
                    regressions.append({**v, 'from_step': 'step10_find_member_carousel'})
                elif col == 'Red':
                    regressions.append({**v, 'from_step': 'step3_mark_cut_candidates or step7_mark_audio_gaps'})

    audio = _run_audio_checks(tl, proj)

    expected_observed: list[str] = []
    expected_missing: list[str] = []
    # We only enforce expected-observed in --strict mode for a couple of obvious cases.
    if args.strict and scope.get('allowed_changes'):
        for rule in scope['allowed_changes']:
            kind = rule.get('kind')
            field = DIFF_KIND_FIELDS.get(kind)
            if field and not diff.get(field):
                expected_missing.append(f'{kind} (rule={rule})')
            else:
                expected_observed.append(kind)

    if args.strict:
        for label in expected_missing:
            violations.append({
                'rule': {'kind': 'expected_change_missing'},
                'reason': f'strict mode: expected change not observed: {label}',
                'item': None,
            })

    passed = len(violations) == 0
    drt_checkpoint = None
    if passed and not args.no_drt:
        drt_checkpoint = _export_drt_checkpoint(resolve, tl, args.step)
        if not drt_checkpoint.get('exported'):
            violations.append({
                'rule': {'kind': 'drt_checkpoint_export'},
                'reason': 'passed audit but failed to export DRT checkpoint: '
                          f'{drt_checkpoint.get("reason")}',
                'item': drt_checkpoint,
            })
            passed = False

    report = {
        'step_id': args.step,
        'passed': passed,
        'description': scope.get('description', ''),
        'creates_new_timeline': bool(scope.get('creates_new_timeline')),
        'timeline_before': pre.get('timeline_name'),
        'timeline_after':  post.get('timeline_name'),
        'counts_before':   pre.get('counts'),
        'counts_after':    post.get('counts'),
        'diff_summary': {
            'clips_added':    len(diff['clips_added']),
            'clips_removed':  len(diff['clips_removed']),
            'clips_modified': len(diff['clips_modified']),
            'markers_ruler_added':   len(diff['markers_ruler_added']),
            'markers_ruler_removed': len(diff['markers_ruler_removed']),
            'markers_clip_added':    len(diff['markers_clip_added']),
            'markers_clip_removed':  len(diff['markers_clip_removed']),
            'colors_changed':        len(diff['colors_changed']),
            'locks_changed':         len(diff['locks_changed']),
        },
        'violations':  violations,
        'regressions': regressions,
        'audio_checks': audio['counts'],
        'audio_flags':  audio['flags'],
        'expected_observed': expected_observed,
        'expected_missing':  expected_missing,
        'drt_checkpoint': drt_checkpoint,
        'diff_full': diff,
    }
    path = S.report_path(args.step)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                    encoding='utf-8')

    print()
    if passed:
        print(f'  PASS — no violations.   report: {path}')
        if drt_checkpoint and drt_checkpoint.get('exported'):
            print(f'  DRT checkpoint: {drt_checkpoint.get("path")}')
    else:
        print(f'  FAIL — {len(violations)} violation(s), {len(regressions)} regression(s)')
        for v in violations[:10]:
            print(f'    - {v.get("reason")}')
        if len(violations) > 10:
            print(f'    ...and {len(violations) - 10} more (see report)')
        print(f'  report: {path}')

    a = audio['counts']
    if a['total'] > 0:
        print(f'  audio checks: pink={a["pink"]}  yellow={a["yellow"]}  '
              f'lime={a["lime"]}  teal={a["teal"]}  brown={a["brown"]}')

    return len(violations)


# ── entry ───────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    snap_ap = sub.add_parser('snapshot', help='Capture pre-step timeline state')
    snap_ap.add_argument('--step', required=True, help='Step ID (see audit_scopes.py)')
    snap_ap.set_defaults(func=cmd_snapshot)

    audit_ap = sub.add_parser('audit', help='Diff + validate after a step')
    audit_ap.add_argument('--step', required=True, help='Step ID (see audit_scopes.py)')
    audit_ap.add_argument('--strict', action='store_true',
                           help='Also fail when an expected change was not observed')
    audit_ap.add_argument('--no-drt', action='store_true',
                          help='Do not export a DRT checkpoint after a passing audit')
    audit_ap.set_defaults(func=cmd_audit)

    args = ap.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
