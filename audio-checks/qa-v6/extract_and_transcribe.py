#!/usr/bin/env python3
"""
Extract and transcribe suspect audio regions.
Simpler direct version.
"""

import json
import subprocess
import os
from pathlib import Path
from faster_whisper import WhisperModel

# Regions to investigate
REGIONS = [
    ("96-105", 96, 105),
    ("196-220", 196, 220),
    ("333-345", 333, 345),
    ("345-360", 345, 360),
    ("730-742", 730, 742),
    ("755-770", 755, 770),
]

SOURCE_VIDEO = r"E:\Misty Red\Misty Red and Blue Crystal Gym Leader Challenge.mp4"
OUTPUT_DIR = Path(r"C:\Programming\resolve-mcp\audio-checks\qa-v6")

print("=" * 60)
print("INVESTIGATING HIDDEN FALSE-STARTS - GROUP A")
print("=" * 60)

# Initialize model once
print("\nLoading Whisper model (large-v3)...")
model = WhisperModel("large-v3", device="cpu", compute_type="int8")

results = {
    "group": "A",
    "regions_checked": [r[0] for r in REGIONS],
    "region_transcripts": [],
    "false_starts_found": []
}

for region_id, start_sec, end_sec in REGIONS:
    print(f"\n--- Region {region_id} ({start_sec}s - {end_sec}s) ---")

    wav_path = OUTPUT_DIR / f"region_{region_id}.wav"

    # Extract region
    print(f"  Extracting...")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(start_sec),
        "-to", str(end_sec),
        "-i", SOURCE_VIDEO,
        "-ac", "1",
        "-ar", "16000",
        str(wav_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR extracting: {result.stderr}")
        continue

    if not wav_path.exists():
        print(f"  ERROR: WAV file not created")
        continue

    file_size = wav_path.stat().st_size / 1024
    print(f"  Extracted {file_size:.1f} KB")

    # Transcribe
    print(f"  Transcribing with large-v3...")
    try:
        segments, info = model.transcribe(
            str(wav_path),
            language="en",
            word_timestamps=True,
            beam_size=5,
            vad_filter=False,
            condition_on_previous_text=False,
            no_repeat_ngram_size=0
        )

        # Build output
        text = ""
        words = []
        segs = []

        for seg in segments:
            text += seg.text
            segs.append({
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": seg.text
            })

            if hasattr(seg, 'words') and seg.words:
                for word in seg.words:
                    words.append({
                        "start": round(word.start, 2),
                        "end": round(word.end, 2),
                        "word": word.word,
                        "probability": round(word.probability, 3)
                    })

        print(f"  Text: '{text.strip()}'")
        print(f"  Word count: {len(words)}")

        if words:
            print(f"  First 10 words:")
            for w in words[:10]:
                dur = w["end"] - w["start"]
                print(f"    {w['start']:.2f}-{w['end']:.2f} ({dur:.2f}s): '{w['word']}' ({w['probability']:.1%})")

        results["region_transcripts"].append({
            "region_id": region_id,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "transcript": text.strip(),
            "word_count": len(words),
            "segments": segs,
            "words": words
        })

        # Clean up WAV
        wav_path.unlink()

    except Exception as e:
        print(f"  ERROR transcribing: {e}")
        continue

print("\n" + "=" * 60)
print("SAVING RESULTS")
print("=" * 60)

output_file = OUTPUT_DIR / "hidden_false_starts_groupA.json"
with open(output_file, "w") as f:
    json.dump(results, f, indent=2)

print(f"\nSaved to: {output_file}")
print(f"Regions processed: {len(results['region_transcripts'])}/{len(REGIONS)}")
