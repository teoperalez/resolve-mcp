#!/usr/bin/env python3
"""
codex_watcher.py — Terminal B watcher for the Claude↔Codex coordination loop.

Polls the .codex-sync/ mailbox every WATCHER_POLL_INTERVAL_S seconds. When it
finds an unmet Claude sentinel (a new brief, or an APPROVE_FOR_QA review), it
invokes Codex via `codex exec` (or `codex exec resume`) with the sentinel's
content on stdin, captures the response, and resumes polling.

Lives at <project>/.codex-sync/scripts/codex_watcher.py — self-contained, stdlib only.

Run:    python .codex-sync\\scripts\\codex_watcher.py
Halt:   Ctrl+C  (or /claude-codex-sync-halt from Terminal A — watcher exits at
        the next poll when status.halted == true)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ─── Config ────────────────────────────────────────────────────────────────────

WATCHER_POLL_INTERVAL_S = 20          # how often to scan the mailbox
SUBPROCESS_TIMEOUT_S = 30 * 60        # max Codex turn duration (30 min)
HEARTBEAT_STALE_AFTER_BEATS = 5       # status skill considers us stale after 5 * poll interval
ATOMIC_TMP_SUFFIX = ".tmp"            # temp file suffix for atomic writes
STATUS_FILENAME = "status.json"
HEARTBEAT_FILENAME = "codex-watcher-heartbeat.json"
STREAM_LOG_FILENAME = "codex-stream.log"
ERROR_LOG_FILENAME = "codex-watcher-error.log"
KICKOFF_FILENAME = "codex-kickoff.md"

# ─── Setup ─────────────────────────────────────────────────────────────────────

def project_root() -> Path:
    """Project root = parent of .codex-sync/ (which contains scripts/codex_watcher.py)."""
    here = Path(__file__).resolve()
    # here = <project>/.codex-sync/scripts/codex_watcher.py
    return here.parent.parent.parent

def mailbox() -> Path:
    return project_root() / ".codex-sync"

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))

def write_json_atomic(p: Path, data: dict) -> None:
    tmp = p.with_name(p.name + ATOMIC_TMP_SUFFIX)
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, p)

def write_text_atomic(p: Path, content: str) -> None:
    tmp = p.with_name(p.name + ATOMIC_TMP_SUFFIX)
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, p)

def log_error(mb: Path, msg: str) -> None:
    log = mb / ERROR_LOG_FILENAME
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"[{now_iso()}] {msg}\n")

# ─── Heartbeat ─────────────────────────────────────────────────────────────────

def write_heartbeat(mb: Path, state: str, consumed_iter: int, consumed_cycle: int) -> None:
    hb = {
        "last_beat": now_iso(),
        "poll_interval_s": WATCHER_POLL_INTERVAL_S,
        "watcher_pid": os.getpid(),
        "current_state": state,                # polling | executing | idle-halt | error
        "consumed_through_iter": consumed_iter,
        "consumed_through_cycle": consumed_cycle,
    }
    try:
        write_json_atomic(mb / HEARTBEAT_FILENAME, hb)
    except OSError as e:
        log_error(mb, f"heartbeat write failed: {e}")

# ─── Status I/O ────────────────────────────────────────────────────────────────

def load_status(mb: Path) -> dict:
    return read_json(mb / STATUS_FILENAME)

def update_status(mb: Path, mutator) -> dict:
    """Read-modify-write status.json atomically. Mutator takes dict, returns dict."""
    st = load_status(mb)
    new_st = mutator(st)
    write_json_atomic(mb / STATUS_FILENAME, new_st)
    return new_st

# ─── YAML frontmatter parsing (minimal — for `verdict:` and `kind:`) ───────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.+?)\n---\s*\n", re.DOTALL)
_SIMPLE_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")

def parse_frontmatter(text: str) -> dict:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    body = m.group(1)
    out: dict = {}
    for line in body.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(" ") or line.startswith("\t"):
            # nested — ignore for the simple use here
            continue
        kv = _SIMPLE_KV_RE.match(line)
        if kv:
            k = kv.group(1).strip()
            v = kv.group(2).strip().strip('"').strip("'")
            out[k] = v
    return out

# ─── Codex invocation ──────────────────────────────────────────────────────────

def codex_binary(st: dict) -> str:
    """Return the configured Codex binary path, validating it exists."""
    binary = st.get("codex", {}).get("binary", "")
    if binary and Path(binary).exists():
        return binary
    # Fallback: discover newest install
    bins_root = Path(r"C:\Users\teope\AppData\Local\OpenAI\Codex\bin")
    if bins_root.exists():
        candidates = sorted(
            (p for p in bins_root.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for c in candidates:
            exe = c / "codex.exe"
            if exe.exists():
                return str(exe)
    raise FileNotFoundError(f"Codex binary not found (configured: {binary!r}).")

def build_codex_argv(st: dict, output_path: Path, is_first_call: bool) -> list[str]:
    """Build the codex exec argv list."""
    binary = codex_binary(st)
    model = st.get("codex", {}).get("model") or "gpt-5.5"
    root = str(project_root())

    argv = [binary, "exec"]

    if not is_first_call:
        strategy = st.get("codex", {}).get("session_resume_strategy", "resume-last")
        first_session = st.get("codex", {}).get("first_session_id")
        argv.append("resume")
        if strategy == "resume-by-id" and first_session:
            argv.append(first_session)
        else:
            argv.append("--last")

    argv += [
        "--json",
        "-c", 'approval_policy="never"',
        "-c", 'sandbox_mode="workspace-write"',
        "-c", "sandbox_workspace_write.network_access=true",
        "-m", model,
        "-o", str(output_path),
    ]

    # `-C` is only valid on `codex exec` (not `codex exec resume`).
    # Sandbox settings are passed via `-c` above so resume turns keep them too.
    if is_first_call:
        argv += ["-C", root]
        argv += ["--skip-git-repo-check"]

    argv.append("-")  # read prompt from stdin
    return argv

# JSONL session id extraction — try several common keys
_SESSION_ID_KEYS = ("session_id", "thread_id", "id", "conversation_id")

def try_extract_session_id(jsonl_line: str) -> str | None:
    try:
        ev = json.loads(jsonl_line)
    except json.JSONDecodeError:
        return None
    if isinstance(ev, dict):
        # Look for session-start-like events
        for key in _SESSION_ID_KEYS:
            v = ev.get(key)
            if isinstance(v, str) and re.match(r"^[0-9a-fA-F-]{36}$", v):
                return v
        # Nested
        for nest_key in ("session", "thread", "metadata"):
            nest = ev.get(nest_key)
            if isinstance(nest, dict):
                for key in _SESSION_ID_KEYS:
                    v = nest.get(key)
                    if isinstance(v, str) and re.match(r"^[0-9a-fA-F-]{36}$", v):
                        return v
    return None

def invoke_codex(mb: Path, st: dict, prompt_text: str, output_path: Path,
                 is_first_call: bool) -> tuple[int, str | None]:
    """
    Invoke Codex with prompt_text on stdin, write final message to output_path,
    tee JSONL to codex-stream.log. Returns (exit_code, captured_session_id).
    """
    argv = build_codex_argv(st, output_path, is_first_call=is_first_call)
    stream_log = mb / STREAM_LOG_FILENAME
    captured_id: str | None = None

    with stream_log.open("a", encoding="utf-8", errors="replace") as log_fh:
        log_fh.write(f"\n\n=== {now_iso()} === invoke (first_call={is_first_call}) ===\n")
        log_fh.write(f"argv: {' '.join(argv)}\n")
        log_fh.flush()

        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(project_root()),
            )
        except FileNotFoundError as e:
            log_error(mb, f"codex binary not launchable: {e}")
            return 127, None

        assert proc.stdin and proc.stdout
        try:
            proc.stdin.write(prompt_text)
            proc.stdin.close()
        except (BrokenPipeError, OSError) as e:
            log_error(mb, f"failed to write stdin to codex: {e}")

        start = time.monotonic()
        try:
            for raw in proc.stdout:
                # Tee to log
                log_fh.write(raw)
                log_fh.flush()
                # Try to extract session_id from JSONL events
                if captured_id is None:
                    sid = try_extract_session_id(raw.strip())
                    if sid:
                        captured_id = sid
                # Mirror to terminal so the user can see Codex progress live
                sys.stdout.write(raw)
                sys.stdout.flush()
                # Bump heartbeat every event so a long-running turn stays visible
                write_heartbeat(mb, "executing",
                                int(st.get("current_iteration", 0)),
                                int(st.get("current_cycle", 0)))
                if time.monotonic() - start > SUBPROCESS_TIMEOUT_S:
                    proc.kill()
                    log_error(mb, f"codex turn exceeded {SUBPROCESS_TIMEOUT_S}s; killed")
                    return 124, captured_id
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            log_error(mb, "codex did not exit cleanly after stdout drained")
            return 124, captured_id

    return proc.returncode, captured_id

# ─── Mailbox scanning ──────────────────────────────────────────────────────────

_BRIEF_RE = re.compile(r"^iter-(\d{2})-claude-brief\.md$")
_REVIEW_RE = re.compile(r"^iter-(\d{2})-claude-review\.md$")
_EXECUTION_RE = re.compile(r"^iter-(\d{2})-codex-execution\.md$")
_QA_RE = re.compile(r"^iter-(\d{2})-codex-qa\.md$")

def find_next_action(mb: Path) -> tuple[str, int] | None:
    """
    Returns ("execute", iter_num) or ("qa", iter_num) for the next thing Codex
    must do, or None if nothing pending.
    """
    files = {p.name for p in mb.iterdir() if p.is_file()}

    briefs = sorted(int(m.group(1)) for m in (_BRIEF_RE.match(n) for n in files) if m)
    reviews = sorted(int(m.group(1)) for m in (_REVIEW_RE.match(n) for n in files) if m)
    executions = {int(m.group(1)) for m in (_EXECUTION_RE.match(n) for n in files) if m}
    qas = {int(m.group(1)) for m in (_QA_RE.match(n) for n in files) if m}

    # Check briefs first — execute is the default branch
    for n in briefs:
        if n not in executions:
            return ("execute", n)

    # Then QAs — any APPROVE_FOR_QA review without a matching qa file
    for n in reviews:
        if n in qas:
            continue
        review_path = mb / f"iter-{n:02d}-claude-review.md"
        try:
            text = review_path.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = parse_frontmatter(text)
        if fm.get("verdict") == "APPROVE_FOR_QA":
            return ("qa", n)

    return None

# ─── The main loop ─────────────────────────────────────────────────────────────

def build_codex_prompt(mb: Path, st: dict, action_kind: str, iter_num: int,
                       is_first_call: bool) -> str:
    """Assemble the stdin payload for Codex."""
    pieces: list[str] = []

    if is_first_call:
        kickoff = mb / KICKOFF_FILENAME
        if kickoff.exists():
            pieces.append(kickoff.read_text(encoding="utf-8"))
            pieces.append("\n\n---\n\n# YOUR FIRST PROMPT\n")
        else:
            log_error(mb, f"kickoff file missing: {kickoff}")

    if action_kind == "execute":
        brief_path = mb / f"iter-{iter_num:02d}-claude-brief.md"
        pieces.append(brief_path.read_text(encoding="utf-8"))
        pieces.append(
            "\n\n---\n\n"
            "EXECUTE THIS BRIEF NOW. Read the files listed in your kickoff "
            "prompt (plan.md, manifest.json, status.json, prior execution "
            "reports in this cycle). Stage artifacts under "
            f".codex-sync/artifacts/iter-{iter_num:02d}/. Write your execution "
            f"report to .codex-sync/iter-{iter_num:02d}-codex-execution.md LAST "
            "(use the .tmp + rename pattern for atomicity). Then STOP — the "
            "watcher will manage the next step.\n"
        )
    elif action_kind == "qa":
        review_path = mb / f"iter-{iter_num:02d}-claude-review.md"
        pieces.append(review_path.read_text(encoding="utf-8"))
        pieces.append(
            "\n\n---\n\n"
            "RUN QA NOW. Above is Claude's APPROVE_FOR_QA review with the QA "
            "checklist. Execute every item. You may fix MINOR issues per "
            "`qa_scope.may_fix`. You may NOT make changes the review's "
            "`qa_scope.may_not_fix` denylist forbids. Write your QA report to "
            f".codex-sync/iter-{iter_num:02d}-codex-qa.md LAST (use .tmp + "
            "rename). Verdict must be PASS | MINOR_FIXED | MAJOR_ESCALATE.\n"
        )
    else:
        raise ValueError(f"unknown action_kind: {action_kind}")

    return "".join(pieces)

def maybe_warn_cycle_change(mb: Path, last_seen_cycle: int, st: dict) -> bool:
    """If the cycle bumped while we were running, warn loudly."""
    cur = int(st.get("current_cycle", 0))
    if cur != last_seen_cycle:
        msg = (
            f"\n!!! CYCLE CHANGE DETECTED: was cycle {last_seen_cycle}, now {cur}.\n"
            "The planner has fired a postmortem. Codex's resume-last session is "
            "STALE for the new cycle. Stop me (Ctrl+C) and restart with "
            "`python .codex-sync\\scripts\\codex_watcher.py` to start a fresh "
            "Codex session for the new cycle.\n"
        )
        sys.stderr.write(msg)
        sys.stderr.flush()
        log_error(mb, msg.strip())
        return True
    return False

def main() -> int:
    # Real-time output even when redirected to a pipe / file
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except AttributeError:
        pass  # Python < 3.7

    mb = mailbox()
    if not mb.exists() or not (mb / STATUS_FILENAME).exists():
        sys.stderr.write(
            f"No .codex-sync/ mailbox found at {mb}. "
            "Run /claude-codex-sync-init in Claude first.\n"
        )
        return 1

    # Record startup in status.json
    update_status(mb, lambda st: {
        **st,
        "watcher": {
            **st.get("watcher", {}),
            "pid": os.getpid(),
            "started_at": now_iso(),
            "current_state": "polling",
        }
    })

    print(f"codex-watcher started.")
    print(f"  pid:     {os.getpid()}")
    print(f"  mailbox: {mb}")
    print(f"  poll:    every {WATCHER_POLL_INTERVAL_S}s")
    print(f"  timeout: {SUBPROCESS_TIMEOUT_S}s per Codex turn")
    print("Ctrl+C to stop. Watcher also exits when status.halted == true.")
    print()

    last_seen_cycle = -1

    try:
        while True:
            try:
                st = load_status(mb)
            except (OSError, json.JSONDecodeError) as e:
                log_error(mb, f"status.json read failed: {e}")
                time.sleep(WATCHER_POLL_INTERVAL_S)
                continue

            if st.get("halted"):
                print(f"[{now_iso()}] status.halted == true — exiting.")
                write_heartbeat(mb, "idle-halt",
                                int(st.get("current_iteration", 0)),
                                int(st.get("current_cycle", 0)))
                return 0

            current_cycle = int(st.get("current_cycle", 0))
            if last_seen_cycle == -1:
                last_seen_cycle = current_cycle
            elif current_cycle != last_seen_cycle:
                maybe_warn_cycle_change(mb, last_seen_cycle, st)
                # Stay running — user is expected to bounce us. But fall through
                # to keep polling so we don't miss a brief.

            write_heartbeat(mb, "polling",
                            int(st.get("current_iteration", 0)),
                            current_cycle)

            action = find_next_action(mb)
            if action is None:
                time.sleep(WATCHER_POLL_INTERVAL_S)
                continue

            kind, iter_num = action
            is_first_call = (
                st.get("codex", {}).get("first_session_id") is None
                and not list(mb.glob("iter-*-codex-execution.md"))
            )

            print(f"\n[{now_iso()}] {'EXECUTE' if kind == 'execute' else 'QA'} "
                  f"iter-{iter_num:02d} (first_call={is_first_call})")

            output_name = (
                f"iter-{iter_num:02d}-codex-execution.md" if kind == "execute"
                else f"iter-{iter_num:02d}-codex-qa.md"
            )
            output_tmp = mb / (output_name + ATOMIC_TMP_SUFFIX)
            output_final = mb / output_name

            prompt = build_codex_prompt(mb, st, kind, iter_num, is_first_call)

            rc, captured_id = invoke_codex(mb, st, prompt, output_tmp, is_first_call)

            if rc == 0 and output_tmp.exists() and output_tmp.stat().st_size > 0:
                os.replace(output_tmp, output_final)
                print(f"[{now_iso()}] wrote {output_final.name}")
            elif rc == 124:
                # Timeout — write a synthetic TIMEOUT execution
                if kind == "execute":
                    synthetic = (
                        "---\n"
                        f"iteration: {iter_num}\n"
                        f"cycle: {current_cycle}\n"
                        f"elapsed_seconds: {SUBPROCESS_TIMEOUT_S}\n"
                        "status: TIMEOUT\n"
                        f"codex_model: {st.get('codex', {}).get('model', 'gpt-5.5')}\n"
                        "codex_session_id: unknown\n"
                        "---\n\n"
                        "## What I did this iteration\n"
                        f"- Codex turn exceeded the {SUBPROCESS_TIMEOUT_S}s watcher "
                        "timeout. The subprocess was killed. No execution report "
                        "was written by Codex itself.\n"
                        f"- Stream log tail: see `.codex-sync/{STREAM_LOG_FILENAME}`.\n\n"
                        "## Open questions for Claude\n"
                        "- Was Codex stuck in an infinite tool-use loop? Inspect "
                        f"the stream log and consider whether the brief was "
                        "ambiguous enough to send Codex spinning.\n"
                    )
                    write_text_atomic(output_final, synthetic)
                    print(f"[{now_iso()}] wrote synthetic TIMEOUT {output_final.name}")
            elif rc != 0:
                # Non-timeout failure — write synthetic ERROR
                synthetic = (
                    "---\n"
                    f"iteration: {iter_num}\n"
                    f"cycle: {current_cycle}\n"
                    "elapsed_seconds: 0\n"
                    "status: ERROR\n"
                    f"codex_model: {st.get('codex', {}).get('model', 'gpt-5.5')}\n"
                    "codex_session_id: unknown\n"
                    "---\n\n"
                    "## What I did this iteration\n"
                    f"- Codex subprocess exited with code {rc}. See "
                    f"`.codex-sync/{STREAM_LOG_FILENAME}` and "
                    f"`.codex-sync/{ERROR_LOG_FILENAME}` for diagnostics.\n\n"
                    "## Open questions for Claude\n"
                    "- Auth issue? Network blip? Sandbox refusal? Triage via the logs.\n"
                )
                write_text_atomic(output_final, synthetic)
                log_error(mb, f"codex rc={rc} for iter-{iter_num:02d} {kind}")
                print(f"[{now_iso()}] wrote synthetic ERROR {output_final.name}")

            # Update status with consumed iter + session id (if captured)
            def _u(st: dict) -> dict:
                codex = dict(st.get("codex", {}))
                if captured_id and codex.get("first_session_id") is None:
                    codex["first_session_id"] = captured_id
                if captured_id:
                    codex["last_session_id"] = captured_id
                return {
                    **st,
                    "codex": codex,
                    "last_codex_status": (
                        "delivered" if rc == 0 else
                        "TIMEOUT" if rc == 124 else "ERROR"
                    ),
                    "last_codex_status_path": f".codex-sync/{output_name}",
                    "last_tick": now_iso(),
                }
            update_status(mb, _u)

            # Clean up any leftover .tmp
            for stale in mb.glob("*.tmp"):
                try:
                    stale.unlink()
                except OSError:
                    pass

            last_seen_cycle = current_cycle
            # Brief breath before resuming poll
            time.sleep(2)

    except KeyboardInterrupt:
        print(f"\n[{now_iso()}] interrupted — exiting cleanly.")
        write_heartbeat(mb, "idle-halt", 0, 0)
        return 0
    except Exception as e:  # noqa: BLE001 — last-resort guard
        log_error(mb, f"watcher fatal: {type(e).__name__}: {e}")
        write_heartbeat(mb, "error", 0, 0)
        raise

if __name__ == "__main__":
    sys.exit(main())
