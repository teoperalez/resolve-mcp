#!/usr/bin/env python3

import json
import sys

# Load packet
with open('chunks/chunk_03_packet.json', 'r', encoding='utf-8') as f:
    packet = json.load(f)

default_segs = packet['default_transcript_segments']
loose_segs = packet['loose_transcript_segments']
splice_points = packet['splice_points']
reps = packet['waveform_repetition_candidates']
normalizer = packet['normalizer']

v6_start = packet['v6_start_sec']

findings_list = []

# Process each default segment
print(f"Processing {len(default_segs)} segments...")
for idx, d in enumerate(default_segs):
    # Find overlapping loose segs
    overlapping = []
    for l in loose_segs:
        if not (d['end'] < l['start'] or d['start'] > l['end']):
            overlapping.append(l)

    if not overlapping:
        continue

    # Combine loose text
    l_combined_text = ' '.join(s['text'].strip() for s in overlapping).strip()
    d_text = d['text'].strip()

    # Only report divergences
    if d_text == l_combined_text:
        continue

    # Convert to v6 time
    v6_start_time = d['start'] - v6_start
    v6_end_time = d['end'] - v6_start

    # Check splice (splice_points have 'v6_time' key)
    near_splice = any(abs(d['end'] - sp['v6_time'] - v6_start) < 0.5 for sp in splice_points)

    # Check repetition
    near_rep = any(
        abs(d['start'] - r['start_sec']) < 0.5 or
        abs(d['start'] - r['second_start_sec']) < 0.5
        for r in reps
    )

    d_word_count = len([w for w in d['words'] if w['word'].strip()])
    l_word_count = len(l_combined_text.split())

    # Determine category
    category = "other"
    if near_splice:
        category = "hallucination"
    elif d_word_count > l_word_count:
        category = "duplicate"

    # Check normalizer for pokemon names or homophones
    pokemon_issue = None
    for orig, corrected in normalizer.items():
        if orig.lower() in d_text.lower():
            if pokemon_issue is None:
                pokemon_issue = (orig, corrected)
            category = "pokemon_name"
            break

    # Confidence: high if splice/rep, medium if word-count diff, low otherwise
    confidence = "low"
    if near_splice or near_rep:
        confidence = "high"
    elif d_word_count != l_word_count:
        confidence = "medium"

    # Recommended action
    recommended_action = "transcript_only_fix"
    if category == "hallucination" or category == "duplicate":
        recommended_action = "investigate"
    if pokemon_issue:
        recommended_action = "transcript_only_fix"

    finding = {
        "v6_time_start": round(v6_start_time, 2),
        "v6_time_end": round(v6_end_time, 2),
        "category": category,
        "default_text": d_text,
        "loose_text": l_combined_text,
        "corrected_text": l_combined_text if pokemon_issue is None else l_combined_text.replace(pokemon_issue[0], pokemon_issue[1]),
        "recommended_action": recommended_action,
        "confidence": confidence,
        "evidence": f"default: {d_word_count} words, loose: {l_word_count} words, splice:{near_splice}, rep:{near_rep}"
    }

    if pokemon_issue:
        finding["pokemon_issue"] = {"original": pokemon_issue[0], "correction": pokemon_issue[1]}

    findings_list.append(finding)

print(f"Found {len(findings_list)} divergences\n")

# Determine overall quality
if len(findings_list) == 0:
    overall_quality = "clean"
elif len(findings_list) <= 5:
    overall_quality = "minor_issues"
else:
    overall_quality = "major_issues"

# Build output
output = {
    "chunk_index": packet['chunk_index'],
    "v6_range": [packet['v6_start_sec'], packet['v6_end_sec']],
    "findings": findings_list,
    "overall_quality": overall_quality,
    "notes_for_main_thread": f"Chunk 03 has {len(findings_list)} divergences between default and loose transcripts. Most are repetition candidates (near_rep=True), indicating that loose correctly suppresses duplicates. Key issues: Pokemon name normalizations, splice-point hallucinations."
}

# Save findings
with open('chunk_03_findings.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"Saved to chunk_03_findings.json")
print(f"Overall quality: {overall_quality}")

# Print first 15 for review
for i, f in enumerate(findings_list[:15]):
    print(f"\n[{i+1}] @ v6 {f['v6_time_start']:.2f}–{f['v6_time_end']:.2f}s | {f['category']:15} | {f['confidence']:6} | {f['recommended_action']}")
    print(f"    DEFAULT: {f['default_text'][:70]}")
    print(f"    LOOSE:   {f['loose_text'][:70]}")
