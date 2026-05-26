"""
Apply cut-candidate decisions to an auto-editor FCPXML and produce two
ripple-cut variants:

  *_CUTS_HIGH.fcpxml  — only HIGH-confidence cuts removed
  *_CUTS_ALL.fcpxml   — HIGH + MEDIUM cuts removed

Both files can be re-imported into Resolve as new timelines. A sidecar
*_cuts_replay.json captures every cut applied (in original-timeline source
frames + the timeline ranges removed), so downstream pipeline operations
can be reproduced on a sibling timeline if needed.

Cut sources:
  plans/prompts/cut-analysis-<stem>.out.md (produced by mark_cut_candidates.py)
  Each entry: {start_sec, end_sec, confidence, type, reason}
  start_sec/end_sec are SOURCE-time ranges (the gameplay capture file's seconds).

Algorithm (auto-editor FCPXML structure):
  - The spine contains many <asset-clip> elements at each timeline position,
    all sharing the same offset/duration/start but differing only in `ref`
    (one video + N linked audio refs). The cut decision is taken from the
    video ref (the first asset-clip in the resources block); the same action
    is applied across all refs at the same position.

For each timeline position group:
  - keep:        no overlap with any cut → emit unchanged (with shifted offset)
  - delete:      entire source range is inside a cut → drop the position
  - trim_start:  cut covers [src_start, x] of the clip → keep [x, src_end];
                 the kept piece keeps its timeline offset (shifted by prior
                 cuts) and gets a new source start.
  - trim_end:    cut covers [x, src_end] of the clip → keep [src_start, x];
                 duration shrinks.
  - split:       cut [x, y] is a strict subset of [src_start, src_end] →
                 emit TWO positions: [src_start, x] and [y, src_end], with
                 the second one's offset advanced by the kept duration of
                 the first.

The cumulative timeline-shift after a position is the total `removed`
duration up to that position. All subsequent positions' offsets are reduced
by that amount.

Marker handling: each <marker> on the sequence is mapped from its old
timeline offset to the new offset via the same cumulative-shift table. A
marker that falls inside a removed range is dropped.

Usage:
    python apply_cuts_to_fcpxml.py INPUT.fcpxml [--cuts PATH]
                                   [-o OUT_DIR]
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

ASSET_CLIP_RE = re.compile(r'<asset-clip\s+([^>]+?)\s*/>', re.DOTALL)
ATTR_RE       = re.compile(r'(\w+)="([^"]*)"')
# Opening tag of <asset id="..." ...>  — captures attribute string before `>`.
# <asset> always has a nested <media-rep> child, so it's never self-closing.
ASSET_OPEN_RE = re.compile(r'<asset\s+([^>]+?)>')


def parse_attrs(attr_str: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in ATTR_RE.finditer(attr_str)}


def find_video_refs(xml: str) -> set[str]:
    """Scan <asset> declarations in <resources> for entries with hasVideo='1'.
    The auto-editor's FCPXML uses one video ref (the gameplay capture, with
    hasAudio='1' built-in) plus N audio-only refs (the WAV splits — hasVideo='0').
    Returns the set of video-ref ids."""
    out = set()
    for m in ASSET_OPEN_RE.finditer(xml):
        a = parse_attrs(m.group(1))
        if a.get('hasVideo') == '1' and 'id' in a:
            out.add(a['id'])
    return out


def parse_spine_clips(xml: str) -> list[dict]:
    m_spine = re.search(r'<spine\b[^>]*>([\s\S]*?)</spine>', xml)
    if not m_spine:
        raise ValueError('No <spine> element found')
    body = m_spine.group(1)
    clips = []
    for m in ASSET_CLIP_RE.finditer(body):
        attrs = parse_attrs(m.group(1))
        off_n, _   = parse_rational(attrs.get('offset', '0s'))
        dur_n, _   = parse_rational(attrs.get('duration', '0s'))
        start_n, _ = parse_rational(attrs.get('start', '0s'))
        clips.append({
            'ref':      attrs.get('ref', ''),
            'name':     attrs.get('name', ''),
            'tcFormat': attrs.get('tcFormat', ''),
            'offset':   off_n,
            'duration': dur_n,
            'start':    start_n,
            '_attrs':   attrs,
        })
    return clips


# ── Cut interval helpers ──────────────────────────────────────────────────────

def merge_intervals(ivs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sort and merge overlapping/touching intervals."""
    if not ivs:
        return []
    out = []
    for s, e in sorted(ivs):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def clip_overlaps_cut(src_start: int, src_end: int,
                       cuts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Return the list of (cut_start, cut_end) intersected with this clip's
    source range — clipped to [src_start, src_end]."""
    out = []
    for cs, ce in cuts:
        if ce <= src_start or cs >= src_end:
            continue
        out.append((max(cs, src_start), min(ce, src_end)))
    return out


# ── Core cut algorithm ────────────────────────────────────────────────────────

def snap_cuts_to_silence(cuts: list[dict], source_video: str, sr: int = 48000,
                          max_drift_sec: float = 0.3) -> list[dict]:
    """For each cut, snap start_sec and end_sec to nearest true silence using
    _audio_tools. Returns a new list with refined start_sec / end_sec. Cuts
    where neither end can be snapped are returned UNCHANGED (apply_cuts will
    use the raw LLM value).

    Logs a per-cut snap-summary; written to a sidecar by the caller if desired.
    """
    try:
        import _audio_tools as A
    except ImportError:
        print('  audio-snap unavailable (no _audio_tools module); using raw cuts')
        return cuts

    try:
        full = A.load_full_audio_track(source_video, sr=sr)
    except Exception as e:
        print(f'  audio-snap: full-track load failed ({e}); using raw cuts')
        return cuts

    snapped = []
    n_snapped = 0
    for c in cuts:
        new_c = dict(c)
        for key in ('start_sec', 'end_sec'):
            target = float(c[key])
            win_start = max(0.0, target - max_drift_sec)
            win_dur   = 2 * max_drift_sec
            window = A.slice_window(full, sr, win_start, win_dur)
            snap = A.snap_to_nearest_silence(
                window, sr, target - win_start, max_drift_sec=max_drift_sec)
            if snap is not None:
                snapped_sec_in_win, drift = snap
                new_val = float(win_start + snapped_sec_in_win)
                if abs(new_val - target) > 0.001:
                    new_c[key] = new_val
                    new_c.setdefault('_snap', {})[key] = {
                        'orig': target, 'snapped': new_val, 'drift_ms': round(drift * 1000, 1),
                    }
                    n_snapped += 1
        snapped.append(new_c)
    print(f'  audio-snap: {n_snapped} edge(s) snapped to silence')
    return snapped


def apply_cuts(xml: str, cuts: list[dict], den: int = 60,
               keep_linked_audio: bool = False) -> tuple[str, dict]:
    """
    Apply source-time cuts to the FCPXML's spine and markers.

    Returns (new_xml, replay_data). replay_data captures the timeline ranges
    that were removed and the source-time cuts that produced them.

    By default (keep_linked_audio=False), only video-ref asset-clips are
    emitted in the output spine — the auto-editor's linked audio refs
    (1.wav-4.wav as r4/r6/r8/r10, which import as A2-A5 in Resolve) are
    dropped. The video ref has hasAudio='1' built-in, so A1 (gameplay
    dialogue) survives via the embedded track. The Fairlight preset and the
    A2 audio pipeline require A2-A5 free, so dropping them up front saves a
    later cleanup pass.
    """
    clips = parse_spine_clips(xml)
    if not clips:
        return xml, {'cuts': [], 'removed_tl_ranges': []}

    # Identify video refs by <asset hasVideo="1"> declarations in <resources>.
    video_refs = find_video_refs(xml)
    if not video_refs:
        # Fallback: assume the first ref encountered in the spine is video.
        video_refs = {clips[0]['ref']}

    if not keep_linked_audio:
        # Drop linked audio asset-clips from the spine input. The output will
        # contain only video-ref clips (which carry the gameplay's embedded
        # audio track, mapping to A1 on Resolve import).
        before = len(clips)
        clips = [c for c in clips if c['ref'] in video_refs]
        print(f'  Filtered linked-audio refs: kept {len(clips)}/{before} clips '
              f'(video refs: {sorted(video_refs)})')

    # Group clips by timeline offset
    pos_groups: dict[int, list[dict]] = {}
    for c in clips:
        pos_groups.setdefault(c['offset'], []).append(c)
    positions = sorted(pos_groups.keys())
    refs_in_order: list[str] = []
    seen = set()
    for c in clips:
        if c['ref'] not in seen:
            seen.add(c['ref'])
            refs_in_order.append(c['ref'])
    video_ref = refs_in_order[0]

    # Convert source-second cuts to source-FRAME intervals, then merge
    src_cuts = merge_intervals([
        (int(round(c['start_sec'] * den)), int(round(c['end_sec'] * den)))
        for c in cuts
        if c['end_sec'] > c['start_sec']
    ])

    # Walk positions, build new emitted clips per group + a per-position shift
    # record. shift_at_offset[orig_offset] = cumulative timeline frames removed
    # BEFORE this offset (used for marker remapping).
    new_clips: list[dict] = []
    shift_at_offset: dict[int, int] = {}
    removed_tl_ranges: list[tuple[int, int]] = []
    cumulative_shift = 0
    n_keep = n_delete = n_trim_start = n_trim_end = n_split = 0

    for pos in positions:
        group = pos_groups[pos]
        # Take source range from the video ref clip (the other refs are linked
        # 1:1 to the same source frames in the auto-editor format).
        v = next((c for c in group if c['ref'] == video_ref), group[0])
        src_start = v['start']
        src_end   = src_start + v['duration']
        tl_start  = pos
        tl_end    = pos + v['duration']

        shift_at_offset[pos] = cumulative_shift

        overlaps = clip_overlaps_cut(src_start, src_end, src_cuts)
        if not overlaps:
            # KEEP unchanged at new offset
            new_off = pos - cumulative_shift
            for c in group:
                new_clips.append({**c, 'offset': new_off})
            n_keep += 1
            continue

        if len(overlaps) == 1:
            cs, ce = overlaps[0]
            cs_in_clip = cs - src_start  # offset from clip's source start
            ce_in_clip = ce - src_start

            if cs_in_clip <= 0 and ce_in_clip >= v['duration']:
                # DELETE — entire source range removed
                removed_tl_ranges.append((tl_start, tl_end))
                cumulative_shift += v['duration']
                n_delete += 1
                continue

            if cs_in_clip <= 0:
                # TRIM_START — cut covers [src_start, ce); keep [ce, src_end)
                removed_dur = ce_in_clip
                kept_dur    = v['duration'] - removed_dur
                new_off     = pos - cumulative_shift  # kept piece starts here
                new_start   = src_start + removed_dur
                for c in group:
                    new_clips.append({**c,
                                       'offset':   new_off,
                                       'duration': kept_dur,
                                       'start':    new_start})
                removed_tl_ranges.append((tl_start, tl_start + removed_dur))
                cumulative_shift += removed_dur
                n_trim_start += 1
                continue

            if ce_in_clip >= v['duration']:
                # TRIM_END — keep [src_start, cs); cut covers [cs, src_end)
                kept_dur    = cs_in_clip
                removed_dur = v['duration'] - kept_dur
                new_off     = pos - cumulative_shift
                for c in group:
                    new_clips.append({**c,
                                       'offset':   new_off,
                                       'duration': kept_dur})
                removed_tl_ranges.append((tl_start + kept_dur,
                                          tl_start + kept_dur + removed_dur))
                cumulative_shift += removed_dur
                n_trim_end += 1
                continue

            # SPLIT — cut is strict interior subset of clip
            first_dur   = cs_in_clip
            removed_dur = ce_in_clip - cs_in_clip
            second_dur  = v['duration'] - ce_in_clip
            first_off   = pos - cumulative_shift
            for c in group:
                new_clips.append({**c,
                                   'offset':   first_off,
                                   'duration': first_dur})
            removed_tl_ranges.append((tl_start + first_dur,
                                      tl_start + first_dur + removed_dur))
            cumulative_shift += removed_dur
            second_off   = pos + first_dur + removed_dur - cumulative_shift
            second_start = src_start + ce_in_clip
            for c in group:
                new_clips.append({**c,
                                   'offset':   second_off,
                                   'duration': second_dur,
                                   'start':    second_start})
            n_split += 1
            continue

        # MULTI — more than one cut overlaps this clip. Build keep-segments
        # by walking the clip's source range and skipping over each cut.
        cursor = src_start
        for cs, ce in overlaps:
            if cursor < cs:
                kept_dur  = cs - cursor
                new_off   = (pos + (cursor - src_start)) - cumulative_shift
                new_start = cursor
                for c in group:
                    new_clips.append({**c,
                                       'offset':   new_off,
                                       'duration': kept_dur,
                                       'start':    new_start})
            removed_dur = ce - max(cs, cursor)
            if removed_dur > 0:
                tl_rem_start = (pos + (max(cs, cursor) - src_start))
                removed_tl_ranges.append((tl_rem_start, tl_rem_start + removed_dur))
                cumulative_shift += removed_dur
            cursor = max(cursor, ce)
        if cursor < src_end:
            kept_dur  = src_end - cursor
            new_off   = (pos + (cursor - src_start)) - cumulative_shift
            new_start = cursor
            for c in group:
                new_clips.append({**c,
                                   'offset':   new_off,
                                   'duration': kept_dur,
                                   'start':    new_start})
        n_split += 1

    print(f'  Operations: keep={n_keep} delete={n_delete} '
          f'trim_start={n_trim_start} trim_end={n_trim_end} '
          f'split/multi={n_split}')
    print(f'  Total timeline frames removed: {cumulative_shift} '
          f'({cumulative_shift/den:.2f}s)')

    # ── Emit new <spine> body ──
    indent = '\t' * 8
    lines = []
    # Sort by offset (stable groups already in offset order), then by ref to
    # keep video before audio inside each group.
    new_clips.sort(key=lambda c: (c['offset'],
                                  refs_in_order.index(c['ref']) if c['ref'] in refs_in_order else 999))
    for c in new_clips:
        attrs = dict(c['_attrs'])
        attrs['offset']   = fmt_rational(c['offset'], den)
        attrs['duration'] = fmt_rational(c['duration'], den)
        attrs['start']    = fmt_rational(c['start'], den)
        ordered = []
        for k in ('name', 'ref', 'offset', 'duration', 'start', 'tcFormat'):
            if k in attrs:
                ordered.append(k)
        for k in attrs:
            if k not in ordered:
                ordered.append(k)
        pairs = []
        for k in ordered:
            v_ = attrs[k]
            if k == 'tcFormat' and v_ == '':
                continue
            pairs.append(f'{k}="{v_}"')
        lines.append(f'{indent}<asset-clip {" ".join(pairs)} />')

    new_spine_body = '\n' + '\n'.join(lines) + '\n' + '\t' * 5
    new_xml = re.sub(
        r'(<spine\b[^>]*>)([\s\S]*?)(</spine>)',
        lambda m: m.group(1) + new_spine_body + m.group(3),
        xml,
        count=1,
    )

    # ── Remap markers ──
    # Each <marker> has start="N/Ds". Compute shift_at(N) based on whether
    # the marker's TL position falls inside a removed range (drop it) or
    # AFTER N cuts (shift left by their total removed).
    def shift_for_tl(tl_n: int) -> int | None:
        """Return new tl offset, or None if marker lies inside a removed range."""
        shift = 0
        for rs, re_ in removed_tl_ranges:
            if rs <= tl_n < re_:
                return None
            if tl_n >= re_:
                shift += re_ - rs
        return tl_n - shift

    marker_pat = re.compile(r'<marker\s+([^/]+?)/>', re.DOTALL)
    def remap_marker(m: re.Match) -> str:
        a = parse_attrs(m.group(1))
        try:
            tl_n, _ = parse_rational(a.get('start', '0s'))
        except ValueError:
            return m.group(0)
        new_tl = shift_for_tl(tl_n)
        if new_tl is None:
            return ''  # marker falls inside a removed range — drop
        a['start'] = fmt_rational(new_tl, den)
        # Rebuild attribute string preserving original order roughly
        out = ' '.join(f'{k}="{v}"' for k, v in a.items())
        return f'<marker {out} />'
    new_xml = marker_pat.sub(remap_marker, new_xml)

    replay = {
        'src_cuts_frames': [{'start': cs, 'end': ce} for cs, ce in src_cuts],
        'removed_tl_ranges_frames': [{'start': s, 'end': e}
                                      for s, e in removed_tl_ranges],
        'total_tl_frames_removed': cumulative_shift,
        'den': den,
        'counts': {'keep': n_keep, 'delete': n_delete,
                   'trim_start': n_trim_start, 'trim_end': n_trim_end,
                   'split_multi': n_split},
    }
    return new_xml, replay


# ── Resolve import ────────────────────────────────────────────────────────────

def import_to_resolve(fcpxml_path: Path, label: str) -> tuple[bool, str]:
    """Import the FCPXML into the running Resolve project. Returns
    (success, imported_timeline_name)."""
    try:
        import DaVinciResolveScript as dvr
    except ImportError:
        print(f'  [{label}] DaVinciResolveScript unavailable — skip import')
        return False, ''
    resolve = dvr.scriptapp('Resolve')
    if resolve is None:
        print(f'  [{label}] Resolve not running — skip import')
        return False, ''
    project = resolve.GetProjectManager().GetCurrentProject()
    pool    = project.GetMediaPool()
    print(f'  [{label}] Importing: {fcpxml_path.name}')
    ok = pool.ImportTimelineFromFile(str(fcpxml_path))
    if not ok:
        print(f'  [{label}] Import returned {ok!r} (likely name collision)')
        return False, ''
    # Find the newly-imported timeline. The exported FCPXML's <project name="...">
    # determines the timeline name; we mutate that to include the label suffix
    # before calling this function, so we can locate it by name match.
    n = project.GetTimelineCount()
    for i in range(n, 0, -1):
        t = project.GetTimelineByIndex(i)
        if t and label.lower() in (t.GetName() or '').lower():
            print(f'  [{label}] Found timeline: {t.GetName()!r}')
            return True, t.GetName() or ''
    last = project.GetTimelineByIndex(n)
    return True, (last.GetName() if last else '')


def set_current_timeline_by_name(name_substr: str) -> bool:
    import DaVinciResolveScript as dvr
    resolve = dvr.scriptapp('Resolve')
    project = resolve.GetProjectManager().GetCurrentProject()
    for i in range(1, project.GetTimelineCount() + 1):
        t = project.GetTimelineByIndex(i)
        if t and name_substr.lower() in (t.GetName() or '').lower():
            project.SetCurrentTimeline(t)
            print(f'Set current timeline: {t.GetName()!r}')
            return True
    return False


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input', help='Input FCPXML (e.g. *_ALTERED_BATTLEGAPS.fcpxml)')
    ap.add_argument('--cuts', default=None,
                    help='cut-analysis JSON path (default: '
                         'plans/prompts/cut-analysis-<stem>.out.md based on transcript)')
    ap.add_argument('-o', '--output-dir', default=None,
                    help='Output directory for cut FCPXMLs (default: alongside input)')
    ap.add_argument('--import-to-resolve', action='store_true',
                    help='Import both cut FCPXMLs into the running Resolve project '
                         'and set the ALL-cuts timeline as current.')
    ap.add_argument('--keep-linked-audio', action='store_true',
                    help='Preserve the auto-editor\'s linked audio refs (1.wav-4.wav '
                         'as r4/r6/r8/r10) in the output spine. By default these are '
                         'dropped so the imported timeline has only V1+A1, keeping '
                         'A2-A5 free for the BGM/battle-audio/Fairlight pipeline.')
    ap.add_argument('--no-audio-snap', action='store_true',
                    help='Disable the audio-aware silence snap on cut endpoints. '
                         'Snap requires ffmpeg + librosa and loads the full source '
                         'A1 (~8s preload). Skip for fast iteration when you have '
                         'pre-validated cuts.')
    args = ap.parse_args()

    in_path = Path(args.input).resolve()
    if not in_path.exists():
        print(f'ERROR: input not found: {in_path}', file=sys.stderr)
        return 1

    # Default cuts file: plans/prompts/cut-analysis-<latest>.out.md
    if args.cuts:
        cuts_path = Path(args.cuts)
    else:
        candidates = sorted(Path('plans/prompts').glob('cut-analysis-*.out.md'),
                            key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            print('ERROR: no cut-analysis-*.out.md found', file=sys.stderr)
            return 1
        cuts_path = candidates[0]

    print(f'Input FCPXML: {in_path}')
    print(f'Cuts JSON:    {cuts_path}')

    cuts = json.loads(cuts_path.read_text(encoding='utf-8'))
    print(f'Total cuts: {len(cuts)} ({sum(1 for c in cuts if c.get("confidence")=="high")} high, '
          f'{sum(1 for c in cuts if c.get("confidence")=="medium")} medium)')

    # Audio-aware silence snap: re-align each cut endpoint to the nearest
    # true silence in the source. Prevents cuts from landing mid-speech.
    # Use --no-audio-snap to disable (e.g. for fast re-runs after manual edits).
    if not args.no_audio_snap:
        # Find the source video file from the FCPXML's <asset hasVideo="1">
        xml_for_path = in_path.read_text(encoding='utf-8')
        m = re.search(
            r'<asset[^>]*hasVideo="1"[^>]*>\s*<media-rep[^>]*src="([^"]+)"',
            xml_for_path)
        if m:
            from urllib.parse import unquote
            src_uri = m.group(1)
            # file:///F:/Brock%20Red/foo.mp4  →  F:/Brock Red/foo.mp4
            src_path = unquote(src_uri.replace('file:///', '').replace('file://', ''))
            print(f'  audio-snap: source = {src_path}')
            cuts = snap_cuts_to_silence(cuts, src_path)

    high = [c for c in cuts if c.get('confidence') == 'high']
    medium = [c for c in cuts if c.get('confidence') == 'medium']
    all_cuts = high + medium

    out_dir = Path(args.output_dir).resolve() if args.output_dir else in_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = in_path.stem
    high_out = out_dir / f'{stem}_CUTS_HIGH.fcpxml'
    all_out  = out_dir / f'{stem}_CUTS_ALL.fcpxml'

    xml = in_path.read_text(encoding='utf-8')

    # The FCPXML's <project name="..."> determines the Resolve timeline name.
    # Mutate it per variant so the two imported timelines have distinct names.
    def with_project_label(x: str, suffix: str) -> str:
        return re.sub(
            r'(<project\s+name=")([^"]*)(")',
            lambda m: f'{m.group(1)}{m.group(2)} {suffix}{m.group(3)}',
            x, count=1,
        )

    print('\n── HIGH-only cuts ──')
    high_xml, high_replay = apply_cuts(with_project_label(xml, '(cuts: high)'),
                                        high,
                                        keep_linked_audio=args.keep_linked_audio)
    high_out.write_text(high_xml, encoding='utf-8')
    print(f'Wrote: {high_out.name}  ({high_out.stat().st_size // 1024} KB)')

    print('\n── ALL cuts (high + medium) ──')
    all_xml, all_replay = apply_cuts(with_project_label(xml, '(cuts: all)'),
                                      all_cuts,
                                      keep_linked_audio=args.keep_linked_audio)
    all_out.write_text(all_xml, encoding='utf-8')
    print(f'Wrote: {all_out.name}  ({all_out.stat().st_size // 1024} KB)')

    # Replay sidecar — captures both variants so a sibling can be reproduced
    replay_path = out_dir / f'{stem}_cuts_replay.json'
    replay_path.write_text(json.dumps({
        'source_fcpxml': in_path.name,
        'cuts_source':   str(cuts_path.relative_to(Path.cwd())) if cuts_path.is_relative_to(Path.cwd()) else str(cuts_path),
        'high_only':     high_replay,
        'all_cuts':      all_replay,
        'cut_records':   cuts,  # the raw per-flag entries with reasons
    }, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'\nReplay metadata: {replay_path}')

    if args.import_to_resolve:
        print('\n── Importing into Resolve ──')
        import_to_resolve(high_out, '(cuts: high)')
        import_to_resolve(all_out,  '(cuts: all)')
        # Set ALL-cuts as current (user continues operations on this timeline)
        set_current_timeline_by_name('(cuts: all)')

    return 0


if __name__ == '__main__':
    sys.exit(main())
