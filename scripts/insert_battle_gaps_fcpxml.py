"""
Insert battle gaps via FCPXML modification (the canonical IRLPC approach).

Resolve's runtime Python API cannot ripple-insert into existing timeline
content. The IRLPC Hyperframes workflow solves this at the FCPXML level
BEFORE the timeline is imported. This script ports the relevant section
of `apply_cuts_to_fcpxml.mjs` (the battle-gap portion only; not the
word-cut / anchor-split features).

Workflow:
  1. Start from the auto-editor's silence-stripped FCPXML
     (e.g. <video>_ALTERED.fcpxml).
  2. Read `transcripts/battles.json` for trainer battle timestamps.
  3. For each battle, find the VIDEO clip (ref r2) whose timeline range
     contains the battle's offset. Pull its source `start` BACKWARD by
     `gap_frames` (subject to available left handle); grow `duration` and
     pull `offset` (timeline position) BACKWARD by the same amount.
  4. For every clip on every ref, shift `offset` forward by the cumulative
     pull from prior battles. Audio refs shift only — they don't back-fill.
  5. Inject `<marker>` entries at each battle's new timeline position.
  6. Write `<input>_BATTLEGAPS.fcpxml`.

The output FCPXML can be imported into Resolve via
`MediaPool.ImportTimelineFromFile()`, creating a new timeline that already
has the battle gaps in place (no runtime ripple-insert needed).

Usage:
    python insert_battle_gaps_fcpxml.py INPUT.fcpxml [--battles PATH]
                                       [--gap-frames 60]
                                       [-o OUTPUT.fcpxml]
                                       [--import-to-resolve]
"""
import sys
import os
import re
import json
import argparse
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401


# ── FCPXML rational arithmetic ────────────────────────────────────────────────

def parse_rational(s: str) -> tuple[int, int]:
    """Parse FCPXML time string like '12345/60s' or '0s' into (num, den)."""
    s = s.strip()
    if s in ('', '0s'):
        return (0, 60)
    m = re.match(r'^(\d+)/(\d+)s$', s)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = re.match(r'^(\d+)s$', s)
    if m:
        return (int(m.group(1)) * 60, 60)
    raise ValueError(f'Cannot parse rational {s!r}')


def fmt_rational(num: int, den: int = 60) -> str:
    return f'{num}/{den}s' if num != 0 else '0s'


# ── Spine parsing ─────────────────────────────────────────────────────────────

# Match `<asset-clip ... />`. The attribute payload can contain quoted strings
# with slashes (e.g. duration="75/60s"), so we accept anything up to the final
# `/>`. The lazy quantifier with the `/>` boundary handles self-closing tags
# cleanly even when neighboring tags also self-close.
ASSET_CLIP_RE = re.compile(
    r'<asset-clip\s+([^>]+?)\s*/>',
    re.DOTALL,
)
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def parse_attrs(attr_str: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in ATTR_RE.finditer(attr_str)}


def parse_spine_clips(xml: str) -> list[dict]:
    """Return all <asset-clip /> elements from the spine, each as a dict
    with parsed fields: ref, offset (num/den), duration, start, name, tcFormat,
    plus the original attribute string for round-tripping unknown attrs."""
    m_spine = re.search(r'<spine\b[^>]*>([\s\S]*?)</spine>', xml)
    if not m_spine:
        raise ValueError('No <spine> element found')
    body = m_spine.group(1)

    clips = []
    for m in ASSET_CLIP_RE.finditer(body):
        attrs = parse_attrs(m.group(1))
        try:
            off_n, off_d  = parse_rational(attrs.get('offset', '0s'))
            dur_n, dur_d  = parse_rational(attrs.get('duration', '0s'))
            start_n, start_d = parse_rational(attrs.get('start', '0s'))
        except ValueError as e:
            raise ValueError(f'Bad time attr in clip {attrs!r}: {e}')
        clips.append({
            'ref':       attrs.get('ref', ''),
            'name':      attrs.get('name', ''),
            'tcFormat':  attrs.get('tcFormat', ''),
            'offset':    (off_n, off_d),
            'duration':  (dur_n, dur_d),
            'start':     (start_n, start_d),
            '_attrs':    attrs,
        })
    return clips


