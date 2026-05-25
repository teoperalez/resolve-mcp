"""Master orchestrator for the final-render-cut-qa skill.

This is the entry point /edittimeline Step 18 calls. It walks the 13 steps from
SKILL.md and writes all artifacts under <workspace>/audio-checks/final-video-qa/.

Status: SCAFFOLD — the orchestrator structure is in place but several steps
delegate to scripts that need first-invocation implementation:
    - Step 4 (transcribe_loose.py)
    - Step 5 (scan_transcript.py)
    - Step 6 (teo_style_filter.py)
    - Step 10 (build_review_html.py)

Steps that ARE implemented as standalone scripts:
    - Step 1 (inspect_render.py) ✅
    - Step 12 partial (map_final_to_source.py) ✅
    - Schema validation (validate_cut_schema.py) ✅

The orchestrator gracefully degrades — when a sub-script is missing, it prints
"TODO: Step N — implement <script>.py" and continues to the next step that can run.
On the first real invocation, Claude fills in the missing pieces interactively.

Usage (matches SKILL.md §Inputs):
    python run.py --render-path "<path>" --workspace "<path>" \
        [--canonical-cut-path X] [--source-transcript Y] [--replay-metadata Z] \
        [--intro-speed-pct 100|400] [--no-auto-confirm] \
        [--max-codex-passes 3] [--max-rebuild-iterations 1] [--archive-prior]
"""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_DIR / 'scripts'


def step_log(step: str, msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f'[{ts}] STEP {step}: {msg}')


def step_todo(step: str, msg: str):
    print(f'[TODO] STEP {step}: {msg} — implement when first triggered')


def archive_prior(workspace: Path, name: str, ext: str):
    """Rolling 2-version retention. Renames current to v(N-1) before overwrite."""
    qa_dir = workspace / 'audio-checks' / 'final-video-qa'
    current = qa_dir / f'{name}{ext}'
    prior = qa_dir / f'{name}_v1{ext}'
    if current.exists():
        if prior.exists():
            prior.unlink()  # delete v(N-2)
        current.rename(prior)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--render-path', required=True)
    ap.add_argument('--workspace', default='.')
    ap.add_argument('--canonical-cut-path', default=None)
    ap.add_argument('--source-transcript', default=None)
    ap.add_argument('--replay-metadata', default=None)
    ap.add_argument('--intro-speed-pct', type=int, choices=[100, 400], default=None)
    ap.add_argument('--no-auto-confirm', action='store_true')
    ap.add_argument('--max-codex-passes', type=int, default=3)
    ap.add_argument('--max-rebuild-iterations', type=int, default=1)
    ap.add_argument('--archive-prior', action='store_true')
    args = ap.parse_args()

    workspace = Path(args.workspace).resolve()
    qa_dir = workspace / 'audio-checks' / 'final-video-qa'
    qa_dir.mkdir(parents=True, exist_ok=True)
    (qa_dir / 'spot-checks').mkdir(exist_ok=True)
    (qa_dir / 'cut-audio').mkdir(exist_ok=True)

    auto_confirm = not args.no_auto_confirm

    # ── Step 0: rotate prior artifacts ─────────────────────────────────────
    if not args.archive_prior:  # rolling retention
        for name, ext in [('final_audio', '.wav'), ('final_transcript_turbo_loose', '.json'),
                          ('final-render-transcript', '.md'), ('final-render-transcript', '.txt'),
                          ('final-render-transcript-highlighted', '.html'),
                          ('waveform-repetitions', '.json'),
                          ('claude-confirmed-final-cuts', '.md'),
                          ('final-verdict', '.md')]:
            archive_prior(workspace, name, ext)
    step_log('0', f'workspace ready at {qa_dir}')

    # ── Step 1: inspect render ─────────────────────────────────────────────
    step_log('1', f'inspecting {args.render_path}')
    r = subprocess.run([sys.executable, str(SCRIPTS_DIR / 'inspect_render.py'),
                        args.render_path], capture_output=True, text=True)
    if r.returncode != 0:
        print(f'ERROR Step 1: {r.stderr}', file=sys.stderr)
        return 1
    inspect_result = json.loads(r.stdout)
    duration = inspect_result['duration_sec']
    step_log('1', f'duration {duration:.2f}s, video {inspect_result["video_streams"]}')

    # ── Step 2: extract audio ──────────────────────────────────────────────
    audio_path = qa_dir / 'final_audio.wav'
    step_log('2', f'extracting audio -> {audio_path}')
    cmd = ['ffmpeg', '-y', '-i', args.render_path, '-vn', '-ac', '1',
           '-ar', '16000', '-c:a', 'pcm_s16le', str(audio_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f'ERROR Step 2: ffmpeg failed: {r.stderr}', file=sys.stderr)
        return 1

    # ── Step 3: spot-check previews (TODO) ─────────────────────────────────
    step_todo('3', 'spot-check previews (opener / battle-ends / outro / carousel-start)')

    # ── Step 4: transcribe loose (TODO) ────────────────────────────────────
    step_todo('4', 'transcribe_loose.py (faster-whisper large-v3-turbo)')

    # ── Step 5-7: scan + style filter + join (TODO) ────────────────────────
    step_todo('5', 'scan_transcript.py (4 scanners + waveform similarity)')
    step_todo('6', 'teo_style_filter.py')
    step_todo('7', 'scanner+waveform join rule application')

    # ── Step 8: battle/vocab/replay sanity (TODO) ──────────────────────────
    step_todo('8', 'battle + vocab + replay-metadata checks')

    # ── Step 9: Codex review (MANUAL RELAY) ────────────────────────────────
    step_todo('9', 'Codex review (manual relay until codex-plugin-cc installed)')
    print('     See references/codex-integration-status.md')

    # ── Step 10-13: HTML, user confirm, mapping, verdict (TODO) ────────────
    step_todo('10', 'build_review_html.py')
    step_todo('11', 'user confirmation prompt')
    step_todo('12', 'source-time mapping + canonical append')
    step_todo('13', 'verdict determination + final-verdict.md write')

    # ── Skeleton verdict so the skill produces SOMETHING runnable ─────────
    verdict_path = qa_dir / 'final-verdict.md'
    verdict_path.write_text(f'''---
schema_version: 2
verdict: REJECT
date: {datetime.now().isoformat()}
render_path: {args.render_path}
render_duration_sec: {duration}
codex_audit_passes: 0
user_confirmed_cuts: 0
new_cuts_appended: 0
next_action: halt-and-investigate
auto_confirmed: false
---

## Summary

Skill is in SCAFFOLD state. Steps 3-13 not yet implemented. See
references/script-specs.md for what each TODO needs.

## Next steps

When you (Claude) hit this scaffold for a real render, fill in the missing scripts
interactively — start with Step 4 (transcribe_loose.py) and Step 5 (scan_transcript.py)
which are the highest-value missing pieces. Steps 3 and 10 are mechanical and can be
written quickly once those are done.

Steps 1, 2, 12 (mapping), and the validator already work.
''', encoding='utf-8')

    step_log('verdict', f'wrote SCAFFOLD verdict to {verdict_path}')
    print()
    print('=' * 70)
    print(f'Skill scaffold completed inspection + audio extraction.')
    print(f'Implementation TODOs: Steps 3-13 (transcribe → scan → style filter → ')
    print(f'  Codex relay → HTML → confirm → map → verdict).')
    print(f'Artifacts: {qa_dir}')
    print('=' * 70)
    return 0


if __name__ == '__main__':
    sys.exit(main())
