# Deterministic GSC Gym Leader Challenge workflow

This is a separate zero-LLM workflow for Crystal/GSC Gym Leader Challenge recordings. Its default and maximum wall-clock budget is 600 seconds.

## Current deployment state

The separate workflow now has three deterministic stages: read-only preflight, complete offline FCPXML build, and a receipt-bound Resolve dry run. Automatic project discovery routes ordinary Gym Leader Challenge sessions to this workflow rather than the legacy LLM workflow. The offline stage performs no Resolve mutation. The Resolve stage requires the exact already-open project name, imports one new timeline UID at most, validates the live track geometry, links the exact outro V1/A3 source pair when needed, and populates reusable asset bins. It then applies the fixed `Standard Gameplay youtube` (`CONSOLE_FLEXI`) Fairlight preset to that exact receipt-bound timeline as the final Resolve mutation, saves immediately, and performs only read-only validation afterward. A build is ready for review only after the saved receipt binds a passing Fairlight report and prevents a duplicate import or preset reapplication.

## Fingerprinted Lt. Surge authority

Every preflight first audits the fingerprinted Lt. Surge reports and post-BGM DRT in `config/gsc_gym_leader_reference_contract.json`. The workflow's target geometry is:

- 3840x2160 at 60 fps.
- `GSCPC Intro Short__400pct.mp4` is the approved silent 4x derivative: 130 source frames at 30 fps, or exactly 260 frames on the 60 fps timeline. Its lineage source is the 512-frame `GSCPC Intro Short.mp4`; Resolve must not apply a second 4x retime.
- Only supplied identity attempt ordinal 1 receives a real 60-frame timeline insert and, for a leader/rival, one V2 intro. Same-trainer retries keep their own physical battle and A2 ranges but receive no additional A1 gap or intro, even if attempt 1 was removed by the dialogue edit. Both neighboring dialogue clips around an inserted gap remain complete and source-identical: no A1 trim, split, or dropped frame is allowed. V1 fills `[B-60,B)` with an exact source-backed bridge from the incoming clip's left handle, so only A1 is silent during the inserted second.
- During Team Challenge and Gym Leader Challenge runs, one active team member fainting and the next member being sent out is not a battle end. Future canonical telemetry must keep the battle lifecycle open until the authoritative patched-ROM battle-ended flag is true and emit paired structured party-replacement evidence. For older recordings whose bound logs lack those events, video recovery requires strong fixed-template title and finite attempt evidence for every raw Battle-state run; it merges only consecutive runs with the exact same evidenced title+attempt, rejects skipped/mismatched attempt sequences, and otherwise fails closed.
- When a logged or deterministic video-recovery battle start lands inside a retained auto-editor segment, assembly evaluates the valid joins on both sides and selects the one with the smallest absolute source-frame delta. Joins that would overlap the prior battle, collapse the current battle, or exceed the fixed 600-frame limit are rejected; exact equidistance fails closed. The receipt records both candidates, their distances, validity, and rejection reasons, and the structural audit recomputes the unique-nearest choice. This prevents a stable battle-UI detector from pushing the gap, intro, and battle BGM past the visual battle start.
- The first attempt of each distinct canonical leader/rival battle group receives a silent 300-frame V2 intro. It covers `[B-300,B)` and ends at `B`, exactly where the A1 gap `[B-60,B)` ends and the battle starts.
- The strict no-flash Surge audit proves ten exact 60-frame major-battle gaps with continuous V1 and ten matching 300-frame V2 leader/rival intros. It does not prove exact gap length for all 15 retained battles.
- The later post-BGM Surge report establishes the 15-battle population, including five no-intro minor battles. Its minor-battle gap values are geometry context only, not exact-gap authority.
- The member-carousel region is one continuous source-backed V1 bed plus contiguous V2 source duplicates with only `CropBottom=530`, immediately followed by the GSC outro MOV on V1/A3.

