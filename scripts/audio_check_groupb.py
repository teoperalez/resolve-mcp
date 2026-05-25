#!/usr/bin/env python3
"""
Extract and re-transcribe suspect audio regions for hidden false-starts detection.
Regions identified from source_loose_transcript.json smearing patterns.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

# List of regions to check: (src_start_sec, src_end_sec, desc)
REGIONS = [
    (775, 795, "so 1.74s smear at 784.98"),
    (860, 880, "even 1.64s smear at 869.80"),
    (895, 920, "bugsy 3.20s smear at 905.76"),
    (947, 968, "we're 1.88s smear at 956.18"),
    (973, 993, "with 1.74s smear at 983.04"),
    (1110, 1137, "so 4.84s smear at 1122.44"),
    (1215, 1235, "but 1.62s smear at 1223.92"),
    (1267, 1295, "than/as smears at 1272+1276"),
]

SOURCE_VIDEO = "E:/Misty Red/Misty Red and Blue Crystal Gym Leader Challenge.mp4"
OUTPUT_JSON = "C:/Programming/resolve-mcp/audio-checks/qa-v6/hidden_false_starts_groupB.json"
TEMP_DIR = tempfile.gettempdir()

def extract_audio(start_sec, end_sec, output_wav):
    """Extract audio region using ffmpeg."""
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start_sec),
        "-to", str(end_sec),
        "-i", SOURCE_VIDEO,
        "-ac", "1",
        "-ar", "16000",
        output_wav
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        return True
    except Exception as e:
        print(f"  Extract failed: {e}")
        return False

def transcribe_region(wav_path):
    """Transcribe audio region using faster-whisper large-v3."""
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel('large-v3', device='cpu', compute_type='int8')
        segments, info = model.transcribe(
            wav_path,
            language='en',
            word_timestamps=True,
            beam_size=5,
            vad_filter=False,
            condition_on_previous_text=False,
            no_repeat_ngram_size=0
        )

        result = {
            'text': '',
            'words': []
        }
        for segment in segments:
            result['text'] += segment.text
            if hasattr(segment, 'words'):
                for word_info in segment.words:
                    result['words'].append({
                        'start': word_info.start,
                        'end': word_info.end,
                        'word': word_info.word
                    })

        return result
    except Exception as e:
        print(f"  Transcription failed: {e}")
        return None

def check_for_false_starts(transcript_text, description):
    """Analyze transcript for signs of false-starts or repetitions."""
    text_lower = transcript_text.lower()

    # Patterns indicating false-starts:
    # - doubled words (word word)
    # - abandoned partial words followed by restart
    # - trailing off then restart
    indicators = [
        r'\b(\w+)\s+\1\b',  # doubled words
        r'[aeiou]+\s+(?:uh|um|er|ah)\s+',  # partial word + filler
        r'(?:the|a|and|but|so)\s+(?:the|a|and|but|so)',  # repeated conjunctions
    ]

    import re
    for pattern in indicators:
        matches = re.findall(pattern, text_lower)
        if matches:
            return True, f"Potential false-start: {matches}"

    return False, None

def main():
    print("Audio Check Group B: Investigating Hidden False-Starts")
    print(f"Source: {SOURCE_VIDEO}")
    print()

    false_starts = []
    regions_checked = []

    for src_start, src_end, desc in REGIONS:
        print(f"Region {src_start}-{src_end}s ({desc})")

        wav_path = os.path.join(TEMP_DIR, f"region_{src_start}_{src_end}.wav")

        # Extract
        if not extract_audio(src_start, src_end, wav_path):
            print(f"  Failed to extract")
            continue

        # Transcribe
        result = transcribe_region(wav_path)
        if not result:
            print(f"  Failed to transcribe")
            continue

        transcript = result['text'].strip()
        print(f"  Transcript: {transcript}")

        # Analyze
        has_false_start, evidence = check_for_false_starts(transcript, desc)

        regions_checked.append({
            'region': f"{src_start}-{src_end}",
            'description': desc,
            'transcript': transcript,
            'has_false_start': has_false_start,
            'evidence': evidence
        })

        if has_false_start:
            print(f"  ! {evidence}")
            false_starts.append({
                'src_start_sec': src_start,
                'src_end_sec': src_end,
                'description': desc,
                'transcript': transcript,
                'evidence': evidence
            })

        print()

        # Cleanup
        if os.path.exists(wav_path):
            os.remove(wav_path)

    # Write output
    output = {
        'group': 'B',
        'source_video': SOURCE_VIDEO,
        'regions_checked': regions_checked,
        'false_starts_found': false_starts,
        'total_regions': len(REGIONS),
        'total_false_starts': len(false_starts)
    }

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Results written to: {OUTPUT_JSON}")
    print(f"Found {len(false_starts)} potential false-starts in {len(regions_checked)} regions")

if __name__ == '__main__':
    main()
