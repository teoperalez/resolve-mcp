---
name: Use Haiku subagents for simple tasks
description: User preference — delegate simple tool calls, lookups, and research to Haiku-model subagents instead of doing them in the main thread
type: feedback
originSessionId: fdcb3861-fc35-47c6-990f-ddc3ccd0f436
---
For simple tasks — single-shot tool calls, targeted file lookups, lightweight research, well-scoped grep/glob searches — spawn a subagent with `model: "haiku"` rather than handling them in the main thread.

**Why:** Haiku is fast and cheap, and offloading simple work keeps the main context window clean for the harder reasoning. The user explicitly asked for this as a default behavior.

**How to apply:**
- Use Agent with `model: "haiku"` for: locating a file, reading a known path to extract one fact, running a grep and summarizing matches, fetching a URL, simple "where is X defined" questions.
- Keep complex reasoning, multi-file synthesis, design work, and code editing in the main thread (or a more capable model).
- When in doubt — if the task is one tool call plus a one-sentence summary — it's a Haiku subagent task.
- Subagent types that benefit most: `Explore` (search), `general-purpose` (one-off lookups), `claude-code-guide` (doc questions).

**Also validated — parallel vision/frame analysis:**
Haiku subagents handle well-scoped, parallel image-by-image analysis effectively (e.g., reading 40+ frames each across 6 subagents to pinpoint a transition frame). Pattern: dispatch one subagent per item, each gets its own file list and a clear single-decision instruction, returns a single JSON object. Works for the refine_battle_ends.py "find the precise end frame" workflow in resolve-mcp.

**Also validated — sequential frame classification with a decision rule:**
For "find the first frame matching pattern X" tasks (e.g., find_member_carousel.py), one Haiku subagent reads a sequence of candidate frames + their adjacent-frame pairs, applies a binary classification + decision rule, and writes the JSON directly to a relay .out.md file. Phase-1-then-phase-2 strategy in the prompt (find candidate first, then verify with adjacent frame) keeps the read count low.
