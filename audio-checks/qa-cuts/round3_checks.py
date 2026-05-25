"""Round-3 cross-chunk + boundary + battle-intersection checks on the canonical cut list."""
import json
import re
from pathlib import Path
from collections import defaultdict

TRANSCRIPT = Path('transcripts/4.json')
CUTS       = Path('plans/prompts/cut-analysis-4.out.md')
BATTLES    = Path('transcripts/battles.json')
BATTLE_ENDS = Path('plans/prompts/battle-ends-refine-Brock_Red_Blue_versus_Crystl.out.md')
OUT        = Path('audio-checks/qa-cuts/round3-checks-report.md')

# Pokémon vocabulary to protect (names + Whisper homophones)
POKEMON_VOCAB = {
    'geodude', 'onix', 'kabutops', 'bayleaf', 'bayleef', 'chikorita', 'sentret',
    'cyndaquil', 'quilava', 'typhlosion', 'totodile', 'croconaw', 'feraligatr',
    'meganium', 'pidgey', 'pidgeotto', 'pidgeot', 'spearow', 'metapod',
    'kakuna', 'scyther', 'koffing', 'weezing', 'gastly', 'haunter', 'gengar',
    'zubat', 'golbat', 'crobat', 'magnemite', 'magneton', 'snorlax', 'rhydon',
    'graveler', 'golem',
    # Trainers
    'brock', 'misty', 'erika', 'sabrina', 'koga', 'janine', 'blaine', 'blue',
    'falkner', 'faulkner', 'bugsy', 'whitney', 'morty', 'jasmine', 'chuck',
    'pryce', 'clair', 'silver', 'red', 'lance', 'will', 'bruno', 'karen',
    'lorelei', 'agatha', 'oak', 'elm', 'gary',
    # Locations
    'pewter', 'cerulean', 'vermillion', 'celadon', 'fuchsia', 'saffron',
    'cinnabar', 'violet', 'azalea', 'goldenrod', 'ecruteak', 'olivine',
    'mahogany', 'blackthorn', 'cherrygrove', 'newbarktown',
    # Moves (commonly mistranscribed)
    'tackle', 'bide', 'harden', 'mudslap', 'pursuit', 'rocksmash', 'rocktomb',
    'rockthrow', 'magnitude', 'earthquake',
    # Items
    'fullheal', 'potion', 'super', 'antidote',
}


def load_transcript():
    t = json.loads(TRANSCRIPT.read_text(encoding='utf-8'))
    return t['segments']


def words_in_window(segs, src_start, src_end):
    """Collect all word objects across segments overlapping [src_start, src_end]."""
    out = []
    for s in segs:
        if s['end'] < src_start or s['start'] > src_end:
            continue
        for w in s.get('words') or []:
            if src_start <= w['start'] <= src_end or src_start <= w['end'] <= src_end:
                out.append({'text': (w.get('word') or '').strip(),
                            'start': w['start'], 'end': w['end']})
    return out


def normalize_word(w):
    return re.sub(r'[^\w]', '', w.lower())


def check_pokemon_boundaries(segs, cuts):
    """For each cut, check if either boundary lands inside or adjacent to a Pokemon name."""
    findings = []
    for cut in cuts:
        s, e = cut['start_sec'], cut['end_sec']
        # Find word at start-0.3 and end+0.3
        for boundary_label, boundary_t in [('start', s - 0.3), ('start', s),
                                            ('end', e), ('end', e + 0.3)]:
            for seg in segs:
                if seg['start'] - 0.5 <= boundary_t <= seg['end'] + 0.5:
                    for w in seg.get('words') or []:
                        if w['start'] <= boundary_t <= w['end']:
                            nw = normalize_word(w.get('word') or '')
                            if nw in POKEMON_VOCAB:
                                findings.append({
                                    'cut': f'{s:.2f}-{e:.2f}',
                                    'boundary': boundary_label,
                                    'boundary_time': boundary_t,
                                    'word': w.get('word'),
                                    'word_time': f'{w["start"]:.3f}-{w["end"]:.3f}',
                                    'severity': 'HIGH if word IS inside cut, else WARN',
                                    'inside_cut': s <= w['start'] and w['end'] <= e,
                                })
    return findings


