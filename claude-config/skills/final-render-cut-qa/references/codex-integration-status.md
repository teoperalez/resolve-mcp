# Codex integration status — TODO

The skill's Step 9 (mandatory Codex adversarial review) currently runs as a **manual relay**, not automated dispatch. This file tracks why and how to fix.

## Current state (as of 2026-05-22)

**Problem.** Two attempts to dispatch Codex via the `codex:codex-rescue` subagent on Windows both returned the same failure:

```
Codex hit a sandbox shell-access failure (`CreateProcessAsUserW failed: 5`)
and could not reach the working directory at C:\Programming\... / C:\Users\teope\codex-workspace\...
```

Error code 5 = `ACCESS_DENIED`. This is a Windows sandbox/UAC issue with the Codex executable's ability to spawn child processes — independent of path.

**Workaround in use.** Step 9 of the skill writes the brief to disk and prints to the user:
```
Codex brief ready at <path>. Paste into your Codex session and write the
verdict to codex-final-render-review.md, then reply 'codex done'.
```

The skill polls for `codex-final-render-review.md` (60s intervals, max 30 min). The user manually copies the brief into Codex, Codex writes the response, the skill resumes.

This works for human-in-the-loop use but blocks `/edittimeline`'s Step 18 from running fully unattended.

## Fix paths (in order of preference)

### 1. Install `openai/codex-plugin-cc` (official OpenAI plugin)

Per a parallel investigation thread, OpenAI ships an official Claude Code plugin that delegates to the local Codex CLI via slash commands:
- `/codex:rescue --background <prompt>`
- `/codex:status`
- `/codex:result`
- `/codex:cancel`

Install:
```
/plugin marketplace add openai/codex-plugin-cc
/plugin install codex@openai-codex
/codex:setup
```

If successful, Step 9 of the skill changes from "write brief + poll for manual response" to:
```python
# Pseudo-code for the eventual Step 9 implementation
codex_job_id = invoke_slash_command(
    'codex:rescue',
    args=['--background', brief_content],
)
verdict = poll_until(
    lambda: invoke_slash_command('codex:status', [codex_job_id]) == 'complete',
    interval=60, timeout=1800,
)
result = invoke_slash_command('codex:result', [codex_job_id])
write_file('codex-final-render-review.md', result)
```

The plugin owns the Codex subprocess lifecycle + sandbox config — should bypass the `CreateProcessAsUserW` issue.

### 2. Codex CLI sandbox-bypass install

If the plugin doesn't materialize, investigate Codex CLI install options:
- `--dangerously-bypass-approvals-and-sandbox` flag (verify on Windows)
- Install Codex CLI as administrator (may avoid UAC sandboxing)
- Move Codex executable out of `%LOCALAPPDATA%` (which has stricter sandboxing) to `%PROGRAMFILES%`

Test by running `codex exec` directly from PowerShell with `--cwd C:\Programming\resolve-mcp\` and a simple read-only task.

### 3. Wrapper script via `subprocess` (bypass agent dispatch)

If neither plugin nor sandbox fix works, write a Python wrapper:
```python
import subprocess
def invoke_codex(brief_text, cwd):
    p = subprocess.run([
        r'C:\Users\teope\AppData\Local\OpenAI\Codex\bin\<latest>\codex.exe',
        'exec',
        '--prompt', brief_text,
        '--cwd', cwd,
        '--dangerously-bypass-approvals-and-sandbox',
    ], capture_output=True, text=True, timeout=1800)
    return p.stdout
```

The wrapper bypasses the `codex:codex-rescue` subagent (which has its own sandbox layer that's failing). It's also less elegant — no progress reporting, no background mode.

## Acceptance criteria for "Codex integration done"

The skill's Step 9 can return APPROVE_FOR_USER_REVIEW or REJECT_WITH_MUST_FIX **without user intervention** on a known-good case (Brock Red v3 final render + canonical cut list). The full pipeline (Step 17 render → Step 18 QA → Step 19 ship-or-rebuild) runs unattended for at least one successful PASS_CLEAN cycle.

Until that's true, the skill prints the manual-relay prompt and waits.

## Related artifacts

- `~/.claude/projects/.../memory/feedback_*.md` — relevant troubleshooting notes
- `audio-checks/.../codex-review-round3.md` — example Codex verdict that came back via manual relay
- The `codex:rescue` and `codex:setup` skills already exist in the Claude Code skill list — they're the natural integration points if dispatch can be unblocked.
