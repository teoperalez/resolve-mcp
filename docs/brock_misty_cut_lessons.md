# Brock and Misty Cut Lessons

This note preserves the reusable editing knowledge from the retired
`audio-checks/` workspaces. Those folders contained per-run transcripts,
preview audio, frame grabs, chunk packets, and one-off scripts for Brock Red and
Misty Red. They are stale artifacts now; the process below is the part worth
keeping.

## Canonical Inputs

- Brock Red source: `E:\Brock Red\Brock Red Blue versus Crystl.mp4`
- Brock Red canonical loose transcript: `transcripts/4.json` or the `_data`
  equivalent.
- Brock Red cut list target: `plans/prompts/cut-analysis-4.out.md`.
- Misty Red iteration history lives in `_data/transcripts/` as
  `dialogue-v{2..13}-transcript.json` and normalized variants.
- Case-specific generated QA folders should live under the source project's
  `CODEx/` or ignored local scratch folders, not as tracked repo state.

## Brock Red Lessons

- The opener duplicate is the regression test: the first take of "This is
  Brock. Brock likes rocks." at source `57.62-61.94` must be removed by the
  high-confidence false-start cut `57.62-78.17`, preserving the clean restart at
  `78.18-81.20`.
- Always audit the loose source transcript end-to-end for repeated n-grams,
  self-correction markers, and abandoned setup before trusting a clip-local
  analyzer. The original clip analyzer missed major repeated-take content.
- Run final-render QA after the 4K render. Brock's final render still exposed
  missed repetitions around the prediction phrasing, randomize-between phrasing,
  outro repeat, and Johto/Gen 2 correction. These were easiest to spot from a
  loose final-render transcript plus source-time mapping.
- For render-time findings, map final time back to source time using the cuts
  replay metadata and intro duration before editing the source-time cut list.
- Treat `WORDS_IN_CLIP(0)` as a candidate, not proof. Brock waveform checks
  showed several micro-cuts had speech-like peaks around `-16` to `-19 dBFS`
  and should be removed from the cut list.
- Waveform guidance from Brock: `peak < -45 dBFS` is silent, `peak < -30 dBFS`
  is low-energy breath/room tone, `peak < -20 dBFS` is borderline/manual review,
  and `peak >= -20 dBFS` is speech-like enough to avoid auto-cutting.
- The verified large Brock dead-air cut was source `1989.96-2016.76`: peak
  about `-39.2 dBFS`, 98 percent silent bins, no speech-like bins.
- Cross-battle cuts can be legitimate commentary cleanup, but battle-window
  overlap should be reported explicitly. Do not silently treat every battle
  overlap as an error.

## Misty Red Lessons

- Misty Red converged only after repeated QA passes and a whole-script critical
  read. Automated scans found many candidates, but the final quality came from
  reading the post-cut transcript as a published video.
- Use loose transcription settings for review: `condition_on_previous_text=False`,
  `no_repeat_ngram_size=0`, `vad_filter=False`, with word timestamps when
  needed. Default Whisper can merge or hide false starts.
- Long word durations can indicate hidden false starts, but they can also be
  emotional emphasis or proper-noun emphasis. Misty examples like extended
  "oh" and repeated "Misty" were legitimate, while suspicious long connector
  words needed waveform inspection.
- Repeated conjunctions and parallel phrasing are often intentional in Teo's
  delivery. Examples like repeated "even if" clauses and stacked "but" starts
  should not be cut without evidence of a genuine restart.
- Do not split atomic numbered references: "Rival 2", "rival number two",
  "attempt number one", "reset 29", "second gym leader", and similar phrases
  move as one unit.
- Run Pokemon-name normalization before final text review. Whisper errors such
  as Starmie/Starby, Blaine/Burt Lane, Bayleef/bay leaf, and similar homophones
  can mask bad cuts or make valid narration look broken.
- Re-audit existing cuts against the loose source after each iteration. Old cut
  boundaries often came from less reliable timestamps and can leave fragments or
  clip the first/last phoneme of a word.

## Retired Artifacts

The old tracked `audio-checks/` tree has been retired. It contained generated
transcripts, HTML reports, frame grabs, temporary MP3 previews, subagent chunk
packets, and one-off scripts such as `apply_round2.py` and `waveform_verify.py`.
Keep using the maintained generic scripts in `scripts/` plus project-local
`CODEx/` outputs for future challenge edits.