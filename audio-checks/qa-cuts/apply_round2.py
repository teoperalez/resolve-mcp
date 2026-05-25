"""Apply Codex round-1 review must-fix items to produce round-2 cut list."""
import json
from pathlib import Path

INPUT = Path('audio-checks/qa-cuts/proposed-cut-list.json')
OUTPUT = Path('audio-checks/qa-cuts/proposed-cut-list-round2.json')

# Confirmed-clean cuts (keep as-is); cite key for tracking
CONFIRMED_CLEAN = {
    (8.46, 9.48), (57.62, 78.17), (161.60, 161.96),
    (945.34, 945.40), (974.58, 974.64), (1001.32, 1002.72),
    (1089.00, 1094.28), (1184.56, 1187.36), (1215.88, 1215.94),
    (1245.14, 1247.94), (1273.98, 1276.78), (1352.42, 1352.58),
    (1962.77, 1967.65), (2064.72, 2065.13), (2273.38, 2274.78),
    (2700.12, 2702.40), (2824.66, 2825.08),
}

# Must-fix operations: key=(orig_start, orig_end), value=spec
# spec = ("modify", new_start, new_end, new_reason) or ("remove", reason)
MUST_FIX = {
    (348.60, 349.80): ("modify", 349.36, 349.44,
        "Tightened to remove only the duplicated 'ahead' word from seg 44 head. Per Codex review: the original range deleted real words from 'we're just gonna go ahead and use tackle' — only the duplicate 'ahead' (~0.08s at the seg 43/44 stitch) should go."),
    (469.00, 472.12): ("modify", 467.98, 470.12,
        "Tightened to remove the abandoned 'i simply predict that' fragment at end of seg 61 (467.98-470.12). Preserves clean restart 'in fact i simply predict that...' starting at seg 62 (470.12). Original boundary clipped 'in fact'."),
    (487.20, 488.12): ("modify", 485.68, 488.12,
        "Extended to remove the whole transition phrase 'but i think' so the splice lands cleanly: 'we'll just have to see. I think honestly...'. Original boundary left 'but' dangling."),
    (504.44, 505.20): ("modify", 504.44, 504.52,
        "Tightened to remove only the duplicated 'going' word (~0.08s) at seg 67/68 stitch. Original range removed 'going to get that far' which is real content."),
    (521.30, 524.50): ("modify", 522.24, 523.20,
        "Tightened to keep 'Violet City and if he' and remove only the second duplicated 'and if he' phrase. Original cut removed 'Violet City' opener."),
    (640.00, 641.60): ("modify", 640.88, 641.20,
        "Tightened to remove only abandoned 'i'm gonna' fragment. Original range removed 'a second hit there' and part of the move call."),
    (673.80, 677.20): ("modify", 674.16, 676.26,
        "Tightened to remove 'i think would just randomize between' fragment only. Preserves restart 'which would simply randomize between...'."),
    (721.12, 722.80): ("remove",
        "Removed per Codex review: this 1.68s pause after 'we once again miss' is a genuine battle reaction beat, not an artifact. LOW confidence + dramatic context = should be editor-discretion KEEP, not an automatic cut."),
    (810.48, 810.97): ("remove",
        "Removed per Codex review: transcript risk — seg 110 reads 'generation now there's no xp...' and Whisper word timestamps put the cut range inside 'now'/'there's'. Without waveform verification proving an isolated non-speech artifact, the cut risks clipping real words. Defaulting to REMOVE."),
    (1603.90, 1604.20): ("remove",
        "Removed per Codex review: the duplicate 'we' has zero-duration transcript timestamp and the current cut likely removes 'can', producing 'now we tackle' instead of 'now we can tackle'. Without waveform-verified tighter boundary, REMOVE."),
    (1627.24, 1628.60): ("remove",
        "Removed per Codex review: 'This time, no poison' is genuine play-by-play that explains the next action in the poison-repetition sequence. Not an artifact."),
    (1744.88, 1745.60): ("remove",
        "Removed per Codex review: 'I go tackle' is genuine rapid battle narration, even though Brock only has Tackle available. Removing the narration beat hurts clarity, not pacing."),
    (1747.34, 1747.88): ("remove",
        "Removed per Codex review: 'Very nice' is a genuine reaction to a meaningful Fury Cutter miss. Real reaction beat, not an artifact."),
    (2440.50, 2441.15): ("modify", 2440.70, 2441.78,
        "Applied the MODIFY proposed in round 1 review: word-timestamps show 'real' ends at 2440.700 and 'strategies' spans 2440.700-2441.780. Extended boundaries to avoid clipping 'real' and to fully remove 'strategies'. Final splice: '...we don't have any real available to us here'."),
    (2713.40, 2716.92): ("modify", 2713.40, 2717.90,
        "Extended to the chunk-9 boundary (2717.90 instead of 2716.92). The dedupe winner from round 1 (chunk-10's tighter range) left duplicated 'i will be coming back' — chunk-9's longer range removes the full false-start 'with a johto version but i will be coming back' so only the clean restart 'with a gen 2 version of brock' remains."),
    (2722.73, 2725.67): ("modify", 2722.86, 2725.64,
        "Applied the MODIFY proposed in chunk-10 review: start 2722.73 was mid-word inside 'but' (span 2722.18-2722.86); end 2725.67 was 30ms into 'with' (starts 2725.64). Corrected to exact word boundaries. Merged effect removes 'with his greater but', retaining 'but with his much improved team'."),
    (2724.84, 2725.64): ("remove",
        "Removed per Codex review item #16 (overlap conflict): this new mid-clip cut is redundant after the modified cut 2722.86-2725.64 above. Final JSON must not contain overlapping ranges."),
}

