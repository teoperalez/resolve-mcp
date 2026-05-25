"""
Normalize Pokemon-name + homophone errors in a Whisper transcript JSON.

Whisper consistently mis-transcribes Pokemon-domain vocabulary (Gastly →
Ghastly, Starmie → Starby, Zubat → "zoom out", Sentret → "Center it"),
common moves (Reflect → Rift), and a handful of trainer names. This script
applies a corrections dictionary to a transcript JSON and writes a
normalized text+JSON deliverable that's actually publishable.

The dictionary lives in `audio-checks/qa-v6/pokemon_normalizer.json` (or
override via --normalizer). Each entry is a from→to mapping. Three classes:

  - pokemon_names: simple word substitutions
  - phrase_corrections: multi-word substitutions
  - move_corrections: Pokemon move name fixes
  - homophones: context-dependent word fixes (e.g. "no" → "know")
  - general_typos: non-Pokemon typos (trader → trainer)
  - trainer_names: trainer name normalizations

Usage:
    python normalize_pokemon_text.py \\
        --transcript transcripts/dialogue-v6-transcript.json \\
        --normalizer audio-checks/qa-v6/pokemon_normalizer.json \\
        --out-text "E:/Misty Red/Misty Red - DIALOGUE_REVIEW_v6_NORMALIZED.txt" \\
        --out-json transcripts/dialogue-v6-normalized.json
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


def apply_dict(text: str, mapping: dict[str, str]) -> tuple[str, list[tuple[str,str,int]]]:
    """Apply each from→to substitution as a word-boundary regex.
    Returns (new_text, list_of_changes)."""
    changes = []
    out = text
    for src, dst in mapping.items():
        if src.startswith('_'):
            continue
        # Use word-boundary if src looks like a single word; else literal phrase
        if ' ' not in src.strip():
            pat = r'\b' + re.escape(src) + r'\b'
        else:
            # Multi-word phrase — match within word boundaries on outer edges
            pat = r'\b' + re.escape(src) + r'\b'
        n_before = len(out)
        new_out, n = re.subn(pat, dst, out)
        if n > 0:
            changes.append((src, dst, n))
            out = new_out
    return out, changes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--transcript', required=True)
    ap.add_argument('--normalizer', required=True)
    ap.add_argument('--out-text', default=None,
                     help='Output text-with-timecodes file (mm:ss prefix per segment)')
    ap.add_argument('--out-json', default=None,
                     help='Output normalized transcript JSON (segments preserved, text fields rewritten)')
    args = ap.parse_args()

    tr = json.loads(Path(args.transcript).read_text(encoding='utf-8'))
    norm = json.loads(Path(args.normalizer).read_text(encoding='utf-8'))

    # Combine all dicts in priority order: phrase first (longest first),
    # then names, moves, homophones, typos.
    combined = {}
    for k in ('phrase_corrections', 'pokemon_names', 'move_corrections',
                'homophones', 'general_typos', 'trainer_names'):
        d = norm.get(k, {})
        for kk, vv in d.items():
            if kk.startswith('_'):
                continue
            combined[kk] = vv
    # Sort keys longest first so phrase substitutions don't get blocked by short ones
    sorted_keys = sorted(combined.keys(), key=lambda k: -len(k))
    sorted_dict = {k: combined[k] for k in sorted_keys}

    all_changes = {}
    # Multi-pass: keep applying until no more changes (handles cases like
    # "Burt Lane → Blaine" + "be Blaine → beat Blaine" where the second
    # substitution only becomes possible after the first applies)
    for seg in tr.get('segments', []):
        for _pass in range(5):
            new_text, changes = apply_dict(seg['text'], sorted_dict)
            if not changes:
                break
            seg['text'] = new_text
            for src, dst, n in changes:
                all_changes[(src, dst)] = all_changes.get((src, dst), 0) + n

    if all_changes:
        print('Applied normalizations:', file=sys.stderr)
        for (src, dst), n in sorted(all_changes.items(), key=lambda x: -x[1]):
            print(f'  {n:3d}× {src!r} → {dst!r}', file=sys.stderr)
    else:
        print('No normalizations applied.', file=sys.stderr)

    if args.out_json:
        Path(args.out_json).write_text(json.dumps(tr, indent=2), encoding='utf-8')
        print(f'\nWrote JSON: {args.out_json}', file=sys.stderr)

    if args.out_text:
        # Two-pass output: first build the text with timecode prefixes, then
        # apply normalizer ACROSS THE WHOLE TEXT to catch substitutions that
        # span Whisper segment boundaries (e.g. "would probably be\n[xx:xx]
        # Blaine" can't match per-segment but can match across the joined text).
        lines = []
        for seg in tr['segments']:
            t = seg['start']
            mm = int(t // 60); ss = int(t % 60)
            lines.append(f'[{mm:02d}:{ss:02d}] {seg["text"].strip()}')
        full_text = '\n'.join(lines)
        # Cross-line normalize: temporarily strip newlines + timecode prefixes
        # to a single space so multi-word substitutions can match across
        # segments. Then restore line breaks by re-splitting on whitespace +
        # original timecodes.
        timecode_pat = re.compile(r'\n(\[\d+:\d+\]) ')
        # Replace "\n[xx:xx] " with a unique placeholder so we can restore
        placeholders = []
        def _stash(m):
            placeholders.append(m.group(1))
            return f' \x00BREAK{len(placeholders)-1}\x00 '
        flat = timecode_pat.sub(_stash, full_text)
        for _pass in range(3):
            new_flat, cross_changes = apply_dict(flat, sorted_dict)
            if not cross_changes:
                break
            flat = new_flat
            for src, dst, n in cross_changes:
                key = (src + ' [cross-line]', dst)
                all_changes[key] = all_changes.get(key, 0) + n
        # Restore line breaks
        def _restore(m):
            idx = int(m.group(1))
            return f'\n{placeholders[idx]} '
        full_text = re.sub(r'\s*\x00BREAK(\d+)\x00\s*', _restore, flat)

        # Explicit cross-segment patches for known cases where a word at the
        # end of one Whisper segment + a word at the start of the next form a
        # phrase the normalizer needs to rewrite. Each pattern allows newline
        # + timecode prefix between the words.
        cross_segment_patches = [
            (r'(would probably )be(\s*(?:\n\[\d+:\d+\] )?Blaine)',
             r'\1beat\2'),
            (r'(she would )be(\s*(?:\n\[\d+:\d+\] )?Janine)',
             r'\1beat\2'),
            (r'(We know she would )be(\s*(?:\n\[\d+:\d+\] )?Janine)',
             r'\1beat\2'),
        ]
        for pat, rep in cross_segment_patches:
            new_text, n = re.subn(pat, rep, full_text)
            if n:
                full_text = new_text
                print(f'  Cross-segment patch: {pat!r} x{n}', file=sys.stderr)
        if all_changes:
            cross_extras = [(k, v) for k, v in all_changes.items() if '[cross-line]' in k[0]]
            if cross_extras:
                print('Cross-line additions:', file=sys.stderr)
                for (src, dst), n in cross_extras:
                    print(f'  {n}x {src!r} -> {dst!r}', file=sys.stderr)
        Path(args.out_text).write_text(full_text, encoding='utf-8')
        print(f'Wrote text: {args.out_text}', file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
