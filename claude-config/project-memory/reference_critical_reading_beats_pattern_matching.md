---
name: Critical reading is the irreplaceable final QA pass
description: Every dialogue review delivery must include a top-to-bottom whole-script read as if it were a published video. Pattern-matching scripts (waveform self-similarity, default-vs-loose diff, splice hallucination scan) catch the obvious symptoms but consistently miss narrative gaps, over-aggressive cuts that leave fragments, and missing-word grammar collapses.
type: reference
project: resolve-mcp
originSessionId: d67a4cf0-ef49-42f3-87a4-44f400894785
---
## Why pattern-matching alone fails

In the Misty Red v6→v13 iterations I built increasingly sophisticated automated QA:
- MFCC waveform self-similarity (`find_audio_repetitions.py`)
- Default-Whisper vs loose-Whisper transcript diff
- Splice-point hallucination scan
- Chunked Haiku subagent dispatch (6 parallel)
- Pokemon-name + homophone normalizer
- Cut-boundary auditor against loose source

Each tool caught real issues. None of them ever caught:

- **"Bugsy can."** — fragment created by an over-aggressive AUDIT-v5 cut that removed "might actually be a little bit of a challenge" along with the false-start
- **"we've taken like 29 resets we've taken like 20-ish resets"** — full duplicate that survived v6 through v12 because the cut at 2969.1-2971.38 had wrong boundaries (only removed "taken like 29 resets", left "We've" stutter)
- **"this starmie wants bubble beam but seriously this starmie wants surf"** — speaker self-correction that survived for similar reasons
- **"she would probably be Blaine"** — should be "**beat** Blaine"; cross-segment so per-segment normalizer didn't catch it
- **"considered at least like on Misty"** — Whisper dropped the word "par" between "on" and "Misty"

Every one of these requires asking *"does this paragraph read as a finished video?"* — a question no pattern-matcher asks.

## The competing-model litmus test

A user fed v8 to Gemini Flash 3 (a less-capable model than Claude) and got dozens of issues flagged on first read. **My entire automated pipeline had missed those issues.** This is the standard: if a competing model would catch something on first read, my QA pipeline shouldn't be delivering it.

## The right place for critical reading

**Stage 4** of the dialogue review QA protocol — AFTER the automated scans have caught their share, BEFORE delivery. Read `*_NORMALIZED.txt` top to bottom. Flag every spot that:

- Has a sentence missing a word ("would probably **be** Blaine" should be "**beat** Blaine")
- Has an obvious duplicate ("29 resets... 20-ish resets")
- Has a fragment ("Bugsy can." with no completion)
- Sets up a claim that's never paid off
- Has Pokemon-name typos the normalizer missed
- Has grammar that no native speaker would produce
- Breaks Teo's voice signature (per §9.4 of speech style doc)

For each, verify against source-time word boundaries and either revise a cut, add a normalizer entry, or document why it's KEEP.

## What's NOT critical-reading's job

- Detecting hidden duplicates Whisper merged → that's the loose-transcript pass
- Finding waveform-similar passages → that's `find_audio_repetitions.py`
- Catching splice hallucinations → that's the splice scan
- Pokemon-name corrections → that's the normalizer dictionary

Critical reading is the LAST pass that catches what slipped through the cracks.

## Concrete process

1. Read the file top-to-bottom
2. For each issue found, note:
   - v6 timestamp where it appears
   - The text that's wrong
   - What it should say (verified via source loose transcript)
3. Map v6 timestamp → source-time via live timeline query
4. Get source-time word boundaries from loose source transcript
5. Decide: cut adjustment OR normalizer entry OR KEEP
6. Apply all fixes
7. Rebuild vN+1
8. Re-read vN+1 critically

## When to stop iterating

When a careful read top-to-bottom finds zero real issues that aren't documented as intentional speaker style. Typically 3-5 iterations after the initial automated pass.

## Time investment

Each critical-reading pass: 15-30 minutes for a 30-min video script. Worth it. The user's standard is "wake up to a nearly-perfect timeline" — that's only achievable with this discipline.
