# Codex Round 3 Verdict

verdict: PASS

summary: Round 3 is clean. The canonical 30-cut list is valid, replay math is sane, the user-confirmed final-render cuts are already represented in source-time, and the 50 cross-chunk n-gram candidates are narrative callbacks or battle-reset replays rather than missed duplicate takes.

## Must-fix items

None.

## Minor fixes applied

None.

## Confirmed clean

- `8.46-9.48` — artifact — high — isolated opening "Thank you" before the real intro.
- `57.62-78.17` — false_start — high — removes TAKE 1 of the Brock opener.
- `161.60-161.96` — artifact — medium — removes duplicated conjunction before "and stats".
- `349.36-349.44` — false_start — high — removes only the duplicate "ahead" inside Rival 1 commentary.
- `467.98-470.12` — false_start — high — removes abandoned "I simply predict that"; this matches user-confirmed final-render cut 1.
- `485.68-488.12` — false_start — high — removes dangling "but I think" before the clean restart.
- `504.44-504.52` — false_start — medium — removes only duplicate "going".
- `522.24-523.20` — false_start — high — removes second "and if he" while preserving "Violet City".
- `634.00-634.82` — artifact — medium — quiet gap between Falkner damage report and next tactical thought.
- `640.88-641.20` — false_start — high — removes abandoned "I'm gonna" before "going to Defense Curl".
- `674.16-676.26` — self_correction — high — removes abandoned randomize phrase; this matches user-confirmed final-render cut 2.
- `945.34-945.40`, `974.58-974.64`, `1001.32-1002.72` — artifact — high — Slowpoke Well "Thank you" hallucination cluster.
- `1089.00-1094.28` — artifact — high — long quiet/alignment gap before "the critical hits"; safe inside Jamesy Proton battle.
- `1184.56-1187.36`, `1215.88-1215.94`, `1245.14-1247.94`, `1273.98-1276.78` — artifact — high — repeated isolated "Thank you" hallucinations.
- `1352.42-1352.58` — artifact — high — duplicated "girl" stitch artifact inside Bugsy commentary.
- `1962.77-1967.65` — artifact — high — silent gap before "poisoned which is pretty bad".
- `1989.96-2016.76` — artifact — high — waveform-verified 26.8s low-energy gap; mostly no-op in FCPXML because auto-editor already removed it.
- `2064.72-2065.13` — false_start — medium — removes "i but" stutter from "but i but with that said".
- `2273.38-2274.78` — stream_chat_acknowledgment — high — isolated "Thanks for watching!" hallucination/social artifact before resumed Bugsy narration.
- `2325.30-2325.78` — artifact — high — borderline waveform level but no speech-like bins; acceptable breath/quiet artifact cut despite loose Whisper timestamp smear.
- `2440.70-2441.78` — artifact — high — removes redundant "strategies" at clean word boundaries.
- `2700.12-2702.40` — repetition — high — removes first duplicate outro line; this matches user-confirmed final-render cut 3.
- `2713.40-2717.90` — false_start — high — removes "with a Johto version but I will be coming back"; this matches user-confirmed final-render cut 4.
- `2722.86-2725.64` — false_start — medium — removes "with his greater but" and preserves "but with his much improved team".
- `2824.66-2825.08` — repetition — high — removes duplicated "interesting" at segment boundary.

Battle-window check: PASS. All 12 WARN cuts are commentary-level artifacts/false starts or speechless gaps inside battle windows, not battle-start/end chops or meaningful battle commentary removals.

Pokemon/vocabulary boundary check: PASS. Manual spot checks on `349.36`, `522.24-523.20`, `640.88-641.20`, `1352.42-1352.58`, and `2440.70-2441.78` agree with the script: no tracked name/move/item boundary is split.

Replay metadata: PASS. `all_cuts.total_tl_frames_removed = 1370` at 60fps = 22.83s, with 9 deletes / 8 trim_start / 11 trim_end / 6 split_multi. The source-vs-timeline discrepancy is expected because several source cuts are in already-removed auto-editor silence.

