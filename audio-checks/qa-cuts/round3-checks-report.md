# Round 3 Cross-cut Verification Report

Generated: 2026-05-19
Canonical cut list: `plans/prompts/cut-analysis-4.out.md` (30 cuts)
Loose transcript:   `transcripts/4.json` (350 segments)

---
## 4.5 — Battle window intersection check (rubric §4.5)

⚠ **FINDINGS:**
- `349.36-349.44` — inside_battle for Rival 1 — severity: WARN (battle commentary)
  {
  "cut": "349.36-349.44",
  "battle": "Rival 1",
  "battle_window": "341.47-382.50",
  "overlap_type": "inside_battle",
  "severity": "WARN (battle commentary)"
}
- `634.00-634.82` — inside_battle for Falkner — severity: WARN (battle commentary)
  {
  "cut": "634.00-634.82",
  "battle": "Falkner",
  "battle_window": "622.97-759.25",
  "overlap_type": "inside_battle",
  "severity": "WARN (battle commentary)"
}
- `640.88-641.20` — inside_battle for Falkner — severity: WARN (battle commentary)
  {
  "cut": "640.88-641.20",
  "battle": "Falkner",
  "battle_window": "622.97-759.25",
  "overlap_type": "inside_battle",
  "severity": "WARN (battle commentary)"
}
- `674.16-676.26` — inside_battle for Falkner — severity: WARN (battle commentary)
  {
  "cut": "674.16-676.26",
  "battle": "Falkner",
  "battle_window": "622.97-759.25",
  "overlap_type": "inside_battle",
  "severity": "WARN (battle commentary)"
}
- `1089.00-1094.28` — inside_battle for Jamesy Proton — severity: WARN (battle commentary)
  {
  "cut": "1089.00-1094.28",
  "battle": "Jamesy Proton",
  "battle_window": "1048.46-1113.80",
  "overlap_type": "inside_battle",
  "severity": "WARN (battle commentary)"
}
- `1352.42-1352.58` — inside_battle for Bugsy — severity: WARN (battle commentary)
  {
  "cut": "1352.42-1352.58",
  "battle": "Bugsy",
  "battle_window": "1340.98-2381.25",
  "overlap_type": "inside_battle",
  "severity": "WARN (battle commentary)"
}
- `1962.77-1967.65` — inside_battle for Bugsy — severity: WARN (battle commentary)
  {
  "cut": "1962.77-1967.65",
  "battle": "Bugsy",
  "battle_window": "1340.98-2381.25",
  "overlap_type": "inside_battle",
  "severity": "WARN (battle commentary)"
}
- `1989.96-2016.76` — inside_battle for Bugsy — severity: WARN (battle commentary)
  {
  "cut": "1989.96-2016.76",
  "battle": "Bugsy",
  "battle_window": "1340.98-2381.25",
  "overlap_type": "inside_battle",
  "severity": "WARN (battle commentary)"
}
- `2064.72-2065.13` — inside_battle for Bugsy — severity: WARN (battle commentary)
  {
  "cut": "2064.72-2065.13",
  "battle": "Bugsy",
  "battle_window": "1340.98-2381.25",
  "overlap_type": "inside_battle",
  "severity": "WARN (battle commentary)"
}
- `2273.38-2274.78` — inside_battle for Bugsy — severity: WARN (battle commentary)
  {
  "cut": "2273.38-2274.78",
  "battle": "Bugsy",
  "battle_window": "1340.98-2381.25",
  "overlap_type": "inside_battle",
  "severity": "WARN (battle commentary)"
}
- `2325.30-2325.78` — inside_battle for Bugsy — severity: WARN (battle commentary)
  {
  "cut": "2325.30-2325.78",
  "battle": "Bugsy",
  "battle_window": "1340.98-2381.25",
  "overlap_type": "inside_battle",
  "severity": "WARN (battle commentary)"
}
- `2440.70-2441.78` — inside_battle for Rival 2 — severity: WARN (battle commentary)
  {
  "cut": "2440.70-2441.78",
  "battle": "Rival 2",
  "battle_window": "2390.53-2633.70",
  "overlap_type": "inside_battle",
  "severity": "WARN (battle commentary)"
}

---
## 4.6 — Pokémon-name / vocabulary boundary check (rubric §4.6)

✅ **PASS** — No cut boundary lands inside a Pokémon name, trainer name, location, or commonly-mistranscribed move token.


---
## NEW — Cross-chunk n-gram repeat scan (gap > 30s, < 180s)

Identifying repeated n-grams (4-gram, content-bearing) that the 30s overlap pass would have missed.

Total candidates found: **50**