# Old micro-cuts that Codex flagged as needing verification — NOW verified via waveform.
# Results (peak dBFS, silent_frac <-45, speech_frac >-20):
#   556.00-556.28  peak=-18.7 silent=58% speech=??  -> SPEECH_LIKE -> REMOVE
#   599.73-600.42  peak=-17.3 silent=32% speech=??  -> SPEECH_LIKE -> REMOVE
#   1778.85-1779.28 peak=-18.5 silent=33% speech=?? -> SPEECH_LIKE -> REMOVE
#   2325.30-2325.78 peak=-20.9 silent=40% speech=0% -> BORDERLINE (quiet, no voice) -> KEEP
#   2692.58-2692.92 peak=-16.1 silent=50% speech=?? -> SPEECH_LIKE -> REMOVE
MICRO_CUTS_VERIFIED_REMOVE = {(556.00, 556.28), (599.73, 600.42),
                              (1778.85, 1779.28), (2692.58, 2692.92)}
MICRO_CUTS_VERIFIED_KEEP = {(2325.30, 2325.78)}

# Two more micro-cuts (not in Codex's explicit verify list but originally
# WORDS_IN_CLIP(0) types) — also verified:
#   172.75-173.05  peak=-16.2 silent=50% -> SPEECH_LIKE -> REMOVE
#   258.57-259.05  peak=-17.0 silent=35% -> SPEECH_LIKE -> REMOVE
# Plus chunk-2 new silence gap:
#   634.00-634.82  peak=-22.2 silent=67% speech=0% -> BORDERLINE (quiet, no voice) -> KEEP
EXTRA_MICRO_REMOVE = {(172.75, 173.05), (258.57, 259.05)}
EXTRA_MICRO_KEEP   = {(634.00, 634.82)}

# 26.8s gap investigation: peak=-39.2 dBFS, 98% silent -> definite cut
INVESTIGATION_ADD = [{
    'start_sec': 1989.96,
    'end_sec':   2016.76,
    'confidence': 'high',
    'type': 'artifact',
    'reason': "26.80s speechless gap between seg 247 ('...the only resource for me to use here is full heals') and seg 248 ('but i'm clearly running out of options too'). Waveform verification: peak -39.2 dBFS, 98% silent (<-45 dBFS bins). Confirmed dead air — only ambient mic floor noise + ducked game audio. Removing reclaims a substantial chunk of pacing without losing content.",
}]


def key(cut):
    return (round(cut['start_sec'], 2), round(cut['end_sec'], 2))


def normalize_confidence(c):
    return c.lower() if isinstance(c, str) else 'medium'


