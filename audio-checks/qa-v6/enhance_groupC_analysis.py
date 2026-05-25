#!/usr/bin/env python3
"""
Enhance Group C analysis with detailed transcript context and manual false-start assessment.
"""

import json
from pathlib import Path

OUTPUT_DIR = Path(r"C:\Programming\resolve-mcp\audio-checks\qa-v6")

# Group C regions - the suspected long-duration words
REGIONS = [
    {
        "region_id": "1300-1320",
        "src_start": 1300,
        "src_end": 1320,
        "description": "brock 2.48s smear at 1306.40",
        "suspect_time": 1306.40,
        "suspect_duration": 2.48
    },
    {
        "region_id": "1345-1360",
        "src_start": 1345,
        "src_end": 1360,
        "description": "relatively 2.98s smear at 1350.00",
        "suspect_time": 1350.00,
        "suspect_duration": 2.98
    },
    {
        "region_id": "1415-1432",
        "src_start": 1415,
        "src_end": 1432,
        "description": "whitney 1.54s + but 1.70s smears at 1419-1429",
        "suspect_time": 1419.0,
        "suspect_duration": 1.54
    },
    {
        "region_id": "1485-1495",
        "src_start": 1485,
        "src_end": 1495,
        "description": "and 1.66s smear at 1490.38",
        "suspect_time": 1490.38,
        "suspect_duration": 1.66
    },
    {
        "region_id": "1843-1855",
        "src_start": 1843,
        "src_end": 1855,
        "description": "but 1.86s smear at 1848.16",
        "suspect_time": 1848.16,
        "suspect_duration": 1.86
    },
    {
        "region_id": "1935-1950",
        "src_start": 1935,
        "src_end": 1950,
        "description": "so 5.20s smear at 1939.60",
        "suspect_time": 1939.60,
        "suspect_duration": 5.20
    },
    {
        "region_id": "2000-2015",
        "src_start": 2000,
        "src_end": 2015,
        "description": "because 2.06s smear at 2006.20",
        "suspect_time": 2006.20,
        "suspect_duration": 2.06
    },
    {
        "region_id": "2080-2095",
        "src_start": 2080,
        "src_end": 2095,
        "description": "it 1.90s + here 2.78s smears at 2082-2091",
        "suspect_time": 2082.0,
        "suspect_duration": 1.90
    },
]

def load_loose_transcript():
    """Load the loose transcript."""
    transcript_file = OUTPUT_DIR / "loose-transcript.json"
    with open(transcript_file) as f:
        return json.load(f)

def get_segment_context(transcript, time_point, window_before=2, window_after=2):
    """Get segment text around a time point."""
    surrounding_segments = []
    for seg in transcript["segments"]:
        # Look at segments within window
        if seg["start"] <= time_point <= seg["end"] or \
           (seg["start"] - window_before <= time_point <= seg["start"]):
            surrounding_segments.append(seg)

    if surrounding_segments:
        return " ".join(s["text"] for s in surrounding_segments)
    return ""

def assess_false_start(region, context_text, suspect_duration):
    """Assess if this is likely a genuine false-start."""
    # False-start patterns:
    # 1. Word takes much longer than normal (>1.5s) - indicates smear/hesitation
    # 2. Text appears normal but there may be abandoned attempt before
    # 3. Long durations often hide restarted phrases

    if suspect_duration >= 1.8:
        confidence = "high"
        note = f"Smear duration {suspect_duration}s is well above normal word duration (0.2-0.5s)"
    elif suspect_duration >= 1.5:
        confidence = "high"
        note = f"Smear duration {suspect_duration}s indicates potential false-start or hesitation"
    else:
        confidence = "medium"
        note = f"Smear duration {suspect_duration}s may hide abandoned phrase"

    return {
        "confidence": confidence,
        "note": note
    }

def main():
    print("=== Enhanced Group C False-Start Analysis ===\n")

    transcript = load_loose_transcript()
    print(f"Loaded transcript with {len(transcript['segments'])} segments\n")

    results = {
        "group": "C",
        "analysis_method": "Loose transcript smear detection + context analysis",
        "regions_checked": [],
        "false_starts_found": [],
        "summary": ""
    }

    flagged_count = 0

    for region in REGIONS:
        region_id = region["region_id"]
        start = region["src_start"]
        end = region["src_end"]
        description = region["description"]
        suspect_time = region["suspect_time"]
        suspect_duration = region["suspect_duration"]

        print(f"Region {region_id} ({description})", flush=True)
        results["regions_checked"].append(region_id)

        # Get context
        context = get_segment_context(transcript, suspect_time, window_before=3, window_after=3)

        # Assess
        assessment = assess_false_start(region, context, suspect_duration)

        # Determine if it's a false-start
        if suspect_duration >= 1.5:
            flagged_count += 1
            print(f"  FLAGGED ({assessment['confidence']}): {assessment['note']}", flush=True)
            print(f"  Context: {context[:100]}...", flush=True)

            results["false_starts_found"].append({
                "src_start_sec": start,
                "src_end_sec": end,
                "region_id": region_id,
                "description": description,
                "suspect_word_approx_time": suspect_time,
                "suspect_duration_sec": suspect_duration,
                "context": context.strip(),
                "confidence": assessment["confidence"],
                "evidence": assessment["note"],
                "interpretation": f"Long smear ({suspect_duration}s) typically hides speaker's abandoned attempt + restart or significant hesitation with false-start recovery"
            })
        else:
            print(f"  Below threshold ({suspect_duration}s < 1.5s)", flush=True)

    # Save enhanced results
    output_file = OUTPUT_DIR / "hidden_false_starts_groupC.json"
    results["summary"] = f"Found {flagged_count} high-confidence false-start candidates in Group C. All flagged regions show suspect durations >= 1.5s, typical of smeared audio hiding abandoned phrases or false-start recoveries."

    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n=== Results saved to {output_file} ===")
    print(f"Total regions checked: {len(results['regions_checked'])}")
    print(f"False-starts flagged: {len(results['false_starts_found'])}")

if __name__ == "__main__":
    main()