The later Surge timeline drifted four gaps to 67/66/69/68 frames and shortened one intro to 290 frames. Those values are fingerprinted as evidence to reject; they are not accepted tolerances. The reference report proves that the outro video and A3 audio share the `GSC Assets outro.mov` source name and the same record range, but it does not expose Resolve link-state metadata. A deployed workflow must create the V1/A3 pair as linked source components and prove that relationship in its receipt-bound live validator.

## Exact battle telemetry

Only `category="battle", name="battle-start"` identifies an opponent. A physical attempt must also have one complete mapper interval from `To Battle -> Battle` through `Battle -> ...`. The workflow rejects partial, nested, orphaned, open, duplicate, or unbound telemetry.

`trainer-ai/gym-leader-battle-start` is never an editorial anchor. It identifies the selected player AI profile and may fire several times inside one physical battle.

Attempts against the same exact `(trainerClass, trainerId)` retain a monotonic identity-attempt ordinal. Every physical attempt keeps its own exact start/end range and battle-BGM range, but only ordinal 1 receives an A1 gap and leader/rival intro. Main-source placement requires an embedded OBS chapter for each exact generic start. A direct logged Win end also requires its exact embedded chapter. When a completed loss/give-up has no direct Win event, its exact mapper-exit frame may be projected only through the two nearest strictly bracketing matched OBS chapters: the bracket may span at most 600 frames and both local offsets must agree with the proven session/source offset within two frames. Missing brackets, wider spans, residual drift, or an out-of-bracket projection fail closed. The workflow never infers an end from narration, the next retry, or an unverified container timestamp.

Historical video recovery uses receipt schema v2. Every raw Battle-state run must carry strong fixed-header title and finite attempt-template evidence and must belong to exactly one resolved physical attempt. Consecutive runs with the exact same evidenced title+attempt are combined from the first start through the final end; a changed attempt splits the range. The former policy that kept the first run and discarded later re-entry runs is rejected, and v1 receipts must be regenerated.

Rival assets are selected from exact trainer identity, not observed order or transcript inference: `RIVAL1` IDs 1-3 use Initial, 4-6 use Azalea, and 7-9 use Burned Tower. The Crystal ROM party-table triplets deterministically select the starter suffix: IDs 1/4/7 are `grass`, 2/5/8 are `fire`, and 3/6/9 are `water`. Unsupported IDs fail. `--rival-starter-type` is an explicit deterministic override only for a known ROM hack; the default is `auto`.

Session time is provenance only. Main-source positions come from a monotonic embedded-OBS-chapter/session-marker alignment, then must be mapped through the immutable deterministic dialogue edit before any final A1/V2/A2 placement.

## Completed source contract

