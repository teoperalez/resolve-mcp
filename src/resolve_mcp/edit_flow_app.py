from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from string import Formatter
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def find_repo_dir() -> Path:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([exe_dir, exe_dir.parent, Path.cwd()])
    else:
        source_dir = Path(__file__).resolve()
        candidates.extend([source_dir.parents[2], Path.cwd()])
    for candidate in candidates:
        if (candidate / "pyproject.toml").exists() and (candidate / "scripts").is_dir():
            return candidate
    return candidates[0]


REPO_DIR = find_repo_dir()
DEFAULT_CONFIG = REPO_DIR / "config" / "edit_flow_profiles.json"


def default_python() -> str:
    venv_python = REPO_DIR / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def open_path(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    webbrowser.open(path.as_uri())


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


class SafeFormat(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def expand_templates(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        previous = value
        for _ in range(6):
            current = previous.format_map(SafeFormat(mapping))
            if current == previous:
                return current
            previous = current
        return previous
    if isinstance(value, list):
        return [expand_templates(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: expand_templates(item, mapping) for key, item in value.items()}
    return value


@dataclass
class Step:
    id: str
    title: str
    command: list[str] = field(default_factory=list)
    optional: bool = False
    skip_unless_all_exist: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        return cls(
            id=str(data.get("id") or data.get("title") or "step"),
            title=str(data.get("title") or data.get("id") or "Step"),
            command=[str(part) for part in data.get("command") or []],
            optional=bool(data.get("optional", False)),
            skip_unless_all_exist=[str(item) for item in data.get("skip_unless_all_exist") or []],
        )


@dataclass
class HtmlReview:
    label: str
    html: Path
    decisions: Path
    part: str = ""


@dataclass
class Profile:
    id: str
    name: str
    description: str
    project_dir: Path
    codex_dir: Path
    paths: dict[str, Path]
    html_reviews: list[HtmlReview]
    prepare_steps: list[Step]
    finish_steps: list[Step]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        base_mapping = {
            "repo": str(REPO_DIR),
            "python": default_python(),
            "project_dir": str(Path(data["project_dir"])),
            "codex_dir": str(Path(data["codex_dir"])),
        }
        raw_paths = data.get("paths") or {}
        expanded_path_strings: dict[str, str] = {}
        mapping = dict(base_mapping)
        for _ in range(6):
            changed = False
            for key, value in raw_paths.items():
                expanded = str(value).format_map(SafeFormat(mapping))
                if mapping.get(key) != expanded:
                    changed = True
                mapping[key] = expanded
                expanded_path_strings[key] = expanded
            if not changed:
                break

        html_reviews = []
        for item in data.get("html_reviews") or []:
            expanded = expand_templates(item, mapping)
            html_reviews.append(
                HtmlReview(
                    label=str(expanded.get("label") or "Review"),
                    html=Path(expanded["html"]),
                    decisions=Path(expanded["decisions"]),
                    part=str(expanded.get("part") or ""),
                )
            )

        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            description=str(data.get("description") or ""),
            project_dir=Path(mapping["project_dir"]),
            codex_dir=Path(mapping["codex_dir"]),
            paths={key: Path(value) for key, value in expanded_path_strings.items()},
            html_reviews=html_reviews,
            prepare_steps=[Step.from_dict(expand_templates(item, mapping)) for item in data.get("prepare_steps") or []],
            finish_steps=[Step.from_dict(expand_templates(item, mapping)) for item in data.get("finish_steps") or []],
        )

    def path(self, key: str) -> Path:
        try:
            return self.paths[key]
        except KeyError as exc:
            raise KeyError(f"Profile {self.name!r} has no path key {key!r}") from exc

    def mapping(self) -> dict[str, str]:
        out = {
            "repo": str(REPO_DIR),
            "python": default_python(),
            "project_dir": str(self.project_dir),
            "codex_dir": str(self.codex_dir),
        }
        out.update({key: str(value) for key, value in self.paths.items()})
        return out


@dataclass
class Candidate:
    key: str
    source: str
    decision: str
    raw: dict[str, Any]
    part: str = ""
    start_sec: float | None = None
    end_sec: float | None = None
    confidence: str = ""
    kind: str = ""
    reason: str = ""

    @classmethod
    def from_raw(cls, key: str, source: str, raw: dict[str, Any], decision: str) -> "Candidate":
        start = raw.get("start_sec", raw.get("source_start_sec"))
        end = raw.get("end_sec", raw.get("source_end_sec"))
        return cls(
            key=key,
            source=source,
            decision=decision,
            raw=dict(raw),
            part=str(raw.get("part") or ""),
            start_sec=float(start) if start is not None else None,
            end_sec=float(end) if end is not None else None,
            confidence=str(raw.get("confidence") or ""),
            kind=str(raw.get("type") or raw.get("label") or ""),
            reason=str(raw.get("reason") or ""),
        )

    def as_tree_values(self) -> tuple[str, str, str, str, str, str, str, str]:
        start = "" if self.start_sec is None else f"{self.start_sec:.2f}"
        end = "" if self.end_sec is None else f"{self.end_sec:.2f}"
        return (
            self.decision.upper(),
            self.source,
            self.part,
            start,
            end,
            self.confidence,
            self.kind,
            self.reason[:220],
        )


def load_profiles(path: Path) -> list[Profile]:
    data = load_json(path)
    if data.get("schema") != "resolve_edit_flow_profiles_v1":
        raise RuntimeError(f"Unsupported profile schema in {path}")
    return [Profile.from_dict(item) for item in data.get("profiles") or []]


def parse_jsonish(text: str) -> Any:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        first = min([idx for idx in (raw.find("["), raw.find("{")) if idx >= 0], default=-1)
        last = max(raw.rfind("]"), raw.rfind("}"))
        if first >= 0 and last > first:
            return json.loads(raw[first:last + 1])
        raise


def normalize_candidate_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("cuts", "candidates", "source_cuts", "narrative_cuts"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [dict(item) for item in rows if isinstance(item, dict)]
    raise RuntimeError("LLM output must be a JSON array or an object containing a cuts/candidates array.")


def probe_resolve() -> dict[str, Any]:
    script_dir = REPO_DIR / "scripts"
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    import _resolve_env  # noqa: F401
    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError(
            "Could not connect to DaVinci Resolve. Check Resolve is open and "
            "Preferences > General > External scripting using is set to Local."
        )
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        raise RuntimeError("No current Resolve project.")
    timeline = project.GetCurrentTimeline()
    return {
        "project": {
            "name": project.GetName(),
            "timeline_count": int(project.GetTimelineCount() or 0),
            "timelineFrameRate": project.GetSetting("timelineFrameRate"),
            "timelineResolutionWidth": project.GetSetting("timelineResolutionWidth"),
            "timelineResolutionHeight": project.GetSetting("timelineResolutionHeight"),
        },
        "timeline": {
            "name": timeline.GetName() if timeline else None,
            "start_frame": int(timeline.GetStartFrame()) if timeline else None,
            "video_tracks": int(timeline.GetTrackCount("video") or 0) if timeline else 0,
            "audio_tracks": int(timeline.GetTrackCount("audio") or 0) if timeline else 0,
        },
        "page": resolve.GetCurrentPage(),
    }


class StepRunner:
    def __init__(self, app: "EditFlowApp") -> None:
        self.app = app
        self.thread: threading.Thread | None = None
        self.cancel_requested = False

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, steps: list[Step], label: str) -> None:
        if self.running:
            raise RuntimeError("A step batch is already running.")
        self.cancel_requested = False
        self.thread = threading.Thread(target=self._run, args=(steps, label), daemon=True)
        self.thread.start()

    def cancel(self) -> None:
        self.cancel_requested = True

    def _run(self, steps: list[Step], label: str) -> None:
        profile = self.app.profile
        if profile is None:
            self.app.post_event("error", "No profile selected.")
            return
        self.app.post_event("log", f"\n=== {label} ===")
        for step in steps:
            if self.cancel_requested:
                self.app.post_event("error", "Step batch cancelled before starting the next command.")
                return
            missing = [str(profile.path(key)) for key in step.skip_unless_all_exist if not profile.path(key).exists()]
            if missing:
                self.app.post_event("log", f"\nSKIP {step.id}: missing optional artifact(s):")
                for item in missing:
                    self.app.post_event("log", f"  - {item}")
                continue
            self.app.post_event("step", (step.id, "running"))
            self.app.post_event("log", f"\n--- {step.title} ---")
            try:
                self._run_command(step)
            except Exception as exc:
                self.app.post_event("step", (step.id, "failed"))
                if step.optional:
                    self.app.post_event("log", f"OPTIONAL STEP FAILED: {exc}")
                    continue
                self.app.post_event("error", f"{step.title} failed: {exc}")
                return
            self.app.post_event("step", (step.id, "done"))
        self.app.post_event("done", label)

    def _run_command(self, step: Step) -> None:
        if not step.command:
            return
        command = step.command
        self.app.post_event("log", " ".join(f'"{part}"' if " " in part else part for part in command))
        process = subprocess.Popen(
            command,
            cwd=str(REPO_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        for line in process.stdout:
            self.app.post_event("log", line.rstrip())
            if self.cancel_requested:
                process.terminate()
                raise RuntimeError("Cancelled.")
        code = process.wait()
        if code != 0:
            raise RuntimeError(f"Command exited with code {code}.")


class EditFlowApp(tk.Tk):
    def __init__(self, config_path: Path) -> None:
        super().__init__()
        self.title("Resolve Edit Flow")
        self.geometry("1260x820")
        self.minsize(980, 640)

        self.config_path = config_path
        self.profiles = load_profiles(config_path)
        self.profile: Profile | None = self.profiles[0] if self.profiles else None
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.runner = StepRunner(self)
        self.candidates: dict[str, Candidate] = {}
        self.step_rows: dict[str, str] = {}

        self._build_ui()
        self._load_profile_into_ui()
        self.after(120, self._poll_events)
        self.after(400, self.refresh_resolve_async)

    def post_event(self, kind: str, payload: Any) -> None:
        self.events.put((kind, payload))

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=10)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Project").grid(row=0, column=0, sticky="w")
        self.profile_var = tk.StringVar()
        self.profile_combo = ttk.Combobox(
            top,
            textvariable=self.profile_var,
            values=[profile.name for profile in self.profiles],
            state="readonly",
        )
        self.profile_combo.grid(row=0, column=1, sticky="ew", padx=(8, 10))
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)

        ttk.Button(top, text="Refresh Resolve", command=self.refresh_resolve_async).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(top, text="Prepare Cuts", command=self.run_prepare).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(top, text="Save Decisions", command=self.save_decisions).grid(row=0, column=4, padx=(0, 6))
        ttk.Button(top, text="Continue Build", command=self.run_finish).grid(row=0, column=5, padx=(0, 6))
        ttk.Button(top, text="Cancel", command=self.runner.cancel).grid(row=0, column=6)

        self.resolve_var = tk.StringVar(value="Resolve: checking...")
        ttk.Label(top, textvariable=self.resolve_var, foreground="#555").grid(row=1, column=0, columnspan=7, sticky="ew", pady=(8, 0))

        panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, weight=3)
        panes.add(right, weight=2)

        left.rowconfigure(3, weight=1)
        left.columnconfigure(0, weight=1)

        self.description = tk.StringVar()
        ttk.Label(left, textvariable=self.description, wraplength=740, foreground="#444").grid(row=0, column=0, sticky="ew")

        action_bar = ttk.Frame(left)
        action_bar.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        for index in range(8):
            action_bar.columnconfigure(index, weight=0)
        ttk.Button(action_bar, text="Open Prompt", command=self.open_prompt).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(action_bar, text="Copy Prompt", command=self.copy_prompt).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(action_bar, text="Load LLM JSON", command=self.load_llm_json_file).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(action_bar, text="Open Review", command=self.open_html_review).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(action_bar, text="Open Folder", command=self.open_project_folder).grid(row=0, column=4, padx=(0, 6))
        ttk.Button(action_bar, text="Refresh Artifacts", command=self.refresh_artifacts).grid(row=0, column=5, padx=(0, 6))

        self.artifact_var = tk.StringVar()
        ttk.Label(left, textvariable=self.artifact_var, foreground="#555", wraplength=760).grid(row=2, column=0, sticky="ew", pady=(0, 6))

        candidate_frame = ttk.LabelFrame(left, text="Cut Candidates")
        candidate_frame.grid(row=3, column=0, sticky="nsew")
        candidate_frame.rowconfigure(0, weight=1)
        candidate_frame.columnconfigure(0, weight=1)
        columns = ("decision", "source", "part", "start", "end", "confidence", "type", "reason")
        self.tree = ttk.Treeview(candidate_frame, columns=columns, show="headings", height=16)
        headings = {
            "decision": "Decision",
            "source": "Source",
            "part": "Part",
            "start": "Start",
            "end": "End",
            "confidence": "Conf.",
            "type": "Type",
            "reason": "Reason",
        }
        widths = {
            "decision": 72,
            "source": 82,
            "part": 70,
            "start": 70,
            "end": 70,
            "confidence": 70,
            "type": 145,
            "reason": 360,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", lambda _event: self.toggle_selected())
        yscroll = ttk.Scrollbar(candidate_frame, orient=tk.VERTICAL, command=self.tree.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=yscroll.set)

        decision_bar = ttk.Frame(left)
        decision_bar.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(decision_bar, text="Mark Cut", command=lambda: self.set_selected_decision("cut")).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(decision_bar, text="Mark Keep", command=lambda: self.set_selected_decision("keep")).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(decision_bar, text="Toggle", command=self.toggle_selected).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(decision_bar, text="All LLM Cut", command=lambda: self.set_source_decision("llm", "cut")).grid(row=0, column=3, padx=(12, 6))
        ttk.Button(decision_bar, text="All Review Keep", command=lambda: self.set_source_decision("review", "keep")).grid(row=0, column=4, padx=(0, 6))

        llm_frame = ttk.LabelFrame(left, text="Paste LLM Cut JSON")
        llm_frame.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        llm_frame.columnconfigure(0, weight=1)
        self.llm_text = tk.Text(llm_frame, height=7, wrap="word", undo=True)
        self.llm_text.grid(row=0, column=0, sticky="ew")
        ttk.Button(llm_frame, text="Parse Into Table", command=self.parse_llm_from_text).grid(row=0, column=1, sticky="ns", padx=(8, 0))

        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        step_frame = ttk.LabelFrame(right, text="Workflow Steps")
        step_frame.grid(row=0, column=0, sticky="ew")
        step_frame.columnconfigure(0, weight=1)
        self.step_tree = ttk.Treeview(step_frame, columns=("phase", "status", "title"), show="headings", height=12)
        self.step_tree.heading("phase", text="Phase")
        self.step_tree.heading("status", text="Status")
        self.step_tree.heading("title", text="Step")
        self.step_tree.column("phase", width=70)
        self.step_tree.column("status", width=70)
        self.step_tree.column("title", width=360)
        self.step_tree.grid(row=0, column=0, sticky="ew")

        log_frame = ttk.LabelFrame(right, text="Run Log")
        log_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(log_frame, height=24, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=log_scroll.set)

    def _on_profile_selected(self, _event: object | None = None) -> None:
        selected = self.profile_var.get()
        self.profile = next((profile for profile in self.profiles if profile.name == selected), None)
        self._load_profile_into_ui()

    def _load_profile_into_ui(self) -> None:
        profile = self.profile
        if profile is None:
            return
        self.profile_var.set(profile.name)
        self.description.set(profile.description)
        self.candidates.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.step_rows.clear()
        for item in self.step_tree.get_children():
            self.step_tree.delete(item)
        for phase, steps in (("prepare", profile.prepare_steps), ("finish", profile.finish_steps)):
            for step in steps:
                iid = f"{phase}:{step.id}"
                self.step_rows[step.id] = iid
                self.step_tree.insert("", "end", iid=iid, values=(phase, "idle", step.title))
        self.refresh_artifacts()

    def _set_step_status(self, step_id: str, status: str) -> None:
        iid = self.step_rows.get(step_id)
        if not iid:
            return
        phase, _old_status, title = self.step_tree.item(iid, "values")
        self.step_tree.item(iid, values=(phase, status, title))

    def _log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll_events(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._log(str(payload))
            elif kind == "error":
                self._log(f"ERROR: {payload}")
                messagebox.showerror("Resolve Edit Flow", str(payload))
            elif kind == "done":
                self._log(f"\nDONE: {payload}")
                self.refresh_artifacts()
            elif kind == "step":
                step_id, status = payload
                self._set_step_status(step_id, status)
            elif kind == "resolve":
                self.resolve_var.set(str(payload))
        self.after(120, self._poll_events)

    def run_prepare(self) -> None:
        if self.profile:
            self.runner.start(self.profile.prepare_steps, "Prepare cut handoff")

    def run_finish(self) -> None:
        if self.profile:
            self.runner.start(self.profile.finish_steps, "Continue build")

    def refresh_resolve_async(self) -> None:
        def worker() -> None:
            try:
                data = probe_resolve()
                project = data["project"]
                timeline = data["timeline"]
                resolution = f"{project.get('timelineResolutionWidth')}x{project.get('timelineResolutionHeight')}"
                self.post_event(
                    "resolve",
                    "Resolve: "
                    f"{project.get('name')} | "
                    f"Timeline: {timeline.get('name') or 'none'} | "
                    f"{project.get('timelineFrameRate')} fps | "
                    f"{resolution} | Page: {data.get('page')}",
                )
            except Exception as exc:
                self.post_event("resolve", f"Resolve: unavailable - {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def refresh_artifacts(self) -> None:
        profile = self.profile
        if profile is None:
            return
        pieces = []
        for key in ("candidate_manifest", "narrative_prompt", "approved_narrative", "hold_regions", "final_manifest"):
            path = profile.paths.get(key)
            if path:
                pieces.append(f"{key}: {'ok' if path.exists() else 'missing'}")
        for review in profile.html_reviews:
            pieces.append(f"{review.label}: {'ok' if review.html.exists() else 'missing'}")
        self.artifact_var.set(" | ".join(pieces))
        self.load_manifest_candidates()
        self.write_handoff_bundle(silent=True)

    def load_manifest_candidates(self) -> None:
        profile = self.profile
        if profile is None:
            return
        manifest_path = profile.paths.get("candidate_manifest")
        if not manifest_path or not manifest_path.exists():
            return
        try:
            manifest = load_json(manifest_path)
        except Exception as exc:
            self._log(f"Could not load candidate manifest: {exc}")
            return
        self._remove_source_candidates({"auto", "review"})
        for index, row in enumerate(manifest.get("auto_cut_candidates") or [], start=1):
            candidate = Candidate.from_raw(f"auto:{index}", "auto", row, "cut")
            self._add_candidate(candidate)
        for index, row in enumerate(manifest.get("review_candidates") or [], start=1):
            candidate = Candidate.from_raw(f"review:{index}", "review", row, "keep")
            self._add_candidate(candidate)

    def _remove_source_candidates(self, sources: set[str]) -> None:
        for key, candidate in list(self.candidates.items()):
            if candidate.source in sources:
                self.candidates.pop(key, None)
                if self.tree.exists(key):
                    self.tree.delete(key)

    def _add_candidate(self, candidate: Candidate) -> None:
        self.candidates[candidate.key] = candidate
        if self.tree.exists(candidate.key):
            self.tree.item(candidate.key, values=candidate.as_tree_values())
        else:
            self.tree.insert("", "end", iid=candidate.key, values=candidate.as_tree_values())

    def parse_llm_from_text(self) -> None:
        text = self.llm_text.get("1.0", "end").strip()
        try:
            rows = normalize_candidate_payload(parse_jsonish(text))
        except Exception as exc:
            messagebox.showerror("LLM JSON", str(exc))
            return
        self._remove_source_candidates({"llm"})
        for index, row in enumerate(rows, start=1):
            confidence = str(row.get("confidence") or "").lower()
            decision = "keep" if confidence in {"low", "reject", "rejected"} else "cut"
            self._add_candidate(Candidate.from_raw(f"llm:{index}", "llm", row, decision))
        self._log(f"Loaded {len(rows)} LLM candidate(s).")

    def load_llm_json_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Load LLM cut JSON",
            filetypes=[("JSON or Markdown", "*.json *.md *.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        text = Path(path).read_text(encoding="utf-8")
        self.llm_text.delete("1.0", "end")
        self.llm_text.insert("1.0", text)
        self.parse_llm_from_text()

    def set_selected_decision(self, decision: str) -> None:
        for key in self.tree.selection():
            candidate = self.candidates.get(key)
            if candidate:
                candidate.decision = decision
                self.tree.item(key, values=candidate.as_tree_values())

    def set_source_decision(self, source: str, decision: str) -> None:
        for key, candidate in self.candidates.items():
            if candidate.source == source:
                candidate.decision = decision
                self.tree.item(key, values=candidate.as_tree_values())

    def toggle_selected(self) -> None:
        for key in self.tree.selection():
            candidate = self.candidates.get(key)
            if candidate:
                candidate.decision = "keep" if candidate.decision == "cut" else "cut"
                self.tree.item(key, values=candidate.as_tree_values())

    def save_decisions(self) -> None:
        profile = self.profile
        if profile is None:
            return
        llm_rows = [candidate.raw for candidate in self.candidates.values() if candidate.source == "llm"]
        if "narrative_output" in profile.paths:
            write_json(profile.path("narrative_output"), llm_rows)

        approved_rows = []
        review_rows = []
        for candidate in self.candidates.values():
            raw = dict(candidate.raw)
            raw["status"] = "approved" if candidate.decision == "cut" else "keep"
            raw["decision_source"] = candidate.source
            if candidate.source in {"llm", "auto"} and candidate.decision == "cut":
                approved_rows.append(raw)
            if candidate.source == "review":
                review_rows.append(raw)

        if "approved_narrative" in profile.paths:
            write_json(profile.path("approved_narrative"), approved_rows)
            sidecar = profile.path("approved_narrative").with_suffix(".review_decisions.json")
            write_json(
                sidecar,
                {
                    "schema": "resolve_edit_flow_decisions_v1",
                    "approved_source_cuts": approved_rows,
                    "review_decisions": review_rows,
                    "all_candidates": [candidate.raw | {"status": candidate.decision, "decision_source": candidate.source} for candidate in self.candidates.values()],
                },
            )

        self._write_pink_decisions(profile)
        self.write_handoff_bundle(silent=True)
        self.refresh_artifacts()
        messagebox.showinfo("Resolve Edit Flow", f"Saved {len(approved_rows)} approved source cut(s).")

    def _write_pink_decisions(self, profile: Profile) -> None:
        review_candidates = [candidate for candidate in self.candidates.values() if candidate.source == "review"]
        if not review_candidates:
            return
        for review in profile.html_reviews:
            pink: dict[str, str] = {}
            for candidate in review_candidates:
                if review.part and candidate.part and review.part != candidate.part:
                    continue
                clip_index = candidate.raw.get("clip_index_local", candidate.raw.get("clip_index", candidate.raw.get("i")))
                if clip_index is None:
                    continue
                pink[str(int(clip_index))] = "cut" if candidate.decision == "cut" else "keep"
            if pink:
                write_json(review.decisions, {"pink": pink, "cuts": {}})
                self._log(f"Wrote waveform decisions: {review.decisions}")

    def write_handoff_bundle(self, silent: bool = False) -> None:
        profile = self.profile
        if profile is None or "handoff_bundle" not in profile.paths:
            return
        manifest_path = profile.paths.get("candidate_manifest")
        manifest = {}
        if manifest_path and manifest_path.exists():
            try:
                manifest = load_json(manifest_path)
            except Exception:
                manifest = {}
        narrative = manifest.get("narrative") or {}
        payload = {
            "schema": "resolve_edit_flow_llm_handoff_v1",
            "profile": profile.name,
            "instructions_path": str(profile.paths.get("llm_instructions", "")),
            "prompt_path": str(profile.paths.get("narrative_prompt", "")),
            "expected_llm_output_path": str(profile.paths.get("narrative_output", "")),
            "candidate_manifest": str(manifest_path or ""),
            "transcripts": narrative.get("transcripts") or narrative.get("transcript"),
            "clip_index": narrative.get("clip_index"),
            "instructions": [
                "Give the LLM the prompt file contents.",
                "Ask it to return only the raw JSON cut-candidate array.",
                "Paste that JSON into the GUI, review candidates, then click Save Decisions.",
            ],
        }
        instructions_path = profile.paths.get("llm_instructions")
        if instructions_path and instructions_path.exists():
            payload["instructions_text"] = instructions_path.read_text(encoding="utf-8")
        write_json(profile.path("handoff_bundle"), payload)
        if not silent:
            self._log(f"Wrote LLM handoff bundle: {profile.path('handoff_bundle')}")

    def open_prompt(self) -> None:
        profile = self.profile
        if profile is None:
            return
        try:
            open_path(profile.path("narrative_prompt"))
        except Exception as exc:
            messagebox.showerror("Open Prompt", str(exc))

    def copy_prompt(self) -> None:
        profile = self.profile
        if profile is None:
            return
        try:
            text = profile.path("narrative_prompt").read_text(encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("Copy Prompt", str(exc))
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self._log("Copied narrative prompt to clipboard.")

    def open_html_review(self) -> None:
        profile = self.profile
        if profile is None:
            return
        existing = [review for review in profile.html_reviews if review.html.exists()]
        if not existing:
            messagebox.showwarning("Open Review", "No review HTML exists yet.")
            return
        try:
            open_path(existing[0].html)
        except Exception as exc:
            messagebox.showerror("Open Review", str(exc))

    def open_project_folder(self) -> None:
        profile = self.profile
        if profile is None:
            return
        path = profile.codex_dir if profile.codex_dir.exists() else profile.project_dir
        try:
            open_path(path)
        except Exception as exc:
            messagebox.showerror("Open Folder", str(exc))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve edit-flow GUI")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dump-profiles", action="store_true", help="Print configured profile names and exit.")
    parser.add_argument("--probe-resolve-json", action="store_true", help="Print Resolve project/timeline/page JSON and exit.")
    args = parser.parse_args(argv)

    if args.probe_resolve_json:
        print(json.dumps(probe_resolve(), indent=2, ensure_ascii=False))
        return 0
    if args.dump_profiles:
        for profile in load_profiles(args.config):
            print(f"{profile.id}\t{profile.name}")
        return 0

    app = EditFlowApp(args.config)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