# ── Battle gap modification ───────────────────────────────────────────────────

def insert_battle_gaps(xml: str, battles: list[dict], gap_frames: int,
                       den: int = 60) -> tuple[str, list[dict]]:
    """Modify the FCPXML spine to back-fill `gap_frames` of source content
    before each battle's video clip and shift all subsequent clips forward
    by the cumulative pull. Returns (new_xml, marker_info_list)."""
    clips = parse_spine_clips(xml)
    if not clips:
        return xml, []

    # Group by ref, preserve original order
    refs_in_order = []
    seen = set()
    for c in clips:
        if c['ref'] not in seen:
            seen.add(c['ref'])
            refs_in_order.append(c['ref'])
    video_ref = refs_in_order[0]
    print(f'  Refs (in order): {refs_in_order}')
    print(f'  Video ref: {video_ref}')

    # Sort battles by source timestamp ascending
    battles_sorted = sorted(battles, key=lambda b: b['timestamp_sec'])

    # Convert battle source-seconds to FCPXML timeline units. The battle's
    # SOURCE second maps to a timeline frame via the auto-editor's V1 layout.
    # We find the video clip whose [start, start+duration) on the SOURCE
    # contains battle.timestamp_sec*den, then compute the timeline offset
    # accordingly.
    video_clips = [c for c in clips if c['ref'] == video_ref]
    # Sort video clips by offset
    video_clips.sort(key=lambda c: c['offset'][0])

    SNAP_TOL_UNITS = den  # 1 second tolerance for snap-forward
    battles_resolved = []  # list of {clip_index_in_video, battle, tl_offset, pull_avail}
    for b in battles_sorted:
        ts = float(b['timestamp_sec'])
        ts_units = int(round(ts * den))
        # 1. Find video clip whose source range CONTAINS ts_units
        target_idx = None
        for i, c in enumerate(video_clips):
            s_n = c['start'][0]
            d_n = c['duration'][0]
            if s_n <= ts_units < s_n + d_n:
                target_idx = i
                break
        # 2. Snap-forward: ts is in a silence-stripped gap; jump to the next
        #    video clip whose source start is >= ts_units (within SNAP_TOL_UNITS).
        if target_idx is None:
            for i, c in enumerate(video_clips):
                s_n = c['start'][0]
                if ts_units <= s_n <= ts_units + SNAP_TOL_UNITS:
                    target_idx = i
                    print(f'  snap-forward: {b["trainer_name"]} @ {ts:.2f}s '
                          f'(src {ts_units}) → next clip src start {s_n}')
                    break
        if target_idx is None:
            print(f'  WARN: {b["trainer_name"]} @ {ts:.2f}s: no video clip contains '
                  f'src frame {ts_units} and no clip starts within '
                  f'{SNAP_TOL_UNITS}u; skipping')
            continue
        target = video_clips[target_idx]
        # Pull amount = min(gap_frames, available left handle = source frames
        # between source 0 and the clip's current start)
        pull_avail = min(gap_frames, target['start'][0])
        battles_resolved.append({
            'video_index': target_idx,
            'battle':      b,
            'pull':        pull_avail,
            'orig_offset': target['offset'][0],
        })

    # cumulative_pull_before(offset_n): sum of pulls for battles whose
    # original target offset < given offset_n. Used to compute shifts.
    # We also need to know each battle's NEW timeline offset for markers.
    battle_pulls_in_order = []  # list of (orig_offset_n, pull)
    for r in battles_resolved:
        battle_pulls_in_order.append((r['orig_offset'], r['pull']))
    battle_pulls_in_order.sort(key=lambda x: x[0])

    def cumulative_shift_before(orig_off_n: int) -> int:
        """How much to shift a clip whose ORIGINAL offset is orig_off_n."""
        total = 0
        for bp_off, bp_pull in battle_pulls_in_order:
            if orig_off_n >= bp_off:
                total += bp_pull
            else:
                break
        return total

    # Build target-clip set (for back-fill)
    target_ids = set()  # set of (ref, index_in_ref_order) — but easier: use id() of dict
    for r in battles_resolved:
        # Identify the same clip in `clips` (not just video_clips) by reference
        # equality (parse_spine_clips returns the same dict object).
        target_ids.add(id(video_clips[r['video_index']]))

    # Recompute each clip's new (offset, duration, start)
    markers = []  # list of {offset_n, name}
    for c in clips:
        orig_off = c['offset'][0]
        shift = cumulative_shift_before(orig_off)
        new_off = orig_off + shift
        new_dur = c['duration'][0]
        new_start = c['start'][0]
        # If this is a battle target, also pull back
        if id(c) in target_ids:
            r = next(rr for rr in battles_resolved
                     if id(video_clips[rr['video_index']]) == id(c))
            pull = r['pull']
            if pull > 0:
                new_off   -= pull
                new_start -= pull
                new_dur   += pull
            markers.append({
                'offset_n':    new_off,
                'name':        f"Battle: {r['battle']['trainer_name']}",
                'description': r['battle'].get('description', ''),
            })
        c['_new_offset_n']   = new_off
        c['_new_duration_n'] = new_dur
        c['_new_start_n']    = new_start

    # Generate updated <asset-clip /> strings and replace the spine body
    indent = '\t\t\t\t\t\t\t\t'
    new_lines = []
    for c in clips:
        attrs = dict(c['_attrs'])
        attrs['offset']   = fmt_rational(c['_new_offset_n'], den)
        attrs['duration'] = fmt_rational(c['_new_duration_n'], den)
        attrs['start']    = fmt_rational(c['_new_start_n'], den)
        # Preserve attribute order roughly: name, ref, offset, duration, start, tcFormat
        ordered_keys = []
        for k in ('name', 'ref', 'offset', 'duration', 'start', 'tcFormat'):
            if k in attrs:
                ordered_keys.append(k)
        for k in attrs:
            if k not in ordered_keys:
                ordered_keys.append(k)
        attr_pairs = [f'{k}="{attrs[k]}"' for k in ordered_keys if attrs[k] != '' or k in ('start','offset','duration')]
        # tcFormat may be empty — skip if so
        attr_pairs = [p for p in attr_pairs if p != 'tcFormat=""']
        new_lines.append(f'{indent}<asset-clip {" ".join(attr_pairs)} />')

    new_spine_body = '\n' + '\n'.join(new_lines) + '\n' + '\t' * 7
    new_xml = re.sub(
        r'(<spine\b[^>]*>)([\s\S]*?)(</spine>)',
        lambda m: m.group(1) + new_spine_body + m.group(3),
        xml,
        count=1,
    )

    # Inject <marker> entries inside <sequence>, after </spine>.
    # Format used by IRLPC and validated against Resolve.
    marker_strs = [
        f'<marker start="0s" duration="1/{den}s" value="Start" completed="0" />'
    ]
    for m in markers:
        safe_name = (m['name']
                     .replace('&', '&amp;')
                     .replace('"', '&quot;')
                     .replace('<', '&lt;'))
        marker_strs.append(
            f'<marker start="{fmt_rational(m["offset_n"], den)}" '
            f'duration="1/{den}s" value="{safe_name}" completed="0" />'
        )
    marker_blob = ''.join(marker_strs)

    new_xml = re.sub(
        r'(</spine>)(\s*)(</sequence>)',
        lambda m: f'{m.group(1)}{marker_blob}{m.group(2)}{m.group(3)}',
        new_xml,
        count=1,
    )

    return new_xml, markers