def main():
    input_cuts = json.loads(INPUT.read_text(encoding='utf-8'))
    output_cuts = []
    applied = []

    for cut in input_cuts:
        k = key(cut)

        # Strip debug fields
        clean = {
            'start_sec': cut['start_sec'],
            'end_sec':   cut['end_sec'],
            'confidence': normalize_confidence(cut['confidence']),
            'type': cut['type'],
            'reason': cut['reason'],
        }

        # Apply must-fix
        if k in MUST_FIX:
            spec = MUST_FIX[k]
            if spec[0] == 'remove':
                applied.append((k, 'REMOVE', spec[1]))
                continue
            elif spec[0] == 'modify':
                _, new_s, new_e, new_reason = spec
                clean['start_sec'] = new_s
                clean['end_sec']   = new_e
                clean['reason']    = new_reason
                applied.append((k, 'MODIFY', f'-> {new_s}-{new_e}'))
                output_cuts.append(clean)
                continue

        # Confirmed clean — keep as-is (with debug fields stripped)
        if k in CONFIRMED_CLEAN:
            output_cuts.append(clean)
            applied.append((k, 'KEEP', 'confirmed clean by Codex'))
            continue

        # Verified micro-cuts
        if k in MICRO_CUTS_VERIFIED_REMOVE or k in EXTRA_MICRO_REMOVE:
            applied.append((k, 'REMOVE_VERIFIED',
                f'waveform shows SPEECH_LIKE peak (-16 to -19 dBFS) — likely game audio or word fragment; not a clean artifact cut'))
            continue
        if k in MICRO_CUTS_VERIFIED_KEEP or k in EXTRA_MICRO_KEEP:
            output_cuts.append(clean)
            applied.append((k, 'KEEP_VERIFIED', 'waveform BORDERLINE/LOW_ENERGY — quiet, no speech (peak < -20 dBFS, speech_frac=0%); safe artifact cut'))
            continue

        # Unrecognized — KEEP but flag
        output_cuts.append(clean)
        applied.append((k, 'KEEP_UNCATEGORIZED', 'not in any Codex list, kept by default'))

    # Add the investigation cut (1989.96-2016.76)
    for new in INVESTIGATION_ADD:
        output_cuts.append(new)
        applied.append(((new['start_sec'], new['end_sec']), 'ADD_NEW',
            'Investigation cut (1989.96-2016.76): waveform verified 98% silent (<-45dBFS), peak -39.2 dBFS - 26.8s of dead air'))

    # Sort + validate
    output_cuts.sort(key=lambda c: c['start_sec'])
    for c in output_cuts:
        assert c['end_sec'] > c['start_sec'], f'Invalid: {c}'
        assert 0 <= c['start_sec'] <= 2840.32, f'OOB: {c}'
        assert 0 <= c['end_sec']   <= 2840.32, f'OOB: {c}'

    # Check overlaps
    overlaps = []
    for i in range(len(output_cuts) - 1):
        a, b = output_cuts[i], output_cuts[i + 1]
        if a['end_sec'] > b['start_sec']:
            overlaps.append((a, b))

    OUTPUT.write_text(json.dumps(output_cuts, indent=2), encoding='utf-8')

    total_removed = sum(c['end_sec'] - c['start_sec'] for c in output_cuts)
    print(f'Wrote {OUTPUT} -- {len(output_cuts)} cuts, total {total_removed:.2f}s')
    print(f'Operations: {sum(1 for _, op, _ in applied if op == "KEEP")} KEEP, '
          f'{sum(1 for _, op, _ in applied if op == "MODIFY")} MODIFY, '
          f'{sum(1 for _, op, _ in applied if op == "REMOVE")} REMOVE, '
          f'{sum(1 for _, op, _ in applied if op == "KEEP_NEEDS_VERIFY")} KEEP_NEEDS_VERIFY, '
          f'{sum(1 for _, op, _ in applied if op == "KEEP_UNCATEGORIZED")} KEEP_UNCAT')
    if overlaps:
        print('OVERLAPS DETECTED:')
        for a, b in overlaps:
            print(f'  {a["start_sec"]}-{a["end_sec"]}  vs  {b["start_sec"]}-{b["end_sec"]}')
    else:
        print('No overlaps. Valid.')

    # Write changelog
    import datetime
    changelog = ['# Round 2 Changelog\n',
                 f'Date: {datetime.datetime.now().isoformat()}',
                 f'Input: {INPUT}  ({len(input_cuts)} cuts)',
                 f'Output: {OUTPUT}  ({len(output_cuts)} cuts, {total_removed:.2f}s total)',
                 '']
    changelog.append('## Operations applied\n')
    for k, op, note in applied:
        changelog.append(f'- `{k[0]:.2f}-{k[1]:.2f}` **{op}** — {note}')
    if overlaps:
        changelog.append('\n## ⚠ OVERLAPS\n')
        for a, b in overlaps:
            changelog.append(f'- `{a["start_sec"]}-{a["end_sec"]}` vs `{b["start_sec"]}-{b["end_sec"]}`')
    Path('audio-checks/qa-cuts/_round2_ops.md').write_text('\n'.join(changelog), encoding='utf-8')
    print(f'Operation log: audio-checks/qa-cuts/_round2_ops.md')


if __name__ == '__main__':
    main()
