"""
Audit an existing cut list against a no-repeat-suppression source transcript.

Default-Whisper transcripts hide false-starts (see memory:
reference_default_whisper_hides_false_starts.md). A cut analyzer that ran
on the default transcript may have produced cuts whose boundaries miss
hidden false-start segments. This script re-checks each cut against the
loose transcript and flags suspect cuts.

Each cut is checked against three heuristics:

  1. **Boundary inside a long word** — if `start_sec` or `end_sec` lands
     inside a word with duration > 1.5s, that word is likely a Whisper
     hallucination over a stretched syllable or trail-off. The cut probably
     should be extended in that direction.

  2. **Dangling repetition** — if the n-gram that ends just before
     `start_sec` (or starts just after `end_sec`) repeats nearby in the
     loose transcript, the cut may be leaving a duplicate copy on the
     timeline. Indicates a false-start the cut missed.

  3. **Atomic numbered references split** — same rule as in
     mark_cut_candidates.py: if the cut boundary lands between a noun and
     its number/ordinal/digit, fix it.

Usage:
    python audit_cuts_against_loose.py \\
        --cuts plans/prompts/cut-analysis-4.out.md \\
        --loose audio-checks/qa-v6/source_loose_transcript.json \\
        --out audio-checks/qa-v6/cut_audit.json
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


def load_words(loose: dict) -> list[dict]:
    """Flatten loose-transcript segments into a single ordered word list."""
    out = []
    for seg in loose.get('segments', []):
        for w in seg.get('words', []) or []:
            out.append({
                'start': w['start'],
                'end':   w['end'],
                'word':  w['word'].strip().lower(),
                'probability': w.get('probability', 0.0),
            })
    out.sort(key=lambda w: w['start'])
    return out


def find_word_at(words: list[dict], t: float) -> dict | None:
    """Word whose [start, end] interval contains time t."""
    for w in words:
        if w['start'] <= t <= w['end']:
            return w
    return None


def words_in_range(words: list[dict], t0: float, t1: float) -> list[dict]:
    return [w for w in words if w['start'] >= t0 and w['end'] <= t1]


def words_around(words: list[dict], t: float, radius: float) -> list[dict]:
    return [w for w in words if abs(w['start'] - t) < radius or abs(w['end'] - t) < radius]


def is_numeric_word(s: str) -> bool:
    s = s.strip(' .,?!').lower()
    if s.isdigit():
        return True
    spelled = {
        'one','two','three','four','five','six','seven','eight','nine','ten',
        'eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen',
        'eighteen','nineteen','twenty','thirty','forty','fifty','sixty','seventy',
        'eighty','ninety','hundred','thousand',
        'first','second','third','fourth','fifth','sixth','seventh','eighth',
        'ninth','tenth',
    }
    return s in spelled


def find_repeated_ngram_after(words: list[dict], end_t: float,
                                lookback_words: int = 8,
                                lookforward_sec: float = 5.0) -> str | None:
    """If the n-gram ending just before end_t also appears within
    lookforward_sec after end_t, return the repeated n-gram."""
    # Words before end_t
    before = [w for w in words if w['end'] <= end_t]
    if len(before) < 2:
        return None
    after = [w for w in words if end_t < w['start'] <= end_t + lookforward_sec]
    if len(after) < 2:
        return None
    # Try 2..6-grams
    for n in (6, 5, 4, 3, 2):
        if len(before) < n or len(after) < n:
            continue
        before_ngram = ' '.join(w['word'] for w in before[-n:]).strip(' .,?!')
        # Slide over `after` words
        for i in range(len(after) - n + 1):
            after_ngram = ' '.join(w['word'] for w in after[i:i+n]).strip(' .,?!')
            if before_ngram == after_ngram and len(before_ngram.split()) >= 2:
                return before_ngram
    return None


def audit_cut(cut: dict, words: list[dict]) -> dict:
    flags = []
    s = cut['start_sec']
    e = cut['end_sec']

    # 1. Boundary inside a long word
    for which, t in (('start', s), ('end', e)):
        w = find_word_at(words, t)
        if w and (w['end'] - w['start']) > 1.5:
            flags.append({
                'kind':     'boundary_in_long_word',
                'side':     which,
                'word':     w['word'],
                'word_dur': round(w['end'] - w['start'], 2),
                'word_range': [round(w['start'],2), round(w['end'],2)],
                'note':    f'Cut {which} at {t:.2f}s lands inside a {w["end"]-w["start"]:.2f}s word "{w["word"]}" — likely a false-start trail-off; consider extending the cut.',
            })

    # 2. Repeated n-gram immediately after the cut end
    rep = find_repeated_ngram_after(words, e)
    if rep:
        flags.append({
            'kind':       'repeated_ngram_after_cut',
            'repeated':   rep,
            'note':       f'After cut end ({e:.2f}s), the n-gram "{rep}" appears again within 5s — cut may be leaving a duplicate phrase on timeline.',
        })

    # 3. Atomic numbered reference split
    for which, t in (('start', s), ('end', e)):
        # Get the word immediately before t and immediately after t
        before = [w for w in words if w['end'] <= t]
        after  = [w for w in words if w['start'] >= t]
        if not before or not after:
            continue
        wb = before[-1]
        wa = after[0]
        # Only flag if they're temporally adjacent (within 0.3s)
        if (wa['start'] - wb['end']) > 0.5:
            continue
        # Pattern: word then number/ordinal split
        if (not is_numeric_word(wb['word'])) and is_numeric_word(wa['word']):
            flags.append({
                'kind': 'atomic_numbered_split',
                'side': which,
                'before_word': wb['word'],
                'after_word':  wa['word'],
                'note': f'Cut {which} at {t:.2f}s splits "{wb["word"]} {wa["word"]}" — atomic numbered reference per Teo Speech Style §9.4.',
            })
        elif is_numeric_word(wb['word']) and (not is_numeric_word(wa['word'])):
            flags.append({
                'kind': 'atomic_numbered_split',
                'side': which,
                'before_word': wb['word'],
                'after_word':  wa['word'],
                'note': f'Cut {which} at {t:.2f}s splits "{wb["word"]} {wa["word"]}" — number split from following noun.',
            })

    return {
        'cut': cut,
        'flags': flags,
        'word_at_start': find_word_at(words, s),
        'word_at_end':   find_word_at(words, e),
        'words_in_range': words_in_range(words, s, e),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cuts', required=True)
    ap.add_argument('--loose', required=True)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    cuts = json.loads(Path(args.cuts).read_text(encoding='utf-8'))
    loose = json.loads(Path(args.loose).read_text(encoding='utf-8'))
    words = load_words(loose)
    print(f'Cuts: {len(cuts)}', file=sys.stderr)
    print(f'Loose words: {len(words)}', file=sys.stderr)
    print(f'Source duration: {words[-1]["end"] if words else 0:.2f}s', file=sys.stderr)

    audits = [audit_cut(c, words) for c in cuts]
    flagged = [a for a in audits if a['flags']]
    print(f'\nFlagged cuts: {len(flagged)}/{len(cuts)}', file=sys.stderr)
    for a in flagged:
        c = a['cut']
        print(f'\n  [{c["start_sec"]:.2f}-{c["end_sec"]:.2f}] {c.get("type","?")}', file=sys.stderr)
        for f in a['flags']:
            print(f'    - {f["kind"]}: {f["note"]}', file=sys.stderr)

    if args.out:
        Path(args.out).write_text(json.dumps(audits, indent=2), encoding='utf-8')
        print(f'\nWrote: {args.out}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
