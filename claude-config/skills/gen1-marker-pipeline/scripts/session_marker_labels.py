"""Helpers for turning RBYNewLayout session events into human marker labels.

Used by `resolve_clip_markers_to_timeline.py` after promoting OBS chapter
markers to the timeline. We replay the same MARKER_RULES + per-rule debounce
logic that `utils/sessionLog-main.js` applies at runtime so the order of
"intended markers" matches the order of OBS chapter markers in the file.

Pure stdlib so it runs under Resolve's embedded Python or any external 3.10+.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional


# Mirror of MARKER_RULES in utils/sessionLog-main.js. If you change one,
# change the other.
@dataclass
class _Rule:
    category: Optional[str] = None
    name: Optional[str] = None
    name_re: Optional[str] = None
    debounce_ms: int = 1500

    def matches(self, ev: dict) -> bool:
        if self.category and ev.get("category") != self.category:
            return False
        if self.name and ev.get("name") != self.name:
            return False
        if self.name_re and not re.search(self.name_re, ev.get("name") or ""):
            return False
        return True


_MARKER_RULES: List[_Rule] = [
    _Rule(category="view", name="intro-started"),
    _Rule(category="view", name="pregame-card-shown"),
    _Rule(category="event", name="first-pokemon-received"),
    _Rule(category="battle", name="battle-start", debounce_ms=2000),
    _Rule(category="battle", name="battle-end", debounce_ms=2000),
    _Rule(category="champion", name="beat-champion-flag"),
    _Rule(category="view", name="post-battle-tiercard-shown"),
    _Rule(category="view", name="post-battle-tiercard-closed"),
    _Rule(category="view", name_re=r"^final-tierlist-(podium|traditional)-shown$"),
    _Rule(category="view", name="member-carousel-started"),
]


def _match_rule(ev: dict) -> Optional[_Rule]:
    for r in _MARKER_RULES:
        if r.matches(ev):
            return r
    return None


# Pretty leader names. Keys are the raw `data.leader` / `data.from` strings
# we emit in Yellow.js (playLeaderAudio first arg).
_LEADER_LABELS = {
    "BROCK": "Brock",
    "MISTY": "Misty",
    "LT.SURGE": "Lt. Surge",
    "ERIKA": "Erika",
    "KOGA": "Koga",
    "SABRINA": "Sabrina",
    "BLAINE": "Blaine",
    "GIOVANNI_GYM": "Giovanni",
    "GIOVANNI_1": "Giovanni (R1)",
    "GIOVANNI_2": "Giovanni (R2)",
    "LORELEI": "Lorelei",
    "BRUNO": "Bruno",
    "AGATHA": "Agatha",
    "LANCE": "Lance",
    "RIVAL3": "Champion",
    "RIVAL": "Rival",
}


# Resolve marker palette (the strings AddMarker accepts):
#   Blue Cyan Green Yellow Red Pink Purple Fuchsia Rose Lavender
#   Sky Mint Lemon Sand Cocoa Cream
# Mapped roughly to each leader's signature type so the timeline reads as
# a type chart at a glance.
_LEADER_COLORS = {
    "BROCK":        "Sand",      # Rock
    "MISTY":        "Sky",       # Water
    "LT.SURGE":     "Yellow",    # Electric
    "ERIKA":        "Green",     # Grass
    "KOGA":         "Purple",    # Poison
    "SABRINA":      "Pink",      # Psychic
    "BLAINE":       "Red",       # Fire
    "GIOVANNI_GYM": "Cream",     # Ground
    "GIOVANNI_1":   "Cream",
    "GIOVANNI_2":   "Cream",
    "LORELEI":      "Cyan",      # Ice
    "BRUNO":        "Cocoa",     # Fighting
    "AGATHA":       "Lavender",  # Ghost
    "LANCE":        "Fuchsia",   # Dragon
    "RIVAL3":       "Rose",      # Champion
    "RIVAL":        "Mint",      # Rival 1/2
}

# Default colors for non-battle marker categories.
_CATEGORY_COLORS = {
    "view":     "Blue",
    "event":    "Green",
    "champion": "Purple",
    "battle":   "Red",
}


def _leader_label(raw):
    if not raw:
        return None
    return _LEADER_LABELS.get(raw, raw.title())


def _leader_color(raw):
    if not raw:
        return None
    return _LEADER_COLORS.get(raw)


def _color_for(ev):
    cat = ev.get("category") or ""
    name = ev.get("name") or ""
    data = ev.get("data") or {}
    if cat == "battle" and name == "battle-start":
        c = _leader_color(data.get("leader"))
        if c:
            return c
    if cat == "battle" and name == "battle-end":
        c = _leader_color(data.get("from"))
        if c:
            return c
    if cat == "view" and name == "intro-started":
        return "Cyan"
    if cat == "view" and name == "pregame-card-shown":
        return "Sky"
    if cat == "event" and name == "first-pokemon-received":
        return "Mint"
    if cat == "champion" and name == "beat-champion-flag":
        return "Rose"
    if cat == "view" and name in ("post-battle-tiercard-shown",
                                  "post-battle-tiercard-closed"):
        return "Yellow"
    if cat == "view" and name.startswith("final-tierlist-"):
        return "Purple"
    if cat == "view" and name == "member-carousel-started":
        return "Sand"
    return _CATEGORY_COLORS.get(cat, "Blue")


def _label_for(ev: dict) -> str:
    cat = ev.get("category") or ""
    name = ev.get("name") or ""
    data = ev.get("data") or {}
    if cat == "battle" and name == "battle-start":
        leader = _leader_label(data.get("leader"))
        return f"{leader} Battle Start" if leader else "Battle Start"
    if cat == "battle" and name == "battle-end":
        leader = _leader_label(data.get("from"))
        return f"{leader} Battle Finish" if leader else "Battle Finish"
    if cat == "view" and name == "intro-started":
        return "Intro"
    if cat == "view" and name == "pregame-card-shown":
        return "Get Pokemon"
    if cat == "event" and name == "first-pokemon-received":
        return "First Pokemon"
    if cat == "champion" and name == "beat-champion-flag":
        return "Beat Champion"
    if cat == "view" and name == "post-battle-tiercard-shown":
        return "Post-Battle Tiercard"
    if cat == "view" and name == "post-battle-tiercard-closed":
        return "Post-Battle Tiercard Closed"
    if cat == "view" and name == "final-tierlist-podium-shown":
        return "Final Tierlist (Podium)"
    if cat == "view" and name == "final-tierlist-traditional-shown":
        return "Final Tierlist (Traditional)"
    if cat == "view" and name == "member-carousel-started":
        return "Member Carousel"
    return f"{cat}:{name}".strip(":") or "Marker"


@dataclass
class IntendedMarker:
    label: str
    note: str
    color: str
    category: str
    name: str
    t_elapsed_ms: int
    tc: str


def replay_markers(events: Iterable[dict]) -> List[IntendedMarker]:
    """Return the ordered list of markers that *would have been fired* for
    these events, applying the same debounce we use at runtime."""
    last_fire_ms: dict[str, int] = {}
    out: List[IntendedMarker] = []
    for ev in events:
        rule = _match_rule(ev)
        if rule is None:
            continue
        key = f"{ev.get('category')}:{ev.get('name')}"
        t_ms = int(ev.get("tElapsedMs") or 0)
        last = last_fire_ms.get(key, -10**12)
        if t_ms - last < rule.debounce_ms:
            continue
        last_fire_ms[key] = t_ms
        data = ev.get("data") or {}
        note_bits = []
        for k in ("leader", "from", "to", "trainer"):
            if k in data and data[k] is not None:
                note_bits.append(f"{k}={data[k]}")
        out.append(
            IntendedMarker(
                label=_label_for(ev),
                note="; ".join(note_bits),
                color=_color_for(ev),
                category=ev.get("category") or "",
                name=ev.get("name") or "",
                t_elapsed_ms=t_ms,
                tc=ev.get("tc") or "",
            )
        )
    return out


# ---------- session log discovery ----------

def default_logs_root() -> str:
    """`%APPDATA%\\rbypc-frontend\\logs` on Windows; closest equivalent
    on macOS/Linux. The Electron app's name is `rbypc-frontend`."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return os.path.join(appdata, "rbypc-frontend", "logs")
    home = os.path.expanduser("~")
    # macOS
    mac = os.path.join(home, "Library", "Application Support", "rbypc-frontend", "logs")
    if os.path.isdir(mac):
        return mac
    # Linux
    return os.path.join(home, ".config", "rbypc-frontend", "logs")


def list_sessions(root: Optional[str] = None) -> List[str]:
    root = root or default_logs_root()
    if not os.path.isdir(root):
        return []
    entries = []
    for name in os.listdir(root):
        full = os.path.join(root, name)
        if os.path.isdir(full) and os.path.isfile(os.path.join(full, "events.json")):
            entries.append(full)
    entries.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return entries


def load_events(session_dir: str) -> List[dict]:
    p = os.path.join(session_dir, "events.json")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def latest_intended_markers(session_dir: Optional[str] = None) -> tuple[Optional[str], List[IntendedMarker]]:
    if session_dir is None:
        sessions = list_sessions()
        if not sessions:
            return None, []
        session_dir = sessions[0]
    events = load_events(session_dir)
    return session_dir, replay_markers(events)
