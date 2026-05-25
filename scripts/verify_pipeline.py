"""
verify_pipeline.py — read the current timeline, run 5 audio/structure checks,
auto-color flag any issues using the editor's convention, write a JSON report.

Color convention (matches the editor's manual flags):
  Pink   — cut lands in speech / tiny speech-remnant clip
  Yellow — missed repetition or stutter cluster
  Lime   — battle pre-roll missing (no quiet 60-frame run before battle clip start)
  Teal   — extra battle pre-roll (60+ quiet frames at clip start but no battle within ±5s)
  Brown  — A2 BGM tagged general/exclude overlaps a battle range

Usage:
    verify_pipeline.py                       # report + auto-color (default)
    verify_pipeline.py --report-only         # report only, no color changes
    verify_pipeline.py --no-pink             # skip the (slow) pink audio scan
    verify_pipeline.py --fix                 # dispatch repair_*.py for each flag
    verify_pipeline.py --preserve-manual     # skip clips that already have a color
    verify_pipeline.py --battles transcripts/battles.json

Exit code = number of flags raised (0 = clean).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

import _audio_tools as A

# ── constants ────────────────────────────────────────────────────────────────

GAP_FRAMES        = 60        # canonical battle pre-roll = 1s @ 60fps
TINY_CLIP_SEC     = 0.30      # clips shorter than this are likely speech remnants
MICRO_CLIP_SEC    = 0.50      # threshold for micro-clip cluster detection
CLUSTER_WIN_SEC   = 1.50      # window for cluster detection
BOUNDARY_PROBE_MS = 40        # tight window straddling the cut frame; tighter than the silence-snap accept (≥80ms) so the verifier only flags TRUE mid-word cuts
SPEECH_THRESH_DB  = -30.0     # is_speech_active threshold
SILENCE_THRESH_DB = -40.0     # find_silence_in_window threshold
PREROLL_QUIET_RATIO = 0.6     # fraction of pre-roll that must be silent
BATTLE_PROXIMITY_SEC = 5.0    # for teal "no battle nearby" check
MFCC_REPEAT_THRESH  = 0.95    # cosine similarity for repetition detection (high to avoid FPs)
MIN_BROWN_OVERLAP_FRAMES = 30 # ignore <0.5s boundary touches in brown overlap check

TL_START_ABS = 0  # set in main() or via set_tl_start() for importers


def set_tl_start(n: int) -> None:
    """External callers (e.g. audit_step.py) call this before invoking the
    check_* functions so that tl_start_s fields in the returned flags are
    timeline-relative seconds (matches what verify_pipeline's CLI produces)."""
    global TL_START_ABS
    TL_START_ABS = int(n)


def load_full_audio_if_needed(source_path: str, sr: int = 48000):
    """Convenience wrapper for importers — loads + caches the full source
    A1 track via the existing _audio_tools cache. Returns None on failure
    so callers can fall back to per-probe extraction."""
    if not source_path:
        return None
    try:
        return A.load_full_audio_track(source_path, sr=sr)
    except Exception as e:
        print(f'WARN: full-track load failed ({e})', file=__import__('sys').stderr)
        return None

REPAIR_FOR_COLOR = {
    'Pink':   'repair_pink_cuts.py',
    'Yellow': 'repair_yellow_repetitions.py',
    'Lime':   'repair_lime_battle_gaps.py',
    'Teal':   'repair_teal_extra_gap.py',
    'Brown':  'repair_brown_bgm.py',
}

# ── helpers ──────────────────────────────────────────────────────────────────

def fmt(f: float) -> str:
    return f'{f:7.2f}s'


def build_v1_source_map(v1_clips, fps: float):
    """List of (tl_start_sec, tl_end_sec, src_start_sec, src_end_sec, clip)."""
    out = []
    for c in v1_clips:
        tl_s = c.GetStart()
        tl_e = c.GetEnd()
        src_s = c.GetLeftOffset()
        src_e = c.GetLeftOffset() + c.GetDuration()
        out.append((tl_s / fps, tl_e / fps,
                    src_s / fps, src_e / fps, c))
    return out


def source_sec_to_tl_sec(source_sec: float, v1_map) -> Optional[float]:
    """Map a source-time second to its current TL position via v1_map. None if not on TL."""
    for tl_s, tl_e, src_s, src_e, _c in v1_map:
        if src_s <= source_sec <= src_e:
            return tl_s + (source_sec - src_s)
    return None


def get_source_path(v1_map) -> Optional[str]:
    """Find the dominant gameplay source path (most-common clip name's path)."""
    if not v1_map:
        return None
    from collections import Counter
    names = Counter(c.GetName() for *_, c in v1_map)
    dominant_name = names.most_common(1)[0][0]
    for *_, c in v1_map:
        if c.GetName() == dominant_name:
            mpi = c.GetMediaPoolItem()
            if mpi:
                return mpi.GetClipProperty('File Path')
    return None


def is_gameplay_clip(clip, dominant_name: str) -> bool:
    """True iff this clip is from the dominant gameplay source — used to
    skip intro/outro/V2-overlay clips that have different source files."""
    return clip.GetName() == dominant_name


# ── checks ───────────────────────────────────────────────────────────────────

def check_pink_cuts(v1_clips, fps: float, source_path: str, do_audio: bool,
                     dominant_name: Optional[str] = None,
                     full_audio = None, sr: int = 48000) -> list[dict]:
    """Flag clips with: (a) tiny duration <TINY_CLIP_SEC, or (b) speech audio
    immediately adjacent (outside) the clip boundary on the source video — i.e.
    the cut truncated active speech."""
    flags = []
    sorted_clips = sorted(v1_clips, key=lambda c: c.GetStart())

    for i, c in enumerate(sorted_clips):
        dur_s = c.GetDuration() / fps
        src_start_s = c.GetLeftOffset() / fps
        src_end_s   = (c.GetLeftOffset() + c.GetDuration()) / fps

        # Tiny-clip check fires for ALL clips (even intro/outro debris).
        # Speech-truncation probes only run for gameplay-source clips.
        is_gameplay = (dominant_name is None) or (c.GetName() == dominant_name)

        # (a) tiny remnant
        if dur_s < TINY_CLIP_SEC:
            flags.append({
                'i': i, 'color': 'Pink',
                'reason': f'tiny clip ({dur_s*1000:.0f}ms < {TINY_CLIP_SEC*1000:.0f}ms) — speech-fragment remnant',
                'tl_start_s': round(c.GetStart() / fps, 3),
                'dur_s': round(dur_s, 3),
                'src_start': c.GetLeftOffset(),
                'src_end': c.GetLeftOffset() + c.GetDuration(),
            })
            continue

        if not do_audio or not source_path or not is_gameplay:
            continue

        # (b) speech immediately outside the clip → cut truncated speech.
        # Only flag boundaries that are real cuts (source-time discontinuity).
        prev = sorted_clips[i - 1] if i > 0 else None
        nxt  = sorted_clips[i + 1] if i + 1 < len(sorted_clips) else None
        probe_dur = BOUNDARY_PROBE_MS / 1000.0  # 0.1s

        # In-cut: was there speech in the source RIGHT before the clip starts?
        is_in_cut = prev is None or (prev.GetLeftOffset() + prev.GetDuration()) / fps != src_start_s
        if is_in_cut and src_start_s > probe_dur:
            try:
                if full_audio is not None:
                    audio = A.slice_window(full_audio, sr,
                                           max(0, src_start_s - probe_dur), probe_dur)
                else:
                    audio = A.extract_audio_window(source_path,
                                                   max(0, src_start_s - probe_dur),
                                                   probe_dur)
                if A.is_speech_active(audio, sr, threshold_db=SPEECH_THRESH_DB):
                    flags.append({
                        'i': i, 'color': 'Pink',
                        'reason': f'cut-in truncated speech (RMS > {SPEECH_THRESH_DB}dB '
                                  f'in {probe_dur*1000:.0f}ms before clip start)',
                        'tl_start_s': round((c.GetStart() - TL_START_ABS) / fps, 3),
                        'dur_s': round(dur_s, 3),
                        'src_start': c.GetLeftOffset(),
                        'src_end': c.GetLeftOffset() + c.GetDuration(),
                    })
                    continue
            except Exception as e:
                print(f'  pink probe failed at clip {i}: {e}', file=sys.stderr)

        # Out-cut: speech in source RIGHT after the clip ends?
        is_out_cut = nxt is None or nxt.GetLeftOffset() / fps != src_end_s
        if is_out_cut:
            try:
                if full_audio is not None:
                    audio = A.slice_window(full_audio, sr, src_end_s, probe_dur)
                else:
                    audio = A.extract_audio_window(source_path, src_end_s, probe_dur)
                if A.is_speech_active(audio, sr, threshold_db=SPEECH_THRESH_DB):
                    flags.append({
                        'i': i, 'color': 'Pink',
                        'reason': f'cut-out truncated speech (RMS > {SPEECH_THRESH_DB}dB '
                                  f'in {probe_dur*1000:.0f}ms after clip end)',
                        'tl_start_s': round((c.GetStart() - TL_START_ABS) / fps, 3),
                        'dur_s': round(dur_s, 3),
                        'src_start': c.GetLeftOffset(),
                        'src_end': c.GetLeftOffset() + c.GetDuration(),
                    })
            except Exception as e:
                print(f'  pink probe failed at clip {i}: {e}', file=sys.stderr)

    return flags


def check_yellow_repetitions(v1_clips, fps: float, source_path: str, do_audio: bool,
                                full_audio = None, sr: int = 48000,
                                dominant_name: Optional[str] = None) -> list[dict]:
    """Detect missed repetitions/stutters.

    (1) Cluster heuristic: 2+ adjacent micro-clips (<MICRO_CLIP_SEC) within a
        CLUSTER_WIN_SEC window — strong signal of stutter or interrupted speech.
    (2) MFCC similarity: each clip vs its immediate next-neighbor; >MFCC_REPEAT_THRESH
        means the spoken content is essentially the same."""
    flags = []
    sorted_clips = sorted(v1_clips, key=lambda c: c.GetStart())
    flagged_idx: set[int] = set()

    # (1) Cluster heuristic
    for i, c in enumerate(sorted_clips):
        if i in flagged_idx:
            continue
        dur_s = c.GetDuration() / fps
        if dur_s >= MICRO_CLIP_SEC:
            continue
        # Look at the next 1–3 clips; if the cluster span is <CLUSTER_WIN_SEC and
        # all are micro-clips, this looks like a stutter cluster.
        cluster = [i]
        for j in range(i + 1, min(i + 5, len(sorted_clips))):
            jc = sorted_clips[j]
            if jc.GetDuration() / fps >= MICRO_CLIP_SEC:
                break
            span_s = (jc.GetStart() + jc.GetDuration() - c.GetStart()) / fps
            if span_s > CLUSTER_WIN_SEC:
                break
            cluster.append(j)
        if len(cluster) >= 2:
            for idx in cluster:
                if idx in flagged_idx:
                    continue
                jc = sorted_clips[idx]
                flags.append({
                    'i': idx, 'color': 'Yellow',
                    'reason': f'micro-clip cluster ({len(cluster)} clips in <{CLUSTER_WIN_SEC}s)',
                    'tl_start_s': round((jc.GetStart() - TL_START_ABS) / fps, 3),
                    'dur_s': round(jc.GetDuration() / fps, 3),
                    'src_start': jc.GetLeftOffset(),
                    'src_end': jc.GetLeftOffset() + jc.GetDuration(),
                })
                flagged_idx.add(idx)

    # (2) MFCC similarity to next neighbor — DISABLED by default.
    # Mean MFCC over short speech windows is too speaker-characteristic — same
    # speaker's clips routinely score 0.97-0.99 even with different content,
    # producing many false positives. Real repetition detection needs DTW or
    # word-level alignment. Enable only when explicitly opted in.
    enable_mfcc = False
    if enable_mfcc and do_audio and source_path:
        for i, c in enumerate(sorted_clips[:-1]):
            if i in flagged_idx:
                continue
            nxt = sorted_clips[i + 1]
            dur_s = c.GetDuration() / fps
            ndur_s = nxt.GetDuration() / fps
            # Only run the expensive MFCC check on small-ish clips where repetition
            # is plausible. Long monologue clips rarely repeat verbatim.
            if dur_s > 3.0 or ndur_s > 3.0:
                continue
            # Only run MFCC on gameplay-source clips (intro/outro/V2 have
            # different source files and would mismatch full_audio)
            if dominant_name and c.GetName() != dominant_name:
                continue
            if dominant_name and nxt.GetName() != dominant_name:
                continue
            try:
                if full_audio is not None:
                    a = A.slice_window(full_audio, sr,
                                       c.GetLeftOffset() / fps, dur_s)
                    b = A.slice_window(full_audio, sr,
                                       nxt.GetLeftOffset() / fps, ndur_s)
                else:
                    a = A.extract_audio_window(source_path,
                                               c.GetLeftOffset() / fps, dur_s)
                    b = A.extract_audio_window(source_path,
                                               nxt.GetLeftOffset() / fps, ndur_s)
                sim = A.mfcc_similarity(a, b, sr)
                if sim >= MFCC_REPEAT_THRESH:
                    # Flag the longer of the two as the repeated content;
                    # the shorter is typically the keeper.
                    target = i if dur_s >= ndur_s else i + 1
                    tc = sorted_clips[target]
                    flags.append({
                        'i': target, 'color': 'Yellow',
                        'reason': f'MFCC repetition (sim={sim:.3f} >= {MFCC_REPEAT_THRESH})',
                        'tl_start_s': round((tc.GetStart() - TL_START_ABS) / fps, 3),
                        'dur_s': round(tc.GetDuration() / fps, 3),
                        'src_start': tc.GetLeftOffset(),
                        'src_end': tc.GetLeftOffset() + tc.GetDuration(),
                    })
                    flagged_idx.add(target)
            except Exception as e:
                print(f'  mfcc probe failed at clip {i}: {e}', file=sys.stderr)

    return flags


def check_lime_missing_preroll(v1_clips, fps: float, source_path: str,
                                 battles: list[dict], do_audio: bool,
                                 full_audio = None, sr: int = 48000) -> list[dict]:
    """For each battle, find the V1 clip containing the battle source-sec.
    Check that the first GAP_FRAMES of the clip are mostly silence (the
    designed pre-roll). If they're active speech, the pre-roll is missing."""
    flags = []
    if not battles:
        return flags
    sorted_clips = sorted(v1_clips, key=lambda c: c.GetStart())
    v1_map = build_v1_source_map(sorted_clips, fps)

    for b in battles:
        b_src = b['timestamp_sec']
        # Find clip containing battle source-sec
        target_idx = None
        for i, (_, _, src_s, src_e, _c) in enumerate(v1_map):
            if src_s <= b_src <= src_e:
                target_idx = i
                break
        if target_idx is None:
            continue
        clip = sorted_clips[target_idx]
        # Check first GAP_FRAMES of clip
        preroll_dur = GAP_FRAMES / fps
        if clip.GetDuration() < GAP_FRAMES:
            # Whole clip is shorter than pre-roll — definitely missing
            flags.append({
                'i': target_idx, 'color': 'Lime',
                'reason': f'clip dur {clip.GetDuration()}f < pre-roll {GAP_FRAMES}f '
                          f'for battle {b["trainer_name"]!r}',
                'tl_start_s': round(clip.GetStart() / fps, 3),
                'dur_s': round(clip.GetDuration() / fps, 3),
                'src_start': clip.GetLeftOffset(),
                'src_end': clip.GetLeftOffset() + clip.GetDuration(),
                'battle': b['trainer_name'],
            })
            continue
        if not do_audio or not source_path:
            continue
        try:
            if full_audio is not None:
                audio = A.slice_window(full_audio, sr,
                                       clip.GetLeftOffset() / fps, preroll_dur)
            else:
                audio = A.extract_audio_window(source_path,
                                               clip.GetLeftOffset() / fps,
                                               preroll_dur)
            sils = A.find_silence_in_window(audio, sr,
                                            threshold_db=SILENCE_THRESH_DB)
            quiet_sec = sum(e - s for s, e in sils)
            ratio = quiet_sec / preroll_dur if preroll_dur > 0 else 0
            if ratio < PREROLL_QUIET_RATIO:
                flags.append({
                    'i': target_idx, 'color': 'Lime',
                    'reason': f'pre-roll only {ratio*100:.0f}% silent '
                              f'(<{PREROLL_QUIET_RATIO*100:.0f}%) for battle {b["trainer_name"]!r}',
                    'tl_start_s': round((clip.GetStart() - TL_START_ABS) / fps, 3),
                    'dur_s': round(clip.GetDuration() / fps, 3),
                    'src_start': clip.GetLeftOffset(),
                    'src_end': clip.GetLeftOffset() + clip.GetDuration(),
                    'battle': b['trainer_name'],
                })
        except Exception as e:
            print(f'  lime probe failed at clip {target_idx}: {e}', file=sys.stderr)

    return flags


def check_teal_extra_preroll(v1_clips, fps: float, source_path: str,
                              battles: list[dict], do_audio: bool,
                              full_audio = None, sr: int = 48000,
                              dominant_name: Optional[str] = None) -> list[dict]:
    """Find V1 clips whose first GAP_FRAMES are mostly silent — that's a
    pre-roll. If there's no battle within BATTLE_PROXIMITY_SEC of clip start,
    this pre-roll is unwanted."""
    flags = []
    if not do_audio or not source_path:
        return flags
    sorted_clips = sorted(v1_clips, key=lambda c: c.GetStart())
    battle_sources = [b['timestamp_sec'] for b in battles]
    preroll_dur = GAP_FRAMES / fps

    for i, clip in enumerate(sorted_clips):
        if clip.GetDuration() < GAP_FRAMES:
            continue
        # Only gameplay-source clips have a full_audio match
        if dominant_name and clip.GetName() != dominant_name:
            continue
        src_start_s = clip.GetLeftOffset() / fps
        try:
            if full_audio is not None:
                audio = A.slice_window(full_audio, sr, src_start_s, preroll_dur)
            else:
                audio = A.extract_audio_window(source_path, src_start_s, preroll_dur)
            sils = A.find_silence_in_window(audio, sr,
                                            threshold_db=SILENCE_THRESH_DB)
            quiet_sec = sum(e - s for s, e in sils)
            ratio = quiet_sec / preroll_dur if preroll_dur > 0 else 0
        except Exception:
            continue
        if ratio < PREROLL_QUIET_RATIO:
            continue
        # Quiet pre-roll detected. Is there a battle within ±5s of clip start
        # in source-time? (Battles' source-sec; if any is within BATTLE_PROXIMITY_SEC
        # AFTER the clip's source start, the pre-roll is legitimate.)
        clip_src_end = (clip.GetLeftOffset() + clip.GetDuration()) / fps
        has_battle = any(src_start_s <= bs <= clip_src_end + BATTLE_PROXIMITY_SEC
                         for bs in battle_sources)
        if not has_battle:
            flags.append({
                'i': i, 'color': 'Teal',
                'reason': f'unwanted pre-roll ({ratio*100:.0f}% silent at start, '
                          f'no battle within {BATTLE_PROXIMITY_SEC}s)',
                'tl_start_s': round(clip.GetStart() / fps, 3),
                'dur_s': round(clip.GetDuration() / fps, 3),
                'src_start': clip.GetLeftOffset(),
                'src_end': clip.GetLeftOffset() + clip.GetDuration(),
            })

    return flags


def check_brown_bgm_under_battle(tl, fps: float, battles: list[dict],
                                   tl_start_abs: int) -> list[dict]:
    """A2 clip whose name's stem is tagged general/exclude in bgm-tags.json
    AND whose TL range overlaps any battle's TL range."""
    flags = []
    tags_path = Path.home() / '.resolve-mcp' / 'bgm-tags.json'
    if not tags_path.exists() or not battles:
        return flags
    tags = json.loads(tags_path.read_text(encoding='utf-8'))

    # Build battle TL ranges via v1_map + green markers
    v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
    v1_map = build_v1_source_map(v1, fps)
    markers = tl.GetMarkers() or {}
    greens = {f + tl_start_abs: m.get('name', '')
              for f, m in markers.items() if m.get('color') == 'Green'}

    battle_ranges = []
    for b in battles:
        tl_start_s = source_sec_to_tl_sec(b['timestamp_sec'], v1_map)
        if tl_start_s is None:
            continue
        end_abs = None
        for f_abs, name in greens.items():
            if b['trainer_name'].lower() in (name or '').lower():
                end_abs = f_abs
                break
        if end_abs is None:
            continue
        # tl_start_s is already in ABSOLUTE seconds (Resolve frames / fps).
        # Multiply by fps to get absolute frame, no further offset needed.
        battle_ranges.append((tl_start_s * fps, end_abs,
                              b['trainer_name']))

    if not battle_ranges:
        return flags

    a2 = sorted(tl.GetItemListInTrack('audio', 2) or [], key=lambda c: c.GetStart())
    for i, clip in enumerate(a2):
        name = clip.GetName() or ''
        # Strip __s..._fi..._fo... fade-variant suffix back to original stem
        base = re.sub(r'__s\d+_e\d+__fi\d+_fo\d+(?=\.\w+$)', '', name)
        base = re.sub(r'__s\d+_e\d+_fi\d+_fo\d+(?=\.\w+$)', '', base)
        # Also try .wav <-> .mp3 swap
        candidates = {base, base.replace('.wav', '.mp3'), base.replace('.mp3', '.wav'),
                      base.replace('_', ' ')}
        tag = None
        for cand in candidates:
            if cand in tags:
                tag = (tags[cand] or {}).get('tag')
                break
        # Resolve .wav-vs-.mp3 tag confusion: if EITHER variant of the filename
        # is tagged battle_*, treat as battle audio (the .wav file may be tagged
        # 'general' as a classifier-cache miss, but the .mp3 with the same stem
        # was correctly tagged battle_gym/battle_rival/battle_generic).
        battle_variants = [t for t in (tags.get(c, {}).get('tag') for c in candidates)
                           if t and t.startswith('battle_')]
        if battle_variants:
            continue  # this is battle audio, NOT a BGM-overlap problem
        if tag not in ('general', 'exclude'):
            continue
        c_start = clip.GetStart()
        c_end   = clip.GetEnd()
        # Overlap with any battle range?
        for b_start, b_end, b_name in battle_ranges:
            if c_start < b_end and c_end > b_start:
                overlap_start = max(c_start, b_start)
                overlap_end   = min(c_end, b_end)
                overlap_frames = overlap_end - overlap_start
                if overlap_frames < MIN_BROWN_OVERLAP_FRAMES:
                    continue  # sub-frame boundary touch, not a real overlap
                overlap_s = overlap_frames / fps
                flags.append({
                    'i': i, 'color': 'Brown',
                    'reason': f'{tag!r}-tagged BGM overlaps battle {b_name!r} '
                              f'by {overlap_s:.2f}s',
                    'tl_start_s': round((c_start - tl_start_abs) / fps, 3),
                    'tl_end_s':   round((c_end   - tl_start_abs) / fps, 3),
                    'name': name,
                    'track': 'A2',
                    'battle': b_name,
                })
                break  # one flag per A2 clip is enough

    return flags


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--report-only', action='store_true',
                    help="Don't set clip colors; just write the JSON report.")
    ap.add_argument('--no-pink', action='store_true',
                    help='Skip the (slow) audio-based pink/yellow/lime/teal checks.')
    ap.add_argument('--fix', action='store_true',
                    help='After reporting, dispatch the matching repair_*.py for each color.')
    ap.add_argument('--preserve-manual', action='store_true',
                    help="Don't touch clips that already have a color assigned.")
    ap.add_argument('--from-timeline', action='store_true',
                    help='Skip auto-detection; read existing clip colors from '
                         'the timeline as the authoritative flag set. Use this '
                         'after manually color-coding issues in Resolve.')
    ap.add_argument('--battles', default='transcripts/battles.json')
    ap.add_argument('--out-dir', default='_data/qa-reports', type=Path)
    args = ap.parse_args()

    r    = dvr.scriptapp('Resolve')
    if r is None:
        print('ERROR: Resolve not connected', file=sys.stderr)
        return 99
    proj = r.GetProjectManager().GetCurrentProject()
    tl   = proj.GetCurrentTimeline()
    if tl is None:
        print('ERROR: no current timeline', file=sys.stderr)
        return 99
    fps      = float(proj.GetSetting('timelineFrameRate'))
    tl_start = tl.GetStartFrame()
    global TL_START_ABS
    TL_START_ABS = tl_start
    print(f'Timeline: {tl.GetName()!r}  fps={fps}  start={tl_start}', flush=True)

    v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
    print(f'V1 clip count: {len(v1)}', flush=True)
    if not v1:
        print('No V1 clips — nothing to verify')
        return 0

    # Resolve gameplay source file
    v1_map = build_v1_source_map(v1, fps)
    source_path = get_source_path(v1_map)
    if source_path:
        # Map E:/F:/C: paths through subst if needed; ffmpeg follows what we pass.
        print(f'Source: {source_path}', flush=True)
    else:
        print('WARN: could not determine gameplay source path', flush=True)

    # Battles
    battles_path = Path(args.battles)
    battles = []
    if battles_path.exists():
        battles = json.loads(battles_path.read_text(encoding='utf-8'))
    print(f'Battles loaded: {len(battles)}', flush=True)

    do_audio = (not args.no_pink) and source_path is not None

    from collections import Counter
    dominant = Counter(c.GetName() for c in v1).most_common(1)[0][0]
    print(f'Dominant gameplay clip name: {dominant!r}')

    # --from-timeline mode: harvest existing clip colors instead of running detectors
    if args.from_timeline:
        print('\n--from-timeline mode: harvesting existing clip colors as flags', flush=True)
        all_flags = []
        for i, c in enumerate(v1):
            color = c.GetClipColor() or ''
            if color in ('Pink', 'Yellow', 'Lime', 'Teal'):
                all_flags.append({
                    'i': i, 'color': color,
                    'reason': 'user-flagged in timeline',
                    'tl_start_s': round((c.GetStart() - tl_start) / fps, 3),
                    'dur_s': round(c.GetDuration() / fps, 3),
                    'src_start': c.GetLeftOffset(),
                    'src_end': c.GetLeftOffset() + c.GetDuration(),
                })
        a2_clips = sorted(tl.GetItemListInTrack('audio', 2) or [],
                          key=lambda c: c.GetStart())
        for i, c in enumerate(a2_clips):
            color = c.GetClipColor() or ''
            if color in ('Brown',):
                all_flags.append({
                    'i': i, 'color': color, 'track': 'A2',
                    'reason': 'user-flagged in timeline',
                    'tl_start_s': round((c.GetStart() - tl_start) / fps, 3),
                    'tl_end_s':   round((c.GetEnd()   - tl_start) / fps, 3),
                    'name': c.GetName(),
                    # Add battle attribution by matching A2 clip's start to nearest battle
                })
        # Annotate Brown flags with battle attribution
        battles = []
        bpath = Path(args.battles)
        if bpath.exists():
            battles = json.loads(bpath.read_text(encoding='utf-8'))
        if battles:
            v1_map = build_v1_source_map(v1, fps)
            for f in all_flags:
                if f['color'] != 'Brown':
                    continue
                # Pick the battle whose TL range overlaps this A2 clip
                best = None
                for b in battles:
                    btl = source_sec_to_tl_sec(b['timestamp_sec'], v1_map)
                    if btl is None:
                        continue
                    if f['tl_start_s'] <= btl - tl_start/fps and btl - tl_start/fps <= f.get('tl_end_s', f['tl_start_s']+1):
                        best = b['trainer_name']
                        break
                    if abs(btl - tl_start/fps - f['tl_start_s']) < 60:  # within 1 min
                        best = b['trainer_name']
                f['battle'] = best
        # Write report and exit
        counts = Counter(f['color'] for f in all_flags)
        print(f'\nHarvested {len(all_flags)} flags from timeline colors:')
        for col in ('Pink', 'Yellow', 'Lime', 'Teal', 'Brown'):
            print(f'  {col}: {counts.get(col, 0)}')
        args.out_dir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r'[^\w\-]', '_', tl.GetName() or 'timeline')
        report_path = args.out_dir / f'{stem}.json'
        report = {
            'timeline': tl.GetName(),
            'fps': fps,
            'tl_start': tl_start,
            'source_path': source_path,
            'mode': 'from-timeline',
            'counts': {col.lower(): counts.get(col, 0) for col in
                       ('Pink', 'Yellow', 'Lime', 'Teal', 'Brown')} | {'total': len(all_flags)},
            'flags': all_flags,
        }
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                               encoding='utf-8')
        print(f'\nReport: {report_path}')
        return len(all_flags)

    # Pre-load the full A1 source track once; all audio checks slice from this.
    # First call extracts ~47min via ffmpeg (one-shot, no seeking).
    full_audio = None
    SR = 48000
    if do_audio:
        import time
        t0 = time.time()
        print(f'\nLoading full audio track from {source_path} ...', flush=True)
        try:
            full_audio = A.load_full_audio_track(source_path, sr=SR)
            print(f'  loaded {len(full_audio)/SR:.1f}s of audio in {time.time()-t0:.1f}s '
                  f'(~{full_audio.nbytes/1024/1024:.0f}MB)', flush=True)
        except Exception as e:
            print(f'  WARN: full-track load failed ({e}); falling back to per-probe ffmpeg.',
                  flush=True)

    # Run all checks
    print(f'\nRunning checks... (audio={do_audio})', flush=True)
    pink  = check_pink_cuts(v1, fps, source_path, do_audio,
                             dominant_name=dominant, full_audio=full_audio, sr=SR)
    print(f'  pink:   {len(pink)}', flush=True)
    yellow = check_yellow_repetitions(v1, fps, source_path, do_audio,
                                       full_audio=full_audio, sr=SR,
                                       dominant_name=dominant)
    print(f'  yellow: {len(yellow)}', flush=True)
    lime  = check_lime_missing_preroll(v1, fps, source_path, battles, do_audio,
                                         full_audio=full_audio, sr=SR)
    print(f'  lime:   {len(lime)}', flush=True)
    teal  = check_teal_extra_preroll(v1, fps, source_path, battles, do_audio,
                                       full_audio=full_audio, sr=SR,
                                       dominant_name=dominant)
    print(f'  teal:   {len(teal)}', flush=True)
    brown = check_brown_bgm_under_battle(tl, fps, battles, tl_start)
    print(f'  brown:  {len(brown)}', flush=True)

    all_flags = pink + yellow + lime + teal + brown
    print(f'\nTotal flags: {len(all_flags)}')

    # Optionally apply clip colors
    if not args.report_only and all_flags:
        sorted_v1 = sorted(v1, key=lambda c: c.GetStart())
        a2_clips  = sorted(tl.GetItemListInTrack('audio', 2) or [],
                           key=lambda c: c.GetStart())
        colored = 0
        for f in all_flags:
            if f.get('track') == 'A2':
                clips = a2_clips
            else:
                clips = sorted_v1
            i = f['i']
            if i >= len(clips):
                continue
            c = clips[i]
            if args.preserve_manual:
                existing = c.GetClipColor() or ''
                if existing and existing != f['color']:
                    continue
            try:
                if c.SetClipColor(f['color']):
                    colored += 1
            except Exception as e:
                print(f'  SetClipColor failed for clip {i}: {e}')
        print(f'Auto-colored {colored}/{len(all_flags)} clips')

    # Write report
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r'[^\w\-]', '_', tl.GetName() or 'timeline')
    report_path = args.out_dir / f'{stem}.json'
    report = {
        'timeline': tl.GetName(),
        'fps': fps,
        'tl_start': tl_start,
        'source_path': source_path,
        'battles_count': len(battles),
        'audio_checks_run': do_audio,
        'counts': {'pink': len(pink), 'yellow': len(yellow),
                   'lime': len(lime), 'teal': len(teal), 'brown': len(brown),
                   'total': len(all_flags)},
        'flags': all_flags,
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                            encoding='utf-8')
    print(f'\nReport: {report_path}')

    # Optional fix dispatch
    if args.fix and all_flags:
        print('\n── Dispatching repair scripts ──')
        scripts_dir = Path(__file__).parent
        py = sys.executable
        by_color = {}
        for f in all_flags:
            by_color.setdefault(f['color'], []).append(f)
        for color in ('Pink', 'Yellow', 'Lime', 'Teal', 'Brown'):
            if color not in by_color:
                continue
            sname = REPAIR_FOR_COLOR.get(color)
            if not sname:
                continue
            script_path = scripts_dir / sname
            if not script_path.exists():
                print(f'  SKIP {color}: {script_path.name} not implemented yet')
                continue
            print(f'  → {sname} ({len(by_color[color])} flags)')
            res = subprocess.run([py, str(script_path)], capture_output=False)
            print(f'    exit code: {res.returncode}')

    return len(all_flags)


if __name__ == '__main__':
    sys.exit(main())