def check_battle_intersection(cuts):
    """No cut may overlap a battle start or refined end window."""
    battles = json.loads(BATTLES.read_text(encoding='utf-8'))
    ends_data = json.loads(BATTLE_ENDS.read_text(encoding='utf-8'))
    end_map = {b['trainer_name'].lower(): b['end_sec'] for b in ends_data}

    findings = []
    for cut in cuts:
        s, e = cut['start_sec'], cut['end_sec']
        for battle in battles:
            t_name = battle['trainer_name']
            t_start = battle['timestamp_sec']
            # Battle start: cut window must not overlap [t_start - 2, t_start + 2]
            if s <= t_start + 2 and e >= t_start - 2:
                findings.append({
                    'cut': f'{s:.2f}-{e:.2f}',
                    'battle': t_name,
                    'battle_start': t_start,
                    'overlap_type': 'battle_start',
                    'severity': 'HIGH',
                })
            # Battle end (if present)
            t_end = end_map.get(t_name.lower())
            if t_end and s <= t_end + 2 and e >= t_end - 2:
                findings.append({
                    'cut': f'{s:.2f}-{e:.2f}',
                    'battle': t_name,
                    'battle_end': t_end,
                    'overlap_type': 'battle_end',
                    'severity': 'HIGH',
                })
            # Inside battle window (between start and end)
            if t_end and s >= t_start and e <= t_end:
                findings.append({
                    'cut': f'{s:.2f}-{e:.2f}',
                    'battle': t_name,
                    'battle_window': f'{t_start:.2f}-{t_end:.2f}',
                    'overlap_type': 'inside_battle',
                    'severity': 'WARN (battle commentary)',
                })
    return findings


def cross_chunk_ngram_scan(segs, ngram_size=4, max_gap=180.0):
    """Scan the whole transcript for repeated n-grams that are MORE THAN 30s apart
    (i.e. would have been missed by the chunk-internal 30s overlap pass).

    Returns clusters where the same n-gram appears 2+ times with > 30s gap.
    Filters out emphatic-restatement n-grams (we look for things with silence between).
    """
    # Tokenize each segment into normalized word list with src times
    word_stream = []
    for si, seg in enumerate(segs):
        for w in seg.get('words') or []:
            tok = normalize_word(w.get('word') or '')
            if tok and len(tok) > 1:
                word_stream.append((tok, w['start'], w['end'], si))

    # Build n-grams
    ngrams = defaultdict(list)
    for i in range(len(word_stream) - ngram_size + 1):
        gram = tuple(t[0] for t in word_stream[i:i + ngram_size])
        # Skip stopword-only ngrams
        if all(g in {'i', 'a', 'the', 'to', 'of', 'and', 'is', 'it', 'in', 'on', 'we',
                     'you', 'this', 'that', 'so', 'just', 'but', 'or', 'as', 'at',
                     'be', 'have', 'has', 'go', 'do'} for g in gram):
            continue
        first_t = word_stream[i][1]
        last_t = word_stream[i + ngram_size - 1][2]
        ngrams[gram].append((first_t, last_t, word_stream[i][3]))

    # Find repeats
    findings = []
    for gram, occurrences in ngrams.items():
        if len(occurrences) < 2:
            continue
        # Sort by time
        occurrences.sort(key=lambda x: x[0])
        for i in range(len(occurrences) - 1):
            t1_start, t1_end, seg1 = occurrences[i]
            t2_start, t2_end, seg2 = occurrences[i + 1]
            gap = t2_start - t1_end
            if 30.0 < gap < max_gap:
                findings.append({
                    'ngram': ' '.join(gram),
                    'first_occurrence_src': f'{t1_start:.2f}-{t1_end:.2f}',
                    'first_segment': seg1,
                    'second_occurrence_src': f'{t2_start:.2f}-{t2_end:.2f}',
                    'second_segment': seg2,
                    'gap_seconds': gap,
                })

    # Filter to interesting ones (gap < 60s OR n-gram is content-heavy)
    findings.sort(key=lambda f: f['gap_seconds'])
    return findings


