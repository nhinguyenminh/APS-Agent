import json
import subprocess
import tempfile
import tkinter as tk
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from aps_ai_connector import (
    ConnectorApp,
    PythonRuntime,
    SDK_RELATIVE_PATH,
    configure_ai_client,
    connect_ai_client,
    generate_config_snippet,
    find_default_scripting_interface_path,
    get_client_config_path,
    install_ai_client,
    install_runtime_dependencies,
    is_ai_client_installed,
    load_app_settings,
    merge_codex_config,
    parse_python_launcher_output,
    save_app_settings,
    select_default_runtime,
    select_runtime,
)


class ConnectorStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        with patch("aps_ai_connector.load_app_settings", return_value={}):
            with patch.object(self.root, "after"):
                self.app = ConnectorApp(self.root)

    def tearDown(self) -> None:
        self.root.destroy()

    def test_success_updates_status_and_selection_change_reenables_connect(self) -> None:
        app = self.app
        app.connect_in_progress = True
        app.connect_results.put(("claude", app.python_path.get(), True, "configured"))
        with patch("aps_ai_connector.messagebox.showinfo") as showinfo:
            app._poll_connect()
        showinfo.assert_not_called()
        self.assertEqual(app.connect_button.cget("text"), "Connected")
        self.assertEqual(str(app.connect_button.cget("state")), "disabled")
        self.assertIn("APS connection has not been tested", app.status.get())

        app.client_name.set("Gemini CLI")
        self.assertEqual(app.connect_button.cget("text"), "Connect")
        self.assertEqual(str(app.connect_button.cget("state")), "normal")

    def test_success_for_old_runtime_does_not_disable_current_selection(self) -> None:
        app = self.app
        app.connect_in_progress = True
        previous = app.python_path.get()
        app.python_path.set("different-python.exe")
        app.connect_results.put(("claude", previous, True, "configured"))
        app._poll_connect()
        self.assertEqual(str(app.connect_button.cget("state")), "normal")
        self.assertIn("Selection changed", app.status.get())

    def test_rescan_keeps_success_until_runtime_changes(self) -> None:
        app = self.app
        executable = app.python_path.get()
        app.connect_results.put(("claude", executable, True, "configured"))
        app._poll_connect()
        app.scan_in_progress = True
        app.scan_results.put(([PythonRuntime(executable, (3, 13, 0), True, "Ready")], None))
        app._poll_scan()
        self.assertEqual(str(app.connect_button.cget("state")), "disabled")
        self.assertIn("Connected", app.status.get())
        app.python_path.set("different-python.exe")
        self.assertEqual(str(app.connect_button.cget("state")), "normal")

    def test_failed_connection_shows_error_and_reenables_button(self) -> None:
        app = self.app
        app.connect_in_progress = True
        app.connect_results.put(("claude", app.python_path.get(), False, "failed"))
        with patch("aps_ai_connector.messagebox.showerror") as showerror:
            app._poll_connect()
        showerror.assert_called_once()
        self.assertEqual(str(app.connect_button.cget("state")), "normal")
        self.assertEqual(app.status.get(), "failed")

    def test_client_detection_runs_in_background_and_shows_activity(self) -> None:
        app = self.app
        with patch("aps_ai_connector.save_app_settings"):
            with patch("aps_ai_connector.threading.Thread") as thread:
                with patch.object(self.root, "after"):
                    app._connect()
        self.assertTrue(app.busy)
        self.assertEqual(str(app.connect_button.cget("state")), "disabled")
        self.assertIn("Checking whether", app.status.get())
        thread.return_value.start.assert_called_once()

        with patch("aps_ai_connector.is_ai_client_installed", return_value=True):
            thread.call_args.kwargs["target"]()
        with patch.object(app, "_start_connect") as start:
            app._poll_client_check()
        start.assert_called_once_with("claude", app.python_path.get())

    def test_cancelled_install_stops_activity(self) -> None:
        app = self.app
        app.connect_in_progress = True
        app._set_busy(True)
        app.client_check_results.put(("claude", app.python_path.get(), False))
        with patch("aps_ai_connector.messagebox.askyesno", return_value=False):
            app._poll_client_check()
        self.assertFalse(app.busy)
        self.assertEqual(str(app.connect_button.cget("state")), "normal")

    def test_activity_is_visible_in_settings_and_controls_are_locked(self) -> None:
        app = self.app
        app._set_busy(True)
        app._open_settings()
        self.assertEqual(str(app.install_button.cget("state")), "disabled")
        self.assertEqual(str(app.python_picker.cget("state")), "disabled")
        self.assertEqual(str(app.settings_progress.cget("mode")), "indeterminate")
        app._set_busy(False)
        self.assertEqual(str(app.install_button.cget("state")), "normal")
        self.assertEqual(str(app.python_picker.cget("state")), "readonly")

    def test_client_hint_explains_gemini_folder_trust(self) -> None:
        self.app.client_name.set("Gemini CLI")
        self.assertIn("untrusted folders cannot use MCP", self.app.client_hint.get())

    def test_running_operation_displays_its_latest_step(self) -> None:
        app = self.app
        app._set_busy(True)
        app.progress_results.put("Installing APS MCP server dependencies...")
        with patch.object(self.root, "after"):
            app._poll_install()
        self.assertIn("Installing APS MCP server", app.status.get())
        self.assertTrue(app.busy)
        app.install_results.put((False, "install failed"))
        with patch("aps_ai_connector.messagebox.showerror"):
            app._poll_install()
        self.assertFalse(app.busy)
        self.assertEqual(app.status.get(), "install failed")


class ConfigSnippetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.python = r"C:\Python\python.exe"
        self.launcher = Path(r"C:\APS Agent\start_aveva_mcp_server.py")

    def test_json_client_snippets_preserve_paths(self) -> None:
        for client in ("gemini", "claude"):
            with self.subTest(client=client):
                config = json.loads(
                    generate_config_snippet(client, self.python, self.launcher)
                )
                server = config["mcpServers"]["aveva"]
                self.assertEqual(server["command"], self.python)
                self.assertEqual(server["args"], [str(self.launcher)])

    def test_codex_snippet_uses_toml_server_table(self) -> None:
        snippet = generate_config_snippet("codex", self.python, self.launcher)
        config = tomllib.loads(snippet)
        server = config["mcp_servers"]["aveva"]
        self.assertEqual(server["command"], self.python)
        self.assertEqual(server["args"], [str(self.launcher)])

    def test_codex_merge_replaces_aveva_and_preserves_other_tables(self) -> None:
        existing = (
            '[mcp_servers.other]\ncommand = "other-tool"\n\n'
            '[mcp_servers.aveva]\ncommand = "old-python"\nargs = []\n\n'
            '[projects."C:/work"]\ntrust_level = "trusted"\n'
        )
        snippet = generate_config_snippet("codex", self.python, self.launcher)

        updated = tomllib.loads(merge_codex_config(existing, snippet))

        self.assertEqual(updated["mcp_servers"]["other"]["command"], "other-tool")
        self.assertEqual(updated["mcp_servers"]["aveva"]["command"], self.python)
        self.assertEqual(updated["projects"]["C:/work"]["trust_level"], "trusted")

    def test_codex_merge_rejects_invalid_toml(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid TOML"):
            merge_codex_config("[mcp_servers\n", "[mcp_servers.aveva]\ncommand='python'")

    def test_json_configuration_preserves_settings_and_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "settings.json"
            original = '{"theme": "dark", "mcpServers": {"other": {"command": "x"}}}\n'
            config_path.write_text(original, encoding="utf-8")

            with patch(
                "aps_ai_connector.get_client_config_path", return_value=config_path
            ):
                result_path, backup = configure_ai_client(
                    "gemini", self.python, self.launcher
                )

            updated = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["theme"], "dark")
            self.assertEqual(updated["mcpServers"]["other"]["command"], "x")
            self.assertEqual(updated["mcpServers"]["aveva"]["command"], self.python)
            self.assertIsNotNone(backup)
            self.assertEqual(backup.read_text(encoding="utf-8"), original)

    def test_app_settings_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            with patch("aps_ai_connector.get_app_settings_path", return_value=path):
                save_app_settings({"client": "codex", "python_executable": self.python})
                settings = load_app_settings()

        self.assertEqual(settings["client"], "codex")
        self.assertEqual(settings["python_executable"], self.python)

    def test_connect_does_not_write_config_when_runtime_is_not_ready(self) -> None:
        runtime = PythonRuntime(self.python, (3, 14, 0), False, "Missing dependency")
        with patch("aps_ai_connector.inspect_python_runtime", return_value=runtime):
            with patch("aps_ai_connector.configure_ai_client") as configure:
                connected, message = connect_ai_client("gemini", self.python)

        self.assertFalse(connected)
        self.assertIn("Open Settings", message)
        configure.assert_not_called()

    def test_connect_configures_client_when_runtime_is_ready(self) -> None:
        runtime = PythonRuntime(self.python, (3, 14, 0), True, "Ready")
        config_path = Path("client-config.json")
        with patch("aps_ai_connector.inspect_python_runtime", return_value=runtime):
            with patch(
                "aps_ai_connector.configure_ai_client",
                return_value=(config_path, None),
            ) as configure:
                connected, message = connect_ai_client("gemini", self.python)

        self.assertTrue(connected)
        self.assertIn(str(config_path), message)
        self.assertIn("Restart gemini", message)
        configure.assert_called_once()
        self.assertEqual(configure.call_args.args[:2], ("gemini", self.python))

    def test_client_config_paths(self) -> None:
        self.assertEqual(get_client_config_path("gemini").name, "settings.json")
        self.assertEqual(get_client_config_path("codex").name, "config.toml")
        self.assertEqual(
            get_client_config_path("claude").name, "claude_desktop_config.json"
        )

    def test_detects_claude_desktop_from_winget_inventory(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Claude Anthropic.Claude 4.29.0", stderr=""
        )
        with patch(
            "aps_ai_connector.shutil.which",
            side_effect=lambda command: (
                "winget.exe" if command in ("winget.exe", "winget") else None
            ),
        ):
            with patch("aps_ai_connector.subprocess.run", return_value=completed):
                self.assertTrue(is_ai_client_installed("claude"))

    def test_detects_claude_desktop_from_appx_package(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="AnthropicPBC.Claude\r\n",
            stderr="",
        )
        with patch("aps_ai_connector.Path.is_file", return_value=False):
            with patch(
                "aps_ai_connector.shutil.which",
                side_effect=lambda command: (
                    "powershell.exe" if command == "powershell.exe" else None
                ),
            ):
                with patch(
                    "aps_ai_connector.subprocess.run", return_value=completed
                ) as run:
                    self.assertTrue(is_ai_client_installed("claude"))

        self.assertIn("Get-AppxPackage", run.call_args.args[0][-1])

    def test_detects_cli_from_path(self) -> None:
        with patch(
            "aps_ai_connector.shutil.which",
            side_effect=lambda command: "C:\\npm\\gemini.cmd"
            if command == "gemini.cmd"
            else None,
        ):
            self.assertTrue(is_ai_client_installed("gemini"))

    def test_installs_claude_desktop_with_exact_winget_package(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0)
        with patch("aps_ai_connector.shutil.which", return_value="winget.exe"):
            with patch(
                "aps_ai_connector.subprocess.run", return_value=completed
            ) as run:
                installed, message = install_ai_client("claude")

        self.assertTrue(installed)
        self.assertIn("installed successfully", message)
        command = run.call_args.args[0]
        self.assertEqual(command[1:4], ["install", "--id", "Anthropic.Claude"])
        self.assertIn("--exact", command)

    def test_installs_codex_cli_from_npm(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0)
        with patch(
            "aps_ai_connector.shutil.which",
            side_effect=lambda command: "C:\\Program Files\\nodejs\\npm.cmd"
            if command == "npm.cmd"
            else None,
        ):
            with patch(
                "aps_ai_connector.subprocess.run", return_value=completed
            ) as run:
                installed, _ = install_ai_client("codex")

        self.assertTrue(installed)
        self.assertTrue(run.call_args.kwargs["shell"])
        self.assertIn("@openai/codex", run.call_args.args[0])

    def test_unknown_client_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            generate_config_snippet("unknown", self.python, self.launcher)

    def test_empty_python_path_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            generate_config_snippet("gemini", "  ", self.launcher)

    def test_selects_newest_runtime_that_passed_imports(self) -> None:
        runtimes = [
            PythonRuntime("python314.exe", (3, 14, 6), False, "DLL error"),
            PythonRuntime("python313.exe", (3, 13, 8), True, "Ready"),
            PythonRuntime("python312.exe", (3, 12, 9), True, "Ready"),
        ]
        self.assertEqual(select_default_runtime(runtimes), runtimes[1])

    def test_falls_back_to_newest_found_runtime_when_none_are_ready(self) -> None:
        runtimes = [
            PythonRuntime("python313.exe", (3, 13, 8), False, "Missing dependency"),
            PythonRuntime("python314.exe", (3, 14, 6), False, "DLL error"),
        ]
        self.assertEqual(select_default_runtime(runtimes), runtimes[1])

    def test_select_runtime_ignores_saved_runtime_until_it_is_ready(self) -> None:
        runtimes = [
            PythonRuntime("python314.exe", (3, 14, 6), False, "Missing dependency"),
            PythonRuntime("python313.exe", (3, 13, 8), True, "Ready"),
        ]
        self.assertEqual(select_runtime(runtimes, "python314.exe"), runtimes[1])

    def test_python_launcher_parser_preserves_paths_with_spaces(self) -> None:
        output = (
            " -V:3.14 * C:\\Python314\\python.exe\n"
            " -V:3.13   C:\\Program Files\\Python313\\python.exe\n"
        )
        self.assertEqual(
            parse_python_launcher_output(output),
            [
                r"C:\Python314\python.exe",
                r"C:\Program Files\Python313\python.exe",
            ],
        )

    def test_default_sdk_path_finds_scripting_interface_toolkit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            one_drive = Path(temp_dir) / "OneDrive"
            sdk_directory = one_drive / SDK_RELATIVE_PATH
            (sdk_directory / "packages" / "simcentralconnect").mkdir(parents=True)
            (sdk_directory / "requirements.txt").write_text("", encoding="utf-8")

            result = find_default_scripting_interface_path(
                home=Path(temp_dir) / "home",
                one_drive_roots=(one_drive,),
            )

        self.assertEqual(result, sdk_directory)

    def test_installs_sdk_and_project_dependencies_in_selected_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sdk_directory = Path(temp_dir) / "ScriptingInterface"
            package_directory = sdk_directory / "packages" / "simcentralconnect"
            package_directory.mkdir(parents=True)
            (sdk_directory / "requirements.txt").write_text("", encoding="utf-8")
            completed = subprocess.CompletedProcess(args=[], returncode=0)
            progress = []

            with patch(
                "aps_ai_connector.subprocess.run", return_value=completed
            ) as run:
                succeeded, _ = install_runtime_dependencies(
                    self.python, str(sdk_directory), progress=progress.append
                )

        self.assertTrue(succeeded)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][0], self.python)
        self.assertEqual(
            run.call_args_list[0].kwargs["cwd"], str(Path(__file__).resolve().parent)
        )
        self.assertEqual(run.call_args_list[1].args[0][0], self.python)
        self.assertEqual(run.call_args_list[1].kwargs["cwd"], str(sdk_directory))
        self.assertEqual(len(progress), 2)
        self.assertIn("APS MCP server", progress[0])
        self.assertIn("AVEVA Scripting Interface", progress[1])

    def test_installs_mcp_dependencies_even_if_sdk_path_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.CompletedProcess(args=[], returncode=0)
            with patch(
                "aps_ai_connector.subprocess.run", return_value=completed
            ) as run:
                succeeded, message = install_runtime_dependencies(
                    self.python, temp_dir
                )

        self.assertFalse(succeeded)
        self.assertIn("APS MCP dependencies were installed", message)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][0], self.python)


if __name__ == "__main__":
    unittest.main()
