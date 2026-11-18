#!/usr/bin/env python3
"""Desktop helper for configuring AI clients to use the AVEVA MCP server."""

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import tomllib
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parent
SERVER_LAUNCHER = PROJECT_ROOT / "start_aveva_mcp_server.py"

CLIENTS = {
    "Gemini CLI": "gemini",
    "Codex CLI": "codex",
    "Claude Desktop": "claude",
}
NPM_CLIENT_PACKAGES = {
    "gemini": ("gemini", "@google/gemini-cli"),
    "codex": ("codex", "@openai/codex"),
}
CLAUDE_WINGET_ID = "Anthropic.Claude"
CLAUDE_APPX_PACKAGE_NAME = "AnthropicPBC.Claude"
CLAUDE_DOWNLOAD_URL = "https://claude.com/download"

BACKGROUND = "#0B111C"
SURFACE = "#172434"
INPUT = "#0D1724"
TEXT = "#EEF3F8"
MUTED = "#A5B6C5"
ACCENT = "#70E1C4"
ACCENT_HOVER = "#91EBD5"
SDK_RELATIVE_PATH = Path(
    "Documents",
    "Digital Engineering",
    "Aveva Process Simulation",
    "Toolkits",
    "ScriptingInterface",
)

PROMPT_NAMES = (
    "Check APS connection",
    "Read simulation and flowsheet",
    "Analyze the flowsheet",
)


@dataclass(frozen=True)
class PythonRuntime:
    executable: str
    version: tuple[int, int, int]
    ready: bool
    details: str

    @property
    def version_text(self) -> str:
        return ".".join(str(part) for part in self.version)

    @property
    def label(self) -> str:
        install_path = str(Path(self.executable).parent) or self.executable
        state = "Ready" if self.ready else "Needs setup"
        return "Python {} | {} | {}".format(
            self.version_text, install_path, state
        )


def get_client_config_path(client: str) -> Path:
    """Return the documented per-user MCP configuration path for a client."""
    if client == "gemini":
        return Path.home() / ".gemini" / "settings.json"
    if client == "codex":
        return Path.home() / ".codex" / "config.toml"
    if client == "claude":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "Claude" / "claude_desktop_config.json"
    raise ValueError("Unsupported AI client: {}".format(client))


