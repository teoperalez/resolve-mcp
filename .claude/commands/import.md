Import game-specific assets into a DaVinci Resolve "assets" bin.

The asset catalog (which assets each game needs) is in `assets/catalog.json`
in this project. The asset manifest (where those files live on THIS machine) is
stored globally at `~/.resolve-mcp/manifest.json` and is shared across all
projects. Only missing or inaccessible paths trigger a prompt — known-good paths
are reused silently.

Run all commands from `C:\Programming\resolve-mcp` using `cmd.exe /c "cd /d C:\Programming\resolve-mcp && ..."`.

---

## Step 1 — Detect game version

Read `transcripts/*.json` (most recently modified). Analyze the `text` field
(first ~3000 characters is enough). Infer the game being played and map it to a
key in `assets/catalog.json` (e.g. `pokemon_crystal`).

If the game isn't in the catalog, tell the user which key you'd suggest adding
and stop. Do not proceed without a catalog match.

## Step 2 — Check the global manifest

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --game GAME_KEY --check"
```

Parse the JSON output:

| `status`        | Action                                                     |
|-----------------|------------------------------------------------------------|
| `ready`         | All paths valid — skip to Step 4                          |
| `needs_paths`   | Prompt user for each item in `missing` and `invalid`       |
| `unknown_game`  | Game not in catalog — tell user, stop                      |

## Step 3 — Gather missing or invalid paths

Present the user with a table of what's needed. For each entry show:
- **Label** — human-readable description (e.g. "B-roll gameplay footage folder")
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

## Step 4 — Import into Resolve

Optionally dry-run first to preview what will be imported:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --game GAME_KEY --do-import --dry-run"
```

Then do the real import:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\import_assets.py --game GAME_KEY --do-import"
```

## Step 5 — Build edited timeline (intro + shift + outro)

Dry-run first to preview the layout:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\insert_intro_outro.py --game GAME_KEY --dry-run"
```

Then build the new timeline:

```
cmd.exe /c "cd /d C:\Programming\resolve-mcp && .venv\Scripts\python scripts\insert_intro_outro.py --game GAME_KEY"
```

This creates a new timeline named `ORIGINAL_NAME (edit)` with:
- Intro prepended at frame 0 (video only on V1)
- All original clips shifted right by the intro's duration
- Outro video appended to V1 after the last clip
- Outro audio (prefer "w audio" variant) on A3 at the same position

The original timeline is preserved intact.

Report to the user:
- Game detected
- How many asset slots were imported and from which paths
- Whether the "assets" bin was created or already existed
- Name of the new edited timeline