# ── Optional Resolve import ───────────────────────────────────────────────────

def import_into_resolve(fcpxml_path: Path, markers: list[dict]) -> bool:
    """Import the modified FCPXML into the current Resolve project, then
    place battle markers via the API (Resolve drops <marker> entries from
    imported FCPXML on most timelines — this is the IRLPC workaround)."""
    try:
        import DaVinciResolveScript as dvr
    except ImportError:
        print('  Could not import DaVinciResolveScript — skipping auto-import')
        return False
    resolve = dvr.scriptapp('Resolve')
    if resolve is None:
        print('  Resolve is not running — skipping auto-import')
        return False
    project = resolve.GetProjectManager().GetCurrentProject()
    pool    = project.GetMediaPool()
    print(f'  Importing into Resolve: {fcpxml_path}')
    result = pool.ImportTimelineFromFile(str(fcpxml_path))
    if not result:
        print(f'  ImportTimelineFromFile returned {result!r} — '
              f'this usually means a timeline with the same project name '
              f'already exists. Rename the existing timeline and re-run.')
        return False
    print(f'  ImportTimelineFromFile returned: {result!r}')

    # Find the newly-imported timeline. ImportTimelineFromFile's return is a
    # PyRemoteObject that doesn't directly expose GetName, so we scan project
    # timelines for the matching name.
    target_name = None
    n = project.GetTimelineCount()
    new_tl = None
    for i in range(1, n + 1):
        t = project.GetTimelineByIndex(i)
        if t and 'battle-gaps' in (t.GetName() or '').lower():
            new_tl = t
            target_name = t.GetName()
            break
    if new_tl is None:
        # Fallback: take the LAST timeline (most recently added).
        new_tl = project.GetTimelineByIndex(n)
        target_name = new_tl.GetName() if new_tl else '?'
        print(f'  WARN: could not find a timeline whose name contains '
              f'"battle-gaps"; assuming the last one ({target_name!r})')
    else:
        print(f'  Located imported timeline: {target_name!r}')
    project.SetCurrentTimeline(new_tl)

    # Place battle markers. Use 'Sand' (the Resolve API doesn't accept 'Orange'
    # for markers — see memory note reference_resolve_marker_colors.md).
    tl_start = new_tl.GetStartFrame()
    placed = 0
    for m in markers:
        rel = m['offset_n'] - tl_start
        for nudge in range(0, 10):
            ok = new_tl.AddMarker(rel + nudge, 'Sand', m['name'],
                                  m.get('description', ''), 1, '')
            if ok:
                placed += 1
                break
    print(f'  Battle markers placed: {placed}/{len(markers)}')
    return True


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input', help='Input FCPXML (e.g. *_ALTERED.fcpxml)')
    ap.add_argument('--battles', default='transcripts/battles.json',
                    help='battles.json from detect_battles.py')
    ap.add_argument('--gap-frames', type=int, default=60)
    ap.add_argument('-o', '--output', default=None,
                    help='Output FCPXML path (default: <input>_BATTLEGAPS.fcpxml)')
    ap.add_argument('--import-to-resolve', action='store_true',
                    help='Also import the output FCPXML into the running Resolve project')
    args = ap.parse_args()

    in_path = Path(args.input).resolve()
    if not in_path.exists():
        print(f'ERROR: input not found: {in_path}', file=sys.stderr)
        return 1
    if args.output:
        out_path = Path(args.output).resolve()
    else:
        out_path = in_path.with_name(in_path.stem + '_BATTLEGAPS.fcpxml')

    battles_path = Path(args.battles).resolve()
    if not battles_path.exists():
        print(f'ERROR: battles file not found: {battles_path}', file=sys.stderr)
        return 1
    battles = json.loads(battles_path.read_text(encoding='utf-8'))
    if not battles:
        print('No battles in file; nothing to do.')
        return 0

    print(f'Input:   {in_path}')
    print(f'Battles: {len(battles)}')
    xml = in_path.read_text(encoding='utf-8')

    new_xml, markers = insert_battle_gaps(xml, battles, args.gap_frames)

    print(f'\nBattle markers placed: {len(markers)}')
    for m in markers:
        sec = m['offset_n'] / 60.0
        print(f'  @ {m["offset_n"]}u ({sec:.2f}s):  {m["name"]}')

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(new_xml, encoding='utf-8')
    print(f'\nWrote: {out_path}  ({out_path.stat().st_size // 1024} KB)')

    # Write a sidecar JSON of markers so the API can re-apply them after import
    # (Resolve drops <marker> entries from FCPXML imports — see IRLPC's
    # resolve_set_markers.py for the canonical fix).
    sidecar = out_path.with_suffix('.markers.json')
    sidecar.write_text(json.dumps({'markers': markers}, indent=2, ensure_ascii=False),
                       encoding='utf-8')
    print(f'Wrote markers sidecar: {sidecar}')

    if args.import_to_resolve:
        import_into_resolve(out_path, markers)

    return 0


if __name__ == '__main__':
    sys.exit(main())
