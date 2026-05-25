"""Validate cut-list JSON against the canonical schema.

Schema (mandatory fields):
    start_sec: float, 0 ≤ start < end ≤ source_duration
    end_sec: float
    confidence: "high" | "medium" | "low"
    type: "false_start" | "repetition" | "self_correction" | "artifact" |
          "whisper_hallucination" | "stream_chat_acknowledgment"
    reason: str (non-empty, must cite transcript segment or src time)

Optional metadata fields (prefixed `_`, ignored by apply_cuts_to_fcpxml.py):
    _source_chunk: int
    _dedup_with: str
    _waveform_peak_dbfs: float
    _codex_audit_pass: int
    _classification: str

Usage:
    python validate_cut_schema.py path/to/cuts.json
    # Exit code 0 on valid, 1 on error
"""
import argparse
import json
import sys

VALID_TYPES = {
    'false_start', 'repetition', 'self_correction', 'artifact',
    'whisper_hallucination', 'stream_chat_acknowledgment', 'mid_clip_false_start',
}
VALID_CONFIDENCE = {'high', 'medium', 'low'}
SOURCE_DURATION_MAX = 100_000.0  # generous upper bound


def validate(cuts, source_duration_max=SOURCE_DURATION_MAX):
    errors = []
    if not isinstance(cuts, list):
        errors.append('Top-level JSON must be an array')
        return errors

    for i, c in enumerate(cuts):
        prefix = f'[{i}]'
        if not isinstance(c, dict):
            errors.append(f'{prefix} not an object'); continue

        for k in ('start_sec', 'end_sec', 'confidence', 'type', 'reason'):
            if k not in c:
                errors.append(f'{prefix} missing field "{k}"')

        try:
            s = float(c['start_sec']); e = float(c['end_sec'])
        except (KeyError, ValueError, TypeError):
            errors.append(f'{prefix} start_sec/end_sec must be numeric')
            continue

        if s < 0 or e < 0:
            errors.append(f'{prefix} start/end must be non-negative; got {s}, {e}')
        if s >= e:
            errors.append(f'{prefix} start_sec ({s}) >= end_sec ({e})')
        if e > source_duration_max:
            errors.append(f'{prefix} end_sec ({e}) exceeds source max ({source_duration_max})')

        conf = c.get('confidence')
        if conf not in VALID_CONFIDENCE:
            errors.append(f'{prefix} invalid confidence "{conf}" (must be one of {VALID_CONFIDENCE})')

        t = c.get('type')
        if t not in VALID_TYPES:
            errors.append(f'{prefix} invalid type "{t}" (must be one of {VALID_TYPES})')

        r = c.get('reason')
        if not r or not isinstance(r, str) or len(r.strip()) < 5:
            errors.append(f'{prefix} reason missing or too short (need ≥5 chars)')

    # Check for overlapping ranges
    sorted_cuts = sorted(
        [(float(c['start_sec']), float(c['end_sec']), i) for i, c in enumerate(cuts)
         if 'start_sec' in c and 'end_sec' in c],
        key=lambda x: x[0],
    )
    for i in range(len(sorted_cuts) - 1):
        s_a, e_a, idx_a = sorted_cuts[i]
        s_b, e_b, idx_b = sorted_cuts[i + 1]
        if e_a > s_b:
            errors.append(
                f'overlap: cut [{idx_a}] ({s_a}-{e_a}) overlaps cut [{idx_b}] ({s_b}-{e_b})'
            )

    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('path', help='Path to cut-list JSON file')
    ap.add_argument('--source-duration-max', type=float, default=SOURCE_DURATION_MAX,
                    help=f'Maximum allowed end_sec (default {SOURCE_DURATION_MAX})')
    args = ap.parse_args()

    try:
        cuts = json.loads(open(args.path, encoding='utf-8').read())
    except Exception as e:
        print(f'ERROR: cannot parse {args.path}: {e}', file=sys.stderr)
        return 1

    errors = validate(cuts, args.source_duration_max)

    if errors:
        print(f'{len(errors)} validation error(s) in {args.path}:')
        for e in errors:
            print(f'  {e}')
        return 1

    print(f'OK: {args.path} ({len(cuts)} cuts, '
          f'{sum(c["end_sec"] - c["start_sec"] for c in cuts):.2f}s total)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
