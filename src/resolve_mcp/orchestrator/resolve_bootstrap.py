from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ProjectProfile


RESOLVE_EXE = Path(r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe")


@dataclass(frozen=True)
class ResolveStatus:
    connected: bool
    project_name: str = ""
    timeline_name: str = ""
    page: str = ""


@dataclass(frozen=True)
class ResolveBootstrapResult:
    launched: bool
    project_name: str
    project_created: bool
    project_loaded: bool
    timeline_name: str
    timeline_created: bool
    page: str

    def summary(self) -> str:
        launch = "launched Resolve" if self.launched else "Resolve already running"
        project_action = "created project" if self.project_created else "loaded project" if self.project_loaded else "using project"
        parts = [f"{launch}; {project_action} {self.project_name!r}"]
        if self.timeline_name:
            timeline_action = "created timeline" if self.timeline_created else "using timeline"
            parts.append(f"{timeline_action} {self.timeline_name!r}")
        parts.append(f"page={self.page or 'unknown'}")
        return "; ".join(parts)


def probe_resolve(repo: Path) -> ResolveStatus:
    dvr = _import_resolve_module(repo)
    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        return ResolveStatus(connected=False)
    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject() if project_manager else None
    timeline = project.GetCurrentTimeline() if project else None
    return ResolveStatus(
        connected=True,
        project_name=project.GetName() if project else "",
        timeline_name=timeline.GetName() if timeline else "",
        page=resolve.GetCurrentPage() or "",
    )


def ensure_resolve_ready(
    profile: ProjectProfile,
    repo: Path,
    *,
    timeout_sec: int = 120,
    ensure_timeline: bool | None = None,
) -> ResolveBootstrapResult:
    dvr = _import_resolve_module(repo)
    launched = False
    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        _launch_resolve()
        launched = True
        resolve = _wait_for_resolve(dvr, timeout_sec)

    project_manager = resolve.GetProjectManager()
    if project_manager is None:
        raise RuntimeError("Resolve is running but ProjectManager is unavailable.")

    target_project = _target_project_name(profile)
    project, project_created, project_loaded = _load_or_create_project(project_manager, target_project)
    if project is None:
        raise RuntimeError(f"Could not load or create Resolve project {target_project!r}.")

    if ensure_timeline is None:
        ensure_timeline = str(profile.parameters.get("resolve_create_bootstrap_timeline", "")).lower() in {"1", "true", "yes"}

    timeline_name = ""
    timeline_created = False
    if ensure_timeline:
        target_timeline = _target_timeline_name(profile)
        timeline, timeline_created = _get_or_create_timeline(project, target_timeline)
        if timeline is not None:
            project.SetCurrentTimeline(timeline)
            timeline_name = timeline.GetName() or target_timeline

    try:
        resolve.OpenPage("edit")
    except Exception:
        pass
    try:
        project_manager.SaveProject()
    except Exception:
        pass

    return ResolveBootstrapResult(
        launched=launched,
        project_name=project.GetName() or target_project,
        project_created=project_created,
        project_loaded=project_loaded,
        timeline_name=timeline_name,
        timeline_created=timeline_created,
        page=resolve.GetCurrentPage() or "",
    )


def _import_resolve_module(repo: Path) -> Any:
    scripts_dir = repo / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import _resolve_env  # noqa: F401
    import DaVinciResolveScript as dvr

    return dvr


def _launch_resolve() -> None:
    if not RESOLVE_EXE.exists():
        raise RuntimeError(f"Resolve executable not found: {RESOLVE_EXE}")
    subprocess.Popen([str(RESOLVE_EXE)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _wait_for_resolve(dvr: Any, timeout_sec: int) -> Any:
    deadline = time.monotonic() + timeout_sec
    last_error = "Resolve did not expose the scripting API yet."
    while time.monotonic() < deadline:
        try:
            resolve = dvr.scriptapp("Resolve")
            if resolve is not None:
                return resolve
        except Exception as exc:
            last_error = str(exc)
        time.sleep(2.0)
    raise RuntimeError(
        "Timed out waiting for DaVinci Resolve scripting. Confirm "
        "Preferences > General > External scripting using is set to Local. "
        f"Last error: {last_error}"
    )


def _target_project_name(profile: ProjectProfile) -> str:
    raw = (
        profile.parameters.get("resolve_project_name")
        or profile.parameters.get("resolve_project")
        or profile.name
    )
    name = str(raw).strip()
    return name or profile.name or profile.id


def _target_timeline_name(profile: ProjectProfile) -> str:
    raw = (
        profile.parameters.get("resolve_timeline_name")
        or profile.parameters.get("resolve_bootstrap_timeline_name")
        or f"{profile.name} bootstrap"
    )
    name = str(raw).strip()
    return name or f"{profile.name or profile.id} bootstrap"


def _load_or_create_project(project_manager: Any, name: str) -> tuple[Any, bool, bool]:
    current = project_manager.GetCurrentProject()
    if current is not None and (current.GetName() or "") == name:
        return current, False, False

    loaded = project_manager.LoadProject(name)
    if loaded:
        return loaded, False, True

    created = project_manager.CreateProject(name)
    if created:
        return created, True, False

    loaded = project_manager.LoadProject(name)
    if loaded:
        return loaded, False, True
    return None, False, False


def _get_or_create_timeline(project: Any, name: str) -> tuple[Any, bool]:
    for index in range(1, int(project.GetTimelineCount() or 0) + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline and (timeline.GetName() or "") == name:
            return timeline, False

    current = project.GetCurrentTimeline()
    if current is not None and int(project.GetTimelineCount() or 0) > 0 and not name:
        return current, False

    media_pool = project.GetMediaPool()
    if media_pool is None:
        raise RuntimeError("Resolve project has no media pool.")
    timeline = media_pool.CreateEmptyTimeline(name)
    if timeline is None:
        current = project.GetCurrentTimeline()
        if current is not None:
            return current, False
        raise RuntimeError(f"CreateEmptyTimeline failed for {name!r}.")
    return timeline, True
