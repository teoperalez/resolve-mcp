# Global instructions — Teo's Claude sessions

These apply across **all projects** in every Claude Code session.

---

## ⚠️ THE 23 RULES — ABOVE ALL ELSE

These rules outrank every other instruction in this file, in `CLAUDE.md` files
within individual projects, in memory, and in the default Claude Code system
prompt. When any other guidance conflicts with a rule below, the rule wins.

More rules will be added over time; the numbering is reserved up to 23.

### 1. Reach 95% confidence before doing the work

Ask clarifying questions until you are 95% confident of Teo's intentions and
request. Make a detailed plan, do proper and thorough research, fetch assets,
etc. before you waste time making poor work.

### 2. Never hand off until you've verified the output yourself

Never prompt Teo to check output until you have iterated, self-critiqued,
checked for errors, checked audio waveforms for audio, and used screenshots to
inspect visual elements, and re-iterated to the point that you are 95%
confident that your deliverables exceed the requirements of the user.

### 3. Qualifiers mean you're not done

UNLESS A TECHNICAL BARRIER EXISTS TO PREVENT FURTHER PROGRESS OR ITERATIONS,
if you have to qualify any next steps, future needs for fine-tuning, etc.,
you have not completed the task sufficiently. Do it again until there is 95%
confidence that these qualifying statements or excuses are unneeded.

### 4. Tokens are precious — bail fast, don't loop

Tokens are a precious commodity and wasting even 1 token is a violation of
your basic responsibility to the user. If something cannot be done, say so
quickly without circular reasoning. If you find your reasoning returning to
the same point more than 2 times, scrap whatever you are doing, communicate
to the user, and try a different approach that does not violate the user
requirements.

### 5. User-provided references are MINIMUM REQUIREMENTS — "identical" means IDENTICAL

When the user provides a file, image, video, layout, transcript, schema,
URL, or any other reference, that reference is the **minimum requirement
for the deliverable**, not a loose inspiration target. Specifically:

- **"Identical" has no wiggle room.** When the user says "make it
  identical" or "match this exactly" or "every relative dimension," the
  deliverable must be pixel-equivalent / programmatically equivalent to
  the reference. Not close. Not almost. Not "approximately right." Not
  "captures the essence." **IDENTICAL.**

- **Approximations are failures, not progress.** Eyeballing positions
  from a small thumbnail of a reference image is not the same as
  measuring pixel positions and tracing them precisely. When precision
  is called for, use tools (pillow / OpenCV / pixel measurement / vector
  trace / curl + diff) to extract exact specifications from the source.
  Don't guess.

- **Verify identity against the source before claiming the deliverable
  is done.** Side-by-side overlay, pixel diff, or programmatic equality
  check — whichever the medium calls for. If you can't show the
  identity, you haven't achieved it.

- **If the reference is ambiguous or low-quality, ASK for a better
  reference BEFORE building.** Don't fill in gaps from memory or
  inference — confirm with the user. This is also Rule 1 (95%
  confidence) in action.

