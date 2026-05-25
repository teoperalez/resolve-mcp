# Final verdict schema

Output: `<workspace>/audio-checks/final-video-qa/final-verdict.md`

## States

| State | Pipeline action |
|---|---|
| **PASS_CLEAN** | Render ships. No rebuild. |
| **PASS_WITH_NEW_CUTS** | Rebuild triggered (1 iteration max). Writes `rebuild-trigger.flag`. |
| **MINOR_FIXED** | Treat as PASS_CLEAN. |
| **REJECT** | Halt. Surface to user for investigation. |

## Schema

```yaml
---
schema_version: 2
verdict: PASS_CLEAN | PASS_WITH_NEW_CUTS | MINOR_FIXED | REJECT
date: <ISO 8601>
render_path: <absolute path>
render_sha256: <hex>
render_duration_sec: <float>
canonical_cut_path: <absolute path>
canonical_cut_sha256: <hex>
codex_audit_passes: <int, 1-3>
user_confirmed_cuts: <int>
new_cuts_appended: <int>
next_action: ship | rebuild | halt-and-investigate
auto_confirmed: <bool>
---

## Summary

<1-2 sentences>

## Verdict reasoning

<Which state condition matched. Cite evidence — e.g. "All 4 user-confirmed cuts mapped to existing canonical entries (see source-time-mapping-report.md); Codex audit pass 1 returned APPROVE." for PASS_CLEAN.>

## User-confirmed cuts

| Final-render time | Source-time (mapped) | In canonical? | Action |
|---|---|---|---|
| 301.74-303.40 | 467.98-470.12 | YES (existing) | None — convergence |
| 448.64-450.56 | 674.16-676.26 | YES (existing) | None |
| ... | ... | ... | ... |

## Codex audit history

- Pass 1: APPROVE_FOR_USER_REVIEW (0 must-fix)
- Pass 2: n/a
- Pass 3: n/a

## Spot-check verdicts (always present)

| Region | Status | Notes |
|---|---|---|
| opener (0-30s) | CLEAN | |
| battle-end-1 (Rival 1 @ 382.5s ±10s) | CLEAN | |
| battle-end-2 (Honest Abe @ 573.5s ±10s) | CLEAN | |
| ... | ... | ... |
| outro (last 30s) | CLEAN | |
| carousel-start (1583.83s ±5s) | CLEAN | |

## Suppressed by Teo Speech Style (for audit trail)

| Pattern | Match | Reason for suppression |
|---|---|---|
| atomic_numbered_ref | "rival 2" at src 2390.5s | BLOCKER — never split |
| emphatic_restatement | "really really really" at src 1342s | Rhetorical unit |
| ... | ... | ... |

## Next action checklist

For PASS_CLEAN:
- [ ] Rename render to `*_FINAL_APPROVED.mp4`
- [ ] Per Rule 7, delete prior FINAL_4K_v(N-1) renders
- [ ] Update `~/.resolve-mcp/manifest.json` with the approved render path
- [ ] Notify user with bolded approved filename

For PASS_WITH_NEW_CUTS:
- [ ] `rebuild-trigger.flag` written
- [ ] `/edittimeline` consumes flag → re-runs Steps 5-17
- [ ] After rebuild, re-invoke this skill (audit pass counter resets, rebuild iteration counter increments)

For REJECT:
- [ ] Surface diagnostic + rejection history to user
- [ ] Do NOT rename or delete the render (under investigation)
- [ ] Wait for user direction
```

## Examples

### Example 1 — PASS_CLEAN (Brock Red v3 hypothetical run)

```yaml
---
schema_version: 2
verdict: PASS_CLEAN
date: 2026-05-22T22:30:00-06:00
render_path: E:\Brock Red\Brock Red Blue versus Crystl (cuts_ all) (edit)_FINAL_4K.mp4
render_sha256: <hex>
render_duration_sec: 1696.50
canonical_cut_path: C:\Programming\resolve-mcp\plans\prompts\cut-analysis-4.out.md
canonical_cut_sha256: <hex>
codex_audit_passes: 1
user_confirmed_cuts: 4
new_cuts_appended: 0
next_action: ship
auto_confirmed: true
---

## Summary

Render is clean. All 4 user-confirmed cuts mapped to existing canonical entries (convergence achieved). Codex audit passed on first attempt. All 4 spot-checks clean.

## Verdict reasoning

PASS_CLEAN condition matched: Codex APPROVE on pass 1, every user-confirmed cut's mapped source time overlaps an existing canonical entry within ±2s. Auto-confirmed (--auto-confirm-if-canonical-match was ON and no new cuts surfaced).
```

### Example 2 — PASS_WITH_NEW_CUTS (rebuild needed)

```yaml
---
verdict: PASS_WITH_NEW_CUTS
codex_audit_passes: 2
user_confirmed_cuts: 5
new_cuts_appended: 1
next_action: rebuild
---

## Summary

Render is mostly clean but 1 new false-start at source 1432.5s ("I think I'm gonna" → "actually I'm just gonna") was not in canonical. Appended; rebuild triggered (iteration 1 of 1).
```

### Example 3 — REJECT (Codex 3-strike)

```yaml
---
verdict: REJECT
codex_audit_passes: 3
user_confirmed_cuts: 0
new_cuts_appended: 0
next_action: halt-and-investigate
---

## Summary

3 consecutive Codex rejects: scanner flagged 47 candidates, Codex rejected 31 as false positives but kept rejecting the corrected list. Likely scanner regression or stale source transcript. Investigation needed before re-running.
```