def is_ai_client_installed(client: str) -> bool:
    if client in NPM_CLIENT_PACKAGES:
        command = NPM_CLIENT_PACKAGES[client][0]
        return any(
            shutil.which(candidate)
            for candidate in (command, command + ".cmd", command + ".exe")
        )
    if client != "claude":
        raise ValueError("Unsupported AI client: {}".format(client))

    local_app_data = Path(
        os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    )
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    candidates = (
        local_app_data / "Programs" / "Claude" / "Claude.exe",
        local_app_data / "AnthropicClaude" / "Claude.exe",
        program_files / "Claude" / "Claude.exe",
    )
    if any(path.is_file() for path in candidates):
        return True

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell:
        try:
            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "Get-AppxPackage -Name '{}' | "
                    "Select-Object -ExpandProperty Name".format(
                        CLAUDE_APPX_PACKAGE_NAME
                    ),
                ],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        else:
            if (
                result.returncode == 0
                and result.stdout.strip().casefold()
                == CLAUDE_APPX_PACKAGE_NAME.casefold()
            ):
                return True

    winget = shutil.which("winget.exe") or shutil.which("winget")
    if not winget:
        return False
    try:
        result = subprocess.run(
            [
                winget,
                "list",
                "--id",
                CLAUDE_WINGET_ID,
                "--exact",
                "--source",
                "winget",
                "--accept-source-agreements",
                "--disable-interactivity",
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return CLAUDE_WINGET_ID.casefold() in result.stdout.casefold()


def install_ai_client(client: str) -> tuple[bool, str]:
    if client in NPM_CLIENT_PACKAGES:
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm:
            return False, "Node.js and npm are required to install this CLI."
        package = NPM_CLIENT_PACKAGES[client][1]
        command = "{} install --global {}".format(
            subprocess.list2cmdline([npm]), package
        )
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=900,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, "{} installation timed out.".format(client)
        except OSError as exc:
            return False, "Could not install {}: {}".format(client, exc)
    elif client == "claude":
        winget = shutil.which("winget.exe") or shutil.which("winget")
        if not winget:
            return False, (
                "Windows Package Manager (winget) is unavailable. Download Claude "
                "Desktop from {}.".format(CLAUDE_DOWNLOAD_URL)
            )
        try:
            result = subprocess.run(
                [
                    winget,
                    "install",
                    "--id",
                    CLAUDE_WINGET_ID,
                    "--exact",
                    "--source",
                    "winget",
                    "--accept-source-agreements",
                    "--accept-package-agreements",
                    "--silent",
                    "--disable-interactivity",
                ],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=900,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, "Claude Desktop installation timed out."
        except OSError as exc:
            return False, "Could not install Claude Desktop: {}".format(exc)
    else:
        raise ValueError("Unsupported AI client: {}".format(client))

    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip()
        tail = "\n".join(output.splitlines()[-12:])
        return False, "{} installation failed:\n{}".format(client, tail)
    return True, "{} installed successfully.".format(client)


def find_default_scripting_interface_path(
    home: Path | None = None, one_drive_roots: tuple[Path, ...] | None = None
) -> Path:
    home_path = home or Path.home()
    roots = list(one_drive_roots or ())
    if one_drive_roots is None:
        for variable in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
            value = os.environ.get(variable)
            if value:
                roots.append(Path(value))
        roots.append(home_path / "OneDrive")
        roots.append(home_path)

    candidates = [root / SDK_RELATIVE_PATH for root in roots]
    for candidate in candidates:
        if (
            (candidate / "requirements.txt").is_file()
            and (candidate / "packages" / "simcentralconnect").is_dir()
        ):
            return candidate
    return candidates[0] if candidates else home_path / SDK_RELATIVE_PATH


def generate_config_snippet(
    client: str, python_executable: str, server_launcher: Path = SERVER_LAUNCHER
) -> str:
    """Build a mergeable MCP configuration snippet without editing user files."""
    if client not in ("gemini", "codex", "claude"):
        raise ValueError("Unsupported AI client: {}".format(client))
    if not python_executable.strip():
        raise ValueError("Select a Python executable.")

    command = str(Path(python_executable.strip()))
    args = [str(server_launcher.resolve())]

    if client == "codex":
        return (
            "[mcp_servers.aveva]\n"
            "command = {}\n"
            "args = {}\n"
        ).format(json.dumps(command), json.dumps(args))

    return json.dumps(
        {"mcpServers": {"aveva": {"command": command, "args": args}}},
        indent=2,
        ensure_ascii=False,
    )


def backup_path_for(path: Path) -> Path | None:
    if not path.exists():
        return None
    base = path.with_name(path.name + ".bak")
    backup = base
    index = 1
    while backup.exists():
        backup = path.with_name(path.name + ".bak.{}".format(index))
        index += 1
    shutil.copy2(path, backup)
    return backup


def atomic_write_text(path: Path, content: str, backup_existing: bool = False) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = backup_path_for(path) if backup_existing else None
    temporary_path = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write(content)
        os.replace(temporary_path, path)
    except (OSError, UnicodeError):
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
        raise
    return backup


def merge_codex_config(existing_text: str, server_section: str) -> str:
    try:
        existing_data = tomllib.loads(existing_text) if existing_text.strip() else {}
    except tomllib.TOMLDecodeError as exc:
        raise ValueError("The existing Codex config is invalid TOML: {}".format(exc)) from exc

    servers = existing_data.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ValueError("The mcp_servers setting in Codex config must be a table.")

    section_pattern = re.compile(
        r"(?m)^[ \t]*\[mcp_servers\.aveva\][ \t]*(?:\#[^\r\n]*)?[ \t]*\r?$"
    )
    sections = list(section_pattern.finditer(existing_text))
    if len(sections) > 1:
        raise ValueError("Codex config contains duplicate AVEVA server sections.")
    if "aveva" in servers and not sections:
        raise ValueError(
            "Codex config defines the AVEVA server in another TOML form; "
            "edit that entry manually to avoid changing unrelated settings."
        )

    replacement = server_section.strip()
    if sections:
        section_start = sections[0].start()
        next_table = re.search(r"(?m)^[ \t]*\[{1,2}[^\r\n]+\]{1,2}", existing_text[sections[0].end():])
        section_end = (
            sections[0].end() + next_table.start()
            if next_table
            else len(existing_text)
        )
        prefix = existing_text[:section_start].rstrip()
        suffix = existing_text[section_end:].lstrip()
        updated = "\n\n".join(part for part in (prefix, replacement, suffix) if part)
        updated += "\n"
    else:
        separator = "\n" if not existing_text or existing_text.endswith("\n") else "\n\n"
        updated = existing_text + separator + replacement + "\n"

    try:
        tomllib.loads(updated)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError("Could not safely update Codex config: {}".format(exc)) from exc
    return updated


def configure_ai_client(
    client: str, python_executable: str, server_launcher: Path = SERVER_LAUNCHER
) -> tuple[Path, Path | None]:
    config_path = get_client_config_path(client)
    server_entry = {
        "command": str(Path(python_executable).expanduser()),
        "args": [str(server_launcher.resolve())],
    }

    if client == "codex":
        existing_text = (
            config_path.read_text(encoding="utf-8")
            if config_path.is_file()
            else ""
        )
        section = generate_config_snippet(client, python_executable, server_launcher)
        updated_text = merge_codex_config(existing_text, section)
    elif client in ("gemini", "claude"):
        if config_path.is_file():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, UnicodeError) as exc:
                raise ValueError(
                    "The existing client config is invalid JSON: {}".format(exc)
                ) from exc
        else:
            data = {}
        if not isinstance(data, dict):
            raise ValueError("The client config root must be a JSON object.")
        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            raise ValueError("The mcpServers setting must be a JSON object.")
        servers["aveva"] = server_entry
        updated_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    else:
        raise ValueError("Unsupported AI client: {}".format(client))

    backup = atomic_write_text(config_path, updated_text, backup_existing=True)
    return config_path, backup


def connect_ai_client(
    client: str,
    python_executable: str,
    server_launcher: Path = SERVER_LAUNCHER,
    progress: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    if progress:
        progress("Checking the selected Python runtime...")
    runtime = inspect_python_runtime(python_executable)
    if not runtime.ready:
        return False, (
            "The selected Python runtime is not ready:\n{}\n\n"
            "Open Settings and install the dependencies first."
        ).format(runtime.details)

    if progress:
        progress("Writing the MCP configuration and backing up existing settings...")
    try:
        config_path, backup = configure_ai_client(
            client, python_executable, server_launcher
        )
    except (OSError, UnicodeError, ValueError) as exc:
        return False, "Could not configure the AI client: {}".format(exc)

    message = "MCP server configured in:\n{}".format(config_path)
    if backup:
        message += "\nPrevious config backed up to:\n{}".format(backup)
    message += "\n\nRestart {} to load the AVEVA tools.".format(client)
    return True, message


def get_app_settings_path() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "APS AI Connector" / "settings.json"


def load_app_settings() -> dict[str, str]:
    path = get_app_settings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Could not read app settings at {}: {}".format(path, exc)) from exc
    if not isinstance(data, dict):
        raise ValueError("App settings must contain a JSON object.")
    return {key: value for key, value in data.items() if isinstance(value, str)}


def save_app_settings(settings: dict[str, str]) -> None:
    path = get_app_settings_path()
    atomic_write_text(
        path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
    )


def install_runtime_dependencies(
    python_executable: str,
    scripting_interface_dir: str,
    progress: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    sdk_dir = Path(scripting_interface_dir).expanduser()
    sdk_requirements = sdk_dir / "requirements.txt"
    local_package = sdk_dir / "packages" / "simcentralconnect"
    project_requirements = PROJECT_ROOT / "requirements.txt"
    if not project_requirements.is_file():
        return False, "Project requirements.txt was not found."

    installs = [("APS MCP server", project_requirements, PROJECT_ROOT)]
    sdk_is_valid = sdk_requirements.is_file() and local_package.is_dir()
    if sdk_is_valid:
        installs.append(("AVEVA Scripting Interface", sdk_requirements, sdk_dir))

    for label, requirements_file, working_directory in installs:
        if progress:
            progress("Installing {} dependencies; this may take a few minutes...".format(label))
        try:
            result = subprocess.run(
                [
                    python_executable,
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    str(requirements_file),
                ],
                cwd=str(working_directory),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=900,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, "{} dependency installation timed out.".format(label)
        except OSError as exc:
            return False, "Could not install {} dependencies: {}".format(label, exc)

        if result.returncode != 0:
            output = (result.stderr or result.stdout).strip()
            tail = "\n".join(output.splitlines()[-12:])
            installed_note = (
                "APS MCP dependencies were installed, but "
                if label == "AVEVA Scripting Interface"
                else ""
            )
            return False, "{}{} dependency installation failed:\n{}".format(
                installed_note, label, tail
            )

    if not sdk_is_valid:
        return False, (
            "APS MCP dependencies were installed, but the selected folder is not "
            "an AVEVA ScriptingInterface toolkit. Expected requirements.txt and "
            "packages\\simcentralconnect."
        )

    return True, (
        "AVEVA Scripting Interface and APS MCP dependencies were installed into "
        "the selected Python environment."
    )


def parse_python_launcher_output(output: str) -> list[str]:
    """Extract interpreter paths from the Windows Python launcher's ``-0p`` output."""
    candidates = []
    for line in output.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        path = parts[1].strip()
        if path.startswith("*"):
            path = path[1:].strip()
        if path:
            candidates.append(path.strip('"'))
    return candidates


def discover_python_executables() -> list[str]:
    """Find Python interpreters registered with the Windows launcher and PATH."""
    candidates: list[str] = [sys.executable]
    launcher = shutil.which("py")
    if launcher:
        try:
            result = subprocess.run(
                [launcher, "-0p"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None

        if result and result.returncode == 0:
            candidates.extend(parse_python_launcher_output(result.stdout))

    path_python = shutil.which("python")
    if path_python:
        candidates.append(path_python)

    unique: dict[str, str] = {}
    for candidate in candidates:
        path = Path(candidate).expanduser()
        path_text = str(path)
        normalized = os.path.normcase(os.path.abspath(path_text))
        unique.setdefault(normalized, path_text)
    return list(unique.values())


def inspect_python_runtime(executable: str) -> PythonRuntime:
    """Check a Python executable's version and whether it can import this server."""
    path = Path(executable).expanduser()

    version_code = (
        "import sys; print('{}.{}.{}'.format("
        "sys.version_info.major, sys.version_info.minor, sys.version_info.micro))"
    )
    try:
        version_result = subprocess.run(
            [str(path), "-c", version_code],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return PythonRuntime(str(path), (0, 0, 0), False, "Version check timed out.")
    except OSError as exc:
        return PythonRuntime(str(path), (0, 0, 0), False, str(exc))

    if version_result.returncode != 0:
        details = version_result.stderr.strip() or "Could not read the Python version."
        return PythonRuntime(str(path), (0, 0, 0), False, details)

    version_parts = version_result.stdout.strip().split(".")
    if len(version_parts) != 3:
        return PythonRuntime(
            str(path), (0, 0, 0), False, "Python returned an invalid version."
        )
    try:
        version = (
            int(version_parts[0]),
            int(version_parts[1]),
            int(version_parts[2]),
        )
    except ValueError:
        return PythonRuntime(
            str(path), (0, 0, 0), False, "Python returned an invalid version."
        )

    import_code = "import fastmcp; from tools import schemas, core, aveva_tools"
    try:
        import_result = subprocess.run(
            [str(path), "-c", import_code],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return PythonRuntime(str(path), version, False, "Import check timed out.")
    except OSError as exc:
        return PythonRuntime(str(path), version, False, str(exc))

    if import_result.returncode != 0:
        details = import_result.stderr.strip() or import_result.stdout.strip()
        return PythonRuntime(
            str(path), version, False, "Server import check failed:\n{}".format(details)
        )

    return PythonRuntime(
        str(path),
        version,
        True,
        "FastMCP and the AVEVA modules imported successfully. "
        "An APS connection has not been tested. Start AVEVA Process Simulation "
        "5.1 or later before making MCP tool calls.",
    )


def select_default_runtime(runtimes: list[PythonRuntime]) -> PythonRuntime | None:
    """Prefer the newest interpreter that passed imports, else the newest found."""
    if not runtimes:
        return None
    ready = [runtime for runtime in runtimes if runtime.ready]
    return max(ready or runtimes, key=lambda runtime: runtime.version)


def select_runtime(
    runtimes: list[PythonRuntime], preferred_executable: str = ""
) -> PythonRuntime | None:
    if preferred_executable:
        preferred_path = os.path.normcase(os.path.abspath(preferred_executable))
        preferred = next(
            (
                runtime
                for runtime in runtimes
                if runtime.ready
                and os.path.normcase(os.path.abspath(runtime.executable))
                == preferred_path
            ),
            None,
        )
        if preferred:
            return preferred
    return select_default_runtime(runtimes)


def check_python_runtime(python_executable: str) -> tuple[bool, str]:
    runtime = inspect_python_runtime(python_executable)
    return runtime.ready, runtime.details


class ConnectorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("APS AI Connector")
        self.root.geometry("880x620")
        self.root.minsize(740, 540)
        self.root.configure(bg=BACKGROUND)

        self.settings_error: str | None = None
        try:
            saved_settings = load_app_settings()
        except ValueError as exc:
            saved_settings = {}
            self.settings_error = str(exc)

        saved_client = saved_settings.get("client", "claude")
        self.client_name = tk.StringVar(
            value=next(
                (name for name, client in CLIENTS.items() if client == saved_client),
                "Claude Desktop",
            )
        )
        self.python_path = tk.StringVar(
            value=saved_settings.get("python_executable", sys.executable)
        )
        self.config_path = tk.StringVar()
        self.runtime_path = tk.StringVar(value=self.python_path.get())
        self.scripting_interface_path = tk.StringVar(
            value=saved_settings.get(
                "scripting_interface_path",
                str(find_default_scripting_interface_path()),
            )
        )
        self.status = tk.StringVar(value="Choose an AI client, then connect.")
        self.client_hint = tk.StringVar()
        self.guide_hint = tk.StringVar()
        self.prompt_name = tk.StringVar(value=PROMPT_NAMES[0])
        self.simulation_name = tk.StringVar()
        self.copy_status = tk.StringVar()
        self.scan_results: queue.Queue[tuple[list[PythonRuntime], str | None]] = (
            queue.Queue()
        )
        self.check_results: queue.Queue[PythonRuntime] = queue.Queue()
        self.install_results: queue.Queue[tuple[bool, str]] = queue.Queue()
        self.progress_results: queue.Queue[str] = queue.Queue()
        self.client_check_results: queue.Queue[tuple[str, str, bool]] = queue.Queue()
        self.connect_results: queue.Queue[
            tuple[str, str, bool, str]
        ] = queue.Queue()
        self.client_install_results: queue.Queue[
            tuple[str, str, bool, str]
        ] = queue.Queue()
        self.runtimes_by_label: dict[str, PythonRuntime] = {}
        self.settings_window: tk.Toplevel | None = None
        self.configured_target: tuple[str, str] | None = None
        self.connect_in_progress = False
        self.scan_in_progress = False
        self.busy = False

        self._configure_styles()
        self._build_ui()
        self.client_name.trace_add("write", self._connection_selection_changed)
        self.python_path.trace_add("write", self._connection_selection_changed)
        self.prompt_name.trace_add("write", self._refresh_prompt)
        self.simulation_name.trace_add("write", self._refresh_prompt)
        self._refresh_config()
        self._refresh_client_hint()
        self._refresh_prompt()
        self.root.after(150, self._start_scan)
        if self.settings_error:
            self.root.after(
                200,
                lambda: messagebox.showwarning(
                    "Settings could not be loaded",
                    self.settings_error,
                    parent=self.root,
                ),
            )

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10))
        style.configure("Root.TFrame", background=BACKGROUND)
        style.configure("Card.TFrame", background=SURFACE)
        style.configure(
            "Title.TLabel",
            background=BACKGROUND,
            foreground=TEXT,
            font=("Segoe UI", 25, "bold"),
        )
        style.configure(
            "Eyebrow.TLabel", background=BACKGROUND, foreground=ACCENT,
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "Subtitle.TLabel", background=BACKGROUND, foreground=MUTED
        )
        style.configure(
            "CardTitle.TLabel",
            background=SURFACE,
            foreground=TEXT,
            font=("Segoe UI", 12, "bold"),
        )
        style.configure("Card.TLabel", background=SURFACE, foreground=TEXT)
        style.configure(
            "Muted.Card.TLabel", background=SURFACE, foreground=MUTED
        )
        style.configure(
            "Activity.Horizontal.TProgressbar",
            troughcolor=INPUT,
            background=ACCENT,
            borderwidth=0,
            thickness=8,
        )
        style.configure(
            "TCombobox",
            fieldbackground=INPUT,
            background=INPUT,
            foreground=TEXT,
            arrowcolor=TEXT,
            padding=8,
        )
        style.configure(
            "TEntry",
            fieldbackground=INPUT,
            foreground=TEXT,
            insertcolor=TEXT,
            padding=8,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", INPUT)],
            selectbackground=[("readonly", ACCENT)],
            selectforeground=[("readonly", TEXT)],
        )
        style.configure(
            "Primary.TButton",
            background=ACCENT,
            foreground="#092621",
            padding=(20, 11),
            borderwidth=0,
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[("active", ACCENT_HOVER), ("disabled", "#354A50")],
            foreground=[("disabled", MUTED)],
        )
        style.configure(
            "Secondary.TButton",
            background="#243648",
            foreground=TEXT,
            padding=(16, 10),
            borderwidth=0,
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#32485E"), ("disabled", "#243648")],
        )

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, style="Root.TFrame", padding=(36, 28))
        self.home_container = container
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(4, weight=1)

        ttk.Label(
            container, text="APS  /  AI CONNECTOR", style="Eyebrow.TLabel"
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            container, text="Connect your AI.", style="Title.TLabel"
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(
            container,
            text="Set up your AI client and start working with AVEVA Process Simulation.",
            style="Subtitle.TLabel",
        ).grid(row=2, column=0, sticky="w", pady=(5, 22))

        connection_card = ttk.Frame(container, style="Card.TFrame", padding=24)
        connection_card.grid(row=3, column=0, sticky="ew")
        connection_card.columnconfigure(1, weight=1)
        ttk.Label(
            connection_card, text="01   Choose an AI client", style="CardTitle.TLabel"
        ).grid(row=0, column=0, sticky="w", padx=(0, 18))
        self.client_picker = ttk.Combobox(
            connection_card,
            textvariable=self.client_name,
            values=tuple(CLIENTS.keys()),
            state="readonly",
        )
        self.client_picker.grid(row=0, column=1, sticky="ew")
        self.client_picker.bind("<<ComboboxSelected>>", self._refresh_config)

        ttk.Label(
            connection_card,
            textvariable=self.client_hint,
            style="Muted.Card.TLabel",
            wraplength=560,
            justify=tk.LEFT,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 0))
        actions = ttk.Frame(connection_card, style="Card.TFrame")
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        actions.columnconfigure(0, weight=1)
        self.connect_button = ttk.Button(
            actions,
            text="Connect",
            style="Primary.TButton",
            command=self._connect,
        )
        self.connect_button.grid(row=0, column=1, padx=(0, 10))
        self.guide_button = ttk.Button(
            actions,
            text="Chat guide",
            style="Secondary.TButton",
            command=self._show_guide,
            state=tk.DISABLED,
        )
        self.guide_button.grid(row=0, column=2, padx=(0, 10))
        ttk.Button(
            actions,
            text="Settings",
            style="Secondary.TButton",
            command=self._open_settings,
        ).grid(row=0, column=3)

        status_card = ttk.Frame(container, style="Card.TFrame", padding=20)
        status_card.grid(row=4, column=0, sticky="new", pady=(16, 0))
        ttk.Label(status_card, text="02   Setup status", style="CardTitle.TLabel").pack(
            anchor="w", pady=(0, 8)
        )
        ttk.Label(
            status_card,
            textvariable=self.status,
            style="Card.TLabel",
            wraplength=560,
            justify=tk.LEFT,
        ).pack(fill=tk.X)
        self.main_progress = ttk.Progressbar(
            status_card, mode="indeterminate", style="Activity.Horizontal.TProgressbar"
        )
        self.main_progress.pack(fill=tk.X, pady=(12, 4))
        ttk.Label(
            status_card,
            text="Activity bar runs during setup; no percentage estimate is available.",
            style="Muted.Card.TLabel",
        ).pack(anchor="w")
        self._build_guide_ui()

    def _build_guide_ui(self) -> None:
        container = ttk.Frame(self.root, style="Root.TFrame", padding=(36, 28))
        self.guide_container = container
        container.columnconfigure(0, weight=1)
        container.rowconfigure(5, weight=1)
        heading = ttk.Frame(container, style="Root.TFrame")
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        title = ttk.Frame(heading, style="Root.TFrame")
        title.grid(row=0, column=0, sticky="w")
        ttk.Label(title, text="APS  /  READY TO CHAT", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(title, text="Continue in your AI.", style="Title.TLabel").pack(anchor="w")
        ttk.Button(
            heading, text="Back to Connect", style="Secondary.TButton",
            command=self._show_home,
        ).grid(row=0, column=1)
        ttk.Label(
            container, textvariable=self.guide_hint, style="Subtitle.TLabel",
            wraplength=680, justify=tk.LEFT,
        ).grid(row=1, column=0, sticky="w", pady=(8, 8))
        ttk.Label(
            container,
            text="MCP configuration is saved. Start APS; its connection has not yet been tested.",
            style="Subtitle.TLabel", wraplength=680, justify=tk.LEFT,
        ).grid(row=2, column=0, sticky="w", pady=(0, 12))

        selectors = ttk.Frame(container, style="Root.TFrame")
        selectors.grid(row=3, column=0, sticky="ew")
        selectors.columnconfigure(1, weight=1)
        selectors.columnconfigure(3, weight=1)
        ttk.Label(selectors, text="Prompt", style="Subtitle.TLabel").grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        ttk.Combobox(
            selectors, textvariable=self.prompt_name, values=PROMPT_NAMES,
            state="readonly",
        ).grid(row=0, column=1, sticky="ew")
        ttk.Label(selectors, text="Simulation", style="Subtitle.TLabel").grid(
            row=0, column=2, padx=(12, 8), sticky="w"
        )
        ttk.Entry(selectors, textvariable=self.simulation_name).grid(
            row=0, column=3, sticky="ew"
        )
        ttk.Label(
            container, text="Enter a simulation name for prompts that open one.",
            style="Subtitle.TLabel",
        ).grid(row=4, column=0, sticky="w", pady=(7, 5))
        self.prompt_text = tk.Text(
            container, wrap=tk.WORD, height=5, background=INPUT, foreground=TEXT,
            insertbackground=TEXT, relief=tk.FLAT, padx=10, pady=10,
            font=("Segoe UI", 10), state=tk.DISABLED,
        )
        self.prompt_text.grid(row=5, column=0, sticky="nsew")
        footer = ttk.Frame(container, style="Root.TFrame")
        footer.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(
            footer, text="Copy prompt", style="Primary.TButton",
            command=self._copy_prompt,
        ).pack(side=tk.LEFT)
        ttk.Label(
            footer, textvariable=self.copy_status, style="Subtitle.TLabel",
        ).pack(side=tk.LEFT, padx=(12, 0))

    def _show_home(self) -> None:
        self.guide_container.pack_forget()
        self.home_container.pack(fill=tk.BOTH, expand=True)

    def _show_guide(self) -> None:
        if self.configured_target is None:
            return
        self._refresh_guide_hint()
        self._refresh_prompt()
        self.home_container.pack_forget()
        self.guide_container.pack(fill=tk.BOTH, expand=True)

    def _refresh_guide_hint(self) -> None:
        hints = {
            "claude": (
                "Quit Claude Desktop completely, reopen it, and start a chat. "
                "Enable the AVEVA connector in the chat if necessary."
            ),
            "gemini": (
                "Open PowerShell and run gemini.cmd. Sign in if prompted; "
                "only trust folders you recognize."
            ),
            "codex": "Open PowerShell and run codex.cmd. Sign in if prompted.",
        }
        self.guide_hint.set(hints[self._selected_client_id()])

    def _refresh_prompt(self, *_: str) -> None:
        name = self.simulation_name.get().strip() or "<simulation name>"
        simulation = json.dumps(name, ensure_ascii=False)
        prompts = {
            PROMPT_NAMES[0]: (
                "Dùng AVEVA MCP tools, gọi aps_connect và báo trạng thái kết nối. "
                "Không tạo, mở, sửa hoặc lưu simulation."
            ),
            PROMPT_NAMES[1]: (
                "Dùng AVEVA MCP tools, gọi aps_connect rồi sim_open({}). "
                "Đọc sim_status, models_list và connectors_list. "
                "Không tạo, sửa hoặc lưu simulation."
            ).format(simulation),
            PROMPT_NAMES[2]: (
                "Dùng AVEVA MCP tools, kết nối APS và mở {} trong phiên MCP. "
                "Chỉ đọc trạng thái, models, connectors và các biến liên quan; "
                "tóm tắt dữ liệu có đơn vị, phân biệt dữ liệu với nhận định. "
                "Không tạo, sửa hoặc lưu simulation."
            ).format(simulation),
        }
        self.prompt_text.configure(state=tk.NORMAL)
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", prompts[self.prompt_name.get()])
        self.prompt_text.configure(state=tk.DISABLED)
        self.copy_status.set("")

    def _copy_prompt(self) -> None:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.prompt_text.get("1.0", "end-1c"))
        except tk.TclError as exc:
            messagebox.showerror("Could not copy prompt", str(exc), parent=self.root)
            return
        self.copy_status.set("Copied. Paste it into your AI chat.")

    def _build_settings_ui(self, parent: tk.Misc) -> None:
        container = ttk.Frame(parent, style="Root.TFrame", padding=28)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        ttk.Label(
            container, text="APS AI Connector", style="Title.TLabel"
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            container,
            text="Configure the Python runtime and AVEVA Scripting Interface SDK.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 20))

        setup_card = ttk.Frame(container, style="Card.TFrame", padding=20)
        setup_card.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        setup_card.columnconfigure(1, weight=1)
        ttk.Label(
            setup_card, text="Runtime and SDK", style="CardTitle.TLabel"
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 14))

        ttk.Label(setup_card, text="Python runtime", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 18), pady=6
        )
        self.python_picker = ttk.Combobox(
            setup_card,
            state="readonly",
            postcommand=self._refresh_python_options,
        )
        self.python_picker.grid(row=1, column=1, sticky="ew", pady=6)
        self.python_picker.bind("<<ComboboxSelected>>", self._select_runtime)
        self.scan_button = ttk.Button(
            setup_card,
            text="Rescan",
            style="Secondary.TButton",
            command=self._start_scan,
        )
        self.scan_button.grid(row=1, column=2, padx=(10, 0), pady=6)

        ttk.Label(setup_card, text="Executable", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 18), pady=6
        )
        ttk.Label(
            setup_card,
            textvariable=self.runtime_path,
            style="Muted.Card.TLabel",
            wraplength=650,
        ).grid(row=2, column=1, sticky="w", pady=6)
        self.browse_python_button = ttk.Button(
            setup_card,
            text="Browse...",
            style="Secondary.TButton",
            command=self._browse_python,
        )
        self.browse_python_button.grid(row=2, column=2, padx=(10, 0), pady=6)

        ttk.Label(setup_card, text="Scripting Interface SDK", style="Card.TLabel").grid(
            row=3, column=0, sticky="w", padx=(0, 18), pady=6
        )
        self.sdk_entry = ttk.Entry(
            setup_card, textvariable=self.scripting_interface_path
        )
        self.sdk_entry.grid(row=3, column=1, sticky="ew", pady=6)
        self.browse_sdk_button = ttk.Button(
            setup_card,
            text="Browse...",
            style="Secondary.TButton",
            command=self._browse_scripting_interface,
        )
        self.browse_sdk_button.grid(row=3, column=2, padx=(10, 0), pady=6)

        ttk.Label(
            setup_card,
            text=(
                "Choose the ScriptingInterface folder inside Toolkits. "
                "It should contain requirements.txt and packages\\simcentralconnect."
            ),
            style="Muted.Card.TLabel",
            wraplength=650,
            justify=tk.LEFT,
        ).grid(row=4, column=1, columnspan=2, sticky="w", pady=(0, 6))

        ttk.Label(setup_card, text="Client settings", style="Card.TLabel").grid(
            row=5, column=0, sticky="w", padx=(0, 18), pady=6
        )
        ttk.Label(
            setup_card,
            textvariable=self.config_path,
            style="Muted.Card.TLabel",
            wraplength=650,
        ).grid(row=5, column=1, columnspan=2, sticky="w", pady=6)

        footer = ttk.Frame(container, style="Root.TFrame")
        footer.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        footer.columnconfigure(3, weight=1)
        ttk.Label(
            footer,
            textvariable=self.status,
            style="Subtitle.TLabel",
            wraplength=620,
            justify=tk.LEFT,
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))
        self.install_button = ttk.Button(
            footer,
            text="Install dependencies",
            style="Secondary.TButton",
            command=self._install_dependencies,
        )
        self.install_button.grid(row=1, column=0, padx=(0, 8), sticky="w")
        self.check_button = ttk.Button(
            footer,
            text="Check runtime",
            style="Secondary.TButton",
            command=self._check_selected_runtime,
        )
        self.check_button.grid(row=1, column=1, padx=(0, 8), sticky="w")
        ttk.Button(
            footer,
            text="Open settings folder",
            style="Secondary.TButton",
            command=self._open_config_folder,
        ).grid(row=1, column=2, padx=(0, 8), sticky="w")
        self.settings_progress = ttk.Progressbar(
            footer, mode="indeterminate", style="Activity.Horizontal.TProgressbar"
        )
        self.settings_progress.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        self._refresh_activity()

    def _selected_client_id(self) -> str:
        return CLIENTS[self.client_name.get()]

    def _connection_selection_changed(self, *_: str) -> None:
        self._refresh_client_hint()
        if self.configured_target and self.configured_target != (
            self._selected_client_id(), self.python_path.get()
        ):
            self.configured_target = None
            self.status.set("Selection changed. Connect to configure the selected AI client.")
            self._show_home()
        self._refresh_connect_button()

    def _refresh_client_hint(self) -> None:
        hints = {
            "claude": "Open Claude Desktop after setup to chat with APS.",
            "gemini": (
                "Run gemini.cmd in PowerShell after setup. If prompted, trust only "
                "a folder you recognize; untrusted folders cannot use MCP."
            ),
            "codex": "Run codex.cmd in PowerShell after setup and sign in if prompted.",
        }
        self.client_hint.set(hints[self._selected_client_id()])

    def _refresh_connect_button(self) -> None:
        configured = self.configured_target is not None
        unavailable = self.connect_in_progress or self.scan_in_progress or self.busy
        self.connect_button.configure(
            text="Connected" if configured else "Connect",
            state=tk.DISABLED if configured or unavailable else tk.NORMAL,
        )
        self.guide_button.configure(
            state=tk.NORMAL if configured and not unavailable else tk.DISABLED,
        )

    def _refresh_activity(self) -> None:
        for name in ("main_progress", "settings_progress"):
            bar = getattr(self, name, None)
            if bar is not None and bar.winfo_exists():
                if self.busy:
                    bar.start(15)
                else:
                    bar.stop()
                    bar.configure(value=0)
        self.client_picker.configure(state="disabled" if self.busy else "readonly")
        for name in (
            "scan_button", "install_button", "check_button",
            "browse_python_button", "browse_sdk_button", "sdk_entry",
        ):
            button = getattr(self, name, None)
            if button is not None and button.winfo_exists():
                button.configure(state=tk.DISABLED if self.busy else tk.NORMAL)
        if hasattr(self, "python_picker") and self.python_picker.winfo_exists():
            self.python_picker.configure(state="disabled" if self.busy else "readonly")
        self._refresh_connect_button()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self._refresh_activity()

    def _update_progress(self) -> None:
        while True:
            try:
                self.status.set(self.progress_results.get_nowait())
            except queue.Empty:
                break

    def _show_configured_status(self) -> None:
        self.status.set(
            "Connected: MCP configured for {}. Restart the client to load it; "
            "the APS connection has not been tested.".format(self.client_name.get())
        )

    def _save_settings(self) -> None:
        save_app_settings(
            {
                "client": self._selected_client_id(),
                "python_executable": self.python_path.get(),
                "scripting_interface_path": self.scripting_interface_path.get(),
            }
        )

    def _connect(self) -> None:
        if self.busy:
            return
        try:
            self._save_settings()
        except OSError as exc:
            messagebox.showerror(
                "Could not save settings", str(exc), parent=self.root
            )
            return

        client = self._selected_client_id()
        executable = self.python_path.get()
        self.connect_in_progress = True
        self._set_busy(True)
        self.status.set("Checking whether {} is installed...".format(self.client_name.get()))
        threading.Thread(
            target=lambda: self.client_check_results.put(
                (client, executable, is_ai_client_installed(client))
            ),
            daemon=True,
        ).start()
        self.root.after(100, self._poll_client_check)

    def _poll_client_check(self) -> None:
        try:
            client, executable, installed = self.client_check_results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_client_check)
            return
        if not installed:
            display_name = self.client_name.get()
            if not messagebox.askyesno(
                "AI client not found",
                "{} is not installed. Install it now?".format(display_name),
                parent=self.root,
            ):
                self.status.set(
                    "{} is not installed. Install it before connecting.".format(
                        display_name
                    )
                )
                self.connect_in_progress = False
                self._set_busy(False)
                return

            self.status.set("Installing {}...".format(display_name))
            threading.Thread(
                target=lambda: self.client_install_results.put(
                    (client, executable, *install_ai_client(client))
                ),
                daemon=True,
            ).start()
            self.root.after(100, self._poll_client_install)
            return

        self._start_connect(client, executable)

    def _poll_client_install(self) -> None:
        try:
            client, executable, succeeded, message = self.client_install_results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_client_install)
            return

        self.status.set(message)
        if succeeded:
            self._start_connect(client, executable)
        else:
            self.connect_in_progress = False
            self._set_busy(False)
            messagebox.showerror("Installation failed", message, parent=self.root)

    def _start_connect(self, client: str, executable: str) -> None:
        self.connect_in_progress = True
        self._set_busy(True)
        self.status.set("Checking Python and configuring the selected AI client...")
        threading.Thread(
            target=lambda: self.connect_results.put(
                (client, executable, *connect_ai_client(
                    client, executable, progress=self.progress_results.put
                ))
            ),
            daemon=True,
        ).start()
        self.root.after(100, self._poll_connect)

    def _poll_connect(self) -> None:
        self._update_progress()
        try:
            client, executable, succeeded, message = self.connect_results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_connect)
            return

        self.connect_in_progress = False
        self._set_busy(False)
        if succeeded and (client, executable) == (
            self._selected_client_id(), self.python_path.get()
        ):
            self.configured_target = (client, executable)
            self._show_configured_status()
            self._show_guide()
        elif succeeded:
            self.status.set(
                "MCP configured for {}. Selection changed; connect the selected "
                "client separately.".format(client)
            )
        else:
            self.status.set(message)
            messagebox.showerror("Could not connect", message, parent=self.root)
        self._refresh_connect_button()

    def _open_settings(self) -> None:
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return

        window = tk.Toplevel(self.root)
        window.title("APS AI Connector Settings")
        window.geometry("1100x740")
        window.minsize(920, 680)
        window.configure(bg=BACKGROUND)
        self.settings_window = window
        self._build_settings_ui(window)
        self._refresh_python_options()
        selected = next(
            (
                runtime
                for runtime in self.runtimes_by_label.values()
                if os.path.normcase(os.path.abspath(runtime.executable))
                == os.path.normcase(os.path.abspath(self.python_path.get()))
            ),
            None,
        )
        if selected:
            self.python_picker.set(selected.label)
        self._refresh_config()
        window.protocol("WM_DELETE_WINDOW", self._close_settings)

    def _close_settings(self) -> None:
        try:
            self._save_settings()
        except OSError as exc:
            messagebox.showerror(
                "Could not save settings",
                str(exc),
                parent=self.settings_window or self.root,
            )
            return
        if self.settings_window:
            self.settings_window.destroy()
            self.settings_window = None

    def _refresh_config(self, event: tk.Event | None = None) -> None:
        if event is not None and event.widget is not self.client_picker:
            return
        client = self._selected_client_id()
        self.config_path.set(str(get_client_config_path(client)))

    def _refresh_python_options(self) -> None:
        if hasattr(self, "python_picker") and self.python_picker.winfo_exists():
            self.python_picker.configure(values=tuple(self.runtimes_by_label.keys()))

    def _select_runtime(self, event: tk.Event | None = None) -> None:
        if event is not None and event.widget is not self.python_picker:
            return
        runtime = self.runtimes_by_label.get(self.python_picker.get())
        if runtime is None:
            return
        self.python_path.set(runtime.executable)
        self.runtime_path.set(runtime.executable)
        self.status.set(runtime.details)
        self._refresh_config()

    def _browse_python(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select a Python executable",
            initialdir=str(Path(self.python_path.get()).parent),
            filetypes=(("Python executable", "python.exe"), ("All files", "*.*")),
        )
        if selected:
            self.python_path.set(selected)
            self.runtime_path.set(selected)
            self.status.set("Custom interpreter selected. Choose Check runtime to validate it.")
            self._refresh_config()

    def _browse_scripting_interface(self) -> None:
        selected = filedialog.askdirectory(
            title="Select the AVEVA ScriptingInterface folder",
            initialdir=self.scripting_interface_path.get(),
        )
        if selected:
            self.scripting_interface_path.set(selected)

    def _install_dependencies(self) -> None:
        if self.busy:
            return
        executable = self.python_path.get()
        sdk_directory = self.scripting_interface_path.get()
        self._set_busy(True)
        self.status.set("Installing SDK and MCP dependencies into the selected Python...")
        threading.Thread(
            target=lambda: self.install_results.put(
                install_runtime_dependencies(
                    executable, sdk_directory, progress=self.progress_results.put
                )
            ),
            daemon=True,
        ).start()
        self.root.after(100, self._poll_install)

    def _poll_install(self) -> None:
        self._update_progress()
        try:
            succeeded, message = self.install_results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_install)
            return

        self._set_busy(False)
        self.status.set(message)
        if succeeded:
            messagebox.showinfo("Installation complete", message, parent=self.root)
            self._start_scan()
        else:
            messagebox.showerror("Installation failed", message, parent=self.root)

    def _start_scan(self) -> None:
        if self.busy:
            return
        self.scan_in_progress = True
        self._set_busy(True)
        self.status.set("Scanning installed Python interpreters and checking imports...")
        threading.Thread(
            target=self._scan_worker,
            daemon=True,
        ).start()
        self.root.after(100, self._poll_scan)

    def _scan_worker(self) -> None:
        try:
            runtimes = [
                inspect_python_runtime(executable)
                for executable in discover_python_executables()
            ]
        except (OSError, ValueError) as exc:
            self.scan_results.put(([], str(exc)))
            return
        runtimes = [runtime for runtime in runtimes if runtime.version != (0, 0, 0)]
        runtimes.sort(key=lambda runtime: runtime.version, reverse=True)
        self.scan_results.put((runtimes, None))

    def _poll_scan(self) -> None:
        try:
            runtimes, error = self.scan_results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_scan)
            return

        self.scan_in_progress = False
        self._set_busy(False)
        if error:
            self.status.set("Python scan failed: {}".format(error))
            return
        if not runtimes:
            self.status.set("No Python interpreters were found. Browse to python.exe.")
            return

        self.runtimes_by_label = {runtime.label: runtime for runtime in runtimes}
        self._refresh_python_options()
        selected = select_runtime(runtimes, self.python_path.get())
        if selected is None:
            self.status.set("No Python interpreters were found.")
            return

        if hasattr(self, "python_picker") and self.python_picker.winfo_exists():
            self.python_picker.set(selected.label)
        self.python_path.set(selected.executable)
        self.runtime_path.set(selected.executable)
        self._refresh_config()
        if not selected.ready and self.configured_target:
            self.configured_target = None
            self._refresh_connect_button()
        if selected.ready and self.configured_target:
            self._show_configured_status()
        elif selected.ready:
            self.status.set(
                "Found {} interpreter(s). Selected the newest runtime that passed "
                "the server import check.".format(len(runtimes))
            )
        else:
            self.status.set(
                "Selected Python {} is not ready: {}".format(
                    selected.version_text, selected.details.splitlines()[-1]
                )
            )

    def _check_selected_runtime(self) -> None:
        if self.busy:
            return
        executable = self.python_path.get()
        self._set_busy(True)
        self.status.set("Checking the selected runtime...")
        threading.Thread(
            target=lambda: self.check_results.put(inspect_python_runtime(executable)),
            daemon=True,
        ).start()
        self.root.after(100, self._poll_check)

    def _poll_check(self) -> None:
        try:
            runtime = self.check_results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_check)
            return

        self._set_busy(False)
        self.status.set(runtime.details)
        if runtime.ready:
            messagebox.showinfo("Runtime check", runtime.details, parent=self.root)
        else:
            messagebox.showerror("Runtime check", runtime.details, parent=self.root)

    def _open_config_folder(self) -> None:
        folder = get_client_config_path(self._selected_client_id()).parent
        if not folder.is_dir():
            messagebox.showinfo(
                "Settings folder not found",
                "Open the client's settings once to create this folder:\n{}".format(
                    folder
                ),
                parent=self.root,
            )
            return
        try:
            subprocess.Popen(["explorer.exe", str(folder)])
        except OSError as exc:
            messagebox.showerror("Could not open folder", str(exc), parent=self.root)


def main() -> None:
    root = tk.Tk()
    ConnectorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
