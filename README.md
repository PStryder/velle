# Velle

*Latin: "to will" — the root of volition.*

Velle is an MCP server that gives Claude Code the ability to prompt itself. It injects text into the terminal as user input via Win32 console APIs, enabling autonomous multi-turn workflows without human intervention. Features include self-prompting chains, 2-step slash command introspection, configurable turn limits, cooldown enforcement, and audit logging.

## How It Works

Velle runs as an MCP server child process of Claude Code. When the agent calls `velle_prompt`, the server injects the text as keyboard input into the parent process's console:

```
Agent calls velle_prompt("investigate the auth module")
    |
    v
Velle MCP Server (child process)
    |
    FreeConsole() -> AttachConsole(parent) -> CreateFile("CONIN$")
    |
    WriteConsoleInputW(key events) -> 500ms delay -> Enter key
    |
    v
Claude Code receives text as user input -> Agent gets a new turn
```

Each turn, the agent decides what to do next and can chain another `velle_prompt` to continue autonomously.

### Slash Command Introspection

Slash commands require a two-step injection: the command itself, then a follow-up prompt so the agent gets a turn to read the output.

```python
velle_prompt(
    text="/context",
    follow_up="Summarize the context usage above.",
    delay_ms=2000,
    follow_up_delay_ms=3000
)
```

The agent receives the slash command output as `<local-command-stdout>` in its context and can act on it.

#### Allowed Slash Commands

| Command | Description |
|---------|-------------|
| `/compact` | Compact conversation to free context |
| `/context` | Visualize context window usage |
| `/usage` | Show plan usage limits and rate limits |
| `/status` | Show version, model, account, connectivity |
| `/stats` | Visualize daily usage, session history |
| `/todos` | Show active todo items |
| `/tasks` | Show running background tasks |
| `/bashes` | Show running background bash commands |
| `/doctor` | Check installation health |
| `/debug` | Read session debug log |
| `/ide` | Show IDE connection status |
| `/release-notes` | View release notes |

Interactive commands (`/help`, `/mcp`, `/config`, etc.) are blocked.

## Tools

### `velle_prompt`

Inject text as user input into the Claude Code session.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `text` | string | *required* | Text to inject |
| `delay_ms` | integer | 500 | Delay before injection (ms) |
| `follow_up` | string | — | Optional second injection for slash commands |
| `follow_up_delay_ms` | integer | 3000 | Delay between first and second injection (ms) |
| `reason` | string | — | Why this prompt is being issued (audit trail) |

### `velle_status`

Returns current session state: turn count, limits, console availability, recent prompt log, and config file path.

## Safety

- **Turn limit** — configurable max self-prompts per session (default: 20). The agent cannot modify this; only the user can edit the config file.
- **Cooldown** — minimum delay between prompts (default: 1000ms). Prevents accidental double-fires.
- **Kill switch** — Ctrl+C stops the agent at any time.
- **Audit trail** — every self-prompt is logged to `velle_audit.jsonl` with timestamp, text, and reason.

## Configuration

Settings are loaded from `velle.json` in the project root:

```json
{
  "turn_limit": 20,
  "cooldown_ms": 1000,
  "budget_usd": 5.00,
  "audit_mode": "both"
}
```

Changes require an MCP server restart (`/mcp` in Claude Code). The agent has no tool to modify configuration — only the user controls these values.

## Installation

### Prerequisites

- Windows 11 (uses Win32 console APIs)
- Python 3.10+
- Claude Code CLI

### Setup

```bash
# Clone the repository
git clone https://github.com/PStryder/velle.git
cd velle

# Create virtual environment and install
uv venv
uv pip install -e .
```

### Register with Claude Code

Add to your Claude Code MCP configuration (`~/.claude/claude_mcp_config.json`):

```json
{
  "mcpServers": {
    "velle": {
      "command": "/path/to/velle/.venv/Scripts/python",
      "args": ["-m", "velle.server"],
      "cwd": "/path/to/velle"
    }
  }
}
```

## Architecture

```
src/velle/
  __init__.py     # Package version
  server.py       # MCP server — tool definitions, session state, audit logging
  injector.py     # Win32 console injection — AttachConsole, CONIN$, WriteConsoleInputW
```

The injector attaches to the parent process's console (since the MCP server's own stdin is a pipe for MCP transport), opens `CONIN$` to get the real console input buffer, writes key events, then detaches. A 500ms delay between text characters and the Enter key ensures reliable submission even when the console is busy with output.

## Project Structure

```
velle/
  README.md               # This file
  pyproject.toml           # Python package configuration
  velle.json               # Runtime configuration (turn limits, cooldown)
  claude_mcp_config.json   # Example MCP server registration
  src/velle/               # Source code
  spike/                   # Proof-of-concept injection tests
  docs/                    # Design specification and command reference
    SPEC.md                # Technical specification
    COMMANDS.md            # Slash command inventory and access classification
```

## Etymology

From Proto-Indo-European *wel-* ("to wish"), through Latin *velle* ("to will"), to Medieval Latin *volitionem* ("volition"). Velle is the act of willing — an agent that chooses its own next action.

## License

Apache 2.0
