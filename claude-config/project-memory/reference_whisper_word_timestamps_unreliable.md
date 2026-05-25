---
name: Whisper word timestamps are unreliable for cut-boundary verification
description: faster-whisper word-level timestamps can be off by 100-400ms, especially around silence boundaries. Always confirm with waveform energy onset/offset before making decisions about cut placement or splice quality.
type: reference
project: resolve-mcp
originSessionId: d67a4cf0-ef49-42f3-87a4-44f400894785
---
## The trap

Faster-whisper exposes per-word timestamps via `word_timestamps=True`. They look authoritative — they're floats with 2 decimal places, they sit inside well-formed segments, they line up with the spoken words to a casual reader. They are NOT precise enough to drive cut-boundary decisions.

Concrete error case (Misty Red 2026-05-15): Whisper said the word `"And"` started at source 535.84. Actual sound onset (verified via 25ms-bin RMS energy) was 536.175 — **a 335ms error**. Based on the bad Whisper timestamp I claimed clip 95 (which starts at src 536.08) was cutting mid-word. It wasn't — the clip starts inside a 550ms silence gap, exactly where auto-editor was supposed to cut. The audio is clean.

## The lesson

**Auto-editor's invariant is real.** It only cuts at silence below its loudness threshold. If a clip boundary exists at source X, then at time X the source audio IS quiet. If your Whisper word timestamps tell you otherwise, **the timestamps are wrong, not the cut.**

## How to actually verify a cut splice

Extract the source audio around the splice and check waveform energy in 25ms bins:

```python
import numpy as np, wave, subprocess
subprocess.run(['ffmpeg', '-y', '-ss', f'{splice_sec - 1.0}',
                '-to', f'{splice_sec + 1.0}',
                '-i', str(source_video),
                '-ac', '1', '-ar', '16000', 'tmp.wav'], check=True)
with wave.open('tmp.wav', 'rb') as wf:
    sr = wf.getframerate()
    samples = np.frombuffer(wf.readframes(wf.getnframes()),
                             dtype=np.int16).astype(np.float32) / 32768.0
bin_size = int(sr * 0.025)
for i in range(0, len(samples) - bin_size, bin_size):
    chunk = samples[i:i+bin_size]
    rms = float(np.sqrt(np.mean(chunk * chunk)))
    print(f'{(splice_sec - 1.0) + i / sr:7.3f}  {rms:.4f}')
```

A clean splice will show RMS dropping to <0.005 well before the cut point and rising sharply (>0.05) some milliseconds after. If RMS is high right at the cut point, THEN you have a mid-word cut — and you should investigate the upstream tool that placed the cut.

## Whisper hallucinates words at splice points

Even when the splice is clean, Whisper sometimes inserts a phantom word at the boundary because the brief silence + sudden sound onset confuses its decoder. Confirmed Misty Red v6 case: Whisper inserted `"honest"` (probability 0.59) at the silence + "And" onset, transcribing the v6 audio as `"...very easily honest and then Rod..."` even though the actual audio was `"...very easily. [550ms silence] And then Rod..."`.

**Implication for QA:** the v6 dialogue review text contains phantom words wherever a clip splice happens to confuse Whisper. Pre-processing the deliverable transcript should:

1. List every clip boundary timestamp from the live timeline
2. Re-transcribe ±1s around each boundary with `condition_on_previous_text=False, no_repeat_ngram_size=0, beam_size=10`
3. Compare against the full-track transcript — words that appear at boundaries with probability <0.7 and are dropped by the targeted re-transcription are likely hallucinations
4. Flag them for review (or remove from the deliverable text)

Also: word-level segment text from a full-track transcribe is NOT trustworthy for word counting, lyric matching, or any kind of downstream textual QA. The only ground truth is the waveform itself.
