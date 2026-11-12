"""The things Jarvis can actually do.

Read-only tools run freely. Anything that writes to disk, runs a shell command,
or otherwise changes the machine goes through `_approve()` first — the model
proposes, you press y. That gate is the entire security model: an agent that
reads your files and your inbox is also an agent that can be instructed by
their contents, so nothing irreversible happens without a human keystroke.
"""

from __future__ import annotations

import ctypes
import fnmatch
import logging
import os
import platform
import shutil
import subprocess
import time
import webbrowser
from ctypes import wintypes
from pathlib import Path

import config
import memory
import notes

log = logging.getLogger("jarvis.tools")

IS_WINDOWS = os.name == "nt"


class Denied(Exception):
    """Raised when the user declines an action. Returned to the model as text."""


def _approve(summary: str, detail: str = "") -> None:
    if not config.REQUIRE_APPROVAL:
        return
    print("\n" + "=" * 60)
    print(f"  APPROVAL NEEDED: {summary}")
    if detail:
        print("-" * 60)
        print(detail[:2000])
    print("=" * 60)
    try:
        answer = input("  Allow? [y/N] ").strip().lower()
    except EOFError:
        answer = ""
    if answer not in ("y", "yes"):
        raise Denied(summary)


def _truncate(text: str, limit: int | None = None) -> str:
    limit = limit or config.MAX_READ_CHARS
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[truncated at {limit} chars of {len(text)}]"


def _resolve(path: str) -> Path:
    return Path(os.path.expandvars(path)).expanduser().resolve()


# --- reading ----------------------------------------------------------------


def list_dir(path: str) -> str:
    """List the contents of a directory.

    Args:
        path: Directory path. Environment variables and ~ are expanded.
    """
    p = _resolve(path)
    if not p.is_dir():
        return f"Not a directory: {p}"
    rows = []
    for entry in sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
        try:
            size = f"{entry.stat().st_size:,}" if entry.is_file() else "<dir>"
        except OSError:
            size = "?"
        rows.append(f"{size:>12}  {entry.name}")
    if not rows:
        return f"{p} is empty."
    return f"{p}\n" + _truncate("\n".join(rows))


def read_file(path: str) -> str:
    """Read a text file from disk.

    Args:
        path: File path. Environment variables and ~ are expanded.
    """
    p = _resolve(path)
    if not p.is_file():
        return f"Not a file: {p}"
    try:
        return _truncate(p.read_text(encoding="utf-8", errors="replace"))
    except OSError as e:
        return f"Could not read {p}: {e}"


def find_files(directory: str, pattern: str, max_results: int = 100) -> str:
    """Find files by name pattern, recursively.

    Args:
        directory: Directory to search under.
        pattern: Glob pattern matched against the file name, e.g. "*.pdf".
        max_results: Stop after this many hits.
    """
    root = _resolve(directory)
    if not root.is_dir():
        return f"Not a directory: {root}"
    hits: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _: None):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "$"))]
        for name in filenames:
            if fnmatch.fnmatch(name.lower(), pattern.lower()):
                hits.append(str(Path(dirpath) / name))
                if len(hits) >= max_results:
                    return "\n".join(hits) + f"\n[stopped at {max_results}]"
    return "\n".join(hits) if hits else f"No files matching {pattern!r} under {root}"


def search_in_files(directory: str, text: str, pattern: str = "*", max_results: int = 40) -> str:
    """Search for a string inside files, recursively. Case-insensitive.

    Args:
        directory: Directory to search under.
        text: The string to look for.
        pattern: Only search files whose name matches this glob, e.g. "*.py".
        max_results: Stop after this many matching lines.
    """
    root = _resolve(directory)
    if not root.is_dir():
        return f"Not a directory: {root}"
    needle = text.lower()
    hits: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _: None):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "$")) and d != "node_modules"]
        for name in filenames:
            if not fnmatch.fnmatch(name.lower(), pattern.lower()):
                continue
            fp = Path(dirpath) / name
            try:
                if fp.stat().st_size > 5_000_000:
                    continue
                with fp.open("r", encoding="utf-8", errors="ignore") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if needle in line.lower():
                            hits.append(f"{fp}:{lineno}: {line.strip()[:200]}")
                            if len(hits) >= max_results:
                                return "\n".join(hits) + f"\n[stopped at {max_results}]"
            except OSError:
                continue
    return "\n".join(hits) if hits else f"No matches for {text!r}"


