"""Aggregate 11 chunk findings into a single unified cut list with dedupe.

Strategy:
1. Load all 11 chunk-NN-findings.json files
2. Collect all `new_cuts` entries
3. Dedupe: two cuts are "same" if their ranges overlap by > 0.5s OR
   their start_sec are within 0.5s of each other. Keep the one with
   smaller range (tighter cut), or merge if user-flagged as merge candidate.
4. Collect `existing_cuts_review` and reconcile conflicts (when two subagents
   disagree on KEEP/MODIFY/REMOVE for the same existing cut, prefer MODIFY
   over KEEP since both agreed the cut should change in some way).
5. Output:
   - `proposed-cut-list.json` — schema-compatible with cut-analysis-4.out.md
   - `aggregation-report.md` — dedupe decisions + conflict resolutions
"""
import json
from pathlib import Path
from collections import defaultdict

FINDINGS_DIR = Path('audio-checks/qa-cuts/findings')
OUT_LIST = Path('audio-checks/qa-cuts/proposed-cut-list.json')
OUT_REPORT = Path('audio-checks/qa-cuts/aggregation-report.md')
EXISTING = Path('plans/prompts/cut-analysis-4.out.md')


def overlaps(a_start, a_end, b_start, b_end, tol=0.5):
    return not (a_end + tol < b_start or b_end + tol < a_start)


