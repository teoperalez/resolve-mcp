#!/usr/bin/env python3
"""
Investigate suspect audio regions for hidden false-starts.
Extract regions from source video, re-transcribe with large-v3 settings,
identify any abandoned phrases and restarts.
"""

import json
import subprocess
import sys
import tempfile
import os
from pathlib import Path

# Suspect regions (in seconds from source_loose_transcript)
REGIONS = [
    ("96-105", 96, 105, "generally 2.24s smear at 99.58"),
    ("196-220", 196, 220, "now 12s + misty 5.8s smears"),
    ("333-345", 333, 345, "still 2.08s smear at 336.12"),
    ("345-360", 345, 360, "so 4.12s smear at 347.68"),
    ("730-742", 730, 742, "watching! 2.06s smear at 735.38"),
    ("755-770", 755, 770, "so 3.32s smear at 758.08"),
]

SOURCE_VIDEO = r"E:\Misty Red\Misty Red and Blue Crystal Gym Leader Challenge.mp4"
OUTPUT_DIR = Path(r"C:\Programming\resolve-mcp\audio-checks\qa-v6")

def extract_region(start_sec, end_sec, region_id):
    """Extract audio region from source video using ffmpeg."""
    wav_path = OUTPUT_DIR / f"region_{region_id}.wav"

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-to", str(end_sec),
        "-i", SOURCE_VIDEO,
        "-ac", "1",
        "-ar", "16000",
        str(wav_path)
    ]

    print(f"Extracting {region_id} ({start_sec}s - {end_sec}s)...", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        print(f"  ERROR: {result.stderr}", flush=True)
        return None

    if not wav_path.exists():
        print(f"  ERROR: Output file not created", flush=True)
        return None

    return wav_path


def transcribe_region(wav_path, region_id):
    """Transcribe extracted region with large-v3 settings."""
    print(f"Transcribing {region_id}...", flush=True)

    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(
            "large-v3",
            device="cpu",
            compute_type="int8"
        )

        segments, info = model.transcribe(
            str(wav_path),
            language="en",
            word_timestamps=True,
            beam_size=5,
            vad_filter=False,
            condition_on_previous_text=False,
            no_repeat_ngram_size=0
        )

        # Collect results
        result = {
            "region_id": region_id,
            "text": "",
            "segments": [],
            "words": []
        }

        for seg in segments:
            result["text"] += seg.text
            result["segments"].append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text
            })

            if hasattr(seg, 'words') and seg.words:
                for word in seg.words:
                    result["words"].append({
                        "start": word.start,
                        "end": word.end,
                        "word": word.word,
                        "probability": word.probability
                    })

        print(f"  Result: '{result['text']}'", flush=True)
        return result

    except Exception as e:
        print(f"  ERROR: {e}", flush=True)
        return None


def detect_false_starts(transcript_result, region_info):
    """
    Analyze transcript for patterns indicating false-starts:
    - Doubled words (word repeated with different continuation)
    - Abandoned phrases followed by restart
    - Trail-off + restart pattern
    """
    text = transcript_result["text"].strip()
    words = transcript_result["words"]

    if not text:
        return None

    # Look for patterns:
    # 1. Doubled words with different continuations
    # 2. Repeated word sequences (e.g., "I want I want")
    # 3. Filler + restart (e.g., "uh the...", "like uh the...")

    # Split into word tokens
    words_only = text.split()

    # Check for immediate repetitions (word repeated within 1-2 words)
    for i in range(len(words_only) - 1):
        if words_only[i].lower().strip('.,!?') == words_only[i + 1].lower().strip('.,!?'):
            # Found a doubled word - this is suspicious
            if i > 0 and i + 2 < len(words_only):
                return {
                    "pattern": "doubled_word",
                    "position": i,
                    "word": words_only[i],
                    "context": " ".join(words_only[max(0, i-2):min(len(words_only), i+4)])
                }

    # Check for common false-start fillers followed by restart
    fillers = ["uh", "um", "like", "you know", "i mean", "basically"]
    for filler in fillers:
        if filler in text.lower():
            # Check if there's a restart pattern after filler
            pass

    return None


def main():
    print("=== Investigating Hidden False-Starts ===\n")

    # Check if ffmpeg is available
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
    except FileNotFoundError:
        print("ERROR: ffmpeg not found. Install with: winget install Gyan.FFmpeg", file=sys.stderr)
        sys.exit(1)

    # Check if faster-whisper is available
    try:
        import faster_whisper
    except ImportError:
        print("ERROR: faster-whisper not found. Install with: pip install faster-whisper", file=sys.stderr)
        sys.exit(1)

    results = {
        "group": "A",
        "regions_checked": [],
        "false_starts_found": [],
        "region_transcripts": []
    }

    # Process each region
    for region_id, start_sec, end_sec, note in REGIONS:
        print(f"\n--- Region {region_id} ({note}) ---")
        results["regions_checked"].append(region_id)

        # Extract
        wav_path = extract_region(start_sec, end_sec, region_id)
        if not wav_path:
            continue

        # Transcribe
        transcript = transcribe_region(wav_path, region_id)
        if not transcript:
            continue

        results["region_transcripts"].append({
            "region_id": region_id,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "transcript": transcript["text"],
            "word_count": len(transcript["words"])
        })

        # Analyze for false-starts (manual inspection for now)
        # Print words with timing for manual review
        print(f"  Full text: {transcript['text']}")
        if transcript["words"]:
            print(f"  Word-level breakdown:")
            for w in transcript["words"][:15]:  # Show first 15 words
                duration = w["end"] - w["start"]
                print(f"    {w['start']:.2f}-{w['end']:.2f} ({duration:.2f}s): '{w['word']}'")

    # Save results
    output_file = OUTPUT_DIR / "hidden_false_starts_groupA.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n=== Results saved to {output_file} ===")
    print(f"Regions checked: {len(results['regions_checked'])}")
    print(f"Transcripts collected: {len(results['region_transcripts'])}")


if __name__ == "__main__":
    main()
