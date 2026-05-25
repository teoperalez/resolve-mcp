---
name: Audio-verify borderline cuts (large-v3 + waveform energy)
description: Methodology for resolving borderline cut decisions in the dialogue review by re-transcribing the disputed segment with large-v3 word-timestamps + analyzing waveform silence boundaries
type: reference
project: resolve-mcp
originSessionId: d67a4cf0-ef49-42f3-87a4-44f400894785
---
When the cut analyzer leaves a moment as borderline ("could be emphatic restatement OR could be false start") or when the user disputes a transcription artifact ("this should say X not Y"), don't guess from the transcript alone. The base Whisper transcript that drove the original analysis is `turbo` quality and has a known failure mode: it merges duplicates ("barriers, so these berries" → "berries"), drops aborted partials ("eight" → "h"), and won't help you decide intent. Re-transcribe the disputed window with `large-v3` and analyze the waveform.

## Procedure

1. **Locate the disputed window in the v4 review WAV.** Use the timecode the user gave (e.g., `[10:08-10:13]`) and pad ±3-10s of context on each side.

2. **Extract via ffmpeg:**
   ```bash
   ffmpeg -y -ss 00:10:05 -to 00:10:18 -i "<v4-wav>" -ac 1 -ar 16000 check_clip.wav
   ```
   16 kHz mono is plenty for Whisper.

3. **Re-transcribe with large-v3 + word timestamps:**
   ```python
   from faster_whisper import WhisperModel
   model = WhisperModel('large-v3', device='cpu', compute_type='int8')   # CUDA-cublas DLLs missing on this venv → CPU fallback works fine for short clips
   segments, info = model.transcribe(path, language='en',
                                     word_timestamps=True, beam_size=5,
                                     vad_filter=False)
   for seg in segments:
       for w in seg.words:
           print(f'{w.start:6.2f}-{w.end:6.2f}  p={w.probability:.2f}  {w.word!r}')
   ```
   `vad_filter=False` is important — VAD will eat short partials and silences, which are exactly the diagnostic signals.

4. **Analyze waveform energy in 50ms bins** to find silence boundaries:
   ```python
   import numpy as np, wave
   with wave.open(path, 'rb') as wf:
       sr = wf.getframerate()
       samples = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
   bin_size = int(sr * 0.05)
   for i in range(0, len(samples) - bin_size, bin_size):
       chunk = samples[i:i+bin_size]
       rms = float(np.sqrt(np.mean(chunk * chunk)))
       # silence threshold ≈ 0.01; runs ≥100ms = real word boundaries
   ```

5. **Decision rule (false start vs emphatic restatement):**
   - **False start** = first attempt is INCOMPLETE (trails off, missing a key word, or has an aborted partial Whisper renders as a single character like ' h' or ' th'). There's typically a measurable silence (200-400ms) at the correction point. **Cut it.**
   - **Emphatic restatement** = the FULL repeated unit is preserved, no silence, intentional rhythm (per Teo style doc §9.4: "we won, we actually won"). **Keep it.**
   - **Slip-of-tongue self-correction** (e.g., "barriers" → "berries") = the wrong word with high probability followed by a pause and the right word. Always cut the wrong word.

6. **Map v4-time back to source-time** via `transcripts/4.json` (the original word-timestamped Whisper) — search for the disputed phrase and read the exact word boundaries. Use those for the cut entry, not the v4 timestamps.

## Why this works

- **large-v3 vs turbo:** large-v3 keeps low-probability tokens that turbo drops/merges. The 0.43-probability ' berries' that turbo merged into the previous 'barriers,' shows up as a separate word in large-v3.
- **word-timestamps + probability:** a lone 0.36s 'h' at high probability between two clean 'i've' tokens is a smoking-gun aborted-word signature.
- **waveform silence:** a 200-400ms gap at the correction point is the speaker's "wait, that's wrong" moment — invisible in any transcript, definitive in waveform energy.

## When to use it

- User flags a moment as "borderline" or "should I cut this?"
- User claims the transcript is wrong about a specific word
- The cut analyzer left something with `confidence: medium` and you can't justify it from the transcript alone
- Before disputing the user's audit findings — verify before pushing back

Two minutes per disputed clip beats arguing from a known-imperfect transcript.

## Validated example (2026-05-15, Misty Red v4 review)

- **"barriers/berries"** at v4 02:32 → large-v3 cleanly transcribed both words (both p=0.99) with 300ms silence between → confirmed slip-of-tongue self-correction → cut added at source 275.49-276.71.
- **"I've gotten it down to eight" duplicate** at v4 10:08-10:13 → large-v3 showed first attempt aborted with lone 0.36s 'h' between two 'i've' tokens, second attempt is complete ("8 HP remaining") → confirmed false start, NOT emphatic restatement → cut added at source 963.34-965.22.
