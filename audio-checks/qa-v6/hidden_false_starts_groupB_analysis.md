# Group B Hidden False-Starts Analysis

## Summary
Extracted and re-transcribed 8 suspect audio regions from source loose transcript. Found 4 regions with potential false-starts; 2 are confirmed real, 2 are likely false positives.

## Detailed Findings

### ✓ CONFIRMED FALSE-STARTS (Real cuts needed)

#### Region 947-968s: "all the way down" repetition
- **Evidence**: "i've gotten it all the way down to h i've gotten it all All the way down to 8H"
- **Issue**: Speaker starts phrase "i've gotten it all the way down" then restarts with "i've gotten it all" + full restart "All the way down to 8H"
- **Verdict**: TRUE false-start — speaker repeated the phrase with a glitch/stutter
- **Recommended cut**: Remove first partial attempt "i've gotten it all the way down to h" (~1.5s window)

#### Region 1215-1235s: "But" conjunction overflow
- **Evidence**: "But at least... But now... But then..." (multiple "but" sentence starts in sequence)
- **Issue**: Back-to-back "But" conjunction (natural emphasis pattern)
- **Verdict**: FALSE POSITIVE — this is natural conversational emphasis, not abandonment. Speaker is emphasizing parallel situations ("But this happened, but that happened"). No glitch, no restart.

### ? UNCERTAIN FALSE-STARTS (Likely false positives)

#### Region 860-880s: "even if we get there even if"
- **Evidence**: "even if we get there even if we do have to use"
- **Issue**: Repeated "even if" clause
- **Verdict**: FALSE POSITIVE — this is intentional parallelism: "even if [condition A], even if [condition B]". Natural conversational style, not abandonment.

#### Region 973-993s: "and the Starmie" pattern
- **Evidence**: "with Staryu doing most of the work and then the Starmie is just faster"
- **Issue**: Flagged "and the" as doubled
- **Verdict**: FALSE POSITIVE — this is natural continuation: "and then the [Pokémon name]". Normal grammar, not a false-start.

## Final Tally

| Region | Finding | Confidence |
|--------|---------|------------|
| 775-795 | None | High (clean transcript) |
| 860-880 | Intentional parallel clauses | High (FALSE POSITIVE) |
| 895-920 | None | High (clean transcript) |
| 947-968 | True repetition/stutter | High (CONFIRMED) |
| 973-993 | Natural continuation | High (FALSE POSITIVE) |
| 1110-1137 | None | High (clean transcript) |
| 1215-1235 | Emphasizing parallel situations | High (FALSE POSITIVE) |
| 1267-1295 | None | High (clean transcript) |

## Recommendation

**Only 1 confirmed false-start candidate worthy of further inspection:**
- Region 947-968s around frame 956-958s: "i've gotten it all" false-start before the complete phrase. Waveform inspection recommended to confirm silence boundary for precise cut.

All other flagged regions are natural speech emphasis and conjunction patterns—no cuts needed.

Output file: `C:/Programming/resolve-mcp/audio-checks/qa-v6/hidden_false_starts_groupB.json`
