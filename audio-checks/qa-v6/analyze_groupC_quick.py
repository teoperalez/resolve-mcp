#!/usr/bin/env python3
"""
Quick analysis of Group C regions using existing loose transcript.
Identifies potential false-starts by finding long-duration words (smears).
"""

import json
from pathlib import Path

OUTPUT_DIR = Path(r"C:\Programming\resolve-mcp\audio-checks\qa-v6")

# Group C regions with their suspected long-duration word locations
REGIONS = [
    {
        "region_id": "1300-1320",
        "src_start": 1300,
        "src_end": 1320,
        "note": "brock 2.48s smear at 1306.40",
        "suspect_word_time": 1306.40,
        "suspect_duration": 2.48
    },
    {
        "region_id": "1345-1360",
        "src_start": 1345,
        "src_end": 1360,
        "note": "relatively 2.98s smear at 1350.00",
        "suspect_word_time": 1350.00,
        "suspect_duration": 2.98
    },
    {
        "region_id": "1415-1432",
        "src_start": 1415,
        "src_end": 1432,
        "note": "whitney 1.54s + but 1.70s smears at 1419-1429",
        "suspect_word_time": 1419.0,
        "suspect_duration": 1.54
    },
    {
        "region_id": "1485-1495",
        "src_start": 1485,
        "src_end": 1495,
        "note": "and 1.66s smear at 1490.38",
        "suspect_word_time": 1490.38,
        "suspect_duration": 1.66
    },
    {
        "region_id": "1843-1855",
        "src_start": 1843,
        "src_end": 1855,
        "note": "but 1.86s smear at 1848.16",
        "suspect_word_time": 1848.16,
        "suspect_duration": 1.86
    },
    {
        "region_id": "1935-1950",
        "src_start": 1935,
        "src_end": 1950,
        "note": "so 5.20s smear at 1939.60",
        "suspect_word_time": 1939.60,
        "suspect_duration": 5.20
    },
    {
        "region_id": "2000-2015",
        "src_start": 2000,
        "src_end": 2015,
        "note": "because 2.06s smear at 2006.20",
        "suspect_word_time": 2006.20,
        "suspect_duration": 2.06
    },
    {
        "region_id": "2080-2095",
        "src_start": 2080,
        "src_end": 2095,
        "note": "it 1.90s + here 2.78s smears at 2082-2091",
        "suspect_word_time": 2082.0,
        "suspect_duration": 1.90
    },
]

def load_loose_transcript():
    """Load the loose transcript."""
    transcript_file = OUTPUT_DIR / "loose-transcript.json"
    with open(transcript_file) as f:
        data = json.load(f)
    return data

def find_words_in_region(transcript, start_sec, end_sec):
    """Find all words in a time region."""
    words_in_region = []
    for seg in transcript["segments"]:
        for word in seg.get("words", []):
            if start_sec <= word["start"] <= end_sec or start_sec <= word["end"] <= end_sec:
                word["duration"] = word["end"] - word["start"]
                words_in_region.append(word)
    return words_in_region

def analyze_region(transcript, region):
    """Analyze a region for false-starts."""
    start_sec = region["src_start"]
    end_sec = region["src_end"]
    suspect_time = region["suspect_word_time"]
    suspect_duration = region["suspect_duration"]

    words_in_region = find_words_in_region(transcript, start_sec, end_sec)

    if not words_in_region:
        return None

    # Find the suspected long-duration word
    suspect_word = None
    for word in words_in_region:
        if abs(word["start"] - suspect_time) < 0.5:  # Match within 0.5s
            suspect_word = word
            break

    if not suspect_word:
        # If exact match not found, look for any anomalously long word
        for word in words_in_region:
            if word["duration"] >= 1.5:
                suspect_word = word
                break

    if suspect_word:
        # Get context
        seg_idx = None
        for seg_idx, seg in enumerate(transcript["segments"]):
            if any(w["start"] == suspect_word["start"] for w in seg.get("words", [])):
                break

        if seg_idx is not None:
            seg = transcript["segments"][seg_idx]
            context = seg["text"]
        else:
            context = suspect_word.get("word", "")

        return {
            "src_start_sec": start_sec,
            "src_end_sec": end_sec,
            "region_id": region["region_id"],
            "description": region["note"],
            "suspect_word": suspect_word.get("word", "").strip(),
            "duration_sec": round(suspect_word["duration"], 2),
            "word_timestamp_sec": round(suspect_word["start"], 2),
            "context": context.strip(),
            "evidence": f"Long-duration word ({suspect_word['duration']:.2f}s) - typical smear hiding false-start or abandoned phrase"
        }

    return None

def main():
    print("=== Analyzing Group C Regions for Hidden False-Starts ===\n")

    # Load transcript
    print("Loading loose transcript...", flush=True)
    transcript = load_loose_transcript()
    print(f"Loaded transcript with {len(transcript['segments'])} segments\n", flush=True)

    results = {
        "group": "C",
        "regions_checked": [],
        "false_starts_found": []
    }

    # Analyze each region
    for region in REGIONS:
        region_id = region["region_id"]
        print(f"Region {region_id} ({region['note']})", flush=True)
        results["regions_checked"].append(region_id)

        analysis = analyze_region(transcript, region)
        if analysis:
            print(f"  FLAGGED: {analysis['suspect_word']} ({analysis['duration_sec']}s)", flush=True)
            print(f"  Context: {analysis['context'][:80]}...", flush=True)
            results["false_starts_found"].append(analysis)
        else:
            print(f"  No match in transcript", flush=True)

    # Save results
    output_file = OUTPUT_DIR / "hidden_false_starts_groupC.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n=== Results saved to {output_file} ===")
    print(f"Regions checked: {len(results['regions_checked'])}")
    print(f"False-starts found: {len(results['false_starts_found'])}")

if __name__ == "__main__":
    main()
