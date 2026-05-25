"""
Comprehensive QA pipeline for dialogue review WAV deliverables.

Implements the protocol established 2026-05-15 after Gemini-flagged QA gaps in
the Misty Red v6 review:

  Phase 1 (this script, orchestrator):
    - Compute waveform-based repetition candidates (catches duplicates that
      Whisper merges via repetition penalty).
    - Re-transcribe the full WAV with large-v3 + condition_on_previous_text=
      False + no_repeat_ngram_size=0 → "loose" transcript that does NOT hide
      repetitions or hallucinations.
    - Pull clip boundaries from the live Resolve timeline + compute v6-to-source
      mapping → splice timestamps for hallucination scan.
    - Chunk all artifacts into N packets for subagent dispatch.

  Phase 2 (Claude main thread, NOT this script):
    - Dispatch one Haiku subagent per chunk in parallel. Each subagent
      compares default-transcript vs loose-transcript, cross-references the
      repetition candidates, audits Pokemon names against the dictionary,
      and reports structured findings.

  Phase 3 (Claude main thread):
    - Aggregate subagent reports. Spot-check each flagged item via direct
      audio extraction + 25ms-bin RMS analysis. Look for cross-chunk
      patterns subagents missed. Build pre-corrected deliverable text.

Usage:
    python dialogue_qa_pipeline.py phase1 \\
        --wav "E:/path/to/v6.wav" \\
        --default-transcript transcripts/dialogue-v6-transcript.json \\
        --normalizer audio-checks/qa-v6/pokemon_normalizer.json \\
        --out-dir audio-checks/qa-v6/ \\
        --n-chunks 6

The script writes:
    audio-checks/qa-v6/loose-transcript.json
    audio-checks/qa-v6/repetitions.json
    audio-checks/qa-v6/v6_to_source_map.json
    audio-checks/qa-v6/splices.json
    audio-checks/qa-v6/chunks/chunk_NN_packet.json   ← hand each to one subagent
    audio-checks/qa-v6/chunks/chunk_NN_audio.wav
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path


# ───────────────────────── pre-compute helpers ─────────────────────────

def compute_repetitions(wav_path: Path, out_path: Path,
                          sim_threshold: float = 0.95,
                          min_duration_ms: float = 400.0) -> None:
    """Run scripts/find_audio_repetitions.py via subprocess so we reuse the
    existing implementation."""
    script = Path(__file__).parent / 'find_audio_repetitions.py'
    cmd = [sys.executable, str(script), str(wav_path),
            '--sim-threshold', f'{sim_threshold}',
            '--min-duration-ms', f'{min_duration_ms}',
            '--out', str(out_path)]
    subprocess.run(cmd, check=True)


def compute_loose_transcript(wav_path: Path, out_path: Path,
                                model_name: str = 'large-v3',
                                device: str = 'cpu') -> None:
    """Re-transcribe with repetition penalty disabled so duplicates and
    hallucinations both become visible."""
    from _cuda_dlls import register_nvidia_dll_dirs
    register_nvidia_dll_dirs()
    from faster_whisper import WhisperModel
    compute_type = 'float16' if device == 'cuda' else 'int8'
    print(f'Loading {model_name} on {device}...', flush=True)
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
    except Exception as e:
        if device == 'cuda':
            print(f'  CUDA failed: {e}; using CPU', flush=True)
            model = WhisperModel(model_name, device='cpu', compute_type='int8')
        else:
            raise
    print(f'Transcribing (no-repeat-suppression)...', flush=True)
    segs, _ = model.transcribe(
        str(wav_path), language='en', word_timestamps=True, beam_size=5,
        vad_filter=False, condition_on_previous_text=False,
        no_repeat_ngram_size=0,
    )
    out = {'segments': []}
    for s in segs:
        out['segments'].append({
            'start': s.start, 'end': s.end, 'text': s.text,
            'words': [{'start': w.start, 'end': w.end, 'word': w.word,
                       'probability': w.probability} for w in (s.words or [])]
        })
        if len(out['segments']) % 20 == 0:
            print(f'  {s.end:.1f}s done', flush=True)
    out_path.write_text(json.dumps(out, indent=2), encoding='utf-8')


def compute_v6_to_source_map(out_dir: Path) -> tuple[Path, Path]:
    """Read live Resolve V1 timeline, build v6_time → source_time map and
    extract splice timestamps."""
    sys.path.insert(0, str(Path(__file__).parent))
    import _resolve_env  # noqa: F401
    import DaVinciResolveScript as dvr
    r = dvr.scriptapp('Resolve')
    p = r.GetProjectManager().GetCurrentProject()
    tl = p.GetCurrentTimeline()
    fps = float(p.GetSetting('timelineFrameRate') or 60)
    v1 = sorted(tl.GetItemListInTrack('video', 1) or [], key=lambda c: c.GetStart())
    names = Counter([c.GetName() for c in v1])
    dominant = names.most_common(1)[0][0]
    out = []
    v6_cum = 0.0
    for c in v1:
        if c.GetName() != dominant:
            continue
        src_start = c.GetLeftOffset() / fps
        src_end   = (c.GetLeftOffset() + c.GetDuration()) / fps
        dur = src_end - src_start
        out.append({'v6_start': v6_cum, 'v6_end': v6_cum + dur,
                    'src_start': src_start, 'src_end': src_end})
        v6_cum += dur
    map_path = out_dir / 'v6_to_source_map.json'
    map_path.write_text(json.dumps(out, indent=2), encoding='utf-8')
    splices = [{'v6_time': out[i]['v6_end'],
                 'prev_src_end': out[i]['src_end'],
                 'next_src_start': out[i+1]['src_start']}
               for i in range(len(out)-1)]
    splice_path = out_dir / 'splices.json'
    splice_path.write_text(json.dumps(splices, indent=2), encoding='utf-8')
    print(f'v6-to-source map: {len(out)} segments, {len(splices)} splices',
          flush=True)
    return map_path, splice_path


def build_chunks(wav_path: Path, default_transcript: dict, loose_transcript: dict,
                 repetitions: list, splices: list, normalizer: dict,
                 out_dir: Path, n_chunks: int = 6,
                 overlap_sec: float = 15.0) -> list[Path]:
    """Split everything into N chunks with overlap and write per-chunk packets
    + audio chunks for subagent dispatch."""
    from math import ceil
    total_dur = max(s['end'] for s in default_transcript['segments'])
    chunk_dur = total_dur / n_chunks
    chunks_dir = out_dir / 'chunks'
    chunks_dir.mkdir(parents=True, exist_ok=True)
    packet_paths = []
    for i in range(n_chunks):
        c_start = max(0.0, i * chunk_dur - overlap_sec)
        c_end   = min(total_dur, (i+1) * chunk_dur + overlap_sec)
        # Filter artifacts to this chunk's window
        def in_range(t_start, t_end=None):
            return c_start <= (t_end if t_end is not None else t_start) <= c_end
        default_segs = [s for s in default_transcript['segments']
                         if in_range(s['start'], s['end'])]
        loose_segs   = [s for s in loose_transcript['segments']
                         if in_range(s['start'], s['end'])]
        chunk_reps   = [r for r in repetitions
                         if in_range(r['start_sec'], r['second_end_sec'])]
        chunk_splices = [s for s in splices if in_range(s['v6_time'])]
        # Extract audio chunk
        audio_path = chunks_dir / f'chunk_{i:02d}_audio.wav'
        cmd = ['ffmpeg', '-y', '-loglevel', 'error',
                '-ss', f'{c_start:.3f}', '-to', f'{c_end:.3f}',
                '-i', str(wav_path),
                '-ac', '1', '-ar', '16000', str(audio_path)]
        subprocess.run(cmd, check=True)
        # Build packet
        packet = {
            'chunk_index': i,
            'chunk_count': n_chunks,
            'v6_start_sec': c_start,
            'v6_end_sec': c_end,
            'audio_wav': str(audio_path),
            'overlap_sec': overlap_sec,
            'default_transcript_segments': default_segs,
            'loose_transcript_segments': loose_segs,
            'waveform_repetition_candidates': chunk_reps,
            'splice_points': chunk_splices,
            'normalizer': normalizer,
            'instructions': (
                'You are analyzing one chunk of a dialogue review WAV. Your job '
                'is to find every transcription error, hidden duplicate, splice '
                'hallucination, Pokemon-name typo, homophone confusion, and '
                'narrative gap in this chunk. Compare default_transcript vs '
                'loose_transcript word-by-word. Cross-reference '
                'waveform_repetition_candidates. Audit Pokemon names against '
                'normalizer. For any suspect spot, you may extract a sub-clip '
                'via ffmpeg and re-transcribe with large-v3 + '
                'no_repeat_ngram_size=0. Return a JSON list of findings.'
            ),
            'expected_output_schema': {
                'findings': [
                    {
                        'v6_time_start': 'float',
                        'v6_time_end': 'float',
                        'category': 'duplicate|hallucination|pokemon_name|homophone|missing_audio|other',
                        'default_text': 'what the default transcript says',
                        'loose_text': 'what large-v3 no-repeat says',
                        'corrected_text': 'what the audio actually says',
                        'recommended_action': 'transcript_only_fix|cut_needed|accept_stutter|investigate',
                        'confidence': 'high|medium|low',
                        'evidence': 'one sentence of justification',
                    }
                ],
                'overall_quality': 'clean|minor_issues|major_issues',
                'notes_for_main_thread': 'cross-chunk patterns or anything beyond per-finding scope',
            },
        }
        packet_path = chunks_dir / f'chunk_{i:02d}_packet.json'
        packet_path.write_text(json.dumps(packet, indent=2), encoding='utf-8')
        packet_paths.append(packet_path)
        print(f'chunk {i:02d}: v6 [{c_start:.1f}-{c_end:.1f}s]  '
              f'default={len(default_segs)} loose={len(loose_segs)} '
              f'reps={len(chunk_reps)} splices={len(chunk_splices)}', flush=True)
    return packet_paths


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='phase', required=True)

    p1 = sub.add_parser('phase1', help='orchestrator pre-compute')
    p1.add_argument('--wav', required=True)
    p1.add_argument('--default-transcript', required=True)
    p1.add_argument('--normalizer', required=True)
    p1.add_argument('--out-dir', required=True)
    p1.add_argument('--n-chunks', type=int, default=6)
    p1.add_argument('--overlap-sec', type=float, default=15.0)
    p1.add_argument('--skip-loose', action='store_true',
                     help='Reuse existing loose-transcript.json')
    p1.add_argument('--skip-reps', action='store_true',
                     help='Reuse existing repetitions.json')
    p1.add_argument('--skip-resolve', action='store_true',
                     help='Reuse existing v6-to-source map + splices')

    args = ap.parse_args()

    if args.phase == 'phase1':
        wav_path = Path(args.wav).resolve()
        out_dir = Path(args.out_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        rep_path = out_dir / 'repetitions.json'
        loose_path = out_dir / 'loose-transcript.json'

        if not args.skip_reps:
            print('=== Computing repetition candidates ===', flush=True)
            compute_repetitions(wav_path, rep_path)

        if not args.skip_loose:
            print('=== Re-transcribing with large-v3 (no-repeat-suppression) ===',
                  flush=True)
            compute_loose_transcript(wav_path, loose_path)

        if not args.skip_resolve:
            print('=== Building v6-to-source map + splices ===', flush=True)
            compute_v6_to_source_map(out_dir)

        print('=== Chunking into per-subagent packets ===', flush=True)
        default = json.loads(Path(args.default_transcript).read_text(encoding='utf-8'))
        loose   = json.loads(loose_path.read_text(encoding='utf-8'))
        reps    = json.loads(rep_path.read_text(encoding='utf-8'))
        splices = json.loads((out_dir / 'splices.json').read_text(encoding='utf-8'))
        normalizer = json.loads(Path(args.normalizer).read_text(encoding='utf-8'))
        packets = build_chunks(wav_path, default, loose, reps, splices,
                                 normalizer, out_dir,
                                 n_chunks=args.n_chunks,
                                 overlap_sec=args.overlap_sec)
        print(f'\nWrote {len(packets)} packets. Hand each to a Haiku subagent '
              f'with the instructions/schema embedded in the packet JSON.')
        return 0

    return 1


if __name__ == '__main__':
    sys.exit(main())