def main():
    # Load all findings; normalize schema
    chunks = []
    for i in range(11):
        p = FINDINGS_DIR / f'chunk-{i:02d}-findings.json'
        if not p.exists():
            print(f'MISSING: {p}'); continue
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
        except Exception as e:
            print(f'INVALID JSON: {p} -- {e}'); raise
        # Normalize schema across the 4 variants subagents used
        start_keys = ['start_sec', 'src_start', 'cut_start', 'start']
        end_keys   = ['end_sec',   'src_end',   'cut_end',   'end']
        reason_keys = ['reason', 'rationale']

        for cut in data.get('new_cuts', []):
            for k in start_keys:
                if k in cut:
                    cut['start_sec'] = cut[k]
                    break
            for k in end_keys:
                if k in cut:
                    cut['end_sec'] = cut[k]
                    break
            for k in reason_keys:
                if k in cut:
                    cut['reason'] = cut[k]
                    break
            cut.setdefault('confidence', 'medium')
            t = cut.get('type', 'artifact')
            type_map = {
                'mid_clip_false_start': 'false_start',
                'mid_clip_self_correction': 'self_correction',
                'silence_gap': 'artifact',
                'silence_gap_borderline': 'artifact',
                'repeated_word_runt': 'repetition',
                'repeated_take': 'repetition',
                'whisper_hallucination': 'artifact',
                'dead_air': 'artifact',
                'silence_runt': 'artifact',
                'word_stitching': 'artifact',
                'donation_stinger': 'artifact',
                'empty_runt': 'artifact',
                'doubled_conjunction': 'artifact',
            }
            cut['type'] = type_map.get(t, t)
        chunks.append(data)

    # Load existing cuts
    existing = json.loads(EXISTING.read_text(encoding='utf-8'))

    # Collect all new_cuts across chunks, tagged with source chunk
    raw_new = []
    for ch in chunks:
        for cut in ch.get('new_cuts', []):
            cut['_source_chunk'] = ch['chunk_index']
            raw_new.append(cut)

    # Dedupe by overlap
    raw_new.sort(key=lambda c: c['start_sec'])
    deduped = []
    dedupe_log = []
    for cut in raw_new:
        matched = None
        for j, kept in enumerate(deduped):
            if overlaps(cut['start_sec'], cut['end_sec'],
                        kept['start_sec'], kept['end_sec'], tol=0.5):
                matched = j
                break
        if matched is None:
            deduped.append(cut)
        else:
            kept = deduped[matched]
            # Pick the tighter cut (smaller range) — and merge confidence/notes
            kept_range = kept['end_sec'] - kept['start_sec']
            cut_range  = cut['end_sec'] - cut['start_sec']
            if cut_range < kept_range:
                # Replace, but keep both reasons
                merged_reason = f"[chunk-{cut['_source_chunk']}] {cut['reason']} | [chunk-{kept['_source_chunk']}] {kept['reason']}"
                cut['reason'] = merged_reason
                cut['_dedup_with'] = f"chunk-{kept['_source_chunk']}"
                deduped[matched] = cut
                dedupe_log.append({
                    'kept': cut,
                    'dropped': kept,
                    'rule': 'tighter cut wins',
                })
            else:
                merged_reason = f"[chunk-{kept['_source_chunk']}] {kept['reason']} | [chunk-{cut['_source_chunk']}] {cut['reason']}"
                kept['reason'] = merged_reason
                kept.setdefault('_dedup_with', f"chunk-{cut['_source_chunk']}")
                dedupe_log.append({
                    'kept': kept,
                    'dropped': cut,
                    'rule': 'tighter cut wins (kept original)',
                })

    # Existing cuts review reconciliation
    existing_reviews = defaultdict(list)  # key: "S-E" range string
    for ch in chunks:
        for r in ch.get('existing_cuts_review', []):
            key = r.get('existing_cut', '')
            r['_source_chunk'] = ch['chunk_index']
            existing_reviews[key].append(r)

    # For each existing cut, decide final verdict
    existing_final = []
    for cut in existing:
        key = f"{cut['start_sec']:.2f}-{cut['end_sec']:.2f}"
        reviews = existing_reviews.get(key, [])
        if not reviews:
            existing_final.append({'cut': cut, 'verdict': 'KEEP', 'rationale': 'no chunk covered'})
            continue
        # Reconcile multiple reviews
        verdicts = [r['verdict'] for r in reviews]
        if 'REMOVE' in verdicts:
            v = 'REMOVE'
        elif 'MODIFY' in verdicts:
            v = 'MODIFY'
            mods = [r.get('modification') for r in reviews if r.get('modification')]
        else:
            v = 'KEEP'
        rationale = ' | '.join([f"[chunk-{r['_source_chunk']}] {r['verdict']}: {r.get('rationale', '')}" for r in reviews])
        record = {'cut': cut, 'verdict': v, 'rationale': rationale, 'review_count': len(reviews)}
        if v == 'MODIFY':
            record['modifications'] = [r.get('modification') for r in reviews if r.get('modification')]
        existing_final.append(record)

    # Build final unified cut list
    # 1. Existing cuts where verdict == KEEP: use as-is
    # 2. Existing cuts where verdict == MODIFY: use modified version (need manual confirmation)
    # 3. Existing cuts where verdict == REMOVE: drop
    # 4. New cuts (deduped): include
    final_cuts = []
    for rec in existing_final:
        if rec['verdict'] == 'REMOVE':
            continue
        if rec['verdict'] == 'MODIFY':
            cut = dict(rec['cut'])
            cut['_was_modified'] = True
            cut['_modify_rationale'] = rec['rationale']
            cut['_modifications_proposed'] = rec.get('modifications', [])
            final_cuts.append(cut)
        else:
            cut = dict(rec['cut'])
            final_cuts.append(cut)

    for cut in deduped:
        # Add the field defaults expected by apply_cuts script
        out = {
            'start_sec': cut['start_sec'],
            'end_sec': cut['end_sec'],
            'confidence': cut['confidence'],
            'type': cut['type'],
            'reason': cut['reason'],
        }
        if 'preserves' in cut:
            out['_preserves'] = cut['preserves']
        if '_source_chunk' in cut:
            out['_source_chunk'] = cut['_source_chunk']
        if '_dedup_with' in cut:
            out['_dedup_with'] = cut['_dedup_with']
        final_cuts.append(out)

    final_cuts.sort(key=lambda c: c['start_sec'])

    # Write output
    OUT_LIST.write_text(json.dumps(final_cuts, indent=2), encoding='utf-8')

    # Write aggregation report
    report = ['# Cut aggregation report\n']
    report.append(f'## Input: 11 chunks -> {len(raw_new)} raw new cuts\n')
    report.append(f'## After dedup: {len(deduped)} unique new cuts')
    report.append(f'## Existing cuts: {len(existing)}; after review: '
                  f'{sum(1 for r in existing_final if r["verdict"] == "KEEP")} KEEP, '
                  f'{sum(1 for r in existing_final if r["verdict"] == "MODIFY")} MODIFY, '
                  f'{sum(1 for r in existing_final if r["verdict"] == "REMOVE")} REMOVE\n')
    report.append(f'## Final cut count: {len(final_cuts)}\n')

    total_sec = sum(c['end_sec'] - c['start_sec'] for c in final_cuts)
    existing_sec = sum(c['end_sec'] - c['start_sec'] for c in existing)
    report.append(f'## Total seconds proposed for cutting: {total_sec:.2f}s '
                  f'(was {existing_sec:.2f}s in original cut-analysis-4.out.md)\n')

    report.append('---\n')
    report.append('## Dedupe events\n')
    if not dedupe_log:
        report.append('_No overlap-region duplicates found between chunks._\n')
    else:
        for ev in dedupe_log:
            k = ev['kept']
            d = ev['dropped']
            report.append(f'- **KEPT** [chunk-{k.get("_source_chunk")}] {k["start_sec"]:.2f}-{k["end_sec"]:.2f} ({k["type"]}, {k["confidence"]})')
            report.append(f'  **DROPPED** [chunk-{d.get("_source_chunk")}] {d["start_sec"]:.2f}-{d["end_sec"]:.2f} ({d["type"]}, {d["confidence"]})')
            report.append(f'  Rule: {ev["rule"]}')
            report.append('')

    report.append('---\n')
    report.append('## Existing-cuts review\n')
    for rec in existing_final:
        c = rec['cut']
        report.append(f'- `{c["start_sec"]:.2f} -> {c["end_sec"]:.2f}` ({c["type"]}, {c["confidence"]}) — **{rec["verdict"]}** (reviews: {rec.get("review_count", 0)})')
        report.append(f'  {rec["rationale"]}')
        if rec['verdict'] == 'MODIFY' and rec.get('modifications'):
            for m in rec['modifications']:
                report.append(f'  Proposed mod: {m}')
        report.append('')

    OUT_REPORT.write_text('\n'.join(report), encoding='utf-8')

    # Stdout summary
    print(f'Aggregated -> {OUT_LIST}')
    print(f'Report -> {OUT_REPORT}')
    print(f'Raw new cuts: {len(raw_new)}')
    print(f'Deduped new cuts: {len(deduped)}')
    print(f'Existing: KEEP={sum(1 for r in existing_final if r["verdict"] == "KEEP")} MODIFY={sum(1 for r in existing_final if r["verdict"] == "MODIFY")} REMOVE={sum(1 for r in existing_final if r["verdict"] == "REMOVE")}')
    print(f'Final unified cut count: {len(final_cuts)}')
    print(f'Total seconds proposed for cutting: {total_sec:.2f}s (was {existing_sec:.2f}s)')


if __name__ == '__main__':
    main()
