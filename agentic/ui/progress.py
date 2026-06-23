"""Streaming progress display — shows agent activity with animated headers."""

from __future__ import annotations

import time
from typing import Any

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.live import Live
from rich.rule import Rule
from rich.text import Text


TOOL_TO_SPECIALIST: dict[str, tuple[str, str, str]] = {
    "scan_repo_tree":       ("Scanner Agent",          "\U0001f50d", "scan"),
    "get_repo_info":        ("Scanner Agent",          "\U0001f50d", "scan"),
    "get_repo_languages":   ("Scanner Agent",          "\U0001f50d", "scan"),
    "read_repo_file":       ("Scanner Agent",          "\U0001f50d", "scan"),
    "lookup_plugin_config": ("Recommender Agent",      "\U0001f9e0", "analyze"),
    "write_yaml":           ("Config Writer",          "✍️",  "apply"),
    "merge_yaml":           ("Config Writer",          "✍️",  "apply"),
    "write_file":           ("Config Writer",          "✍️",  "apply"),
    "write_techdocs":       ("Config Writer",          "✍️",  "apply"),
    "restart_rhdh":         ("Verify Agent",           "🔍",  "verify"),
    "check_rhdh_health":    ("Verify Agent",           "🔍",  "verify"),
    "diagnose_plugin_errors": ("Verify Agent",         "🔍",  "verify"),
    "read_container_logs":  ("Verify Agent",           "🔍",  "verify"),
}

PHASE_DISPLAY: dict[str, str] = {
    "scan":      "Scanning Repositories",
    "analyze":   "Matching Signals to Plugins",
    "recommend": "Building Plugin Proposals",
    "generate":  "Generating Catalog Entities",
    "apply":     "Applying Configuration",
    "verify":    "Verifying Health",
}

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

GLARE_SPEED = 6.0
SPINNER_SPEED = 12.0


def _describe_tool(name: str, inp: dict[str, Any]) -> str:
    if name == "scan_repo_tree":
        return f"Scanning file tree of {inp.get('owner', '')}/{inp.get('repo', '')}"
    if name == "read_repo_file":
        return f"Reading {inp.get('path', '')} from {inp.get('owner', '')}/{inp.get('repo', '')}"
    if name == "get_repo_languages":
        return f"Detecting languages in {inp.get('owner', '')}/{inp.get('repo', '')}"
    if name == "get_repo_info":
        return f"Getting repo info for {inp.get('owner', '')}/{inp.get('repo', '')}"
    if name == "lookup_plugin_config":
        return f"Looking up config for {inp.get('plugin_name', '')} plugin"
    if name == "write_yaml":
        return f"Writing {inp.get('path', '')}"
    if name == "merge_yaml":
        return f"Merging config into {inp.get('path', '')}"
    if name == "write_file":
        return f"Writing {inp.get('path', '')}"
    if name == "read_yaml":
        return f"Reading {inp.get('path', '')}"
    if name == "restart_rhdh":
        if inp.get("full"):
            return "Full stack restart (compose down/up)"
        if inp.get("reinstall_plugins") is False:
            return "Restarting RHDH (config reload only)"
        return "Reinstalling plugins and restarting RHDH"
    if name == "check_rhdh_health":
        return "Waiting for RHDH to become healthy..." if inp.get("wait") else "Checking RHDH health"
    if name == "diagnose_plugin_errors":
        return "Scanning logs for plugin errors"
    if name == "read_container_logs":
        return f"Reading {inp.get('service', 'rhdh')} container logs"
    if name == "write_techdocs":
        return f"Generating TechDocs for {inp.get('entity', '')}"
    return f"Running {name}"


def _summarize_result(name: str, result: dict[str, Any]) -> str:
    if name == "scan_repo_tree":
        return f"{result.get('count', 0)} files found"
    if name == "get_repo_languages":
        langs = result.get("languages", {})
        top = sorted(langs.items(), key=lambda x: x[1], reverse=True)[:3]
        return ", ".join(f"{l} {v:.0f}%" for l, v in top) if top else ""
    if name == "check_rhdh_health":
        return "healthy" if result.get("healthy") else result.get("message", "unhealthy")
    if name == "diagnose_plugin_errors":
        c = result.get("count", 0)
        return f"{c} errors found" if c else "no errors"
    if name in ("write_yaml", "merge_yaml", "write_file", "write_techdocs"):
        return "written" if result.get("success") else result.get("error", "failed")
    if name == "restart_rhdh":
        mode = result.get("mode", "fast")
        return f"{mode} restart ok" if result.get("success") else f"{mode} restart failed"
    if name == "lookup_plugin_config":
        if "error" in result:
            return "not found"
        return result.get("title", "found")
    if name == "get_repo_info":
        desc = result.get("description", "")
        return desc[:60] + "..." if len(desc) > 60 else desc
    return ""


