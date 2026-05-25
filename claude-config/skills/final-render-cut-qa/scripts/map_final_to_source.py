"""Map a final-render timestamp to source-video time.

See `../references/source-time-mapping.md` for the full algorithm + worked example.

Usage:
    python map_final_to_source.py --final-sec 301.74 \
        --replay "E:/Brock Red/Brock Red Blue versus Crystl_ALTERED_BATTLEGAPS_cuts_replay.json" \
        --intro-speed 400 --intro-native-sec 17.07 --first-v1-source-sec 78.83

    # Or auto-detect mode:
    python map_final_to_source.py --final-sec 301.74 --workspace /path/to/project
"""
import argparse
import json
import sys
from pathlib import Path


def final_to_source(
    final_sec: float,
    replay_path: str,
    intro_speed_pct: int,
    intro_native_sec: float,
    first_v1_source_in_sec: float,
) -> float:
    """Map a final-render timestamp (seconds) to source-video time (seconds).

    Raises ValueError if final_sec is inside the intro graphic.
    """
    replay = json.loads(Path(replay_path).read_text(encoding='utf-8'))
    fps = replay['den']

    intro_placed_sec = intro_native_sec * 100 / intro_speed_pct

    if final_sec < intro_placed_sec:
        raise ValueError(
            f'final {final_sec}s is inside the intro graphic (0..{intro_placed_sec}s); '
            f'not a source time'
        )

    # Edit-timeline time relative to first source-content frame
    edit_tl_sec = final_sec - intro_placed_sec

    # Walk removed_tl_ranges_frames; each removed range shifts source time forward
    # The ranges are in EDIT-TIMELINE frames (after intro placement; the apply_cuts
    # script records them as offset from the source-content start).
    shift = 0.0
    for r in replay['all_cuts']['removed_tl_ranges_frames']:
        rs = r['start'] / fps
        re_ = r['end'] / fps
        if edit_tl_sec + shift >= rs:
            shift += (re_ - rs)
        else:
            break  # ranges sorted; once we pass, no more apply

    return first_v1_source_in_sec + edit_tl_sec + shift


def auto_detect(workspace: Path) -> dict:
    """Auto-detect replay_path, intro_speed_pct, intro_native_sec, first_v1_source_sec.

    Reads:
      - transcripts/min-battles.json (is_minimum_battles → intro_speed)
      - transcripts/<stem>.json (audio field → source dir → replay path)
      - intro asset duration (TODO: query Resolve API or pass --intro-native-sec)
      - first V1 clip source-in (TODO: query Resolve API or pass --first-v1-source-sec)

    Returns dict with detected values, raises if any cannot be determined.
    """
    min_battles = json.loads((workspace / 'transcripts' / 'min-battles.json').read_text(encoding='utf-8'))
    intro_speed_pct = 100 if min_battles.get('is_minimum_battles') else 400

    # Find most-recent transcript
    transcripts_dir = workspace / 'transcripts'
    candidates = sorted(
        [f for f in transcripts_dir.glob('*.json')
         if f.stem not in {'min-battles', 'battles', 'battle-types', 'rival-starter'}],
        key=lambda f: f.stat().st_mtime, reverse=True
    )
    if not candidates:
        raise RuntimeError(f'No source transcript JSON found in {transcripts_dir}')
    transcript = json.loads(candidates[0].read_text(encoding='utf-8'))
    audio = transcript.get('audio')
    if not audio:
        raise RuntimeError(f'Transcript {candidates[0]} has no `audio` field')
    src_dir = Path(audio).parent
    if src_dir.name.endswith('_tracks'):
        src_dir = src_dir.parent

    # Find replay file (most recent `*_cuts_replay.json` in src_dir)
    replays = sorted(src_dir.glob('*_cuts_replay.json'),
                     key=lambda f: f.stat().st_mtime, reverse=True)
    if not replays:
        raise RuntimeError(f'No *_cuts_replay.json in {src_dir}')

    return {
        'replay_path': str(replays[0]),
        'intro_speed_pct': intro_speed_pct,
        'intro_native_sec': None,  # caller must supply or look up
        'first_v1_source_in_sec': None,  # caller must supply or look up
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--final-sec', type=float, required=True,
                    help='Final-render timestamp (seconds)')
    ap.add_argument('--replay', type=str,
                    help='Path to *_cuts_replay.json (default: auto-detect)')
    ap.add_argument('--intro-speed', type=int, choices=[100, 400],
                    help='Intro retime percent (default: auto-detect from min-battles.json)')
    ap.add_argument('--intro-native-sec', type=float, default=17.07,
                    help='Native intro duration before retime (default 17.07s for GSCPC Intro Short)')
    ap.add_argument('--first-v1-source-sec', type=float,
                    help='Source time of first non-intro V1 clip '
                         '(required; query Resolve API or pass manually)')
    ap.add_argument('--workspace', type=str, default='.',
                    help='Project root for auto-detect (default: cwd)')
    args = ap.parse_args()

    workspace = Path(args.workspace).resolve()
    replay_path = args.replay
    intro_speed = args.intro_speed

    if replay_path is None or intro_speed is None:
        detected = auto_detect(workspace)
        replay_path = replay_path or detected['replay_path']
        intro_speed = intro_speed or detected['intro_speed_pct']

    if args.first_v1_source_sec is None:
        print('ERROR: --first-v1-source-sec is required (no auto-detect for this value yet).',
              file=sys.stderr)
        print('Query Resolve API: tl.GetItemListInTrack("video", 1)[1].GetLeftOffset() / fps',
              file=sys.stderr)
        return 1

    try:
        source_sec = final_to_source(
            args.final_sec, replay_path, intro_speed,
            args.intro_native_sec, args.first_v1_source_sec,
        )
    except ValueError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 1

    print(f'{source_sec:.3f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