def main():
    segs = load_transcript()
    cuts = json.loads(CUTS.read_text(encoding='utf-8'))

    print(f'Loaded {len(segs)} transcript segments, {len(cuts)} cuts')

    # Run checks
    pokemon_findings = check_pokemon_boundaries(segs, cuts)
    battle_findings  = check_battle_intersection(cuts)
    ngram_findings   = cross_chunk_ngram_scan(segs)

    # Report
    report = ['# Round 3 Cross-cut Verification Report\n',
              f'Generated: 2026-05-19',
              f'Canonical cut list: `plans/prompts/cut-analysis-4.out.md` ({len(cuts)} cuts)',
              f'Loose transcript:   `transcripts/4.json` ({len(segs)} segments)',
              '',
              '---',
              '## 4.5 — Battle window intersection check (rubric §4.5)\n']
    if not battle_findings:
        report.append('✅ **PASS** — No cut overlaps any battle start frame (±2s) or refined battle end.\n')
    else:
        report.append('⚠ **FINDINGS:**')
        for f in battle_findings:
            report.append(f'- `{f["cut"]}` — {f["overlap_type"]} for {f["battle"]} — severity: {f["severity"]}')
            report.append(f'  {json.dumps(f, indent=2)}')
    report.append('')

    report.append('---\n## 4.6 — Pokémon-name / vocabulary boundary check (rubric §4.6)\n')
    if not pokemon_findings:
        report.append('✅ **PASS** — No cut boundary lands inside a Pokémon name, trainer name, location, or commonly-mistranscribed move token.\n')
    else:
        report.append('⚠ **FINDINGS:**')
        for f in pokemon_findings:
            sev = 'BLOCKER' if f['inside_cut'] else 'WARN'
            report.append(f'- `{f["cut"]}` — {sev}: boundary at {f["boundary"]}={f["boundary_time"]:.2f}s lands inside word "{f["word"]}" at {f["word_time"]}')

    report.append('')
    report.append('---\n## NEW — Cross-chunk n-gram repeat scan (gap > 30s, < 180s)\n')
    report.append(f'Identifying repeated n-grams (4-gram, content-bearing) that the 30s overlap pass would have missed.\n')
    report.append(f'Total candidates found: **{len(ngram_findings)}**\n')

    if ngram_findings:
        report.append('| n-gram | gap (s) | first src | second src | first seg | second seg |')
        report.append('|---|---|---|---|---|---|')
        for f in ngram_findings[:50]:
            report.append(f'| "{f["ngram"]}" | {f["gap_seconds"]:.1f} | {f["first_occurrence_src"]} | {f["second_occurrence_src"]} | {f["first_segment"]} | {f["second_segment"]} |')
        if len(ngram_findings) > 50:
            report.append(f'\n_(showing top 50 of {len(ngram_findings)} — full list in JSON)_')

    # Write JSON of full ngram findings for Codex
    Path('audio-checks/qa-cuts/round3-ngrams.json').write_text(
        json.dumps(ngram_findings, indent=2), encoding='utf-8')

    OUT.write_text('\n'.join(report), encoding='utf-8')

    # Summary
    print(f'\nBattle intersection findings: {len(battle_findings)}')
    print(f'Pokemon-name boundary findings: {len(pokemon_findings)}')
    print(f'Cross-chunk n-gram repeat candidates: {len(ngram_findings)}')
    print(f'\nReport: {OUT}')
    print(f'N-gram JSON: audio-checks/qa-cuts/round3-ngrams.json')


if __name__ == '__main__':
    main()
