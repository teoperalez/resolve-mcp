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
        _data/audits/<step>_report.json. Exit with violation count.

        --strict   also fails if expected changes were not observed.

A non-zero exit code means the pipeline should STOP and the user should
inspect the report before continuing.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
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


def _check_must_preserve(diff: dict, must_preserve: list, fps: float) -> list[dict]:
    """Return a list of violations for must_preserve rules that diff broke."""
    violations: list[dict] = []
    for rule in must_preserve:
        kind = rule.get('kind')

        if kind == 'clips':
            # No clips removed/modified on the given track (if track specified)
            rt = rule.get('track')
            for c in diff.get('clips_removed', []):
                if rt is None or _clip_track_tuple(c) == (rt[0], int(rt[1])):
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
                    return c in except_colors
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
        def colored_counter(snap: dict) -> Counter:
            out = Counter()
            for kind in ('video', 'audio', 'subtitle'):
                for _idx, tdata in snap.get('tracks', {}).get(kind, {}).items():
                    for clip in tdata.get('clips', []):
                        color = clip.get('clip_color') or ''
                        if not color:
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
                synthetic = {
                    'track_kind': item.get('identity', ['', ''])[0][:1].lower(),
                    'track_index': int(item.get('identity', ['', '0'])[0][1:] or 0)
                    if len(item.get('identity', [])) > 0 else 0,
                }
                # Use original-shaped fallback for matcher
                if not _allowed(kind, item, allowed, fps):
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
    _r, proj, tl = _connect()
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

    if scope.get('creates_new_timeline'):
        # In new-timeline mode the diff would be "everything different" —
        # skip diff/preserve checks; validate derived expectations only.
        violations.extend(_check_creates_new_timeline(pre, post, scope))
    else:
        # Standard mode: preserve + unexpected-change scan
        violations.extend(_check_must_preserve(diff, scope.get('must_preserve', []), fps))
        violations.extend(_scan_unexpected(diff, scope, fps))

        # Special-case A2 overlap detection
        for rule in scope.get('must_preserve', []):
            if rule.get('kind') == 'no_a2_overlaps':
                violations.extend(_check_no_a2_overlaps(post, fps))

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
        'diff_full': diff,
    }
    path = S.report_path(args.step)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                    encoding='utf-8')

    print()
    if passed:
        print(f'  PASS — no violations.   report: {path}')
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
    audit_ap.set_defaults(func=cmd_audit)

    args = ap.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
