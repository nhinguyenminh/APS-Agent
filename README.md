# AVEVA MCP Server (Compiled Distribution)

A **Model Context Protocol (MCP)** server that exposes AVEVA process simulation tools to AI applications like Claude Desktop, Cursor, and other MCP-compatible clients.


## ⚠️ Requirements

| Requirement | Version |
|-------------|---------|
| **Python** | 3.11+ for the connector; server requires compatible AVEVA modules |
| **OS** | Windows 10/11 (64-bit) |
| **AVEVA SDK** | Installed separately |

> **Compatibility note:** The connector scans installed Python versions and selects the newest runtime that passes the server import check. The `.pyd` modules currently included in this repository were built for Python 3.13; using a different version requires compatible rebuilt modules.

## 🚀 Quick Start

### 1. Prepare the Python runtime

Start the desktop connector:

```bash
python aps_ai_connector.py
```

In **Settings**, select the Python runtime and click **Install dependencies**.
This installs the project's `requirements.txt` and the local Scripting Interface
requirements into that exact interpreter. Avoid bare `pip install` commands:
they may install into a different Python than the AI client will run.

The default Scripting Interface SDK path is detected from the local `Toolkits`
folder. Use **Install dependencies** in Settings to install that toolkit's local
`simcentralconnect` package and the project's MCP requirements into the selected
Python environment; no AVEVA toolkit files are copied into this repository. The
Scripting Interface requires AVEVA Process Simulation 5.1 or later, and APS must
be running before MCP tools can connect. The runtime import check does not test an
APS connection.

### 2. Configure an AI client

Choose Gemini CLI, Codex CLI, or Claude Desktop and click **Connect**. The
connector checks whether the selected client is installed. If it is missing, it
asks before installing it: Claude Desktop through Windows Package Manager
(`winget`), or Gemini/Codex CLI through npm. Node.js and npm are required for
Gemini CLI and Codex CLI. It then checks the selected Python runtime, adds the
AVEVA server entry to the client's configuration, and backs up an existing
configuration before updating it. Restart the AI client to load the MCP server.
After successful configuration, **Connected** is shown in the connector and its
button is disabled until you change the selected client or Python runtime. This
status confirms configuration only, not a live connection to APS.
Runtime selection, SDK path, dependency installation, and runtime checks are
available under **Settings**; these preferences are saved per user.
The status card shows the current step and an animated activity indicator while
checks or installations run. It is not a percentage or time estimate.

To chat after connecting Gemini CLI or Codex CLI, open a new PowerShell window
and run `gemini.cmd` or `codex.cmd`. Sign in when prompted. These are command-line AI
clients, not the Gemini or ChatGPT web apps. Start APS, then ask the AI to use
`aps_connect`, `sim_open` with the simulation name, and read-only tools. A
simulation visible in APS may need to be opened separately in the MCP session.
Gemini CLI blocks MCP servers in untrusted folders. If prompted, review the
folder and choose to trust it only if you recognize it; use `/permissions` in
Gemini to review a prior decision. `gemini.cmd mcp list` shows connection status.

### 3. Run the MCP Server Manually (optional)

Gemini CLI, Codex CLI, and Claude Desktop start the configured stdio server
automatically. Use these commands only to test the server directly or run it with
an alternate transport.

```powershell
# PowerShell; replace both paths with the values from your installation
& "<Python.exe selected in Settings>" `
  "<APS-Agent path>\start_aveva_mcp_server.py"

# SSE transport (for web-based clients)
& "<Python.exe selected in Settings>" `
  "<APS-Agent path>\start_aveva_mcp_server.py" sse --port 8000

# Streamable HTTP transport (for modern clients)
& "<Python.exe selected in Settings>" `
  "<APS-Agent path>\start_aveva_mcp_server.py" http --port 8000
```
If you run successfully, you can stop the server and move on to next step.

### 4. Manual MCP Configuration (optional)

Use the following steps only if you prefer to edit a client's configuration
manually instead of using **Connect** in the desktop app.

You can find a detailed tutorial on how to locate and edit your Claude Desktop configuration file in the official documentation: [Connect to local MCP servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers)
For other MCP clients, please refer to their respective documentation on configuring local MCP servers. Although the interfaces may differ, the core logic remains the same:
you need to specify:

- Specify the **Python executable** that will run the server  
- Specify the **path to the script** that launches your MCP server  

Add the following to your Claude Desktop configuration file. Update the paths to match your environment:

```json
{
  "mcpServers": {
    "aveva": {
      "command": "C:/Users/xxxx/AppData/Local/miniconda3/envs/your_py313_env/python.exe",
      "args": [
        "C:/path/to/distribute/start_aveva_mcp_server.py"
      ]
    }
  }
}
```
Quit the claude desktop completely from the background, and restart it, the MCP tools will be automatically loaded when claude desktop starts. Try to ask something and explicitly mentioning using AVEVA tools.
![Demo of Claude Desktop integration](./demo_claudedesktop.png)

You can see the claude agent used the tools "Aps connect" and "Sim create" for the task.

## 📁 Package Contents

| File | Description |
|------|-------------|
| `start_aveva_mcp_server.py` | Main launcher script |
| `aveva_mcp_server.py` | MCP server with tool definitions |
| `aps_ai_connector.py` | Desktop app for connecting an AI client and managing runtime settings |
| `requirements.txt` | Python dependencies |
| `tools/*.pyd` | Compiled logic modules |
| `tools/__init__.py` | Package initializer |

## 🔧 Troubleshooting

### "DLL load failed" or "ImportError"
- Select a runtime that passes the connector's import check
- The current `.pyd` binaries were built for Python 3.13; newer versions need compatible rebuilt binaries

### "ModuleNotFoundError: No module named 'fastmcp' or 'pydantic'"
- In the connector, open **Settings**, confirm the **Executable** path, and click
  **Install dependencies**.
- If installing manually, use that exact executable, not bare `pip` or `python`:
  `"<python.exe from Settings>" -m pip install -r "<path to APS-Agent>\requirements.txt"`
- Verify with the same executable:
  `"<python.exe from Settings>" -c "import fastmcp, pydantic; print('MCP dependencies OK')"`

### AVEVA connection errors
- Verify AVEVA Process Simulation is installed
- Ensure AVEVA SDK Python components are accessible
- Test with: `python -c "import simcentralconnect; print('AVEVA OK')"`

## 📚 Learn More

- [Model Context Protocol](https://modelcontextprotocol.io/docs/getting-started/intro)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [AVEVA Process Simulation Documentation](https://aveva.com)

---

## Citation
[Liang, Jingkang, Niklas Groll, and Gürkan Sin. "Large Language Model Agent for User-friendly Chemical Process Simulations."(2026).](https://www.sciencedirect.com/science/article/pii/S2772508126000256)