# --- the machine ------------------------------------------------------------


def open_app(name: str) -> str:
    """Launch an application or open a file/folder with its default program.

    Args:
        name: Executable name (e.g. "notepad", "code"), or a full path to a
            file or folder.
    """
    target = name.strip()
    if not target:
        return "No application given."
    p = Path(os.path.expandvars(target)).expanduser()
    try:
        if p.exists():
            if IS_WINDOWS:
                os.startfile(str(p.resolve()))  # noqa: S606 - user-directed launch
            else:
                subprocess.Popen(["xdg-open", str(p.resolve())])
            return f"Opened {p}"
        exe = shutil.which(target)
        if exe:
            subprocess.Popen([exe], creationflags=_no_window())
            return f"Launched {exe}"
        if IS_WINDOWS:
            # Start-Process resolves Start-menu apps and App Paths entries that
            # aren't on PATH (Spotify, Cursor, Chrome, ...).
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"Start-Process {_ps_quote(target)}"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if r.returncode == 0:
                return f"Launched {target}"
            return f"Could not launch {target}: {r.stderr.strip()[:300]}"
        return f"Could not find {target}"
    except OSError as e:
        return f"Could not launch {target}: {e}"


def focus_window(title_contains: str) -> str:
    """Bring an already-open window to the foreground by title.

    Args:
        title_contains: Case-insensitive substring of the window title.
    """
    if not IS_WINDOWS:
        return "Window focus is Windows-only."
    needle = title_contains.lower()
    user32 = ctypes.windll.user32
    found: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if needle in buf.value.lower():
            found.append((int(hwnd), buf.value))
        return True

    user32.EnumWindows(_enum, 0)
    if not found:
        return f"No visible window matching {title_contains!r}"
    hwnd, title = found[0]
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # SetForegroundWindow is refused unless the calling thread shares input
    # state with the current foreground window — hence AttachThreadInput.
    fg = user32.GetForegroundWindow()
    tid_target = user32.GetWindowThreadProcessId(hwnd, None)
    tid_fg = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    if tid_fg and tid_target:
        user32.AttachThreadInput(tid_fg, tid_target, True)
    user32.SetForegroundWindow(hwnd)
    if tid_fg and tid_target:
        user32.AttachThreadInput(tid_fg, tid_target, False)
    return f"Focused: {title}"


def list_windows() -> str:
    """List the titles of all visible windows."""
    if not IS_WINDOWS:
        return "Window listing is Windows-only."
    user32 = ctypes.windll.user32
    titles: list[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                titles.append(buf.value)
        return True

    user32.EnumWindows(_enum, 0)
    return "\n".join(titles) if titles else "No visible windows."


def open_url(url: str) -> str:
    """Open a URL in the default browser.

    Args:
        url: The URL to open.
    """
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        return "Only http/https URLs are allowed."
    webbrowser.open(url)
    return f"Opened {url}"


def media_control(action: str) -> str:
    """Control system media playback and volume via virtual keys.

    Args:
        action: One of "playpause", "next", "previous", "stop", "volumeup",
            "volumedown", "mute".
    """
    if not IS_WINDOWS:
        return "Media control is Windows-only."
    keys = {
        "playpause": 0xB3,
        "next": 0xB0,
        "previous": 0xB1,
        "stop": 0xB2,
        "volumeup": 0xAF,
        "volumedown": 0xAE,
        "mute": 0xAD,
    }
    vk = keys.get(action.strip().lower().replace(" ", "").replace("_", ""))
    if vk is None:
        return f"Unknown action. Options: {', '.join(keys)}"
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP
    return f"Sent {action}."


def system_status() -> str:
    """Report time, date, battery, disk space, and machine info."""
    lines = [
        f"Time: {time.strftime('%A %d %B %Y, %H:%M')}",
        f"Machine: {platform.node()} ({platform.system()} {platform.release()})",
    ]
    try:
        usage = shutil.disk_usage(Path.home().anchor or "/")
        lines.append(
            f"Disk: {usage.free / 1e9:.0f} GB free of {usage.total / 1e9:.0f} GB"
        )
    except OSError:
        pass
    if IS_WINDOWS:
        try:
            class SPS(ctypes.Structure):
                _fields_ = [
                    ("ACLineStatus", wintypes.BYTE),
                    ("BatteryFlag", wintypes.BYTE),
                    ("BatteryLifePercent", wintypes.BYTE),
                    ("SystemStatusFlag", wintypes.BYTE),
                    ("BatteryLifeTime", wintypes.DWORD),
                    ("BatteryFullLifeTime", wintypes.DWORD),
                ]

            sps = SPS()
            if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
                pct = sps.BatteryLifePercent
                plugged = "plugged in" if sps.ACLineStatus == 1 else "on battery"
                if pct != 255:
                    lines.append(f"Battery: {pct}% ({plugged})")
        except Exception:
            pass
    return "\n".join(lines)


# --- writing (gated) --------------------------------------------------------


def write_file(path: str, content: str) -> str:
    """Write text to a file, creating or overwriting it. Requires user approval.

    Args:
        path: Destination file path.
        content: The full text to write.
    """
    if not config.ALLOW_WRITES:
        return "File writing is disabled (JARVIS_ALLOW_WRITES=false)."
    p = _resolve(path)
    verb = "Overwrite" if p.exists() else "Create"
    try:
        _approve(f"{verb} {p} ({len(content)} chars)", content[:1000])
    except Denied:
        return "User declined the write."
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            backup = p.with_suffix(p.suffix + ".bak")
            shutil.copy2(p, backup)
        p.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} chars to {p}"
    except OSError as e:
        return f"Write failed: {e}"