Preflight accepts only a finalized, non-partial main OBS source with exactly one non-empty 3840x2160 video stream at 60 fps. File size and modification time must remain unchanged across the media probe; any change is treated as an active recording and fails closed. The selected one-based dialogue-audio ordinal is explicit (`5` by default, matching Surge's zero-based `audio:stream=4`), must exist, and must identify a non-empty 48 kHz OBS audio stream. This prevents a vertical capture or a different OBS mix from silently entering the edit.

## Deterministic member-carousel boundary

The preferred boundary is exact telemetry: the final complete `view/member-carousel-started` / `view/member-carousel-ended` pair whose end hands off to `view/channel-exp-bar-shown` within two 60 fps frames. The `started` frame is the carousel boundary. It is bound to an exact OBS chapter when available; otherwise it must pass the same strict nearest-bracketing chapter projection used for mapper exits, including the 600-frame maximum span and two-frame residual limit.

Older GSC sessions do not emit those events. Their zero-model fallback is the fixed 4K60 lower-corner luma detector validated on the preserved Surge reference. It samples the two 160x160 bottom-corner patches plus a top-center control patch and selects the final transition having six bright pre-roll frames in both corners (`luma >= 40`), then 120 sustained dark lower-corner frames while the control patch remains active for at least 40 frames. This rejects ordinary full-frame fades. The scan is capped at 120 seconds and fails closed if no qualifying transition is found. CUDA and CPU fallback share one absolute timeout. These thresholds and pixels are fixed; there is no per-video tuning, image classification, or LLM review.

Both telemetry and luma fallback produce an exact source frame. Final assembly must map that frame through the deterministic dialogue-edit map; if the frame lies in a removed interval, it snaps to the next retained source-backed edit boundary. The preflight records that final-timeline mapping requirement but cannot claim deployment readiness until the edit map, assembly receipt, and live validator exist.

## Audio reservations

- `Dual Screen Lovelife.mp3` owns the opening A2 identity and is excluded from the randomized deck. It begins at source offset 764 so the 4x picture intro lands on the same musical point as the native intro. It is the only non-battle identity allowed to repeat: exactly once at the opening and once immediately after the final battle.
- The exact six filenames fingerprinted in the Surge reference contract must be the complete contents of `GSCNewLayout/audio/Gen 2 battle audio`; missing or extra MP3s fail closed. They are selected in deterministic complete shuffle bags with no adjacent repeat.
- Each retained physical battle range has one exact assignment ID and deterministic 30-frame edge metadata, including retries. Every physical attempt restarts its assigned original battle asset at that asset's media-source start (normally source frame zero). A2 always references the original MP3 path and original visible filename with its complete source duration and editable left/right handles; rendered, renamed, or `a2-fades` derivatives are forbidden.
- Every positive non-battle range after a completed battle starts a fresh, previously unused shuffled identity at source frame zero. An immediate battle-to-battle boundary hands directly to the next assigned battle theme. Randomized non-battle identities never wrap or repeat.
- The post-final range always begins `Dual Screen Lovelife.mp3`, then `Motivated By Clouds.mp3`, then `Roll Me in Stardust.mp3`, then a still-unused randomized identity. The four identities receive deterministic fair shares when the remaining program is shorter than their natural combined durations, so every identity is present and starts at source frame zero.
- The randomized deck excludes all three named post-final tracks and `Golden Goose.mp3`; missing reserved assets fail closed.
- `Golden Goose.mp3` is blocked from A2 and is retained only as the outro identity reservation. The synchronized outro uses `F:\GSC Assets\GSC Assets outro.mov` on V1 and that MOV's linked source audio on A3; no second standalone Golden Goose clip is placed.

## Post-recording dry run

Do not run this while the recording is active. Once `meta.json` says the recording is finalized, open Resolve Studio with external scripting enabled and select the intended project. The one-command dry run is:

```powershell
.venv\Scripts\python.exe scripts\run_gsc_gym_deterministic_workflow.py resolve-dry-run `
  --source "F:\path\to\completed-main-OBS-recording.mp4" `
  --session-dir "C:\Users\Teo\AppData\Roaming\gscpc-frontend\logs\exact-session" `
  --output-dir "F:\CodexTemp\gsc-gym-deterministic\erika-victreebel" `
  --resolve-project "EXACT OPEN RESOLVE PROJECT NAME" `
  --dialogue-audio-ordinal 5 `
  --result-json "F:\CodexTemp\gsc-gym-dry-run.json"
```

Use `build-offline` instead of `resolve-dry-run` to generate and audit every artifact without connecting to Resolve. `preflight` (or the legacy `dry-run` alias) remains read-only.

The source must satisfy the completed-source contract, remain unchanged across a two-second dwell and through the final handoff, contain enough embedded OBS chapters, and align unambiguously to the exact session. The runner refuses active/partial or wrong-format recordings, an absent/wrong-rate dialogue stream, fuzzy battle events, unprojectable mapper exits, an unprovable carousel boundary, missing assets, absent intro media, non-Gym-Leader sessions, non-allowlisted workflow steps, result/output paths outside F:, and any runtime request above ten minutes. An outer process-tree watchdog terminates only its own worker and media helpers before the ten-minute ceiling; it does not terminate Resolve, OBS, the frontend, or unrelated processes.
