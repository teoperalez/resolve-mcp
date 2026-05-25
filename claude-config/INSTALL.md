# Claude config — cross-machine install

Snapshot of the Claude Code global + project config that this repo's automation depends on. Copied here so you can `git clone` this repo on a new machine and bootstrap Claude with the same rules, memory, and skills.

Snapshot date: 2026-05-23
Source machine: Windows, `C:\Users\teope\.claude\`

## What's in this folder

```
claude-config/
├── INSTALL.md                              (this file)
├── global-CLAUDE.md                        Copy of ~/.claude/CLAUDE.md (THE 23 RULES — global)
├── Teo Speech Style.md                     Copy of ~/.claude/Teo Speech Style.md
├── project-memory/                         18 .md files — copies of ~/.claude/projects/C--Programming-resolve-mcp/memory/
│   ├── MEMORY.md                           Index file (lists every reference + feedback)
│   ├── feedback_*.md                       Bug + behavior notes
│   └── reference_*.md                      Long-form reference docs
└── skills/                                 4 skills (full source — copies of ~/.claude/skills/<name>/)
    ├── gen1-marker-pipeline/               Gen 1 RBY auto-editor + chapter marker pipeline
    ├── gen1-leader-tracks/                 Gen 1 leader intros + battle audio routing
    ├── verify-fairlight-preset/            Fairlight preset verification (mandatory pre-render gate)
    └── final-render-cut-qa/                Post-render QA pipeline (cut audit + Codex review gate)
```

The project-level `CLAUDE.md` (the resolve-mcp-specific rules) is already tracked at the repo root (`C:\Programming\resolve-mcp\CLAUDE.md`) — no separate copy here.

## Install on a new machine

### 1. Clone the repo

```powershell
cd C:\Programming
git clone https://github.com/teoperalez/resolve-mcp.git
cd resolve-mcp
```

### 2. Install global Claude config

```powershell
# Back up any existing global CLAUDE.md
if (Test-Path "$env:USERPROFILE\.claude\CLAUDE.md") {
    Move-Item "$env:USERPROFILE\.claude\CLAUDE.md" "$env:USERPROFILE\.claude\CLAUDE.md.backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
}

# Ensure the .claude directory exists
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.claude\" | Out-Null

# Copy the global rules + speech style
Copy-Item "claude-config\global-CLAUDE.md" "$env:USERPROFILE\.claude\CLAUDE.md"
Copy-Item "claude-config\Teo Speech Style.md" "$env:USERPROFILE\.claude\Teo Speech Style.md"
```

### 3. Install project memory files

The project memory folder name is derived from the project path with backslashes replaced by `--`:

```powershell
$projectMemDir = "$env:USERPROFILE\.claude\projects\C--Programming-resolve-mcp\memory"
New-Item -ItemType Directory -Force -Path $projectMemDir | Out-Null
Copy-Item "claude-config\project-memory\*.md" $projectMemDir -Force
```

### 4. Install skills

```powershell
$skillsDir = "$env:USERPROFILE\.claude\skills"
New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null
Copy-Item "claude-config\skills\*" $skillsDir -Recurse -Force
```

After this, Claude Code will see the 4 skills (`gen1-marker-pipeline`, `gen1-leader-tracks`, `verify-fairlight-preset`, `final-render-cut-qa`) in its skill list on the next session start.

### 5. Verify

Open a new Claude Code session in `C:\Programming\resolve-mcp\` and confirm:
- The 23 Rules are loaded (Rule 6 about deleting iteration artifacts, Rule 7 about cap-at-2)
- The 4 skills appear in the skills list
- Project memory references like `feedback_src_overlap_cut_bug.md` resolve correctly when Claude searches memory

### 6. Bootstrap the rest of the pipeline (one-time)

- `pip install -r requirements.txt` (or equivalent — confirm via the project README)
- Set up DaVinci Resolve scripting: Preferences → System → General → External scripting using → Local
- Install ffmpeg + ffprobe on PATH (`winget install Gyan.FFmpeg` on Windows)
- For GPU transcription: `.venv\Scripts\pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`
- Configure `~/.resolve-mcp/manifest.json` shared paths via `python scripts/import_assets.py --set-shared-path <id> <path>` for `type_icons`, `bgm`, `badges`, `gymleaders`, `pokemon_art`, `battle_intros`, `silver_battle_intros`

## Re-syncing after upstream updates

If the source-of-truth `~/.claude/CLAUDE.md` or any skill is updated on the source machine, copy the changes back into `claude-config/` and commit:

```powershell
# Re-copy global files
Copy-Item "$env:USERPROFILE\.claude\CLAUDE.md" "claude-config\global-CLAUDE.md"
Copy-Item "$env:USERPROFILE\.claude\Teo Speech Style.md" "claude-config\Teo Speech Style.md"

# Re-copy project memory
robocopy "$env:USERPROFILE\.claude\projects\C--Programming-resolve-mcp\memory" `
         "claude-config\project-memory" `
         /MIR /XO

# Re-copy skills (mirror to remove deleted files)
robocopy "$env:USERPROFILE\.claude\skills" "claude-config\skills" `
         /MIR /XO /XD __pycache__

# Then git add + commit + push
git add claude-config/
git commit -m "sync: claude-config from source machine"
git push
```

## What's NOT in this snapshot

- **`~/.claude/skills/` skills you didn't write yourself** (e.g. `anthropic-skills:*`, `iterate-*`, `pipeline-*`, etc.) — these come from Anthropic plugin marketplaces or other sources and should be re-installed via their original channels, not committed here
- **`~/.claude/settings.json`** — machine-specific (paths, env vars, plugin configs). Re-create on the new machine
- **`~/.claude/projects/*/CONVERSATION.jsonl`** — your conversation history. Optional to copy; not included here for privacy
- **`~/.resolve-mcp/manifest.json`** — asset paths, machine-local
- **`~/.resolve-mcp/bgm-tags.json`** — BGM classifications, machine-local (but useful: copy manually if migrating)
- **`%APPDATA%\rbypc-frontend\logs\`** — RBY session logs from the overlay app; per-recording state
- **DaVinci Resolve project files** — separate (`.drp` exports + the `Fairlight\Presets\` files)

## Quick reference: skill purposes

| Skill | Purpose |
|---|---|
| `gen1-marker-pipeline` | Phase 1 (pre-Resolve): auto-editor + chapter marker injection. Phase 2 (in-Resolve): marker labelling via RBYNewLayout session log. |
| `gen1-leader-tracks` | After phase 2: insert gym leader intro videos on V1 + route leader audio across A3/A2 with -3dB crossfade. Handles Red/Blue version variants. |
| `verify-fairlight-preset` | Idempotent verification that the Fairlight mixer preset is applied + saved. Auto-applies if missing. Mandatory pre-render gate. |
| `final-render-cut-qa` | After 4K render: transcribe with loose-Whisper, scan for missed cuts, Codex adversarial review, user confirmation, source-time mapping. Last gate before delivery. |

See each skill's `SKILL.md` for full usage + the `references/` folder for spec details.
