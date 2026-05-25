# Version detection

Determines whether to use `Yellow` or `Red/Blue` asset variants.

## Source: session log `meta.json`

Each RBYNewLayout session writes a `meta.json` at `%APPDATA%\rbypc-frontend\logs\<sessionId>\meta.json`. Schema:

```json
{
  "pokemon": "Victreebel",
  "starter": 71,
  "runType": "Ultra Minimum Battles",
  "version": "Red and Blue",
  "battleRules": "Ultra Minimum Battles",
  "specialRules": {...},
  "startedAt": "2026-05-16T04:28:56.871Z",
  "starterName": "UltraBel2",
  "attempt": 3
}
```

The `version` field is the authoritative source for asset variant selection.

## Mapping

`detect_version_from_meta()` (in `leader_asset_map.py`):

| meta.json `version` | Skill version |
|---|---|
| `"Yellow"` | `yellow` |
| `"Red"` | `red_blue` |
| `"Blue"` | `red_blue` |
| `"Red and Blue"` | `red_blue` |
| `"Red/Blue"` | `red_blue` (anything containing "red" or "blue") |
| `""` / missing | `None` (error: user must pass explicit `--version`) |
| anything else | `None` (error: user must pass explicit `--version`) |

The match is case-insensitive and uses substring containment on "red" or "blue".

## Auto-detect flow

1. `--session-dir <path>` provided? Use that.
2. Else: scan `%APPDATA%\rbypc-frontend\logs\<*>` for subdirs containing `events.json`.
3. Sort by mtime descending; pick the latest.
4. Load `meta.json` from that dir.
5. Parse `version` field via `detect_version_from_meta()`.
6. If None → error out with message asking user to pass `--version` explicit.

## Override

`--version yellow` or `--version red_blue` skips auto-detect entirely.

Use this when:
- No session log exists for the recording
- Multiple sessions are present and the latest isn't the right one (use `--session-dir` to point at the specific session, OR just override `--version`)
- The session log's `version` field is wrong (rare but possible)
- Running on a non-RBY project for testing

## Cross-reference

The `version` field is also used by:
- The RBYNewLayout overlay app itself to switch backgrounds and styling
- This skill (asset variant selection)
- A future `gen1-edit-timeline` skill (intro graphics — different opening cards per version)

If the version detected here is wrong, ALL downstream version-dependent operations will be wrong too. Spot-check by inspecting `meta.json` directly before kicking off the skill:

```powershell
Get-Content "$env:APPDATA\rbypc-frontend\logs\<latest>\meta.json" | ConvertFrom-Json | Select-Object version, pokemon, runType
```

## Victreebel example (verified 2026-05-16 recording)

```json
{
  "pokemon": "Victreebel",
  "runType": "Ultra Minimum Battles",
  "version": "Red and Blue",
  ...
}
```

`detect_version_from_meta()` → `'red_blue'` → the skill will pick `SurgeBlue.mp4`, `ErikaBlue.mp4`, `KogaBlue.mp4`, `SabrinaBlue.mp4`, `BlaineBlue.mp4`, `GiovanniBlue.mp4`, `ChampionBlue.mp4` for those leader battles (and the base file for Brock, Misty, Lorelei, Bruno, Agatha, Lance which have no Blue variant).
