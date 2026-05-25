#!/usr/bin/env python3
"""
Analyze Group C suspect regions for hidden false-starts.
Extract + re-transcribe with large-v3 to find word smears hiding false-starts.

Regions (from cut analysis):
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
import sys
import tempfile
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

# Suspect regions (id, start_sec, end_sec, description)
REGIONS = [
    ("1300-1320", 1300, 1320, "brock 2.48s smear at 1306.40"),
    ("1345-1360", 1345, 1360, "relatively 2.98s smear at 1350.00"),
    ("1415-1432", 1415, 1432, "whitney 1.54s + but 1.70s smears at 1419-1429"),
    ("1485-1495", 1485, 1495, "and 1.66s smear at 1490.38"),
    ("1843-1855", 1843, 1855, "but 1.86s smear at 1848.16"),
    ("1935-1950", 1935, 1950, "so 5.20s smear at 1939.60"),
    ("2000-2015", 2000, 2015, "because 2.06s smear at 2006.20"),
    ("2080-2095", 2080, 2095, "it 1.90s + here 2.78s smears at 2082-2091"),
]

SOURCE_VIDEO = r"E:\Misty Red\Misty Red and Blue Crystal Gym Leader Challenge.mp4"
OUTPUT_DIR = Path(r"C:\Programming\resolve-mcp\audio-checks\qa-v6")

def extract_region(start_sec: int, end_sec: int, region_id: str) -> Optional[Path]:
    """Extract audio region from source video using ffmpeg."""
    wav_path = OUTPUT_DIR / f"region_{region_id}.wav"

    # Skip if already extracted
    if wav_path.exists():
        print(f"  Using cached {wav_path.name} ({wav_path.stat().st_size / 1024:.0f}K)", flush=True)
        return wav_path

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-to", str(end_sec),
        "-i", SOURCE_VIDEO,
        "-ac", "1",
        "-ar", "16000",
        str(wav_path)
    ]

    print(f"  Extracting {region_id} ({start_sec}s - {end_sec}s)...", flush=True)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"    ERROR: {result.stderr[:200]}", flush=True)
            return None
        if not wav_path.exists():
            print(f"    ERROR: Output file not created", flush=True)
            return None
        print(f"    Created {wav_path.name} ({wav_path.stat().st_size / 1024:.0f}K)", flush=True)
        return wav_path
    except Exception as e:
        print(f"    ERROR: {e}", flush=True)
        return None

def transcribe_region(wav_path: Path, region_id: str) -> Optional[Dict[str, Any]]:
    """Transcribe region with large-v3."""
    print(f"  Transcribing {region_id}...", flush=True)

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
                    word_duration = word.end - word.start
                    result["words"].append({
                        "start": word.start,
                        "end": word.end,
                        "duration": word_duration,
                        "word": word.word,
                        "probability": word.probability
                    })

        print(f"    Text: '{result['text'].strip()}'", flush=True)
        print(f"    Words: {len(result['words'])}, Segments: {len(result['segments'])}", flush=True)
        return result

    except Exception as e:
        print(f"    ERROR: {e}", flush=True)
        return None

def find_long_duration_words(transcript: Dict[str, Any], threshold_sec: float = 1.5) -> List[Dict[str, Any]]:
    """Find words with unusual durations (smears)."""
    candidates = []
    for word_info in transcript["words"]:
        if word_info["duration"] >= threshold_sec:
            candidates.append(word_info)
    return candidates

def analyze_for_false_start(transcript: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Detect false-start patterns:
    - Long-duration words (potential smear hiding false-start)
    - Doubled/repeated words
    - Abandoned phrase + restart
    """
    text = transcript["text"].strip()
    words = transcript["words"]

    if not text or not words:
        return None

    # Find anomalously long words (these smears often hide false-starts)
    long_words = find_long_duration_words(transcript, threshold_sec=1.5)

    if long_words:
        # This is the primary indicator: a word that takes too long
        # Usually indicates the speaker abandoned an attempt and restarted
        first_long = long_words[0]
        return {
            "pattern_type": "long_duration_word",
            "word": first_long["word"],
            "duration_sec": round(first_long["duration"], 2),
            "timestamp_sec": round(first_long["start"], 2),
            "full_text": text,
            "confidence": "high" if first_long["duration"] >= 2.0 else "medium",
            "interpretation": f"Word '{first_long['word'].strip()}' takes {first_long['duration']:.2f}s - likely smear hiding false-start"
        }

    # Check for doubled words (speaker repeated themselves)
    text_words = text.lower().split()
    for i in range(len(text_words) - 1):
        w1 = text_words[i].strip('.,!?')
        w2 = text_words[i + 1].strip('.,!?')
        if w1 == w2 and len(w1) > 2:  # Avoid matching short words
            return {
                "pattern_type": "doubled_word",
                "word": w1,
                "position": i,
                "full_text": text,
                "confidence": "medium",
                "interpretation": f"Word '{w1}' repeated - possible false-start correction"
            }

    return None

def main():
    print("=== Analyzing Group C Suspect Regions for Hidden False-Starts ===\n")

    # Verify source exists
    if not os.path.exists(SOURCE_VIDEO):
        print(f"ERROR: Source video not found: {SOURCE_VIDEO}", file=sys.stderr)
        sys.exit(1)

    # Check ffmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
    except FileNotFoundError:
        print("ERROR: ffmpeg not found. Install with: winget install Gyan.FFmpeg", file=sys.stderr)
        sys.exit(1)

    # Check faster-whisper
    try:
        import faster_whisper
    except ImportError:
        print("ERROR: faster-whisper not installed. Run: pip install faster-whisper", file=sys.stderr)
        sys.exit(1)

    results = {
        "group": "C",
        "regions_checked": [],
        "false_starts_found": []
    }

    # Process each region
    for region_id, start_sec, end_sec, note in REGIONS:
        print(f"\nRegion {region_id} ({note})")
        results["regions_checked"].append(region_id)

        # Extract
        wav_path = extract_region(start_sec, end_sec, region_id)
        if not wav_path:
            continue

        # Transcribe
        transcript = transcribe_region(wav_path, region_id)
        if not transcript:
            continue

        # Analyze
        analysis = analyze_for_false_start(transcript)
        if analysis:
            print(f"  FLAGGED: {analysis['interpretation']}", flush=True)
            results["false_starts_found"].append({
                "src_start_sec": start_sec,
                "src_end_sec": end_sec,
                "region_id": region_id,
                "description": note,
                **analysis
            })
        else:
            print(f"  No obvious false-start pattern", flush=True)

    # Save results
    output_file = OUTPUT_DIR / "hidden_false_starts_groupC.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n=== Results saved to {output_file} ===")
    print(f"Regions checked: {len(results['regions_checked'])}")
    print(f"False-starts found: {len(results['false_starts_found'])}")

if __name__ == "__main__":
    main()
