"""
Full battle gap insertion pipeline — runs all three steps in sequence:

  Step 1: transcribe_audio.py   — transcribes A1 audio source → transcripts/<stem>.json
  Step 2: detect_battles.py     — relay prompt written; Claude Code responds → battles.json
  Step 3: insert_battle_gaps.py — inserts 1s source footage gaps at each battle start

Usage:
    python battle_workflow.py [--gap-frames 60] [--model medium.en] [--dry-run]

After Step 2's prompt file is written, this script will print the path and pause.
Read the .in.md file, analyze it, and write your JSON response to the .out.md file.
The script resumes automatically once the .out.md is detected.
"""
import sys
import os
import subprocess
import argparse
from pathlib import Path

PYTHON  = sys.executable
SCRIPTS = Path(__file__).parent


def run(script: str, *args, check=True):
    cmd = [PYTHON, str(SCRIPTS / script)] + list(args)
    print(f'\n{"="*60}')
    print(f'Running: {" ".join(str(c) for c in cmd)}')
    print('='*60)
    result = subprocess.run(cmd)
    if check and result.returncode != 0:
        print(f'\nStep failed (exit {result.returncode}). Stopping.', file=sys.stderr)
        sys.exit(result.returncode)
    return result.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--gap-frames', default=60,   type=int,
                        help='Gap length in frames (default: 60 = 1s @ 60fps)')
    parser.add_argument('--model',      default='medium.en',
                        help='faster-whisper model (default: medium.en)')
    parser.add_argument('--dry-run',    action='store_true',
                        help='Step 3 dry-run: report without modifying Resolve')
    parser.add_argument('--skip-transcribe', action='store_true',
                        help='Skip Step 1 (use existing transcripts/)')
    args = parser.parse_args()

    transcripts_dir = 'transcripts'
    plans_dir       = 'plans/prompts'

    # Step 1: Transcribe
    if not args.skip_transcribe:
        run('transcribe_audio.py', '--model', args.model, '--out', transcripts_dir)
    else:
        print('Skipping transcription (--skip-transcribe)')

    # Find transcript file
    transcript_files = list(Path(transcripts_dir).glob('*.json'))
    if not transcript_files:
        print(f'No transcript JSON found in {transcripts_dir}/', file=sys.stderr)
        sys.exit(1)
    transcript = max(transcript_files, key=lambda p: p.stat().st_mtime)
    battles_out = Path(transcripts_dir) / 'battles.json'

    # Step 2: Detect battles (relay — Claude Code must respond)
    print(f'\n{"="*60}')
    print('Step 2: Battle detection via relay')
    print(f'Transcript: {transcript}')
    print('The prompt will be written to plans/prompts/.')
    print('Claude Code must read the .in.md and write the .out.md response.')
    print('='*60)
    run('detect_battles.py', str(transcript),
        '--out', str(battles_out),
        '--plans-dir', plans_dir,
        '--timeout-sec', '600')

    # Step 3: Insert gaps
    step3_args = ['insert_battle_gaps.py', str(battles_out),
                  '--gap-frames', str(args.gap_frames)]
    if args.dry_run:
        step3_args.append('--dry-run')
    run(*step3_args)

    print('\nDone.')


if __name__ == '__main__':
    main()
