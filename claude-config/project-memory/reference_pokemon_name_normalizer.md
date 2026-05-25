---
name: Pokemon-name + homophone + Whisper-STT normalizer dictionary
description: Whisper consistently mis-transcribes Pokemon-domain vocabulary in IRL Pokemon Challenges videos. Apply this normalizer to every dialogue review text deliverable before handing to the user.
type: reference
project: resolve-mcp
originSessionId: d67a4cf0-ef49-42f3-87a4-44f400894785
---
## The problem

Whisper (turbo and large-v3) doesn't know Pokemon names. It transcribes them phonetically, often wrong. Some errors are deterministic (Whisper makes the SAME mistake every time — "bay leaf" for "Bayleaf"). Others vary between runs.

Common error classes:
- **Pokemon names** misheard as English words: Gastly→Ghastly, Starmie→Starby/Star Me, Zubat→"zoom out", Sentret→"Center it", Bayleaf→"bay leaf"/"bait leaf"/"Bayleef", Voltorb→"Volt Orb", Spearow→"spearo", Magnemite→"Magna Mite"
- **Pokemon move names** misheard: Reflect→"Rift", Harden→"hardened", Double Slap→"Devil Slap", Psywave→"Psi wave", Razor Leaf→"Razorly"/"Razorleaf"/"Razor Lee"
- **Trainer names** misheard: Falkner→"Faulkner"/"Falconer", Blaine→"Burt Lane"/"Burtlane"
- **Homophones** in Pokemon context: "no Razor Leaf" should be "**know** Razor Leaf" (when context is "he does no/know Razor Leaf")
- **General typos**: "trader"→"trainer"
- **Phrase merges where Whisper drops words**: "would react to" → "would do" or "wood to"; "his run" → "brun"; "considered at least like on par" → "considered at least like on" (drops "par")

## Where the dict lives

`audio-checks/qa-v6/pokemon_normalizer.json` — categories:
- `pokemon_names`: simple word substitutions
- `phrase_corrections`: multi-word substitutions
- `move_corrections`: Pokemon move name fixes
- `homophones`: context-sensitive (use specific surrounding text)
- `general_typos`
- `trainer_names`

## How to apply

`scripts/normalize_pokemon_text.py --transcript <vN-transcript.json> --normalizer <dict.json> --out-text <vN_NORMALIZED.txt> --out-json <vN-normalized.json>`

The script:
1. Sorts keys longest-first so phrase substitutions take priority over single-word ones
2. Multi-pass per segment (handles cascades like "Burt Lane → Blaine" then "be Blaine → beat Blaine")
3. Cross-segment patches for cases that span Whisper segment boundaries (e.g. "would probably be \n[xx:xx] Blaine")

## Extending

When critical reading or subagent QA finds a new STT error:

1. Verify the SOURCE audio actually contains the correct word (extract + re-transcribe with large-v3 + no_repeat_ngram_size=0)
2. If audio is correct but transcript is wrong → add normalizer entry (transcript-only fix, no cut needed)
3. If audio is wrong (speaker false-start, doubled phrase, etc.) → revise cut list (audio fix, requires v(N+1) rebuild)

Distinguishing the two is critical. Don't add a normalizer entry for something that's wrong in the audio — that creates discrepancy between the deliverable text and what the user hears.

## What's KEEP-as-speaker-voice (do NOT normalize)

Per Teo style guide §9.4, these are speaker's actual phrasing and must be preserved:

- **"Jamesy Proton"** — speaker's nickname for Team Rocket Executive Proton
- **"Billy Boy"** — speaker's nickname for Bill
- **"scary carry"** — speaker's nickname/joke for Lass Carrie (Whitney's gym member)
- **"trash-man Lt. Surge"** — recurring speaker characterization
- **"stunt on"** — colloquial speaker phrasing
- **"two-hitter"/"one-hitter"** — speaker shorthand for two-hit/one-hit KO
- **"still today"** — speaker actually says this at the intro
- **"same type water type moves"** — speaker shorthand for "STAB (Same Type Attack Bonus) water type moves"

## Cross-segment normalization

Whisper often splits adjacent words across segment boundaries (so "would probably be Blaine" ends up as "...would probably be" on one line and "Blaine. We know..." on the next). The normalizer's cross-segment pass handles this by temporarily stripping newlines + timecodes for matching, then restoring.

Specific cross-segment patches in the dictionary (each as a `re` pattern with `\s*(?:\n\[\d+:\d+\] )?` allowance for newline+timecode between words):
- `(would probably )be(\s*(?:\n\[\d+:\d+\] )?Blaine)` → `\1beat\2`
- `(she would )be(\s*(?:\n\[\d+:\d+\] )?Janine)` → `\1beat\2`
- `(We know she would )be(\s*(?:\n\[\d+:\d+\] )?Janine)` → `\1beat\2`

Add more as needed when critical reading catches them.

## Validated ~80-entry dictionary

The Misty Red v13 normalizer caught and fixed 30+ transcript-only issues. Use it as a starting point for any IRL Pokemon Challenges dialogue review. Update across videos when new Whisper errors surface.
