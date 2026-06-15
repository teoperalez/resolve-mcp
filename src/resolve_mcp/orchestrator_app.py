from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
import tkinter as tk

from .orchestrator import DEFAULT_WORKFLOW_CONFIG, load_catalog
from .orchestrator.dependencies import DependencyCheck, check_runtime_dependencies
from .orchestrator.fcpxml_review import FCPXMLReviewModel, load_fcpxml_review_model
from .orchestrator.llm_dispatch import LLMDispatcher
from .orchestrator.models import ProjectProfile, WorkflowCatalog, WorkflowDefinition, WorkflowStep
from .orchestrator.prompt_engine import PromptEngine
from .orchestrator.project_discovery import discover_project
from .orchestrator.runner import OrchestratorRunner, RunEvent, ThreadedRun
from .orchestrator.status import collect_artifact_status, step_readiness


def chrome_executable() -> str | None:
    candidates = [
        shutil.which("chrome"),
        shutil.which("chrome.exe"),
        os.environ.get("CHROME_PATH"),
        str(Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        str(Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def open_html_in_chrome(path: Path) -> bool:
    if os.name != "nt" or path.suffix.lower() not in {".html", ".htm"}:
        return False
    chrome = chrome_executable()
    if not chrome:
        return False
    subprocess.Popen([chrome, path.resolve().as_uri()])
    return True


def open_path(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    if open_html_in_chrome(path):
        return
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    if path.is_dir():
        webbrowser.open(str(path))
        return
    webbrowser.open(path.resolve().as_uri())


PARAMETER_ORDER = [
    "source_media",
    "dialogue_audio",
    "auto_editor_input",
    "auto_editor_export",
    "auto_editor_margin",
    "auto_editor_edit",
    "auto_editor_when_normal",
    "auto_editor_when_silent",
    "auto_editor_frame_rate",
    "auto_editor_extra_args",
    "auto_editor_preview",
    "session_dir",
    "session_events",
    "session_meta",
    "source_name",
    "pipeline_script",
    "timeline_fps",
    "whisper_model",
    "llm_dispatch_mode",
    "llm_open_code_workspace",
    "llm_timeout_sec",
    "llm_model",
    "livestream_edit_mode",
    "livestream_cut_chat_interactions",
    "livestream_bypass_gameplay_narrative_cuts",
    "video_track",
    "carousel_max_candidates",
    "review_fcpxml",
    "render_preset",
    "render_name",
    "render_dir",
    "resolve_project_name",
    "resolve_timeline_name",
]

PATH_ORDER = [
    "candidate_manifest",
    "raw_autoeditor_fcpxml",
    "review_fcpxml",
    "narrative_prompt",
    "narrative_clip_index",
    "narrative_output",
    "waveform_candidates",
    "ngram_candidates",
    "artifact_candidates",
    "programmatic_candidates",
    "approved_narrative",
    "approved_source_cuts",
    "native_normalized_ranges",
    "game_audio",
    "html_decisions",
    "html_clips",
    "html_index",
    "html_segmap",
    "fcpxml_review_artifact",
    "fcpxml_review_decisions",
    "final_manifest",
    "clip_color_report",
    "pipeline_order_report",
    "transcript_json",
    "battles_json",
    "battle_gaps_fcpxml",
    "llm_instructions",
]

FIELD_LABELS = {
    "approved_narrative": "Approved Narrative Cuts",
    "approved_source_cuts": "Approved Source Cuts",
    "artifact_candidates": "Artifact/Short-Clip Candidates",
    "auto_editor_edit": "Auto-Editor Edit Expression",
    "auto_editor_export": "Auto-Editor Export",
    "auto_editor_extra_args": "Auto-Editor Extra Args",
    "auto_editor_frame_rate": "Auto-Editor Frame Rate",
    "auto_editor_input": "Auto-Editor Input",
    "auto_editor_margin": "Auto-Editor Margin",
    "auto_editor_preview": "Auto-Editor Preview Only",
    "auto_editor_when_normal": "When Sounded/Normal",
    "auto_editor_when_silent": "When Silent",
    "battle_gaps_fcpxml": "Battle Gaps FCPXML",
    "battles_json": "Battle Detection JSON",
    "candidate_manifest": "Cut Candidate Manifest",
    "carousel_max_candidates": "Carousel Candidates To Check",
    "categories_json": "Waveform Categories",
    "clips_json": "Timeline Clip Index",
    "codex_dir": "CODEx Folder",
    "cut_review_dir": "Cut Review Folder",
    "dialogue_audio": "Dialogue Audio",
    "fcpxml_review_artifact": "FCPXML Review Data",
    "fcpxml_review_decisions": "FCPXML Review Decisions",
    "clip_color_report": "Clip Color Report",
    "final_manifest": "Final Assembly Manifest",
    "game_audio": "Game Audio Bridge WAV",
    "html_clips": "HTML Review Clips",
    "html_decisions": "HTML Review Decisions",
    "html_index": "HTML Review Page",
    "html_segmap": "HTML Review Segment Map",
    "llm_instructions": "LLM Instructions",
    "llm_dispatch_mode": "LLM Dispatch Mode",
    "llm_model": "LLM Model Override",
    "llm_open_code_workspace": "Open Code Workspace",
    "llm_timeout_sec": "LLM Timeout Seconds",
    "livestream_bypass_gameplay_narrative_cuts": "Bypass Gameplay Narrative Cuts",
    "livestream_cut_chat_interactions": "Cut Chat/Aside Interactions",
    "livestream_edit_mode": "Livestream Edit Mode",
    "narrative_output": "Narrative LLM Output",
    "native_normalized_ranges": "Normalized HTML Review Cuts",
    "narrative_clip_index": "Narrative Clip Index",
    "narrative_prompt": "Narrative LLM Prompt",
    "ngram_candidates": "N-Gram Candidates",
    "pipeline_script": "Pipeline Script",
    "pipeline_order_report": "Pipeline Validation Report",
    "programmatic_candidates": "Programmatic Candidate Bundle",
    "raw_autoeditor_fcpxml": "Raw Auto-Editor FCPXML",
    "render_dir": "Render Folder",
    "render_name": "Render Name",
    "render_preset": "Render Preset",
    "resolve_project_name": "Resolve Project Name",
    "resolve_timeline_name": "Resolve Timeline Name",
    "review_fcpxml": "Review FCPXML",
    "session_dir": "Session Log Folder",
    "session_events": "Session Events",
    "session_meta": "Session Metadata",
    "source_media": "Source Media",
    "source_name": "Source Name",
    "timeline_fps": "Timeline FPS",
    "transcript_json": "Transcript JSON",
    "video_track": "Video Track",
    "whisper_model": "Whisper Model",
    "waveform_candidates": "Waveform Candidates",
}

FIELD_HELP = {
    "approved_source_cuts": "Source-time cuts approved by human/LLM review. Final assembly consumes this.",
    "auto_editor_edit": "auto-editor expression that decides loud vs silent sections, usually audio.",
    "auto_editor_export": "auto-editor export target, usually final-cut-pro for FCPXML.",
    "auto_editor_extra_args": "Advanced auto-editor flags appended exactly as written.",
    "auto_editor_frame_rate": "Timeline frame rate passed to auto-editor.",
    "auto_editor_input": "Media or extracted dialogue WAV auto-editor analyzes.",
    "auto_editor_margin": "Keeps a small buffer around sounded sections, e.g. 0.2s.",
    "auto_editor_preview": "When true, runs --preview instead of writing a new FCPXML.",
    "auto_editor_when_normal": "Action for sounded sections. nil keeps them at normal speed.",
    "auto_editor_when_silent": "Action for silent sections. cut removes them.",
    "artifact_candidates": "Programmatic detector output for empty transcript sections, very short clips, and artifact patterns.",
    "candidate_manifest": "Final ranked cut-candidate bundle after LLM, programmatic detectors, and FCPXML section-safety checks.",
    "clip_color_report": "Per-section clip color report for intro, battles, post-battle cards, tierlists, and carousel.",
    "dialogue_audio": "Mic/dialogue WAV used for waveform QA and review snippets.",
    "final_manifest": "Report written after the completed timeline is assembled.",
    "html_decisions": "Saved keep/cut decisions from the browser waveform review.",
    "game_audio": "Extracted game-audio bridge track used by BGM placement.",
    "llm_dispatch_mode": "auto uses Codex CLI when available, otherwise opens Code and waits for output.",
    "llm_model": "Optional Codex model name for this profile. Leave blank to use your Codex default.",
    "llm_open_code_workspace": "When true, opens/reuses Code with the prompt and output file for visibility.",
    "llm_timeout_sec": "Maximum time to wait for automatic or Code-workspace LLM feedback.",
    "livestream_bypass_gameplay_narrative_cuts": "When enabled, the narrative LLM avoids ordinary gameplay polish cuts while still allowing structural and livestream chat/asides review.",
    "livestream_cut_chat_interactions": "When enabled in livestream mode, the narrative LLM looks for chat replies, stream asides, and clarifications unrelated to the main run.",
    "livestream_edit_mode": "Adds livestream/VOD editorial rules to the narrative cut prompt and review metadata.",
    "narrative_clip_index": "Source-backed clip list used by the broad narrative LLM prompt and programmatic transcript checks.",
    "native_normalized_ranges": "Offline-normalized HTML review decisions converted to source/timeline ranges.",
    "ngram_candidates": "Programmatic repeated n-gram leads. These are never auto-applied without compiler approval.",
    "pipeline_script": "Project pipeline bridge used by workflow stages.",
    "pipeline_order_report": "Validation report for the completed pipeline order and final timeline artifacts.",
    "programmatic_candidates": "Combined waveform, n-gram, and artifact detector output before final candidate ranking.",
    "review_fcpxml": "Offline review-base FCPXML. This is not imported into Resolve during review.",
    "waveform_candidates": "Waveform QA candidates before the final FCPXML section-safety compiler.",
    "session_dir": "Matched RBYNewLayout log folder, if one exists.",
    "source_media": "Main recording or source video for the project.",
}

FILE_KEYS = {
    "approved_narrative",
    "approved_source_cuts",
    "artifact_candidates",
    "battle_gaps_fcpxml",
    "battles_json",
    "candidate_manifest",
    "dialogue_audio",
    "fcpxml_review_artifact",
    "fcpxml_review_decisions",
    "clip_color_report",
    "final_manifest",
    "game_audio",
    "html_clips",
    "html_decisions",
    "html_index",
    "html_segmap",
    "llm_instructions",
    "narrative_clip_index",
    "native_normalized_ranges",
    "narrative_output",
    "narrative_prompt",
    "ngram_candidates",
    "pipeline_script",
    "pipeline_order_report",
    "programmatic_candidates",
    "raw_autoeditor_fcpxml",
    "review_fcpxml",
    "session_events",
    "session_meta",
    "source_media",
    "transcript_json",
    "waveform_candidates",
}

DIRECTORY_KEYS = {
    "cut_review_dir",
    "html_review_dir",
    "native_review_dir",
    "render_dir",
    "session_dir",
}

BOOL_SETTING_KEYS = {
    "auto_editor_preview",
    "llm_open_code_workspace",
    "livestream_bypass_gameplay_narrative_cuts",
    "livestream_cut_chat_interactions",
    "livestream_edit_mode",
}

AUTO_EDITOR_FIELDS = [
    "auto_editor_input",
    "raw_autoeditor_fcpxml",
    "auto_editor_export",
    "auto_editor_margin",
    "auto_editor_edit",
    "auto_editor_when_normal",
    "auto_editor_when_silent",
    "auto_editor_frame_rate",
    "auto_editor_preview",
    "auto_editor_extra_args",
]


class OrchestratorApp(tk.Tk):
    def __init__(self, catalog: WorkflowCatalog, config_path: Path) -> None:
        super().__init__()
        self.config_path = config_path
        self.catalog = catalog
        self.raw_config = self._read_config()
        self.profile: ProjectProfile | None = catalog.profiles[0] if catalog.profiles else None
        self.workflow: WorkflowDefinition | None = None
        self.events: queue.Queue[RunEvent] = queue.Queue()
        self.prompt_engine = PromptEngine(catalog.repo)
        self.threaded_run = ThreadedRun(
            OrchestratorRunner(catalog.repo, self.events.put, llm_step_handler=self._handle_llm_step)
        )
        self.step_rows: dict[str, str] = {}
        self.review_model: FCPXMLReviewModel | None = None
        self.segment_decisions: dict[str, dict] = {}
        self.generated_prompt_paths: dict[str, Path] = {}
        self.project_fields: dict[str, tk.StringVar] = {}
        self.parameter_vars: dict[str, tk.Variable] = {}
        self.path_vars: dict[str, tk.Variable] = {}
        self.auto_editor_vars: dict[str, tk.StringVar] = {}
        self.dependency_checks: list[DependencyCheck] = []
        self.llm_task_thread: threading.Thread | None = None

        self.title("Resolve Orchestrator")
        self.geometry("1360x860")
        self.minsize(1120, 700)
        self._configure_style()
        self._build_ui()
        self._load_profile()
        self.after(120, self._poll_events)
        self.after(400, self.refresh_resolve_async)
        self.after(800, lambda: self.check_dependencies(prompt=True))
        self.after(500, self._set_initial_pane_sizes)

    def _read_config(self) -> dict:
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def _write_config(self) -> None:
        self.config_path.write_text(json.dumps(self.raw_config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _set_initial_pane_sizes(self) -> None:
        try:
            self.main_panes.sashpos(0, int(self.winfo_width() * 0.72))
        except tk.TclError:
            pass

    def _configure_style(self) -> None:
        self.configure(background="#f5f6f8")
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#f5f6f8")
        style.configure("TLabelframe", background="#f5f6f8", padding=10)
        style.configure("TLabelframe.Label", background="#f5f6f8", foreground="#1f2937", font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background="#f5f6f8", foreground="#1f2937", font=("Segoe UI", 9))
        style.configure("Muted.TLabel", background="#f5f6f8", foreground="#6b7280", font=("Segoe UI", 8))
        style.configure("Header.TLabel", background="#f5f6f8", foreground="#111827", font=("Segoe UI", 13, "bold"))
        style.configure("TButton", font=("Segoe UI", 9), padding=(10, 5))
        style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"), padding=(12, 6))
        style.configure("Treeview", rowheight=25, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

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
            values=[profile.name for profile in self.catalog.profiles],
            state="readonly",
        )
        self.profile_combo.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_profile_selected())
        ttk.Button(top, text="Reload Config", command=self.reload_config).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(top, text="Save Project", command=self.save_project_profile).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(top, text="Check Tools", command=lambda: self.check_dependencies(prompt=True)).grid(row=0, column=4, padx=(0, 6))
        ttk.Button(top, text="Check Resolve", command=self.refresh_resolve_async).grid(row=0, column=5, padx=(0, 6))
        ttk.Button(top, text="Launch Resolve", command=self.launch_resolve).grid(row=0, column=6, padx=(0, 6))
        ttk.Button(top, text="Run / Redo Selected", command=self.run_selected_steps).grid(row=0, column=7, padx=(0, 6))
        ttk.Button(top, text="Run Full", command=self.run_full_workflow).grid(row=0, column=8, padx=(0, 6))
        ttk.Button(top, text="Cancel", command=self.threaded_run.runner.cancel).grid(row=0, column=9)
        self.profile_detail = tk.StringVar()
        ttk.Label(top, textvariable=self.profile_detail, foreground="#555").grid(row=1, column=0, columnspan=10, sticky="ew", pady=(8, 0))
        self.resolve_detail = tk.StringVar(value="Resolve: not checked")
        ttk.Label(top, textvariable=self.resolve_detail, foreground="#555").grid(row=2, column=0, columnspan=10, sticky="ew", pady=(4, 0))

        self.main_panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes = self.main_panes
        panes.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, weight=4)
        panes.add(right, weight=1)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self.tabs = ttk.Notebook(left)
        self.tabs.grid(row=0, column=0, sticky="nsew")
        self.projects_tab = ttk.Frame(self.tabs, padding=8)
        self.workflow_tab = ttk.Frame(self.tabs, padding=8)
        self.auto_editor_tab = ttk.Frame(self.tabs, padding=8)
        self.llm_tab = ttk.Frame(self.tabs, padding=8)
        self.review_tab = ttk.Frame(self.tabs, padding=8)
        self.artifacts_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.projects_tab, text="Projects")
        self.tabs.add(self.workflow_tab, text="Workflow")
        self.tabs.add(self.auto_editor_tab, text="Auto-Editor")
        self.tabs.add(self.llm_tab, text="LLM Packets")
        self.tabs.add(self.review_tab, text="FCPXML Review")
        self.tabs.add(self.artifacts_tab, text="Artifacts")
        self._build_projects_tab()
        self._build_workflow_tab()
        self._build_auto_editor_tab()
        self._build_llm_tab()
        self._build_review_tab()
        self._build_artifacts_tab()

        log_frame = ttk.LabelFrame(right, text="Run Log")
        log_frame.grid(row=0, column=0, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(log_frame, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

    def launch_resolve(self) -> None:
        resolve_path = Path(r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe")
        if not resolve_path.exists():
            messagebox.showerror("Launch Resolve", f"Resolve executable not found:\n{resolve_path}")
            return
        try:
            subprocess.Popen([str(resolve_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            messagebox.showerror("Launch Resolve", str(exc))
            return
        self.resolve_detail.set("Resolve: launching...")
        self.after(15000, self.refresh_resolve_async)

    def refresh_resolve_async(self) -> None:
        self.resolve_detail.set("Resolve: checking...")

        def worker() -> None:
            try:
                data = self._probe_resolve()
                project = data.get("project") or "no project"
                page = data.get("page") or "project manager"
                self.events.put(RunEvent("resolve", f"Resolve: connected | Project: {project} | Page: {page}"))
            except Exception as exc:
                self.events.put(RunEvent("resolve", f"Resolve: unavailable - {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _probe_resolve(self) -> dict:
        scripts_dir = self.catalog.repo / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import _resolve_env  # noqa: F401
        import DaVinciResolveScript as dvr

        resolve = dvr.scriptapp("Resolve")
        if resolve is None:
            raise RuntimeError(
                "Could not connect. Open Resolve and set Preferences > General > External scripting using > Local."
            )
        project_manager = resolve.GetProjectManager()
        project = project_manager.GetCurrentProject() if project_manager else None
        return {
            "project": project.GetName() if project else None,
            "page": resolve.GetCurrentPage(),
        }

    def _steps_need_resolve(self, steps: list[WorkflowStep]) -> bool:
        return any(step.requires_resolve for step in steps)

    def _step_needs_resolve(self, step: WorkflowStep) -> bool:
        return step.requires_resolve

    def _preflight_resolve_for_steps(self, steps: list[WorkflowStep]) -> bool:
        return True

    def _build_projects_tab(self) -> None:
        self.projects_tab.columnconfigure(0, weight=1)
        self.projects_tab.rowconfigure(2, weight=1)

        actions = ttk.Frame(self.projects_tab)
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(actions, text="New", command=self.new_project_profile).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(actions, text="Duplicate", command=self.duplicate_project_profile).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(actions, text="Save", command=self.save_project_profile).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(actions, text="Delete", command=self.delete_project_profile).grid(row=0, column=3, padx=(0, 18))
        ttk.Button(actions, text="Browse Project", command=lambda: self._browse_profile_dir("project_dir")).grid(row=0, column=4, padx=(0, 6))
        ttk.Button(actions, text="Browse CODEx", command=lambda: self._browse_profile_dir("codex_dir")).grid(row=0, column=5, padx=(0, 18))
        ttk.Button(actions, text="Reload Config", command=self.reload_config).grid(row=0, column=6, padx=(0, 6))
        ttk.Button(actions, text="Advanced Config", command=self.open_advanced_config).grid(row=0, column=7)

        form = ttk.LabelFrame(self.projects_tab, text="Project Profile")
        form.grid(row=1, column=0, sticky="ew")
        for col in (1, 3):
            form.columnconfigure(col, weight=1)

        field_specs = [
            ("id", "ID", 0, 0),
            ("name", "Name", 0, 2),
            ("game_version", "Game Version", 2, 0),
            ("challenge_type", "Challenge Type", 2, 2),
            ("project_dir", "Project Folder", 3, 0),
            ("codex_dir", "CODEx Folder", 3, 2),
        ]
        for key, label, row, col in field_specs:
            ttk.Label(form, text=label).grid(row=row, column=col, sticky="w", padx=(8, 6), pady=5)
            var = tk.StringVar()
            self.project_fields[key] = var
            ttk.Entry(form, textvariable=var).grid(row=row, column=col + 1, sticky="ew", padx=(0, 8), pady=5)

        ttk.Label(form, text="Workflow").grid(row=1, column=0, sticky="w", padx=(8, 6), pady=5)
        workflow_var = tk.StringVar()
        self.project_fields["workflow_id"] = workflow_var
        self.workflow_id_combo = ttk.Combobox(
            form,
            textvariable=workflow_var,
            values=[workflow.id for workflow in self.catalog.workflows],
            state="readonly",
        )
        self.workflow_id_combo.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=5)
        self.workflow_id_combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_workflow_defaults_to_editor())

        ttk.Label(form, text="Description").grid(row=1, column=2, sticky="w", padx=(8, 6), pady=5)
        description_var = tk.StringVar()
        self.project_fields["description"] = description_var
        ttk.Entry(form, textvariable=description_var).grid(row=1, column=3, sticky="ew", padx=(0, 8), pady=5)

        self.project_settings_tabs = ttk.Notebook(self.projects_tab)
        self.project_settings_tabs.grid(row=2, column=0, sticky="nsew", pady=(10, 0))

        self.project_automation_tab = ttk.Frame(self.project_settings_tabs, padding=10)
        self.project_artifact_tab = ttk.Frame(self.project_settings_tabs, padding=10)
        self.project_settings_tabs.add(self.project_automation_tab, text="Automation Settings")
        self.project_settings_tabs.add(self.project_artifact_tab, text="Artifact Paths")

        self.project_automation_tab.rowconfigure(1, weight=1)
        self.project_automation_tab.columnconfigure(0, weight=1)
        ttk.Label(
            self.project_automation_tab,
            text="Project inputs and workflow options",
            style="Header.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.parameter_fields = self._scrollable_fields(self.project_automation_tab, row=1)

        self.project_artifact_tab.rowconfigure(1, weight=1)
        self.project_artifact_tab.columnconfigure(0, weight=1)
        ttk.Label(
            self.project_artifact_tab,
            text="Generated files and review artifacts",
            style="Header.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.path_fields = self._scrollable_fields(self.project_artifact_tab, row=1)

    def _build_workflow_tab(self) -> None:
        self.workflow_tab.rowconfigure(1, weight=1)
        self.workflow_tab.columnconfigure(0, weight=1)
        self.workflow_description = tk.StringVar()
        ttk.Label(self.workflow_tab, textvariable=self.workflow_description, wraplength=820, foreground="#444").grid(
            row=0, column=0, sticky="ew", pady=(0, 8)
        )
        columns = ("phase", "kind", "status", "title")
        self.step_tree = ttk.Treeview(self.workflow_tab, columns=columns, show="headings", selectmode="extended")
        for column, width in (("phase", 90), ("kind", 110), ("status", 80), ("title", 520)):
            self.step_tree.heading(column, text=column.title())
            self.step_tree.column(column, width=width, anchor="w")
        self._configure_tree_status_tags(self.step_tree)
        self.step_tree.grid(row=1, column=0, sticky="nsew")
        self.step_tree.bind("<Double-1>", lambda _event: self.review_selected_step_outputs())
        buttons = ttk.Frame(self.workflow_tab)
        buttons.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="Select Phase", command=self.select_phase).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(buttons, text="Refresh Status", command=self.refresh_status).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(buttons, text="Select Downstream", command=self.select_downstream_steps).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(buttons, text="Redo From Selected", command=self.run_downstream_steps).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(buttons, text="Review Outputs", command=self.review_selected_step_outputs).grid(row=0, column=4, padx=(0, 6))
        ttk.Button(buttons, text="Open Project Folder", command=self.open_project_folder).grid(row=0, column=5, padx=(0, 6))
        ttk.Button(buttons, text="Open CODEx Folder", command=self.open_codex_folder).grid(row=0, column=6)

    def _build_auto_editor_tab(self) -> None:
        self.auto_editor_tab.columnconfigure(0, weight=1)
        self.auto_editor_tab.rowconfigure(1, weight=1)
        ttk.Label(
            self.auto_editor_tab,
            text="Auto-editor runs offline and produces the raw FCPXML/dialogue spine used by later review-base steps.",
            wraplength=920,
            foreground="#444",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 8))

        form = ttk.Frame(self.auto_editor_tab)
        form.grid(row=1, column=0, sticky="nsew")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        for row, key in enumerate(AUTO_EDITOR_FIELDS):
            col = 0 if row % 2 == 0 else 2
            grid_row = row // 2
            ttk.Label(form, text=self._field_label(key)).grid(row=grid_row, column=col, sticky="nw", padx=(0, 8), pady=5)
            var = tk.StringVar()
            self.auto_editor_vars[key] = var
            entry = ttk.Entry(form, textvariable=var)
            entry.grid(row=grid_row, column=col + 1, sticky="ew", pady=5)
            if key in FILE_KEYS or key in DIRECTORY_KEYS:
                ttk.Button(
                    form,
                    text="Browse",
                    command=lambda k=key: self._browse_auto_editor_value(k),
                ).grid(row=grid_row, column=col + 1, sticky="e", padx=(0, 2))

        buttons = ttk.Frame(self.auto_editor_tab)
        buttons.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="Save Settings", command=self.save_project_profile).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(buttons, text="Preview", command=lambda: self.run_auto_editor(preview=True)).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(buttons, text="Run Auto-Editor", style="Accent.TButton", command=lambda: self.run_auto_editor(preview=False)).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(buttons, text="Review FCPXML", command=self.review_auto_editor_output).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(buttons, text="Open Output", command=self.open_auto_editor_output).grid(row=0, column=4)

    def _build_llm_tab(self) -> None:
        self.llm_tab.columnconfigure(0, weight=1)
        self.llm_tab.rowconfigure(2, weight=1)
        row = ttk.Frame(self.llm_tab)
        row.grid(row=0, column=0, sticky="ew")
        row.columnconfigure(1, weight=1)
        ttk.Label(row, text="Task").grid(row=0, column=0, sticky="w")
        self.llm_task_var = tk.StringVar()
        self.llm_task_combo = ttk.Combobox(row, textvariable=self.llm_task_var, state="readonly")
        self.llm_task_combo.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.llm_task_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_llm_detail())
        ttk.Button(row, text="Generate Packet", command=self.generate_prompt_packet).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(row, text="Run LLM", style="Accent.TButton", command=self.run_current_llm_task).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(row, text="Open Prompt", command=self.open_generated_prompt).grid(row=0, column=4, padx=(0, 6))
        ttk.Button(row, text="Open Output", command=self.open_llm_output).grid(row=0, column=5)
        self.llm_detail = tk.StringVar()
        ttk.Label(self.llm_tab, textvariable=self.llm_detail, wraplength=840, foreground="#555").grid(row=1, column=0, sticky="ew", pady=(8, 8))
        self.llm_text = tk.Text(self.llm_tab, wrap="word")
        self.llm_text.grid(row=2, column=0, sticky="nsew")

    def _build_review_tab(self) -> None:
        self.review_tab.rowconfigure(2, weight=1)
        self.review_tab.columnconfigure(0, weight=1)
        row = ttk.Frame(self.review_tab)
        row.grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="Load FCPXML", command=self.load_fcpxml).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(row, text="Keep", command=lambda: self.set_segment_decision("keep")).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(row, text="Cut", command=lambda: self.set_segment_decision("cut")).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(row, text="Manual Fit", command=lambda: self.set_segment_decision("manual_fit")).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(row, text="Note", command=self.note_selected_segments).grid(row=0, column=4, padx=(0, 6))
        ttk.Button(row, text="Export Decisions", command=self.export_segment_decisions).grid(row=0, column=5)
        self.review_detail = tk.StringVar(value="No FCPXML loaded.")
        ttk.Label(self.review_tab, textvariable=self.review_detail, foreground="#555").grid(row=1, column=0, sticky="ew", pady=(8, 8))
        columns = ("decision", "offset", "duration", "source_start", "source_end", "name", "source")
        self.segment_tree = ttk.Treeview(self.review_tab, columns=columns, show="headings", selectmode="extended")
        widths = {
            "decision": 90,
            "offset": 80,
            "duration": 80,
            "source_start": 100,
            "source_end": 100,
            "name": 260,
            "source": 420,
        }
        for column in columns:
            self.segment_tree.heading(column, text=column.replace("_", " ").title())
            self.segment_tree.column(column, width=widths[column], anchor="w")
        self.segment_tree.grid(row=2, column=0, sticky="nsew")

    def _build_artifacts_tab(self) -> None:
        self.artifacts_tab.rowconfigure(0, weight=1)
        self.artifacts_tab.columnconfigure(0, weight=1)
        columns = ("state", "key", "path", "required_by", "produced_by")
        self.artifact_tree = ttk.Treeview(self.artifacts_tab, columns=columns, show="headings")
        widths = {
            "state": 70,
            "key": 220,
            "path": 560,
            "required_by": 240,
            "produced_by": 240,
        }
        for column in columns:
            self.artifact_tree.heading(column, text=column.replace("_", " ").title())
            self.artifact_tree.column(column, width=widths[column], anchor="w")
        self._configure_tree_status_tags(self.artifact_tree)
        self.artifact_tree.grid(row=0, column=0, sticky="nsew")
        self.artifact_tree.bind("<Double-1>", lambda _event: self.review_selected_artifact())
        scroll = ttk.Scrollbar(self.artifacts_tab, orient=tk.VERTICAL, command=self.artifact_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.artifact_tree.configure(yscrollcommand=scroll.set)
        buttons = ttk.Frame(self.artifacts_tab)
        buttons.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="Review Selected", command=self.review_selected_artifact).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(buttons, text="Open File", command=self.open_selected_artifact).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(buttons, text="Open Folder", command=self.open_selected_artifact_folder).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(buttons, text="Refresh", command=self.refresh_status).grid(row=0, column=3)

    @staticmethod
    def _configure_tree_status_tags(tree: ttk.Treeview) -> None:
        tree.tag_configure("status_done", background="#e7f6ec", foreground="#14532d")
        tree.tag_configure("status_ok", background="#e7f6ec", foreground="#14532d")
        tree.tag_configure("status_ready", background="#f8fafc", foreground="#1f2937")
        tree.tag_configure("status_blocked", background="#f3f4f6", foreground="#6b7280")
        tree.tag_configure("status_running", background="#e0f2fe", foreground="#075985")
        tree.tag_configure("status_missing", background="#fff7ed", foreground="#9a3412")
        tree.tag_configure("status_failed", background="#fee2e2", foreground="#991b1b")
        tree.tag_configure("status_skipped", background="#f3f4f6", foreground="#4b5563")

    @staticmethod
    def _status_tag(status: str) -> str:
        return f"status_{status.lower().replace(' ', '_')}"

    def _on_profile_selected(self) -> None:
        selected = self.profile_var.get()
        self.profile = next((profile for profile in self.catalog.profiles if profile.name == selected), None)
        self._load_profile()

    def _load_profile(self) -> None:
        if self.profile is None:
            return
        self.workflow = self.catalog.effective_workflow(self.profile)
        self.profile_var.set(self.profile.name)
        self.profile_detail.set(
            f"{self.profile.game_version} | {self.profile.challenge_type} | {self.profile.project_dir}"
        )
        self.workflow_description.set(self.workflow.description)
        self._populate_project_editor()
        self._populate_steps()
        self._populate_llm_tasks()
        self._populate_artifacts()

    def _populate_project_editor(self) -> None:
        if self.profile is None:
            return
        values = {
            "id": self.profile.id,
            "name": self.profile.name,
            "workflow_id": self.profile.workflow_id,
            "game_version": self.profile.game_version,
            "challenge_type": self.profile.challenge_type,
            "project_dir": self.profile.project_dir,
            "codex_dir": self.profile.codex_dir,
            "description": self.profile.description,
        }
        for key, value in values.items():
            if key in self.project_fields:
                self.project_fields[key].set(value)
        self._populate_setting_fields(dict(self.profile.parameters), dict(self.profile.paths))
        self._populate_auto_editor_fields()

    def _scrollable_fields(self, parent: ttk.Frame, row: int) -> ttk.Frame:
        wrapper = ttk.Frame(parent)
        wrapper.grid(row=row, column=0, sticky="nsew")
        wrapper.rowconfigure(0, weight=1)
        wrapper.columnconfigure(0, weight=1)
        canvas = tk.Canvas(wrapper, highlightthickness=0, borderwidth=0, background="#f5f6f8")
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(wrapper, orient=tk.VERTICAL, command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)
        inner = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_inner_configure(_event) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(event) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        inner.bind("<Configure>", on_inner_configure)
        canvas.bind("<Configure>", on_canvas_configure)
        inner.columnconfigure(0, weight=1)
        return inner

    def _populate_setting_fields(self, parameters: dict, paths: dict) -> None:
        self._rebuild_setting_list(self.parameter_fields, self.parameter_vars, parameters, PARAMETER_ORDER)
        self._rebuild_setting_list(self.path_fields, self.path_vars, paths, PATH_ORDER)
        self._populate_auto_editor_fields()

    def _populate_auto_editor_fields(self) -> None:
        if not hasattr(self, "auto_editor_vars"):
            return
        for key, var in self.auto_editor_vars.items():
            source = self.path_vars if key in self.path_vars else self.parameter_vars
            if key in source:
                value = source[key].get()
                if isinstance(value, bool):
                    var.set("true" if value else "false")
                else:
                    var.set(str(value))

    def _sync_auto_editor_vars_to_settings(self) -> None:
        for key, var in self.auto_editor_vars.items():
            source = self.path_vars if key in self.path_vars else self.parameter_vars
            if key in source:
                if key in BOOL_SETTING_KEYS:
                    source[key].set(self._coerce_bool(var.get()))
                else:
                    source[key].set(var.get().strip())

    def _rebuild_setting_list(
        self,
        parent: ttk.Frame,
        var_map: dict[str, tk.Variable],
        values: dict,
        preferred_order: list[str],
    ) -> None:
        for child in parent.winfo_children():
            child.destroy()
        var_map.clear()
        keys = self._ordered_setting_keys(values, preferred_order)
        for row, key in enumerate(keys):
            value = values.get(key, "")
            item = ttk.Frame(parent, padding=(0, 4))
            item.grid(row=row, column=0, sticky="ew")
            item.columnconfigure(1, weight=1)

            label_box = ttk.Frame(item)
            label_box.grid(row=0, column=0, sticky="nw", padx=(0, 12))
            ttk.Label(label_box, text=self._field_label(key)).grid(row=0, column=0, sticky="w")
            help_text = FIELD_HELP.get(key, "Workflow setting")
            ttk.Label(label_box, text=help_text, style="Muted.TLabel", wraplength=250).grid(row=1, column=0, sticky="w")

            if key in BOOL_SETTING_KEYS or isinstance(value, bool):
                var = tk.BooleanVar(value=self._coerce_bool(value))
                var_map[key] = var
                ttk.Checkbutton(item, variable=var).grid(row=0, column=1, sticky="w", pady=(1, 0))
            else:
                var = tk.StringVar(value="" if value is None else str(value))
                var_map[key] = var
                ttk.Entry(item, textvariable=var).grid(row=0, column=1, sticky="ew", pady=(1, 0))
            if key in FILE_KEYS or key in DIRECTORY_KEYS:
                ttk.Button(
                    item,
                    text="Browse",
                    command=lambda k=key, m=var_map: self._browse_setting_value(m, k),
                ).grid(row=0, column=2, padx=(8, 0))

        if not keys:
            ttk.Label(parent, text="No settings for this section.", style="Muted.TLabel").grid(row=0, column=0, sticky="w")

    def _ordered_setting_keys(self, values: dict, preferred_order: list[str]) -> list[str]:
        ordered = [key for key in preferred_order if key in values]
        remaining = sorted(key for key in values if key not in set(ordered))
        return ordered + remaining

    def _field_label(self, key: str) -> str:
        return FIELD_LABELS.get(key, key.replace("_", " ").title())

    def _browse_setting_value(self, var_map: dict[str, tk.Variable], key: str) -> None:
        current = str(var_map[key].get()).strip()
        initial = self._initial_browse_dir(current)
        if key in DIRECTORY_KEYS:
            selected = filedialog.askdirectory(initialdir=initial)
        else:
            selected = filedialog.askopenfilename(initialdir=initial)
        if selected:
            var_map[key].set(selected.replace("\\", "/"))

    def _browse_auto_editor_value(self, key: str) -> None:
        if key not in self.auto_editor_vars:
            return
        current = self.auto_editor_vars[key].get().strip()
        initial = self._initial_browse_dir(current)
        if key in DIRECTORY_KEYS:
            selected = filedialog.askdirectory(initialdir=initial)
        elif key == "raw_autoeditor_fcpxml":
            selected = filedialog.asksaveasfilename(
                initialdir=initial,
                defaultextension=".fcpxml",
                filetypes=[("FCPXML", "*.fcpxml *.xml"), ("All files", "*.*")],
            )
        else:
            selected = filedialog.askopenfilename(initialdir=initial)
        if selected:
            self.auto_editor_vars[key].set(selected.replace("\\", "/"))

    def run_auto_editor(self, *, preview: bool) -> None:
        if not self.profile:
            return
        if not self.save_project_profile():
            return
        assert self.profile is not None
        command = [
            self.profile.mapping(self.catalog.repo).get("python", sys.executable),
            "scripts/orchestrator_auto_editor.py",
            "--config",
            str(self.config_path),
            "--profile",
            self.profile.id,
        ]
        if preview:
            command.append("--preview")
        self._run_background_command(command, label="auto-editor")

    def review_auto_editor_output(self) -> None:
        if not self.profile:
            return
        self._sync_auto_editor_vars_to_settings()
        payload = self._profile_payload_from_editor()
        profile = ProjectProfile.from_dict(payload)
        path = profile.path("raw_autoeditor_fcpxml", self.catalog.repo)
        self.review_artifact_path("raw_autoeditor_fcpxml", path)

    def open_auto_editor_output(self) -> None:
        if not self.profile:
            return
        self._sync_auto_editor_vars_to_settings()
        payload = self._profile_payload_from_editor()
        profile = ProjectProfile.from_dict(payload)
        path = profile.path("raw_autoeditor_fcpxml", self.catalog.repo)
        if not path.exists():
            messagebox.showwarning("Auto-Editor", f"Output does not exist yet:\n{path}")
            return
        open_path(path)

    def _run_background_command(self, command: list[str], *, label: str) -> None:
        def target() -> None:
            self.events.put(RunEvent("log", " ".join(f'"{part}"' if " " in part else part for part in command)))
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(self.catalog.repo),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                self.events.put(RunEvent("error", f"Could not launch {label}: {exc}"))
                return
            assert process.stdout is not None
            for line in process.stdout:
                self.events.put(RunEvent("log", line.rstrip()))
            code = process.wait()
            if code == 0:
                self.events.put(RunEvent("log", f"{label} completed."))
                self.events.put(RunEvent("artifacts", "refresh"))
            else:
                self.events.put(RunEvent("error", f"{label} exited with code {code}."))

        threading.Thread(target=target, daemon=True).start()

    def check_dependencies(self, *, prompt: bool = False) -> None:
        python = sys.executable
        if self.profile:
            python = self.profile.mapping(self.catalog.repo).get("python", sys.executable)
        try:
            checks = check_runtime_dependencies(python)
        except Exception as exc:
            messagebox.showerror("Dependency Check", str(exc))
            return
        self.dependency_checks = checks
        for check in checks:
            state = "ok" if check.ok else "missing"
            self._log(f"Tool check: {check.title}: {state} - {check.detail}")
        missing_required = [item for item in checks if not item.ok and item.id in {"codex", "auto_editor"}]
        if prompt and missing_required:
            self._show_dependency_dialog(checks)

    def _show_dependency_dialog(self, checks: list[DependencyCheck]) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Required Tools")
        dialog.geometry("820x360")
        dialog.transient(self)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)
        ttk.Label(
            dialog,
            text="Install missing tools before running the related workflow steps.",
            style="Header.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 8))
        columns = ("state", "tool", "required_for", "detail", "install")
        tree = ttk.Treeview(dialog, columns=columns, show="headings", selectmode="browse")
        widths = {"state": 80, "tool": 130, "required_for": 210, "detail": 210, "install": 300}
        for column in columns:
            tree.heading(column, text=column.replace("_", " ").title())
            tree.column(column, width=widths[column], anchor="w")
        self._configure_tree_status_tags(tree)
        tree.grid(row=1, column=0, sticky="nsew", padx=12)
        first_missing = ""
        for check in checks:
            state = "ok" if check.ok else "missing"
            tree.insert(
                "",
                "end",
                iid=check.id,
                values=(state, check.title, check.required_for, check.detail, check.install_text),
                tags=(self._status_tag(state),),
            )
            if not check.ok and not first_missing:
                first_missing = check.id
        if first_missing:
            tree.selection_set(first_missing)
            tree.see(first_missing)
        buttons = ttk.Frame(dialog)
        buttons.grid(row=2, column=0, sticky="ew", padx=12, pady=12)
        ttk.Button(buttons, text="Install Selected", command=lambda: self._install_selected_dependency(tree)).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(buttons, text="Copy Command To Log", command=lambda: self._log_selected_dependency_command(tree)).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(buttons, text="Close", command=dialog.destroy).grid(row=0, column=2)

    def _selected_dependency(self, tree: ttk.Treeview) -> DependencyCheck | None:
        selection = tree.selection()
        if not selection:
            return None
        dep_id = selection[0]
        return next((item for item in self.dependency_checks if item.id == dep_id), None)

    def _install_selected_dependency(self, tree: ttk.Treeview) -> None:
        check = self._selected_dependency(tree)
        if not check:
            messagebox.showwarning("Install Tool", "Select a tool first.")
            return
        if check.ok:
            messagebox.showinfo("Install Tool", f"{check.title} is already installed.")
            return
        if not check.install_command:
            messagebox.showwarning("Install Tool", f"No automatic install command is configured for {check.title}.")
            return
        if not messagebox.askyesno("Install Tool", f"Run this command?\n\n{check.install_text}"):
            return
        self._run_background_command(check.install_command, label=f"install {check.title}")

    def _log_selected_dependency_command(self, tree: ttk.Treeview) -> None:
        check = self._selected_dependency(tree)
        if not check:
            messagebox.showwarning("Install Tool", "Select a tool first.")
            return
        self._log(f"Install {check.title}: {check.install_text or 'manual install required'}")

    def _initial_browse_dir(self, current: str) -> str | None:
        if current and "{" not in current:
            path = Path(current)
            if path.is_dir():
                return str(path)
            if path.parent.exists():
                return str(path.parent)
        project_dir = self.project_fields.get("project_dir")
        if project_dir and project_dir.get().strip() and Path(project_dir.get().strip()).exists():
            return project_dir.get().strip()
        return None

    def _collect_setting_values(self, var_map: dict[str, tk.Variable], *, coerce: bool) -> dict:
        values = {}
        for key, var in var_map.items():
            raw_value = var.get()
            if isinstance(raw_value, bool):
                values[key] = raw_value if coerce else ("true" if raw_value else "false")
                continue
            raw = str(raw_value).strip()
            values[key] = self._coerce_setting_value(key, raw) if coerce else raw
        return values

    @staticmethod
    def _coerce_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _coerce_setting_value(self, key: str, value: str):
        if value == "":
            return ""
        if key in {"timeline_fps", "video_track", "carousel_max_candidates", "waveform_sr", "review_sr", "battle_gap_frames", "llm_timeout_sec"}:
            try:
                return int(value)
            except ValueError:
                return value
        if key in {"speech_rms", "voiced_zcr", "fade_sec", "source_duration_sec", "log_match_score"}:
            try:
                return float(value)
            except ValueError:
                return value
        if value.lower() in {"true", "false"}:
            return value.lower() == "true"
        return value

    def open_advanced_config(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Advanced Project Config")
        dialog.geometry("920x620")
        dialog.transient(self)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)

        tabs = ttk.Notebook(dialog)
        tabs.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        params_tab = ttk.Frame(tabs, padding=8)
        paths_tab = ttk.Frame(tabs, padding=8)
        tabs.add(params_tab, text="Automation Settings JSON")
        tabs.add(paths_tab, text="Artifact Paths JSON")
        for frame in (params_tab, paths_tab):
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)

        params_text = tk.Text(params_tab, wrap="none", undo=True)
        paths_text = tk.Text(paths_tab, wrap="none", undo=True)
        params_text.grid(row=0, column=0, sticky="nsew")
        paths_text.grid(row=0, column=0, sticky="nsew")
        params_text.insert("1.0", json.dumps(self._collect_setting_values(self.parameter_vars, coerce=True), indent=2, ensure_ascii=False))
        paths_text.insert("1.0", json.dumps(self._collect_setting_values(self.path_vars, coerce=False), indent=2, ensure_ascii=False))

        buttons = ttk.Frame(dialog, padding=(10, 0, 10, 10))
        buttons.grid(row=1, column=0, sticky="ew")
        buttons.columnconfigure(0, weight=1)

        def apply() -> None:
            try:
                parameters = json.loads(params_text.get("1.0", "end").strip() or "{}")
                paths = json.loads(paths_text.get("1.0", "end").strip() or "{}")
            except json.JSONDecodeError as exc:
                messagebox.showerror("Advanced Config", str(exc), parent=dialog)
                return
            if not isinstance(parameters, dict) or not isinstance(paths, dict):
                messagebox.showerror("Advanced Config", "Both JSON documents must be objects.", parent=dialog)
                return
            self._populate_setting_fields(parameters, paths)
            dialog.destroy()

        ttk.Button(buttons, text="Apply", style="Accent.TButton", command=apply).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=2)

    def reload_config(self) -> None:
        selected_id = self.project_fields.get("id", tk.StringVar()).get() or (self.profile.id if self.profile else "")
        try:
            self.raw_config = self._read_config()
            self.catalog = load_catalog(self.config_path)
        except Exception as exc:
            messagebox.showerror("Reload Config", str(exc))
            return
        self.prompt_engine = PromptEngine(self.catalog.repo)
        self.profile_combo["values"] = [profile.name for profile in self.catalog.profiles]
        self.workflow_id_combo["values"] = [workflow.id for workflow in self.catalog.workflows]
        self.profile = next((profile for profile in self.catalog.profiles if profile.id == selected_id), None)
        if self.profile is None and self.catalog.profiles:
            self.profile = self.catalog.profiles[0]
        self._load_profile()
        self._log(f"Reloaded project config: {self.config_path}")

    def new_project_profile(self) -> None:
        selected_dir = filedialog.askdirectory(title="Choose project folder")
        if not selected_dir:
            return
        project_dir = Path(selected_dir)
        try:
            discovery = discover_project(project_dir)
        except Exception as exc:
            messagebox.showerror("New Project", f"Project auto-detection failed:\n{exc}")
            return

        workflow_id = discovery.workflow_id
        if workflow_id not in {workflow.id for workflow in self.catalog.workflows}:
            workflow_id = self.project_fields.get("workflow_id", tk.StringVar()).get()
        if not workflow_id and self.catalog.workflows:
            workflow_id = self.catalog.workflows[0].id

        if discovery.needs_manual:
            name = simpledialog.askstring(
                "New Project",
                "No matching RBY log was found. Project name:",
                initialvalue=project_dir.name,
            )
            if not name:
                return
        else:
            name = discovery.project_name

        profile_id = self._unique_profile_id(self._slugify(name))
        parameters = self._default_parameters_for_workflow(workflow_id)
        parameters.update(discovery.parameters)
        paths = self._default_paths_for_workflow(workflow_id)
        paths.update(discovery.paths)
        payload = {
            "id": profile_id,
            "name": name,
            "workflow_id": workflow_id,
            "game_version": discovery.game_version,
            "challenge_type": discovery.challenge_type,
            "description": discovery.reason,
            "project_dir": discovery.project_dir,
            "codex_dir": discovery.codex_dir,
            "parameters": parameters,
            "paths": paths,
        }
        self.raw_config.setdefault("profiles", []).append(payload)
        self._write_config()
        self._select_profile_by_id(profile_id)
        self.tabs.select(self.projects_tab)
        self._log(f"Created project profile: {name}")
        self._log(discovery.reason)

    def duplicate_project_profile(self) -> None:
        if not self.profile:
            return
        source = self._raw_profile(self.profile.id)
        if not source:
            messagebox.showerror("Duplicate Project", "Could not find the current profile in the config file.")
            return
        name = simpledialog.askstring("Duplicate Project", "New project name:", initialvalue=f"{self.profile.name} Copy")
        if not name:
            return
        payload = json.loads(json.dumps(source))
        payload["id"] = self._unique_profile_id(self._slugify(name))
        payload["name"] = name
        self.raw_config.setdefault("profiles", []).append(payload)
        self._write_config()
        self._select_profile_by_id(payload["id"])
        self.tabs.select(self.projects_tab)
        self._log(f"Duplicated project profile: {name}")

    def delete_project_profile(self) -> None:
        if not self.profile:
            return
        if len(self.catalog.profiles) <= 1:
            messagebox.showwarning("Delete Project", "Keep at least one project profile in the catalog.")
            return
        if not messagebox.askyesno("Delete Project", f"Delete project profile {self.profile.name!r}?"):
            return
        profile_id = self.profile.id
        self.raw_config["profiles"] = [item for item in self.raw_config.get("profiles", []) if item.get("id") != profile_id]
        self._write_config()
        self.profile = None
        self.reload_config()
        self._log(f"Deleted project profile: {profile_id}")

    def save_project_profile(self) -> bool:
        try:
            payload = self._profile_payload_from_editor()
        except Exception as exc:
            messagebox.showerror("Save Project", str(exc))
            return False
        old_id = self.profile.id if self.profile else payload["id"]
        existing = self.raw_config.setdefault("profiles", [])
        for item in existing:
            if item.get("id") == payload["id"] and item.get("id") != old_id:
                messagebox.showerror("Save Project", f"Profile id {payload['id']!r} already exists.")
                return False
        replaced = False
        for index, item in enumerate(existing):
            if item.get("id") == old_id:
                existing[index] = payload
                replaced = True
                break
        if not replaced:
            existing.append(payload)
        try:
            self._write_config()
            self._select_profile_by_id(payload["id"])
        except Exception as exc:
            messagebox.showerror("Save Project", str(exc))
            return False
        self._log(f"Saved project profile: {payload['name']}")
        return True

    def _profile_payload_from_editor(self) -> dict:
        profile_id = self.project_fields["id"].get().strip()
        name = self.project_fields["name"].get().strip()
        workflow_id = self.project_fields["workflow_id"].get().strip()
        project_dir = self.project_fields["project_dir"].get().strip()
        codex_dir = self.project_fields["codex_dir"].get().strip()
        if not profile_id:
            raise ValueError("Project ID is required.")
        if not re.match(r"^[A-Za-z0-9_.-]+$", profile_id):
            raise ValueError("Project ID may contain only letters, numbers, underscores, periods, and hyphens.")
        if not name:
            raise ValueError("Project name is required.")
        if workflow_id not in {workflow.id for workflow in self.catalog.workflows}:
            raise ValueError(f"Unknown workflow: {workflow_id}")
        self._sync_auto_editor_vars_to_settings()
        parameters = self._collect_setting_values(self.parameter_vars, coerce=True)
        paths = self._collect_setting_values(self.path_vars, coerce=False)
        return {
            "id": profile_id,
            "name": name,
            "workflow_id": workflow_id,
            "game_version": self.project_fields["game_version"].get().strip(),
            "challenge_type": self.project_fields["challenge_type"].get().strip(),
            "description": self.project_fields["description"].get().strip(),
            "project_dir": project_dir,
            "codex_dir": codex_dir,
            "parameters": parameters,
            "paths": paths,
        }

    def _select_profile_by_id(self, profile_id: str) -> None:
        self.raw_config = self._read_config()
        self.catalog = load_catalog(self.config_path)
        self.prompt_engine = PromptEngine(self.catalog.repo)
        self.profile_combo["values"] = [profile.name for profile in self.catalog.profiles]
        self.workflow_id_combo["values"] = [workflow.id for workflow in self.catalog.workflows]
        self.profile = self.catalog.profile(profile_id)
        self._load_profile()

    def _raw_profile(self, profile_id: str) -> dict | None:
        for item in self.raw_config.get("profiles", []):
            if item.get("id") == profile_id:
                return item
        return None

    def _browse_profile_dir(self, field: str) -> None:
        current = self.project_fields.get(field)
        initial = current.get() if current else ""
        path = filedialog.askdirectory(initialdir=initial if initial and Path(initial).exists() else None)
        if path and current:
            current.set(path.replace("\\", "/"))
            if field == "project_dir" and not self.project_fields["codex_dir"].get().strip():
                self.project_fields["codex_dir"].set("{project_dir}/CODEx")

    def _apply_workflow_defaults_to_editor(self) -> None:
        workflow_id = self.project_fields["workflow_id"].get().strip()
        parameters = self._collect_setting_values(self.parameter_vars, coerce=True)
        paths = self._collect_setting_values(self.path_vars, coerce=False)
        for key, value in self._default_parameters_for_workflow(workflow_id).items():
            parameters.setdefault(key, value)
        for key, value in self._default_paths_for_workflow(workflow_id).items():
            paths.setdefault(key, value)
        self._populate_setting_fields(parameters, paths)

    def _default_parameters_for_workflow(self, workflow_id: str) -> dict:
        common = {
            "workflow_config": "{repo}/config/orchestrator_workflows.json",
            "timeline_fps": 60,
            "whisper_model": "large-v3-turbo",
            "llm_dispatch_mode": "auto",
            "llm_open_code_workspace": True,
            "llm_timeout_sec": 3600,
            "llm_model": "",
            "livestream_edit_mode": False,
            "livestream_cut_chat_interactions": False,
            "livestream_bypass_gameplay_narrative_cuts": False,
            "video_track": 1,
            "source_media": "",
            "dialogue_audio": "",
            "auto_editor_input": "{dialogue_audio}",
            "auto_editor_export": "final-cut-pro",
            "auto_editor_margin": "0.2s",
            "auto_editor_edit": "audio",
            "auto_editor_when_normal": "nil",
            "auto_editor_when_silent": "cut",
            "auto_editor_frame_rate": "{timeline_fps}",
            "auto_editor_extra_args": "",
            "auto_editor_preview": False,
            "waveform_sr": 16000,
            "review_sr": 44100,
            "speech_rms": 0.02,
            "voiced_zcr": 0.25,
            "render_preset": "qa",
            "render_name_arg": "",
            "render_name": "",
            "render_dir_arg": "",
            "render_dir": "",
            "fairlight_timeline_arg": "",
            "fairlight_timeline": "",
        }
        if workflow_id == "gen1_rby_umb_review_first":
            common.update({
                "pipeline_script": "scripts/run_mewtwo_rby_umb_pipeline.py",
                "carousel_max_candidates": 30,
                "review_fcpxml": "{codex_dir}/cut_review/review_base.fcpxml",
            })
        elif workflow_id == "pokemon_gym_leader_challenge":
            common.update({
                "game_key": "pokemon_crystal",
                "input_fcpxml": "",
                "battle_gap_frames": 60,
                "import_to_resolve_flag": "--import-to-resolve",
                "battle_intro_overlap_sec": 5,
                "include_other_battle_intros_flag": "",
                "intro_speed_arg": "",
                "intro_speed": "",
                "seed_arg": "",
                "seed": "",
                "rival_track_arg": "",
                "rival_track": "",
                "gym_track_arg": "",
                "gym_track": "",
                "other_track_arg": "",
                "other_track": "",
                "fade_sec": 0.5,
                "carousel_marker_names": "Member Carousel Start,Member Carousel",
                "carousel_max_candidates": 30,
            })
        return common

    def _default_paths_for_workflow(self, workflow_id: str) -> dict:
        common = {
            "clips_json": "{codex_dir}/cut_review/clips.json",
            "raw_autoeditor_fcpxml": "{project_dir}/{source_name}_AUTOEDITOR_RAW.fcpxml",
            "review_clips_json": "{codex_dir}/cut_review/clips_for_review.json",
            "categories_json": "{codex_dir}/cut_review/categories.json",
            "cut_review_dir": "{codex_dir}/cut_review",
            "html_review_dir": "{codex_dir}/cut_review/review",
            "html_clips": "{codex_dir}/cut_review/clips_for_review.json",
            "html_index": "{codex_dir}/cut_review/review/index.html",
            "html_segmap": "{codex_dir}/cut_review/review/segmap.json",
            "html_decisions": "{codex_dir}/cut_review/review/pink_decisions.json",
            "native_review_dir": "{codex_dir}/cut_review/native",
            "approved_review_timeline": "{profile_name} approved review spine",
            "transcript_json": "{codex_dir}/transcripts/transcript.json",
            "narrative_prompt": "{codex_dir}/cut_review/narrative/review.in.md",
            "narrative_clip_index": "{codex_dir}/cut_review/narrative/clip_index.json",
            "narrative_output": "{codex_dir}/cut_review/narrative/review.out.json",
            "waveform_candidates": "{codex_dir}/cut_review/waveform_candidates.json",
            "ngram_candidates": "{codex_dir}/cut_review/ngram_candidates.json",
            "artifact_candidates": "{codex_dir}/cut_review/artifact_candidates.json",
            "programmatic_candidates": "{codex_dir}/cut_review/programmatic_candidates.json",
            "approved_narrative": "{codex_dir}/cut_review/approved_narrative_cuts.json",
            "native_normalized_ranges": "{codex_dir}/review_decisions_native/review_decisions_normalized_ranges.json",
            "fcpxml_review_artifact": "{codex_dir}/cut_review/fcpxml_segment_review.json",
            "fcpxml_review_decisions": "{codex_dir}/cut_review/fcpxml_segment_decisions.json",
            "pipeline_order_report": "{codex_dir}/mewtwo_pipeline_order_report.json",
            "review_fcpxml": "{codex_dir}/cut_review/review_base.fcpxml",
            "llm_instructions": "{repo}/docs/edit_flow_llm_instructions.md",
        }
        if workflow_id == "gen1_rby_umb_review_first":
            common.update({
                "candidate_manifest": "{codex_dir}/cut_review/cut_candidates.json",
                "approved_source_cuts": "{codex_dir}/cut_review/approved_source_cuts.json",
                "game_audio": "{project_dir}/{source_name}_tracks/{source_name}_3.wav",
                "final_manifest": "{codex_dir}/final_rebuild_manifest.json",
                "clip_color_report": "{codex_dir}/qa-reports/section_color_report.json",
            })
        elif workflow_id == "pokemon_gym_leader_challenge":
            common.update({
                "battles_json": "{codex_dir}/transcripts/battles.json",
                "battle_gaps_fcpxml": "{codex_dir}/fcpxml/battle_gaps.fcpxml",
            })
        return common

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_").lower()
        return slug or "project"

    def _unique_profile_id(self, base: str) -> str:
        existing = {item.get("id") for item in self.raw_config.get("profiles", [])}
        candidate = base
        index = 2
        while candidate in existing:
            candidate = f"{base}_{index}"
            index += 1
        return candidate

    def _populate_steps(self) -> None:
        self.step_rows.clear()
        for item in self.step_tree.get_children():
            self.step_tree.delete(item)
        if not self.workflow:
            return
        readiness = step_readiness(self.profile, self.workflow, self.catalog.repo) if self.profile else {}
        for step in self.workflow.steps:
            iid = step.id
            status = readiness.get(step.id, "idle")
            self.step_rows[step.id] = iid
            self.step_tree.insert(
                "",
                "end",
                iid=iid,
                values=(step.phase, step.kind, status, step.title),
                tags=(self._status_tag(status),),
            )

    def _populate_artifacts(self) -> None:
        for item in self.artifact_tree.get_children():
            self.artifact_tree.delete(item)
        if not self.profile or not self.workflow:
            return
        for artifact in collect_artifact_status(self.profile, self.workflow, self.catalog.repo):
            state = "ok" if artifact.exists else "missing"
            self.artifact_tree.insert(
                "",
                "end",
                iid=artifact.key,
                values=(
                    state,
                    artifact.key,
                    str(artifact.path),
                    ", ".join(sorted(artifact.required_by)),
                    ", ".join(sorted(artifact.produced_by)),
                ),
                tags=(self._status_tag(state),),
            )

    def refresh_status(self) -> None:
        if not self.profile or not self.workflow:
            return
        readiness = step_readiness(self.profile, self.workflow, self.catalog.repo)
        for step_id, status in readiness.items():
            if step_id in self.step_rows:
                phase, kind, _old_status, title = self.step_tree.item(step_id, "values")
                self.step_tree.item(step_id, values=(phase, kind, status, title))
                self.step_tree.item(step_id, tags=(self._status_tag(status),))
        self._populate_artifacts()

    def _populate_llm_tasks(self) -> None:
        if not self.workflow:
            return
        task_ids = list(dict.fromkeys([step.llm_task for step in self.workflow.steps if step.llm_task] + self.workflow.llm_tasks))
        labels = []
        for task_id in task_ids:
            try:
                task = self.catalog.effective_llm_task(self.profile, task_id)  # type: ignore[arg-type]
            except Exception:
                continue
            labels.append(f"{task.id} - {task.title}")
        self.llm_task_combo["values"] = labels
        if labels:
            self.llm_task_var.set(labels[0])
            self._refresh_llm_detail()

    def _selected_steps(self) -> list:
        if not self.workflow:
            return []
        selected = set(self.step_tree.selection())
        if not selected:
            return []
        return [step for step in self.workflow.steps if step.id in selected]

    def run_selected_steps(self) -> None:
        if not self.profile or not self.workflow:
            return
        steps = self._selected_steps()
        if not steps:
            messagebox.showwarning("Resolve Orchestrator", "Select one or more workflow steps first.")
            return
        try:
            self.threaded_run.start(self.profile, self.workflow, steps)
        except Exception as exc:
            messagebox.showerror("Resolve Orchestrator", str(exc))

    def run_full_workflow(self) -> None:
        if not self.profile or not self.workflow:
            return
        steps = [step for step in self.workflow.steps if step.run_in_full]
        try:
            self.threaded_run.start(self.profile, self.workflow, steps)
        except Exception as exc:
            messagebox.showerror("Resolve Orchestrator", str(exc))

    def select_downstream_steps(self) -> None:
        steps = self._downstream_steps_from_selection()
        if not steps:
            messagebox.showwarning("Resolve Orchestrator", "Select the first workflow step to redo.")
            return
        self.step_tree.selection_set([step.id for step in steps])
        self.step_tree.see(steps[0].id)

    def run_downstream_steps(self) -> None:
        if not self.profile or not self.workflow:
            return
        steps = self._downstream_steps_from_selection()
        if not steps:
            messagebox.showwarning("Resolve Orchestrator", "Select the first workflow step to redo.")
            return
        try:
            self.threaded_run.start(self.profile, self.workflow, steps)
        except Exception as exc:
            messagebox.showerror("Resolve Orchestrator", str(exc))

    def _downstream_steps_from_selection(self) -> list[WorkflowStep]:
        if not self.workflow:
            return []
        selected = set(self.step_tree.selection())
        if not selected:
            return []
        selected_indexes = [index for index, step in enumerate(self.workflow.steps) if step.id in selected]
        if not selected_indexes:
            return []
        start = min(selected_indexes)
        return [
            step
            for index, step in enumerate(self.workflow.steps)
            if index >= start and (step.run_in_full or step.id in selected)
        ]

    def review_selected_step_outputs(self) -> None:
        if not self.profile or not self.workflow:
            return
        steps = self._selected_steps()
        if not steps:
            messagebox.showwarning("Review Outputs", "Select a workflow step first.")
            return
        candidates: list[tuple[int, str, Path]] = []
        priority = {
            "html_index": 0,
            "review_fcpxml": 1,
            "raw_autoeditor_fcpxml": 2,
            "fcpxml_review_artifact": 3,
            "transcript_json": 4,
            "narrative_prompt": 5,
            "narrative_output": 6,
            "candidate_manifest": 7,
            "programmatic_candidates": 8,
            "waveform_candidates": 9,
            "ngram_candidates": 10,
            "artifact_candidates": 11,
        }
        for step in steps:
            for artifact in step.artifacts_out:
                path = self.profile.path(artifact.key, self.catalog.repo)
                if path.exists():
                    candidates.append((priority.get(artifact.key, 50), artifact.key, path))
        if candidates:
            _priority, key, path = sorted(candidates, key=lambda item: item[0])[0]
            self.review_artifact_path(key, path)
            return
        messagebox.showwarning("Review Outputs", "The selected step has no existing output artifact to review yet.")

    def select_phase(self) -> None:
        if not self.workflow:
            return
        phases = sorted({step.phase for step in self.workflow.steps})
        phase = simpledialog.askstring("Select Phase", f"Phase ({', '.join(phases)}):")
        if not phase:
            return
        self.step_tree.selection_set([step.id for step in self.workflow.steps if step.phase == phase])

    def generate_prompt_packet(self) -> None:
        if not self.profile or not self.workflow:
            return
        task_id = self._current_task_id()
        if not task_id:
            return
        task = self.catalog.effective_llm_task(self.profile, task_id)
        packet = self.prompt_engine.build_packet(self.profile, self.workflow, task)
        self.prompt_engine.write_packet(packet)
        self.generated_prompt_paths[task.id] = packet.prompt_path
        self.llm_text.delete("1.0", "end")
        self.llm_text.insert("1.0", packet.prompt_text)
        self._log(f"Wrote LLM prompt: {packet.prompt_path}")
        self._log(f"Wrote LLM packet: {packet.packet_path}")

    def run_current_llm_task(self) -> None:
        if not self.profile or not self.workflow:
            return
        if self.llm_task_thread and self.llm_task_thread.is_alive():
            messagebox.showwarning("Resolve Orchestrator", "An LLM task is already running.")
            return
        task_id = self._current_task_id()
        if not task_id:
            return
        profile = self.profile
        workflow = self.workflow
        task = self.catalog.effective_llm_task(profile, task_id)

        def target() -> None:
            try:
                dispatcher = LLMDispatcher(
                    self.catalog.repo,
                    log=lambda message: self.events.put(RunEvent("log", message)),
                )
                result = dispatcher.dispatch(profile, workflow, task)
                self.generated_prompt_paths[task.id] = result.prompt_path
                self.events.put(RunEvent("log", f"LLM feedback confirmed: {result.output_path}"))
                self.events.put(RunEvent("artifacts", "refresh"))
            except Exception as exc:
                self.events.put(RunEvent("error", str(exc)))

        self.llm_task_thread = threading.Thread(target=target, daemon=True)
        self.llm_task_thread.start()

    def _handle_llm_step(self, profile: ProjectProfile, workflow: WorkflowDefinition, step) -> None:
        if not step.llm_task:
            self.events.put(RunEvent("log", f"{step.title}: no LLM task configured.", step.id, "done"))
            return
        task = self.catalog.effective_llm_task(profile, step.llm_task)
        dispatcher = LLMDispatcher(
            self.catalog.repo,
            log=lambda message: self.events.put(RunEvent("log", message, step.id, "running")),
        )
        result = dispatcher.dispatch(profile, workflow, task)
        self.generated_prompt_paths[task.id] = result.prompt_path
        self.events.put(RunEvent("log", f"LLM feedback confirmed: {result.output_path}", step.id, "done"))

    def open_generated_prompt(self) -> None:
        task_id = self._current_task_id()
        generated = self.generated_prompt_paths.get(task_id)
        if generated:
            try:
                open_path(generated)
            except Exception as exc:
                messagebox.showerror("Resolve Orchestrator", str(exc))
            return
        self._open_task_path("prompt_path")

    def open_llm_output(self) -> None:
        self._open_task_path("output_path")

    def _open_task_path(self, attr: str) -> None:
        if not self.profile:
            return
        task_id = self._current_task_id()
        if not task_id:
            return
        task = self.catalog.effective_llm_task(self.profile, task_id)
        path_value = getattr(task, attr)
        if not path_value:
            messagebox.showwarning("Resolve Orchestrator", f"Task has no {attr}.")
            return
        try:
            open_path(Path(path_value))
        except Exception as exc:
            messagebox.showerror("Resolve Orchestrator", str(exc))

    def _current_task_id(self) -> str:
        raw = self.llm_task_var.get()
        if " - " in raw:
            return raw.split(" - ", 1)[0]
        return raw.strip()

    def _refresh_llm_detail(self) -> None:
        if not self.profile:
            return
        task_id = self._current_task_id()
        if not task_id:
            return
        task = self.catalog.effective_llm_task(self.profile, task_id)
        self.llm_detail.set(f"{task.task_type}: {task.why_llm}")

    def load_fcpxml(self) -> None:
        path = filedialog.askopenfilename(
            title="Load FCPXML",
            filetypes=[("FCPXML", "*.fcpxml *.xml"), ("All files", "*.*")],
        )
        if not path:
            return
        self._load_fcpxml_path(Path(path))

    def _populate_segments(self) -> None:
        for item in self.segment_tree.get_children():
            self.segment_tree.delete(item)
        model = self.review_model
        if not model:
            return
        for segment in model.video_segments:
            decision = self.segment_decisions.get(segment.id, {}).get("decision", "keep")
            self.segment_tree.insert("", "end", iid=segment.id, values=self._segment_values(segment.id, decision))
        self.review_detail.set(f"{model.path} | {len(model.video_segments)} video segment(s)")

    def _segment_values(self, segment_id: str, decision: str) -> tuple:
        assert self.review_model is not None
        segment = next(item for item in self.review_model.video_segments if item.id == segment_id)
        return (
            decision,
            segment.offset_frames,
            segment.duration_frames,
            segment.source_start_frames,
            segment.source_end_frames,
            segment.name,
            segment.source_path,
        )

    def set_segment_decision(self, decision: str) -> None:
        if not self.review_model:
            return
        for segment_id in self.segment_tree.selection():
            segment = next(item for item in self.review_model.video_segments if item.id == segment_id)
            current = self.segment_decisions.get(segment_id, segment.as_decision_row())
            current["decision"] = decision
            self.segment_decisions[segment_id] = current
            self.segment_tree.item(segment_id, values=self._segment_values(segment_id, decision))

    def note_selected_segments(self) -> None:
        note = simpledialog.askstring("Segment Note", "Note for selected segment(s):")
        if note is None or not self.review_model:
            return
        for segment_id in self.segment_tree.selection():
            segment = next(item for item in self.review_model.video_segments if item.id == segment_id)
            current = self.segment_decisions.get(segment_id, segment.as_decision_row())
            current["note"] = note
            self.segment_decisions[segment_id] = current

    def export_segment_decisions(self) -> None:
        if not self.review_model:
            return
        default = self.review_model.path.with_suffix(".segment_decisions.json")
        path = filedialog.asksaveasfilename(
            title="Export segment decisions",
            initialfile=default.name,
            initialdir=str(default.parent),
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        decisions = {
            segment.id: self.segment_decisions.get(segment.id, segment.as_decision_row())
            for segment in self.review_model.video_segments
            if self.segment_decisions.get(segment.id, {}).get("decision", "keep") != "keep"
        }
        self.review_model.write_decisions(Path(path), decisions)
        self._log(f"Wrote segment decisions: {path}")

    def review_selected_artifact(self) -> None:
        selected = self.artifact_tree.selection()
        if not selected:
            messagebox.showwarning("Review Artifact", "Select an artifact first.")
            return
        values = self.artifact_tree.item(selected[0], "values")
        if len(values) < 3:
            return
        key = str(values[1])
        path = Path(str(values[2]))
        self.review_artifact_path(key, path)

    def open_selected_artifact(self) -> None:
        selected = self.artifact_tree.selection()
        if not selected:
            messagebox.showwarning("Open Artifact", "Select an artifact first.")
            return
        values = self.artifact_tree.item(selected[0], "values")
        path = Path(str(values[2]))
        if not path.exists():
            messagebox.showwarning("Open Artifact", f"Artifact does not exist yet:\n{path}")
            return
        open_path(path)

    def open_selected_artifact_folder(self) -> None:
        selected = self.artifact_tree.selection()
        if not selected:
            messagebox.showwarning("Open Artifact Folder", "Select an artifact first.")
            return
        values = self.artifact_tree.item(selected[0], "values")
        path = Path(str(values[2]))
        folder = path if path.is_dir() else path.parent
        if not folder.exists():
            messagebox.showwarning("Open Artifact Folder", f"Folder does not exist yet:\n{folder}")
            return
        open_path(folder)

    def review_artifact_path(self, key: str, path: Path) -> None:
        if not path.exists():
            messagebox.showwarning("Review Artifact", f"Artifact does not exist yet:\n{path}")
            return
        if path.is_dir():
            open_path(path)
            return
        suffix = path.suffix.lower()
        if suffix in {".fcpxml", ".xml"}:
            self._load_fcpxml_path(path)
            return
        if suffix in {".html", ".htm"}:
            open_path(path)
            return
        self._show_artifact_preview(key, path)

    def _load_fcpxml_path(self, path: Path) -> None:
        try:
            fps = 60.0
            if self.profile:
                fps = float(self.profile.mapping(self.catalog.repo).get("timeline_fps", "60") or 60)
            self.review_model = load_fcpxml_review_model(path, fps=fps, video_only=True)
        except Exception as exc:
            messagebox.showerror("FCPXML Review", str(exc))
            return
        self.segment_decisions.clear()
        self._populate_segments()
        self.tabs.select(self.review_tab)

    def _show_artifact_preview(self, key: str, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            messagebox.showerror("Review Artifact", str(exc))
            return
        if path.suffix.lower() == ".json":
            try:
                text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            except json.JSONDecodeError:
                pass
        limit = 500_000
        clipped = len(text) > limit
        if clipped:
            text = text[:limit] + "\n\n[Preview truncated. Open the file for the full artifact.]"
        dialog = tk.Toplevel(self)
        dialog.title(f"Review Artifact: {key}")
        dialog.geometry("980x700")
        dialog.transient(self)
        dialog.rowconfigure(1, weight=1)
        dialog.columnconfigure(0, weight=1)
        ttk.Label(dialog, text=str(path), foreground="#555", wraplength=940).grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        preview = tk.Text(dialog, wrap="none")
        preview.insert("1.0", text)
        preview.configure(state="disabled")
        preview.grid(row=1, column=0, sticky="nsew", padx=10)
        scroll = ttk.Scrollbar(dialog, orient=tk.VERTICAL, command=preview.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        preview.configure(yscrollcommand=scroll.set)
        buttons = ttk.Frame(dialog)
        buttons.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
        ttk.Button(buttons, text="Open File", command=lambda: open_path(path)).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(buttons, text="Open Folder", command=lambda: open_path(path.parent)).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(buttons, text="Close", command=dialog.destroy).grid(row=0, column=2)

    def open_project_folder(self) -> None:
        if self.profile:
            open_path(Path(self.profile.project_dir))

    def open_codex_folder(self) -> None:
        if self.profile:
            open_path(Path(self.profile.codex_dir))

    def _poll_events(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event.kind == "log":
                self._log(event.message)
            elif event.kind == "step":
                if event.step_id in self.step_rows:
                    phase, kind, _status, title = self.step_tree.item(event.step_id, "values")
                    self.step_tree.item(event.step_id, values=(phase, kind, event.status, title))
                    self.step_tree.item(event.step_id, tags=(self._status_tag(event.status),))
                    if event.status == "done":
                        self._populate_artifacts()
            elif event.kind == "pause":
                self._log(event.message)
            elif event.kind == "resolve":
                self.resolve_detail.set(event.message)
            elif event.kind == "artifacts":
                self.refresh_status()
            elif event.kind == "error":
                self._log(f"ERROR: {event.message}")
                messagebox.showerror("Resolve Orchestrator", event.message)
        self.after(120, self._poll_events)

    def _log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve orchestrator GUI")
    parser.add_argument("--config", type=Path, default=DEFAULT_WORKFLOW_CONFIG)
    parser.add_argument("--dump-workflows", action="store_true")
    args = parser.parse_args(argv)

    catalog = load_catalog(args.config)
    if args.dump_workflows:
        for workflow in catalog.workflows:
            print(f"{workflow.id}\t{workflow.name}")
        return 0

    app = OrchestratorApp(catalog, args.config)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