class _DynamicRenderable:
    """Wraps AgentProgressDisplay so Live re-builds the display on every tick."""

    def __init__(self, display: AgentProgressDisplay) -> None:
        self._display = display

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield self._display._build()


class AgentProgressDisplay:
    """Real-time progress display with animated agent headers and thinking."""

    def __init__(self, console: Console) -> None:
        self.console = console
        self.phase = "scan"
        self.specialist = "Scanner Agent"
        self.specialist_icon = "\U0001f50d"
        self._thinking_lines: list[str] = []
        self._current_tool_desc: str | None = None
        self._tool_start: float | None = None
        self._tool_history: list[dict[str, Any]] = []
        self._completed_sections: list[dict[str, Any]] = []
        self._handoff_message: str | None = None
        self._live: Live | None = None
        self._start_time = time.time()
        self._prev_specialist: str | None = None

    def start(self) -> None:
        self._live = Live(
            _DynamicRenderable(self),
            console=self.console,
            refresh_per_second=12,
            transient=False,
        )
        self._live.start()

    def stop(self) -> None:
        if self._live:
            self._finalize_section()
            self._live.update(self._build_final())
            self._live.stop()
            self._live = None

    def on_prescan_event(self, event_type: str, event_data: dict[str, Any]) -> None:
        """Handle events from the local pre-scanner."""
        owner = event_data.get("owner", "")
        repo = event_data.get("repo", "")

        if event_type == "scan_start":
            self._current_tool_desc = f"Scanning {owner}/{repo}"
            self._tool_start = time.time()
        elif event_type == "scan_info":
            desc = event_data.get("description", "")
            topics = event_data.get("topics", [])
            entry: dict[str, Any] = {
                "description": f"Repo info for {owner}/{repo}",
                "duration": time.time() - self._tool_start if self._tool_start else 0.0,
                "summary": desc[:60] if desc else "",
                "tool": "get_repo_info",
            }
            sub_items = []
            if desc:
                sub_items.append(desc[:80])
            if topics:
                sub_items.append("Topics: " + ", ".join(topics[:5]))
            if sub_items:
                entry["sub_items"] = sub_items
            self._tool_history.append(entry)
        elif event_type == "scan_tree":
            count = event_data.get("count", 0)
            self._tool_history.append({
                "description": f"File tree of {owner}/{repo}",
                "duration": time.time() - self._tool_start if self._tool_start else 0.0,
                "summary": f"{count} files",
                "tool": "scan_repo_tree",
                "sub_items": [f"{count} files in tree"],
            })
        elif event_type == "scan_languages":
            langs = event_data.get("languages", {})
            top = sorted(langs.items(), key=lambda x: x[1], reverse=True)[:4]
            self._tool_history.append({
                "description": f"Languages in {owner}/{repo}",
                "duration": time.time() - self._tool_start if self._tool_start else 0.0,
                "summary": ", ".join(f"{l} {v:.0f}%" for l, v in top[:3]),
                "tool": "get_repo_languages",
                "sub_items": [", ".join(f"{l} {v:.1f}%" for l, v in top)] if top else [],
            })
        elif event_type == "scan_signals":
            signals = event_data.get("signals", [])
            if signals:
                self._tool_history.append({
                    "description": f"Signals detected in {owner}/{repo}",
                    "duration": 0.0,
                    "summary": f"{len(signals)} technologies",
                    "tool": "detect_signals",
                    "sub_items": [", ".join(signals)],
                })
        elif event_type == "scan_complete":
            self._current_tool_desc = None
            self._tool_start = None

    def on_turn_start(self, turn: int) -> None:
        self._thinking_lines = []

    def on_text_delta(self, text: str) -> None:
        for ch in text:
            if ch == "\n":
                self._thinking_lines.append("")
            elif self._thinking_lines:
                self._thinking_lines[-1] += ch
            else:
                self._thinking_lines.append(ch)

        self._thinking_lines = [l for l in self._thinking_lines if l.strip()]
        if len(self._thinking_lines) > 4:
            self._thinking_lines = self._thinking_lines[-4:]

    def on_text_done(self, text: str) -> None:
        if '"plugin"' in text and '"packages"' in text:
            self._transition("Recommender Agent", "\U0001f9e0", "recommend")
        elif '"component_type"' in text:
            self._transition("Entity Generator Agent", "\U0001f4dd", "generate")

    def on_tool_start(self, tool_name: str, tool_input: dict[str, Any]) -> None:
        specialist, icon, phase = TOOL_TO_SPECIALIST.get(
            tool_name, (self.specialist, self.specialist_icon, self.phase),
        )
        if specialist != self.specialist:
            self._transition(specialist, icon, phase)
        elif phase != self.phase:
            self.phase = phase

        self._current_tool_desc = _describe_tool(tool_name, tool_input)
        self._tool_start = time.time()
        self._thinking_lines = []

    def on_tool_end(self, tool_name: str, result: dict[str, Any]) -> None:
        duration = time.time() - self._tool_start if self._tool_start else 0.0
        summary = _summarize_result(tool_name, result)
        desc = self._current_tool_desc or tool_name

        entry: dict[str, Any] = {
            "description": desc,
            "duration": duration,
            "summary": summary,
            "tool": tool_name,
        }

        if tool_name == "scan_repo_tree":
            count = result.get("count", 0)
            entry["sub_items"] = [f"{count} files in tree"]
        elif tool_name == "get_repo_languages":
            langs = result.get("languages", {})
            top = sorted(langs.items(), key=lambda x: x[1], reverse=True)[:4]
            if top:
                entry["sub_items"] = [", ".join(f"{l} {v:.1f}%" for l, v in top)]
        elif tool_name == "get_repo_info":
            items = []
            if result.get("description"):
                d = result["description"]
                items.append(d[:80] + "..." if len(d) > 80 else d)
            if result.get("topics"):
                items.append("Topics: " + ", ".join(result["topics"][:5]))
            if items:
                entry["sub_items"] = items
        elif tool_name == "check_rhdh_health":
            status = "Healthy" if result.get("healthy") else result.get("message", "unhealthy")
            entry["sub_items"] = [status]
        elif tool_name == "diagnose_plugin_errors":
            c = result.get("count", 0)
            entry["sub_items"] = [f"{c} errors" if c else "Clean — no errors"]

        self._tool_history.append(entry)
        self._current_tool_desc = None
        self._tool_start = None

    def _transition(self, new_specialist: str, icon: str, phase: str) -> None:
        signal_info = ""
        if self.specialist == "Scanner Agent" and self._tool_history:
            scans = [t for t in self._tool_history if t["tool"] == "scan_repo_tree"]
            signal_info = f"{len(scans)} repos scanned" if scans else ""
        elif self.specialist == "Recommender Agent" and self._tool_history:
            lookups = [t for t in self._tool_history if t["tool"] == "lookup_plugin_config"]
            signal_info = f"{len(lookups)} plugin configs verified" if lookups else ""

        self._finalize_section()

        if signal_info:
            self._handoff_message = f"Context passed to {new_specialist}: {signal_info}"
        else:
            self._handoff_message = None

        self._prev_specialist = self.specialist
        self.specialist = new_specialist
        self.specialist_icon = icon
        self.phase = phase

    def _finalize_section(self) -> None:
        if not self._tool_history and not self._thinking_lines:
            return
        self._completed_sections.append({
            "specialist": self.specialist,
            "icon": self.specialist_icon,
            "phase": self.phase,
            "tools": list(self._tool_history),
            "handoff": self._handoff_message,
        })
        self._tool_history = []
        self._thinking_lines = []

    def _now_frame(self) -> int:
        return int(time.time() * SPINNER_SPEED)

    def _build_animated_header(self, name: str, icon: str, active: bool) -> Text:
        header = Text()
        header.append("  ")

        if active:
            frame = self._now_frame()
            spinner = SPINNER_FRAMES[frame % len(SPINNER_FRAMES)]
            header.append(f"{icon} ", style="bold")

            glare_pos = int(time.time() * GLARE_SPEED) % (len(name) + 8)
            for i, ch in enumerate(name):
                dist = abs(i - glare_pos)
                if dist == 0:
                    header.append(ch, style="bold white on grey23")
                elif dist == 1:
                    header.append(ch, style="bold white")
                elif dist == 2:
                    header.append(ch, style="bold bright_cyan")
                else:
                    header.append(ch, style="bold cyan")

            header.append(f"  {spinner} ", style="bold yellow")
            header.append("active", style="bold yellow")
        else:
            header.append(f"{icon} ", style="dim")
            header.append(name, style="dim bold")
            header.append("  ✓ ", style="green")
            header.append("complete", style="green")

        return header

    def _build_completed_section(self, section: dict[str, Any]) -> list[RenderableType]:
        parts: list[RenderableType] = []
        parts.append(Rule(style="dim"))
        parts.append(Text())
        parts.append(self._build_animated_header(section["specialist"], section["icon"], active=False))

        for entry in section["tools"]:
            line = Text()
            line.append("  ✓ ", style="green")
            line.append(entry["description"], style="dim")
            if entry.get("summary"):
                line.append(f" — {entry['summary']}", style="dim")
            line.append(f"  ({entry['duration']:.1f}s)", style="dim")
            parts.append(line)

            for sub in entry.get("sub_items", []):
                sub_line = Text()
                sub_line.append(f"    │─ {sub}", style="dim")
                parts.append(sub_line)

        if section.get("handoff"):
            parts.append(Text())
            handoff = Text()
            handoff.append("  \U0001f4cb ", style="bold")
            handoff.append(section["handoff"], style="italic cyan")
            parts.append(handoff)

        parts.append(Text())
        return parts

    def _build(self) -> RenderableType:
        now = time.time()
        parts: list[RenderableType] = []

        for section in self._completed_sections:
            parts.extend(self._build_completed_section(section))

        parts.append(Rule(style="dim"))
        parts.append(Text())
        parts.append(self._build_animated_header(self.specialist, self.specialist_icon, active=True))

        phase_name = PHASE_DISPLAY.get(self.phase, "Working...")
        phase_line = Text()
        phase_line.append(f"  {phase_name}", style="dim italic")
        parts.append(phase_line)

        if self._thinking_lines:
            parts.append(Text())
            think_header = Text()
            think_header.append("  \U0001f4ad ", style="bold")
            think_header.append("Thinking", style="bold dim")
            parts.append(think_header)
            for line in self._thinking_lines:
                t = Text()
                t.append(f"  │ {line[:120]}", style="dim italic")
                parts.append(t)

        for entry in self._tool_history:
            line = Text()
            line.append("  ✓ ", style="green")
            line.append(entry["description"], style="dim")
            if entry.get("summary"):
                line.append(f" — {entry['summary']}", style="dim")
            line.append(f"  ({entry['duration']:.1f}s)", style="dim")
            parts.append(line)

            for sub in entry.get("sub_items", []):
                sub_line = Text()
                sub_line.append(f"    │─ {sub}", style="dim")
                parts.append(sub_line)

        if self._current_tool_desc:
            elapsed = now - self._tool_start if self._tool_start else 0.0
            frame = self._now_frame()
            spinner = SPINNER_FRAMES[frame % len(SPINNER_FRAMES)]
            parts.append(Text())
            tool_line = Text()
            tool_line.append(f"  {spinner} ", style="yellow bold")
            tool_line.append(self._current_tool_desc, style="")
            tool_line.append(f"  ({elapsed:.1f}s)", style="dim")
            parts.append(tool_line)

        parts.append(Text())
        return Group(*parts)

    def _build_final(self) -> RenderableType:
        parts: list[RenderableType] = []

        for section in self._completed_sections:
            parts.extend(self._build_completed_section(section))

        if self._tool_history:
            parts.append(Rule(style="dim"))
            parts.append(Text())
            parts.append(self._build_animated_header(self.specialist, self.specialist_icon, active=False))

            for entry in self._tool_history:
                line = Text()
                line.append("  ✓ ", style="green")
                line.append(entry["description"], style="dim")
                if entry.get("summary"):
                    line.append(f" — {entry['summary']}", style="dim")
                line.append(f"  ({entry['duration']:.1f}s)", style="dim")
                parts.append(line)

                for sub in entry.get("sub_items", []):
                    sub_line = Text()
                    sub_line.append(f"    │─ {sub}", style="dim")
                    parts.append(sub_line)

            parts.append(Text())

        parts.append(Rule(style="dim"))
        return Group(*parts)
