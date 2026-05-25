# Teo Speech Style — patterns that downweight false-positive cuts

Loaded by `scripts/teo_style_filter.py`. Each candidate cut matching one of these patterns is downgraded to `INTENTIONAL_RHETORIC` (excluded from the missed-cuts list) unless the candidate ALSO has a waveform silent-gap > 1s between repeats.

Source: `~/.claude/Teo Speech Style.md` (kept in sync; this file is the skill-local extract).

---

## §9.4 — Atomic numbered references (BLOCKER — never split)

Cut boundaries inside these phrases are auto-rejected:

| Pattern (regex, case-insensitive) | Examples |
|---|---|
| `\b(rival|attempt|reset|round|loop|try)\s+(\d+\|one\|two\|three\|four\|five\|six\|seven\|eight\|nine\|ten)\b` | "rival 2", "attempt one", "reset 29", "loop 3" |
| `\b(my\|the\|his\|her\|their)\s+(first\|second\|third\|fourth\|fifth)\s+(pokemon\|gym\|gym leader\|battle\|trainer\|fight)\b` | "my second Pokemon", "the second gym leader" |
| `\blevel\s+(\d+\|one\|two\|...)\s+\w+` | "level 14 Onix", "level 12 Geodude" |
| `\b(one\|two\|three\|four\|five\|six\|seven\|eight\|nine\|ten)\s+full\s+heals?\b` | "five full heals", "two full heals per pokemon" |
| `\b\d+\s+(damage\|hp\|exp\|attempts\|resets)\b` | "two damage per hit", "11 HP", "29 resets" |

If a candidate cut's `start_sec` or `end_sec` falls between the noun and its number/ordinal, REJECT the cut as a BLOCKER. No downgrading — these never become cuts.

## §3 — Emphatic restatements (NOT false starts)

Repeated words that ARE rhetorical emphasis, not false-start stutters:

| Pattern | Behavior |
|---|---|
| `\b(really\s+){2,}` | "really really really close" — keep all, classify INTENTIONAL_RHETORIC |
| `\b(super\s+){2,}` | "super super easy" |
| `\b(way\s+){2,}` | "way way way more" |
| `\b(very\s+){2,}` | "very very very specific" |
| `\b(just\s+){2,}` | "just just gonna" — borderline; check waveform for silence between repeats |

Decision rule: if the repeated word sequence has NO waveform silence (peak > -30 dBFS continuous), it's emphasis. KEEP.

## §1 — Opener vocabulary (sentence starters, not repeats)

Common sentence openers. If these appear at the start of consecutive segments, they're not repeats — they're segment introductions:

- `"Now, ..."` / `"Now the thing is..."`
- `"And so..."` / `"And the thing is..."`
- `"OK so..."` / `"Alright so..."`
- `"Of course..."`
- `"Basically..."` / `"Essentially..."`
- `"You see..."`

If a candidate flags one of these as a "repeated phrase" between segments > 30s apart, downgrade to NARRATIVE_CALLBACK.

## §6 — Aside conventions

Post-clause asides where the noun appears twice (in the main clause + in the aside):

- `"[noun], as it's called here in Japan"` → "Tokyo, as it's called here in Japan"
- `"[noun], or [synonym] as some call it"` → "Geodude, or 'rock dude' as some call it"

If a repeated noun is followed by `"as it's called"`, `"or"`, `"a.k.a."`, `"also known as"`, the second occurrence is intentional. KEEP both.

## §4 — "but..."-pivot patterns

Distinguishing genuine self-correction from rhetorical pivot:

| Pattern | Classification |
|---|---|
| `"X. But actually Y"` | Self-correction (X is wrong, Y is right) → potential CUT |
| `"X. But also Y"` | Additive pivot (both true) → KEEP |
| `"X. But the thing is Y"` | Contextual pivot (Y nuances X) → KEEP |
| `"X. But wait, Y"` | Self-correction (Y replaces X) → potential CUT |
| `"X. But Y is..."` | New topic introduction → KEEP |

Decision rule: a "but" pivot is a self-correction (cut candidate) only when the post-but content directly negates the pre-but content. Otherwise it's rhetorical structure.

## §2 — Approximate quantifiers

The speaker prefers approximate language. Apparent imprecision is intentional, not a false start:

- `"about [N]"` / `"around [N]"` / `"roughly [N]"`
- `"less than [N]"` / `"more than [N]"` / `"at least [N]"`
- `"[N] or so"` / `"[N]-ish"`
- `"basically [N]"` / `"essentially [N]"`

If a candidate flags the noun/quantifier pair as a repeat, downgrade — these are stylistic.

## §7 — Time-anchored personal claims

Patterns like:
- `"back when I was [N]"`
- `"the first time I [verb]"`
- `"about [N] years ago"`
- `"when I lived in [place]"`

These often introduce a recurring personal-history thread. If similar phrases appear 60+ seconds apart, that's NARRATIVE_CALLBACK, not duplicate.

## §8 — Battle-reset commentary

Pokémon gameplay: each reset attempt is a new battle, but the commentary often repeats:
- `"that brings out the [Pokemon]"`
- `"and we get poisoned"`
- `"X damage per hit"`
- `"we have to use the full heal"`

These are repeated because the GAME repeats, not because the speaker is restarting a take. Classification: BATTLE_RESET_REPLAY. KEEP all instances if inside a battle window (intersection check via `transcripts/battles.json` + refined battle ends).

---

## Updating this file

This file is a snapshot. The canonical version is `~/.claude/Teo Speech Style.md`. When that doc is updated (new pattern observations from transcripts), bump this file in sync. The skill loads patterns from THIS file (not the canonical) so its behavior is reproducible.

Bump procedure:
1. Read `~/.claude/Teo Speech Style.md` for new §entries with ≥3 transcript examples
2. Add matching pattern + behavior to the appropriate section above
3. Date the change at the bottom
4. Run skill on a known-good case to verify no regressions

Last sync: 2026-05-22 (initial skill scaffold from v2 doc).