SPEECH_LIKE micro-cut removals: PASS. Keeping the audio for `172.75-173.05`, `258.57-259.05`, `556.00-556.28`, `599.73-600.42`, `1778.85-1779.28`, and `2692.58-2692.92` was the right conservative call; waveform peaks show audible content, and none is needed for pacing.

## N-gram repeat verdicts

- `"get put to sleep"` (`2471.96-2472.68` -> `2505.30-2506.08`): BATTLE_RESET_REPLAY — Rival 2 status-condition commentary across different turns.
- `"gonna have to hope"` (`2116.50-2117.36` -> `2151.28-2152.00`): BATTLE_RESET_REPLAY — escalating Bugsy plan commentary, not a retake.
- `"able to get through"` (`1768.60-1769.36` -> `1807.12-1808.00`): BATTLE_RESET_REPLAY — failed Bugsy attempt followed by revised smart-Brock attempt.
- `"be able to get"` (`1768.52-1769.12` -> `1806.94-1807.66`): BATTLE_RESET_REPLAY — same event family as above.
- `"him from sending out"` (`1552.12-1553.00` -> `1593.04-1594.24`): BATTLE_RESET_REPLAY — comparing plans to avoid/alter Scyther timing.
- `"two damage per hit"` (`2445.40-2446.64` -> `2489.18-2490.32`): BATTLE_RESET_REPLAY — Rival 2 damage-state callback.
- `"were simply going to"` (`229.20-229.96` -> `273.18-274.00`): NARRATIVE_CALLBACK — rules/setup language reused.
- `"that brings out the"` (`1482.24-1483.52` -> `1537.64-1539.14`): BATTLE_RESET_REPLAY — repeated Bugsy team sequencing in different attempts.
- `"brings out the scyther"` (`1482.64-1484.04` -> `1538.56-1539.70`): BATTLE_RESET_REPLAY.
- `"brock could actually get"` (`110.48-112.28` -> `169.22-170.92`): NARRATIVE_CALLBACK — intro thesis restated as goal.
- `"could actually get in"` (`110.76-112.60` -> `169.64-171.28`): NARRATIVE_CALLBACK.
- `"that brings out the"` (`1755.20-1756.90` -> `1814.42-1815.38`): BATTLE_RESET_REPLAY — different Bugsy attempt outcomes.
- `"find out how far"` (`108.56-109.58` -> `168.14-169.22`): NARRATIVE_CALLBACK — intro thesis.
- `"to find out how"` (`108.42-109.20` -> `167.88-168.88`): NARRATIVE_CALLBACK.
- `"critical hit fury cutter"` (`1760.64-1761.92` -> `1820.72-1822.18`): BATTLE_RESET_REPLAY — Scyther event recurs in separate attempts.
- `"find out how far"` (`168.14-169.22` -> `229.96-230.88`): NARRATIVE_CALLBACK.
- `"to find out how"` (`167.88-168.88` -> `229.84-230.54`): NARRATIVE_CALLBACK.
- `"full heal and now"` (`2417.74-2419.34` -> `2480.48-2486.44`): BATTLE_RESET_REPLAY — Rival 2 resource tracking.
- `"it turns out that"` (`1035.18-1036.08` -> `1100.94-1102.08`): NARRATIVE_CALLBACK — conclusion phrasing after observations.
- `"that brings out the"` (`1415.98-1416.88` -> `1482.24-1483.52`): BATTLE_RESET_REPLAY — Bugsy team progression.
- `"in every single battle"` (`218.60-220.62` -> `288.64-290.42`): NARRATIVE_CALLBACK — Full Heal rule restated.
- `"get put to sleep"` (`2402.78-2403.58` -> `2471.96-2472.68`): BATTLE_RESET_REPLAY — Rival 2 sleep-risk commentary.
- `"brings out the scyther"` (`1741.96-1743.04` -> `1814.62-1815.90`): BATTLE_RESET_REPLAY.
- `"brings out the scyther"` (`1662.14-1663.36` -> `1741.96-1743.04`): BATTLE_RESET_REPLAY.
- `"that brings out the"` (`1661.96-1662.92` -> `1741.80-1742.64`): BATTLE_RESET_REPLAY.
- `"have level 12 geo"` (`541.64-543.12` -> `627.40-628.56`): NARRATIVE_CALLBACK — trainer/Brock team setup repeated for battle context.
- `"level 12 geo dude"` (`541.98-543.42` -> `627.72-628.78`): NARRATIVE_CALLBACK.
- `"our last full heal"` (`2501.38-2502.32` -> `2591.66-2592.72`): BATTLE_RESET_REPLAY — Rival 2 resource tracking.
- `"how far brock could"` (`168.64-169.98` -> `266.08-267.02`): NARRATIVE_CALLBACK.
- `"if we get put"` (`2402.50-2403.14` -> `2504.98-2505.64`): BATTLE_RESET_REPLAY.
- `"we get put to"` (`2402.68-2403.28` -> `2505.20-2505.76`): BATTLE_RESET_REPLAY.
- `"brings out the scyther"` (`1538.56-1539.70` -> `1662.14-1663.36`): BATTLE_RESET_REPLAY.
- `"that brings out the"` (`1537.64-1539.14` -> `1661.96-1662.92`): BATTLE_RESET_REPLAY.
- `"gen brock turns out"` (`2639.50-2641.82` -> `2770.72-2772.60`): NARRATIVE_CALLBACK — conclusion then later recap.
- `"it for this one"` (`2706.78-2707.42` -> `2837.18-2837.84`): NARRATIVE_CALLBACK — outro close and final signoff.
- `"because of the fact"` (`1378.36-1379.56` -> `1520.84-1521.74`): NARRATIVE_CALLBACK — common explanatory phrase.
- `"of the fact that"` (`1378.90-1379.70` -> `1521.24-1522.02`): NARRATIVE_CALLBACK.
- `"but this could be"` (`1546.88-1548.82` -> `1694.26-1697.02`): BATTLE_RESET_REPLAY — hypothesis language across Bugsy plan revisions.
- `"and we can see"` (`350.88-351.54` -> `498.04-498.68`): NARRATIVE_CALLBACK — generic observation phrase.
- `"this could be the"` (`1547.70-1549.02` -> `1695.92-1697.64`): BATTLE_RESET_REPLAY.
- `"we get poisoned again"` (`1469.44-1472.14` -> `1623.92-1625.42`): BATTLE_RESET_REPLAY — repeated Kakuna poison events.
- `"thats available to us"` (`2436.18-2437.42` -> `2592.72-2593.78`): BATTLE_RESET_REPLAY — Rival 2 resource/options commentary.
- `"smart brock using the"` (`1330.72-1332.54` -> `1496.08-1497.72`): NARRATIVE_CALLBACK — announces smart-Brock strategy, then transitions into it.
- `"brock using the best"` (`1331.28-1332.80` -> `1496.66-1498.10`): NARRATIVE_CALLBACK.
- `"that brings out the"` (`1814.42-1815.38` -> `1984.92-1986.66`): BATTLE_RESET_REPLAY — different Bugsy team transitions.
- `"to see how this"` (`1424.14-1424.80` -> `1600.04-1601.22`): BATTLE_RESET_REPLAY — attempt framing, not duplicate take.
- `"out that brings out"` (`1481.90-1483.32` -> `1661.64-1662.80`): BATTLE_RESET_REPLAY.
- `"pokemon out that brings"` (`1481.60-1482.94` -> `1661.30-1662.46`): BATTLE_RESET_REPLAY.
- `"that pokemon out that"` (`1481.34-1482.64` -> `1661.08-1662.14`): BATTLE_RESET_REPLAY.
- `"knock that pokemon out"` (`1481.02-1482.24` -> `1660.68-1661.96`): BATTLE_RESET_REPLAY.

## Open questions for Claude

None blocking. Proceed with rebuild/re-render.