def run_powershell(command: str, reason: str) -> str:
    """Run a PowerShell command and return its output. Requires user approval.

    Args:
        command: The PowerShell command to run.
        reason: One short sentence on why this command is needed. Shown to the
            user in the approval prompt.
    """
    if not config.ALLOW_SHELL:
        return "Shell access is disabled (JARVIS_ALLOW_SHELL=false)."
    if not IS_WINDOWS:
        return "PowerShell is Windows-only."
    try:
        _approve(f"Run PowerShell — {reason}", command)
    except Denied:
        return "User declined the command."
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=config.SHELL_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after {config.SHELL_TIMEOUT_S}s."
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    parts = [f"exit code: {r.returncode}"]
    if out:
        parts.append(f"stdout:\n{_truncate(out, 8000)}")
    if err:
        parts.append(f"stderr:\n{_truncate(err, 4000)}")
    return "\n".join(parts)


# --- memory -----------------------------------------------------------------


def remember(fact: str) -> str:
    """Store a fact about the user that should persist across sessions.

    Use this for durable preferences and context, not for details that only
    matter in the current conversation.

    Args:
        fact: A single self-contained sentence.
    """
    return memory.add(fact)


def forget(about: str) -> str:
    """Delete remembered facts containing the given text.

    Args:
        about: Substring identifying which facts to drop.
    """
    return memory.forget(about)


def save_note(text: str, tags: str = "") -> str:
    """Save something to the user's long-term notes (second brain).

    Use for ideas, meeting notes, decisions, things worth finding later. For a
    short standing fact about the user, use remember instead.

    Args:
        text: The note, self-contained enough to make sense months later.
        tags: Optional space-separated keywords.
    """
    return notes.add(text, tags)


def search_notes(query: str) -> list[str]:
    """Search the user's saved notes. Check this before saying you don't know
    something the user may have told you or written down earlier.

    Args:
        query: Keywords to look for.
    """
    return notes.search(query) or ["No matching notes."]


# --- helpers ----------------------------------------------------------------


def _no_window() -> int:
    return subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


READ_TOOLS = [
    list_dir,
    read_file,
    find_files,
    search_in_files,
    list_windows,
    system_status,
]
ACTION_TOOLS = [open_app, focus_window, open_url, media_control]
MEMORY_TOOLS = [remember, forget, save_note, search_notes]


def active_tools() -> list:
    if config.HUB:
        return list(MEMORY_TOOLS)
    tools = [*READ_TOOLS, *ACTION_TOOLS, *MEMORY_TOOLS]
    if config.ALLOW_WRITES:
        tools.append(write_file)
    if config.ALLOW_SHELL and IS_WINDOWS:
        tools.append(run_powershell)
    return tools
