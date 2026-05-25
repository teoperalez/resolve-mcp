---
name: Default Whisper hides false-starts in source transcripts — cut analysis must use no-repeat baseline
description: faster-whisper with default settings (condition_on_previous_text=True, no_repeat_ngram_size > 0) silently merges false-starts into clean segments. Cut analysis based on this transcript misses or mis-bounds cuts. Always re-transcribe the SOURCE with no-repeat-suppression before doing cut analysis.
type: reference
project: resolve-mcp
originSessionId: d67a4cf0-ef49-42f3-87a4-44f400894785
---
## The bug

Misty Red v6 caught a regression where the rendered audio plays *"Now of course Misty's come... Now of course Misty has to go up against..."* — a clean false-start with restart. The cut analyzer (driven by `transcripts/4.json`, the default Whisper transcript of the source) saw only:

```
[391.04-400.24] " Now, of course, Misty has to go up against the second gym leader of this generation"
    391.04-391.44  ' Now,'
    391.50-391.62  ' of'
    391.62-391.84  ' course,'
    392.04-396.88  ' Misty'   ← suspiciously 4.84-second word
    396.88-397.10  ' has'
    ...
```

That `' Misty'` token at 392.04-396.88 is a 4.84-second word — Whisper's tell that something is wrong. Re-transcribing the same source with `condition_on_previous_text=False, no_repeat_ngram_size=0, beam_size=5` reveals the truth:

```
" could be in this generation now of course misty's come now of course misty has to go up against the"
    1.48-2.44   ' now'        ← false-start "now"
    2.44-3.50   ' of'
    3.50-3.78   ' course'
    3.78-4.54   " misty's"    ← false-start "misty's"
    4.54-6.58   ' come'       ← false-start tails off (2.04-second drag word)
    6.58-7.86   ' now'        ← clean restart "now"
    7.86-8.06   ' of'
    8.06-8.30   ' course'
    8.30-8.86   ' misty'      ← clean restart "misty has to..."
    ...
```

Default Whisper merged the false start into one giant `' Misty'` word. The 2.04-second `' come'` and the doubled `' now of course'` simply don't appear in the default transcript.

## Implications for cut analysis

The cut analyzer (`scripts/mark_cut_candidates.py`) reads the default-Whisper transcript. **Every false-start and stuttery section in the source is invisible to it.** A cut placed at the boundaries shown by default Whisper will be wrong by hundreds of milliseconds — extending past one part of the false start, leaving the rest. Result: phrases like *"now of course now of course misty has to..."* survive into the final cut.

## Procedure for accurate cut analysis

Before running the cut analyzer, generate a `source_loose_transcript.json`:

```python
from faster_whisper import WhisperModel
m = WhisperModel('large-v3', device='cpu', compute_type='int8')
segs, _ = m.transcribe(SOURCE_WAV_PATH,
                        language='en', word_timestamps=True, beam_size=5,
                        vad_filter=False,
                        condition_on_previous_text=False,
                        no_repeat_ngram_size=0)
```

Then either:

1. **Replace `transcripts/4.json` with the loose transcript** for cut analyzer input. The cut analyzer's logic doesn't change; the input is just better.

2. **OR run the cut analyzer twice** — once on default, once on loose — and merge the cut lists, preferring loose-derived boundaries when they conflict.

Approach (1) is cleaner. The trade-off: loose transcript has more "noise" segments because it doesn't suppress repetitions. The cut analyzer should treat back-to-back identical phrases as `repetition` cuts (it already does).

## Detecting false-starts in the loose transcript

A false-start signature in word-level data:
- A word with duration > 1.5s (Whisper hallucinating extension because the speaker drew out a word or trailed off — `come` 2.04s in the example)
- A repeated short n-gram within a 5-second window (`now of course` appearing twice within 5s)
- A very long word followed by silence then a repeat of an earlier short word

Add these checks to the cut analyzer's `attach_transcript_to_clips` step.

## Time cost

Re-transcribing a 47-minute source video with large-v3 on CPU (int8) takes ~25-40 min. This is acceptable as a one-time cost per project. CUDA float16 would be ~3 min if cublas/cudnn DLLs were installed.

## Confirmed regression date

2026-05-15 (Misty Red v6 review). User flagged that v6 contained the duplicate "now of course now of course" that default Whisper hid. Source re-transcription confirmed both copies are in the source audio. Cut at 392.04-394.82 was extended to 389.48-394.58 to fully cover the false-start.
