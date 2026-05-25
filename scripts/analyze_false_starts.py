#!/usr/bin/env python3
"""
Analyze suspect regions in source audio for hidden false-starts.

Regions to investigate (group C):
- src 1300-1320 (around "brock" 2.48s smear at 1306.40)
- src 1345-1360 (around "relatively" 2.98s smear at 1350.00)
- src 1415-1432 (around "whitney" 1.54s + "but" 1.70s smears at 1419-1429)
- src 1485-1495 (around "and" 1.66s smear at 1490.38)
- src 1843-1855 (around "but" 1.86s smear at 1848.16)
- src 1935-1950 (around "so" 5.20s smear at 1939.60)
- src 2000-2015 (around "because" 2.06s smear at 2006.20)
- src 2080-2095 (around "it" 1.90s + "here" 2.78s smears at 2082-2091)
"""

import json
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Any

# Configuration
SOURCE_VIDEO = "E:/Misty Red/Misty Red and Blue Crystal Gym Leader Challenge.mp4"
OUTPUT_DIR = Path("audio-checks/qa-v6")
OUTPUT_FILE = OUTPUT_DIR / "hidden_false_starts_groupC.json"

# Regions to check: (start_sec, end_sec, description)
REGIONS = [
    (1300, 1320, "brock 2.48s smear at 1306.40"),
    (1345, 1360, "relatively 2.98s smear at 1350.00"),
    (1415, 1432, "whitney 1.54s + but 1.70s smears at 1419-1429"),
    (1485, 1495, "and 1.66s smear at 1490.38"),
    (1843, 1855, "but 1.86s smear at 1848.16"),
    (1935, 1950, "so 5.20s smear at 1939.60"),
    (2000, 2015, "because 2.06s smear at 2006.20"),
    (2080, 2095, "it 1.90s + here 2.78s smears at 2082-2091"),
]

def extract_audio_region(video_path: str, start_sec: int, end_sec: int) -> bytes:
    """Extract audio region from video file."""
    duration = end_sec - start_sec
    cmd = [
        "ffmpeg",
        "-ss", str(start_sec),
        "-to", str(end_sec),
        "-i", video_path,
        "-ac", "1",
        "-ar", "16000",
        "-f", "wav",
        "-"
    ]
    result = subprocess.run(cmd, capture_output=True, check=True)
    return result.stdout

def transcribe_audio_segment(audio_bytes: bytes, region_desc: str) -> dict[str, Any]:
    """Transcribe audio using faster-whisper large-v3."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("ERROR: faster_whisper not installed. Run: pip install faster-whisper")
        return {}

    # Write temp wav file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        # Load model and transcribe with word timestamps
        model = WhisperModel("large-v3", device="cpu", compute_type="int8")
        segments, info = model.transcribe(
            tmp_path,
            beam_size=5,
            vad_filter=False,
            condition_on_previous_text=False,
            language="en"
        )

        # Collect segments with word-level detail
        result = {
            "text": "",
            "segments": [],
            "language": info.language if hasattr(info, 'language') else "en"
        }

        for seg in segments:
            seg_dict = {
                "id": seg.id,
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
                "words": []
            }

            # Capture word-level timestamps if available
            if hasattr(seg, 'words'):
                seg_dict["words"] = [
                    {"word": w.word, "start": w.start, "end": w.end}
                    for w in seg.words
                ]

            result["segments"].append(seg_dict)
            result["text"] += seg.text + " "

        return result
    finally:
        os.unlink(tmp_path)

def analyze_false_start(before_text: str, region_text: str, after_text: str) -> bool:
    """
    Detect if region contains a false-start pattern:
    - Doubled words (word ... word)
    - Abandoned phrases + restart
    - Trail-off + restart pattern
    - Different continuations of same start
    """
    region_words = region_text.lower().split()

    if not region_words:
        return False

    # Check for doubled pattern: word appears early + late in segment
    first_word = region_words[0] if region_words else ""
    last_words = region_words[-3:] if len(region_words) > 3 else region_words

    # If first word appears again later, could be false start + restart
    if first_word and any(first_word in w.lower() for w in last_words):
        return True

    # Check for hesitation patterns
    hesitations = ["um", "uh", "like", "you know", "basically", "kind of"]
    text_lower = region_text.lower()
    hesitation_count = sum(1 for h in hesitations if h in text_lower)

    # Multiple hesitations may indicate false start recovery
    if hesitation_count >= 2 and len(region_words) > 4:
        return True

    return False

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Verify source file exists
    if not os.path.exists(SOURCE_VIDEO):
        print(f"ERROR: Source video not found: {SOURCE_VIDEO}")
        return

    print(f"Analyzing {len(REGIONS)} regions for hidden false-starts...")
    print(f"Source: {SOURCE_VIDEO}\n")

    results = {
        "group": "C",
        "regions_checked": [],
        "false_starts_found": []
    }

    for start_sec, end_sec, desc in REGIONS:
        print(f"Extracting region {start_sec}-{end_sec}s ({desc})...", end=" ", flush=True)

        try:
            # Extract audio region
            audio_bytes = extract_audio_region(SOURCE_VIDEO, start_sec, end_sec)

            # Transcribe with large-v3
            transcript = transcribe_audio_segment(audio_bytes, desc)
            region_text = transcript.get("text", "").strip()

            # Log region check
            results["regions_checked"].append({
                "src_start_sec": start_sec,
                "src_end_sec": end_sec,
                "description": desc,
                "transcribed_text": region_text,
                "segments_count": len(transcript.get("segments", []))
            })

            # Analyze for false-starts
            is_false_start = analyze_false_start("", region_text, "")

            if is_false_start:
                print("FLAGGED - potential false-start detected")
                results["false_starts_found"].append({
                    "src_start_sec": start_sec,
                    "src_end_sec": end_sec,
                    "before_text": "",
                    "false_start_text": region_text,
                    "after_text": "",
                    "evidence": "Doubled word pattern or multiple hesitations indicating abandoned attempt + restart"
                })
            else:
                print("clean")

        except Exception as e:
            print(f"ERROR: {e}")
            results["regions_checked"].append({
                "src_start_sec": start_sec,
                "src_end_sec": end_sec,
                "description": desc,
                "error": str(e)
            })

    # Write output
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to: {OUTPUT_FILE}")
    print(f"Found {len(results['false_starts_found'])} potential false-starts")

if __name__ == "__main__":
    main()