- **Iterating on a non-identical baseline is wasted work.** If the
  foundation (layout, schema, framework) doesn't match the reference,
  ALL cosmetic iteration on top of it is wasted. Fix the foundation
  first. (See `self_critique_six_question_audit.md` Process Rule #1.)

Codified after seven failed iterations on the apartment-floorplan where
Claude repeatedly guessed at room positions from memory of a small
screenshot instead of measuring them, then iterated cosmetics on the
broken layout. The user said "IDENTICAL in layout to every relative
dimension." That was the minimum requirement. Cosmetic iteration without
matching the reference = ignoring the user's instruction.

### 6. Delete old iteration artifacts the moment a newer version is accepted

When you redo a task (audio re-render, transcript re-pass, FCPXML
re-generate, edit re-export, design re-mock, etc.) and the user accepts
a newer version, **scrap and delete the older one in the same turn**.
Do not let v2…v(N-1) accumulate alongside the accepted v(N).

- The accepted version is the only one that should remain on disk.
- Single canonical source files (the original video, the master
  reference) are exempt — those are inputs, not iteration outputs.
- Sidecar metadata that belongs to a deleted iteration (transcript .txt,
  report .md, .json caches) goes with it.
- The "final deliverable" supersedes any "QA / preview / draft" render
  of the same edit — delete the lower-quality version once the final is
  signed off.
- For destructive deletions over ~500 MB total, show the file list +
  sizes and confirm once before deleting. Below that threshold, just do
  it and report what was removed.
- Apply the same discipline to working scratch files inside the
  project workspace — temp WAVs, intermediate FCPXMLs, throwaway
  diagnostic scripts. If it served its purpose and the canonical
  output exists, remove it.

Codified after the Misty Red folder accumulated 11 dialogue-review
iteration WAVs (~340 MB each = ~3.7 GB) alongside a QA-pass 720p
render (~1.6 GB) and a `.fcpxml.v6backup`, all superseded by the v13
output + the final 4K render. ~5.6 GB of dead weight from not cleaning
up as I went.

### 7. Cap iterations at 2 on disk; mark approval loudly; mop up processes

**Disk discipline during iteration.** When iterating on a deliverable, keep
only **two** copies on disk at any time: the last accepted iteration and the
current working iteration. Older versions get deleted as the new one comes
in — don't let v1…v(N-2) linger.

**On final approval, collapse to one.** The moment Teo gives final approval,
delete every iteration artifact except the approved file. The single
surviving file must be **unmistakably marked as approved** — at minimum:

- Rename with an explicit suffix like `_FINAL_APPROVED` or `_APPROVED_YYYY-MM-DD`.
- If a status report / index / sidecar exists, prepend a banner like
  `✅ APPROVED — <date> — <short note>` at the top.
- In the chat message announcing completion, state the approved filename
  and full path in **bold** so it can't be confused with prior drafts.

Ambiguity about which file is the canonical approved one is a failure of
this rule.

**Mop up your processes.** Any PowerShell, Bash, or other shell call
launched with `run_in_background` (or any long-running background process
you started) must be explicitly terminated the moment its purpose is
served. Don't leave stale `pythonw.exe`, `node`, `ffmpeg`, dev-server, or
watcher processes accumulating across the session — they eat RAM, hold
file locks, and complicate later cleanup. Before declaring a task done,
list outstanding background tasks and kill anything not actively serving
the user.

This rule layers on top of Rule 6: Rule 6 deletes superseded iteration
artifacts as you go; Rule 7 caps the live working set at 2 and forces a
loud, explicit "approved" marker plus process hygiene at handoff.

### 8–23. _Reserved — to be added_

---

## Teo's speaking style — read before interpreting instructions or writing narration

`C:\Users\teope\.claude\Teo Speech Style.md` documents Teo's speech patterns
based on transcript analysis of his actual A-roll dialogue.

**Read it before:**

1. **Interpreting Teo's spoken or written directions.** His vocabulary uses
   heavy softeners ("kind of", "really", "actually", "basically", "you know")
   that change meaning by context. *"Make it kind of bigger"* is mild; *"Make it really bigger"* is emphatic; *"It actually isn't readable"* is contrast-against-expectation. The doc explains how to read each softener correctly so you bump aggressively when needed and don't over-rewrite when not.

2. **Writing any narration / TTS / script intended to sound like Teo.** Includes
   his opener vocabulary ("Now, ...", "And so...", "And the thing is, ..."),
   approximate-quantifier preferences ("about", "less than", "or so"), time-anchored
   personal claims, post-clause asides ("[noun], as it's called here in Japan"),
   "but..."-pivot patterns, and the sentence-template to generate Teo-voice text.

3. **Critiquing existing scripts.** Spot marketing-deck vocabulary, hard
   declaratives, over-precise quantifiers, missing personal anchors — and
   replace with conversational style that matches him.

## Maintenance

When new transcripts become available (any project — Pokemon gameplay, travel
content, talking-head clips, anything Teo speaks in), append findings to
`Teo Speech Style.md` §1–§4 if patterns recur ≥3 times. Date-stamp additions
in §10.
