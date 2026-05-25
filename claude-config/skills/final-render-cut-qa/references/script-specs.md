# Script API specs

Each script in `scripts/` is invoked as a subprocess from `run.py`. They communicate via stdout JSON or written files.

## Implemented ✅

### `_cuda_dlls.py`
- `register_nvidia_dll_dirs() -> list[str]` — call BEFORE `from faster_whisper import WhisperModel`. Returns list of added DLL dir paths.

### `inspect_render.py <video-path>`
- Wraps `ffprobe`. Prints JSON `{path, duration_sec, video_streams, audio_streams, ok, errors}` to stdout.
- Exit 0 on valid render (duration > 0, video + audio streams present); 1 on any failure.

### `map_final_to_source.py --final-sec <T> --replay <path> --intro-speed {100|400} --intro-native-sec <s> --first-v1-source-sec <s>`
- Stdout: single float (source seconds).
- Exit 1 if `final_sec` is inside intro graphic.
- Auto-detect mode: `--workspace <path>` reads `transcripts/min-battles.json` + most-recent transcript + `<src-dir>/*_cuts_replay.json`. Still needs `--first-v1-source-sec` manually (Resolve API query TBD).

### `validate_cut_schema.py <cut-list.json>`
- Validates schema, reports overlaps. Exit 0/1.

---

## TODO (scaffold present, implementation needed) ⏳

### `transcribe_loose.py <audio.wav> --out <output.json>`

Spec:
1. Call `_cuda_dlls.register_nvidia_dll_dirs()` first
2. `WhisperModel('large-v3-turbo', device='cuda', compute_type='float16')` with CPU `int8` fallback
3. Transcribe with: `language='en', word_timestamps=True, beam_size=5, vad_filter=False, condition_on_previous_text=False, no_repeat_ngram_size=0`
4. If duration > 1800s and falling back to CPU, prompt user to confirm (~5h transcription)
5. Write `{audio: <path>, segments: [{id, start, end, text, words: [{word, start, end}]}], language, duration}` JSON

Estimated: ~50 lines, ~1h to write + test.

### `scan_transcript.py <transcript.json> --out <candidates.json>`

Spec — four scanners in parallel:
1. **Long word duration:** flag every word where `(w.end - w.start) >= 1.5s`. Reason field cites the long-duration word + its parent segment.
2. **Repeated n-grams (3-7):** sliding window same-segment + adjacent-segment + ≤30s. Filter content-bearing only (skip stopword-only ngrams).
3. **Self-correction regex:** match "i mean", "actually", "no wait", "scratch that", "but i but", "we we", "going going", "ahead ahead", etc.
4. **Whisper hallucination:** isolated short phrase (len < 0.5s OR <4 words) + ≥30s speechless context + (sub-frame duration <0.1s OR token in known-hallucination set).

Output JSON: array of `{start_sec, end_sec, type, reason, _scanner, _confidence}`. Each candidate has `_scanner ∈ {long_word, ngram, self_correction, hallucination}`.

Estimated: ~150 lines, ~2-3h to write + test.

### `teo_style_filter.py --candidates <in.json> --out-passed <out.json> --out-suppressed <suppressed.md>`

Spec:
1. Load patterns from `../references/teo-speech-style-patterns.md`
2. For each candidate, check against §9.4 atomic numbered refs (BLOCKER → drop), §3 emphatic restatements (downgrade), §1 opener vocabulary (downgrade), §6 aside conventions, §4 "but..."-pivot, §2 approximate quantifiers, §8 battle-reset commentary
3. Passing candidates → `out-passed`; suppressed → `out-suppressed.md` with reason

Estimated: ~80 lines, regex-heavy.

### `build_review_html.py --transcript <json> --candidates <json> --spot-checks-dir <path> --out <html>`

Spec:
1. Render full transcript with `<mark>` spans on candidate ranges
2. Top section: spot-check region embedded `<audio>` players
3. Candidate section: each cut with audio player + classification + suggested action + CUT/KEEP/DEFER buttons (form posts to `claude-confirmed-final-cuts.md`)
4. Use a single-file template (vanilla HTML+CSS+JS, no external deps)

Estimated: ~200 lines incl. CSS/JS.

### `find_audio_repetitions.py` (REUSE)

Already exists at `C:/Programming/resolve-mcp/scripts/find_audio_repetitions.py`. Copy or symlink into `scripts/` for the skill to be self-contained.

---

## Implementation priority

When the skill is first triggered on a real render:
1. Implement `transcribe_loose.py` (Step 4) — gates everything downstream
2. Implement `scan_transcript.py` (Step 5) — produces the candidate list
3. Implement `teo_style_filter.py` (Step 6) — most impactful false-positive reduction
4. Implement `build_review_html.py` (Step 10) — needed for user confirmation UX
5. Wire `find_audio_repetitions.py` into Step 5's waveform-similarity input
6. Implement Step 12 source-time mapping invocation (uses existing `map_final_to_source.py`)
7. Implement Step 13 verdict logic

Steps 1, 2, 8 (validators), and 12 (mapping) already work.
