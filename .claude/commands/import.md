Import game-specific assets and shared assets into DaVinci Resolve bins.

The asset catalog (which assets each game needs, plus shared folder definitions)
is in `assets/catalog.json` in this project. The asset manifest (where those
files live on THIS machine) is stored globally at `~/.resolve-mcp/manifest.json`
and is shared across all projects. Only missing or inaccessible paths trigger a
prompt — known-good paths are reused silently.

Run all commands from `C:\Programming\resolve-mcp` using `cmd.exe /c "cd /d C:\Programming\resolve-mcp && ..."`.

---

## Step 1 — Detect game version

Read `transcripts/*.json` (most recently modified). Analyze the `text` field
(first ~3000 characters is enough). Infer the game being played and map it to a
key in `assets/catalog.json` (e.g. `pokemon_crystal`).

If the game isn't in the catalog, tell the user which key you'd suggest adding
and stop. Do not proceed without a catalog match.

## Step 2 — Import shared assets (type icons, BGM, badges, Pokémon artwork)

Check whether shared asset folder paths are configured:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --check-shared"
```

Parse the JSON output:

| `status`           | Action                                                               |
|--------------------|----------------------------------------------------------------------|
| `ready`            | All paths valid — skip to Step 3                                    |
| `needs_paths`      | Prompt user for each item in `missing` and `invalid`                |
| `no_shared_assets` | No shared assets defined in catalog — skip to Step 3               |

### Gathering missing shared paths

Present the user with a table of what's needed. For each entry show:
- **Label** — human-readable description
- **Bin name** — the sub-bin it will create under "assets" in Resolve
- **Old path** (for `invalid` entries only)

Ask the user to provide the folder path for each. Accept them one at a time
or all at once — wait for a response before proceeding.

For each path the user provides, validate it exists (must be a directory), then store it:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --set-shared-path ASSET_ID "PATH""
```

If the script reports an error, tell the user and re-ask for that specific asset.

After all paths are set, re-run `--check-shared` to confirm `"status": "ready"`.

### Importing shared assets into Resolve

Optionally dry-run first:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --import-shared --dry-run"
```

Then do the real import:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --import-shared"
```

This creates sub-bins inside the "assets" bin — one per shared asset folder
(e.g. `types`, `bgm`, `badges`, `pokemon-art`). All files including those in
subfolders are imported into the corresponding sub-bin.

## Step 3 — Check the game-specific manifest

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --game GAME_KEY --check"
```

Parse the JSON output:

| `status`        | Action                                                     |
|-----------------|------------------------------------------------------------|
| `ready`         | All paths valid — skip to Step 5                          |
| `needs_paths`   | Prompt user for each item in `missing` and `invalid`       |
| `unknown_game`  | Game not in catalog — tell user, stop                      |

## Step 4 — Gather missing or invalid game-specific paths

Present the user with a table of what's needed. For each entry show:
- **Label** — human-readable description (e.g. "GSC intro short")
- **Type** — `file` or `folder`
- **Old path** (for `invalid` entries only) — the stored path that no longer works

Ask the user to provide paths. Accept them one at a time or all at once — wait
for a response before proceeding.

For each path the user provides, validate it exists, then store it:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --game GAME_KEY --set-path ASSET_ID "PATH""
```

If the script reports an error (path not found), tell the user and re-ask for
that specific asset.

After all paths are set, re-run `--check` to confirm `"status": "ready"` before
proceeding.

## Step 5 — Import game assets into Resolve

Optionally dry-run first to preview what will be imported:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --game GAME_KEY --do-import --dry-run"
```

Then do the real import:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --game GAME_KEY --do-import"
```

## Step 6 — Classify the video (Minimum Battles vs normal playthrough)

The intro plays at 4x speed for normal playthroughs, full speed (100%) for Minimum Battles Series videos. Run the classifier so `insert_intro_outro.py` picks the right speed automatically:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\detect_minimum_battles.py"
```

This is a **relay** — the script writes `plans/prompts/min-battles-<stem>.in.md` containing the transcript and a definition. YOU must:
1. Poll with Read tool until the `.in.md` appears
2. Read the transcript and classify
3. Write **only** a single JSON object to the corresponding `.out.md`:
   ```json
   {"is_minimum_battles": true|false, "pokemon_count": N, "trainers_attempted": ["A", "B"], "reasoning": "..."}
   ```

The script caches the result to `transcripts/min-battles.json` and exits.

## Step 7 — Build edited timeline (intro + shift + outro)

Dry-run first to preview the layout (the dry-run will also report which intro speed was auto-detected from the cache):

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\insert_intro_outro.py --game GAME_KEY --dry-run"
```

Then build the new timeline:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\insert_intro_outro.py --game GAME_KEY"
```

To force a specific intro speed (overrides auto-detect):

```
cmd.exe /c "... insert_intro_outro.py --game GAME_KEY --intro-speed 400"   rem 4x
cmd.exe /c "... insert_intro_outro.py --game GAME_KEY --intro-speed 100"   rem full speed
```

This creates a new timeline named `ORIGINAL_NAME (edit)` with:
- Intro prepended at frame 0 (video only on V1)
- All original clips shifted right by the intro's duration
- Outro video appended to V1 after the last clip
- Outro audio (prefer "w audio" variant) on A3 at the same position

The original timeline is preserved intact.

Report to the user:
- Game detected
- How many shared asset files were imported and into which sub-bins (or "already configured" if paths were already set)
- How many game-specific asset slots were imported and from which paths
- Whether the "assets" bin was created or already existed
- Name of the new edited timeline