| n-gram | gap (s) | first src | second src | first seg | second seg |
|---|---|---|---|---|---|
| "get put to sleep" | 32.6 | 2471.96-2472.68 | 2505.30-2506.08 | 298 | 302 |
| "gonna have to hope" | 33.9 | 2116.50-2117.36 | 2151.28-2152.00 | 260 | 263 |
| "able to get through" | 37.8 | 1768.60-1769.36 | 1807.12-1808.00 | 223 | 230 |
| "be able to get" | 37.8 | 1768.52-1769.12 | 1806.94-1807.66 | 223 | 229 |
| "him from sending out" | 40.0 | 1552.12-1553.00 | 1593.04-1594.24 | 178 | 184 |
| "two damage per hit" | 42.5 | 2445.40-2446.64 | 2489.18-2490.32 | 294 | 300 |
| "were simply going to" | 43.2 | 229.20-229.96 | 273.18-274.00 | 23 | 32 |
| "that brings out the" | 54.1 | 1482.24-1483.52 | 1537.64-1539.14 | 167 | 176 |
| "brings out the scyther" | 54.5 | 1482.64-1484.04 | 1538.56-1539.70 | 167 | 176 |
| "brock could actually get" | 56.9 | 110.48-112.28 | 169.22-170.92 | 9 | 18 |
| "could actually get in" | 57.0 | 110.76-112.60 | 169.64-171.28 | 9 | 18 |
| "that brings out the" | 57.5 | 1755.20-1756.90 | 1814.42-1815.38 | 222 | 231 |
| "find out how far" | 58.6 | 108.56-109.58 | 168.14-169.22 | 9 | 18 |
| "to find out how" | 58.7 | 108.42-109.20 | 167.88-168.88 | 9 | 18 |
| "critical hit fury cutter" | 58.8 | 1760.64-1761.92 | 1820.72-1822.18 | 222 | 232 |
| "find out how far" | 60.7 | 168.14-169.22 | 229.96-230.88 | 18 | 23 |
| "to find out how" | 61.0 | 167.88-168.88 | 229.84-230.54 | 18 | 23 |
| "full heal and now" | 61.1 | 2417.74-2419.34 | 2480.48-2486.44 | 290 | 299 |
| "it turns out that" | 64.9 | 1035.18-1036.08 | 1100.94-1102.08 | 121 | 131 |
| "that brings out the" | 65.4 | 1415.98-1416.88 | 1482.24-1483.52 | 156 | 167 |
| "in every single battle" | 68.0 | 218.60-220.62 | 288.64-290.42 | 21 | 34 |
| "get put to sleep" | 68.4 | 2402.78-2403.58 | 2471.96-2472.68 | 288 | 298 |
| "brings out the scyther" | 71.6 | 1741.96-1743.04 | 1814.62-1815.90 | 216 | 231 |
| "brings out the scyther" | 78.6 | 1662.14-1663.36 | 1741.96-1743.04 | 201 | 216 |
| "that brings out the" | 78.9 | 1661.96-1662.92 | 1741.80-1742.64 | 201 | 216 |
| "have level 12 geo" | 84.3 | 541.64-543.12 | 627.40-628.56 | 72 | 82 |
| "level 12 geo dude" | 84.3 | 541.98-543.42 | 627.72-628.78 | 72 | 82 |
| "our last full heal" | 89.3 | 2501.38-2502.32 | 2591.66-2592.72 | 302 | 312 |
| "how far brock could" | 96.1 | 168.64-169.98 | 266.08-267.02 | 18 | 30 |
| "if we get put" | 101.8 | 2402.50-2403.14 | 2504.98-2505.64 | 288 | 302 |
| "we get put to" | 101.9 | 2402.68-2403.28 | 2505.20-2505.76 | 288 | 302 |
| "brings out the scyther" | 122.4 | 1538.56-1539.70 | 1662.14-1663.36 | 176 | 201 |
| "that brings out the" | 122.8 | 1537.64-1539.14 | 1661.96-1662.92 | 176 | 201 |
| "gen brock turns out" | 128.9 | 2639.50-2641.82 | 2770.72-2772.60 | 319 | 338 |
| "it for this one" | 129.8 | 2706.78-2707.42 | 2837.18-2837.84 | 328 | 349 |
| "because of the fact" | 141.3 | 1378.36-1379.56 | 1520.84-1521.74 | 151 | 173 |
| "of the fact that" | 141.5 | 1378.90-1379.70 | 1521.24-1522.02 | 151 | 173 |
| "but this could be" | 145.4 | 1546.88-1548.82 | 1694.26-1697.02 | 178 | 205 |
| "and we can see" | 146.5 | 350.88-351.54 | 498.04-498.68 | 44 | 66 |
| "this could be the" | 146.9 | 1547.70-1549.02 | 1695.92-1697.64 | 178 | 205 |
| "we get poisoned again" | 151.8 | 1469.44-1472.14 | 1623.92-1625.42 | 165 | 193 |
| "thats available to us" | 155.3 | 2436.18-2437.42 | 2592.72-2593.78 | 293 | 312 |
| "smart brock using the" | 163.5 | 1330.72-1332.54 | 1496.08-1497.72 | 145 | 170 |
| "brock using the best" | 163.9 | 1331.28-1332.80 | 1496.66-1498.10 | 145 | 170 |
| "that brings out the" | 169.5 | 1814.42-1815.38 | 1984.92-1986.66 | 231 | 247 |
| "to see how this" | 175.2 | 1424.14-1424.80 | 1600.04-1601.22 | 158 | 185 |
| "out that brings out" | 178.3 | 1481.90-1483.32 | 1661.64-1662.80 | 167 | 200 |
| "pokemon out that brings" | 178.4 | 1481.60-1482.94 | 1661.30-1662.46 | 167 | 200 |
| "that pokemon out that" | 178.4 | 1481.34-1482.64 | 1661.08-1662.14 | 167 | 200 |
| "knock that pokemon out" | 178.4 | 1481.02-1482.24 | 1660.68-1661.96 | 167 | 200 |