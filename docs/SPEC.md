# Velle Technical Specification

## Overview

Velle is an MCP server that bridges the gap between the agent and the client. It exposes tools for self-prompting (`velle_prompt`), client-layer introspection (`velle_query`), session status (`velle_status`), and configuration (`velle_configure`). All tools work through the same mechanism: injecting text as user input into the Claude Code process's stdin. Because Claude Code's slash commands output their results into the conversation context, this gives the agent both autonomy (self-directed action loops) and introspection (access to client-side information like token usage, MCP status, and memory state).

## Architecture

### Components

```
+------------------------------------------------------------------+
|                        Claude Code Session                        |
|                                                                   |
|  +-------------------+       +-----------------------------+      |
|  |  Agent (Claude)   | <---> |  MCP Protocol               |      |
|  |                   |       |  (tool calls & results)      |      |
|  +-------------------+       +-------------+---------------+      |
|          ^                                 |                      |
|          |                                 v                      |
|    stdin |                   +-----------------------------+      |
|          |                   |  Velle MCP Server            |      |
|          |                   |                              |      |
|          +<--inject----------|  - Find parent CC process    |      |
|                              |  - Write to stdin            |      |
|                              |  - Inject slash commands      |      |
|                              |  - Log to MemoryGate         |      |
|                              |  - Enforce guardrails        |      |
|                              +-----------------------------+      |
+------------------------------------------------------------------+
```

### Process Model

1. Claude Code starts and loads Velle as an MCP server
2. The MCP server runs as a child process of Claude Code
3. When `velle_prompt` is called, the server:
   a. Validates against guardrail limits
   b. Logs the prompt to MemoryGate (audit trail)
   c. Locates the parent Claude Code process
   d. Injects the text into the parent's stdin
   e. Returns confirmation to the agent
4. Claude Code receives the injected text as a new user message
5. The agent processes it and may call `velle_prompt` again

## MCP Tool Interface

### `velle_prompt`

Inject text as user input into the current Claude Code session.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `text` | string | yes | The text to inject as user input |
| `delay_ms` | integer | no | Delay in milliseconds before injection (default: 500) |
| `reason` | string | no | Why this self-prompt is being issued (logged to audit trail) |

**Returns:**

```json
{
  "status": "injected",
  "turn_count": 3,
  "turn_limit": 20,
  "budget_remaining": "estimated $X.XX",
  "timestamp": "ISO-8601"
}
```

**Errors:**

| Code | Condition |
|------|-----------|
| `TURN_LIMIT_REACHED` | Maximum self-prompt iterations exceeded |
| `BUDGET_EXCEEDED` | Cost budget threshold reached |
| `INJECTION_FAILED` | Could not write to Claude Code stdin |
| `COOLDOWN_ACTIVE` | Minimum delay between prompts not met |

### `velle_query`

Execute a slash command in the Claude Code session and inject a follow-up prompt so the agent gets a turn to process the output. This is a **two-step injection**:

1. Inject the slash command (e.g., `/context`) → client processes it, outputs to conversation
2. Inject a follow-up prompt → agent gets a new turn where it can read the command output

Without the second step, the command output would sit in the conversation with no agent turn to process it. Velle handles both steps automatically with a configurable delay between them.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `command` | string | yes | The slash command to execute (e.g., "/context", "/memory", "/compact") |
| `follow_up` | string | no | Prompt to inject after the command completes (default: "Process the output of the {command} command and continue.") |
| `delay_ms` | integer | no | Delay between command injection and follow-up injection in ms (default: 3000) |
| `reason` | string | no | Why this query is being issued (logged to audit trail) |

**Returns:**

```json
{
  "status": "injected",
  "command": "/context",
  "follow_up": "Process the output of the /context command and continue.",
  "note": "Two-step injection: command first, then follow-up prompt after delay",
  "timestamp": "ISO-8601"
}
```

**Injection Sequence:**

The two-step injection is inherently safe from a timing perspective. The MCP tool call returns its result to the agent *before* any injection happens. The agent must finish generating its response before Claude Code reads the next stdin input. So the natural sequence is:

1. Agent calls `velle_query` → MCP tool begins processing
2. MCP tool returns confirmation → agent receives tool result
3. Agent finishes generating its response (tool result acknowledgment)
4. Claude Code reads stdin → picks up the injected slash command
5. Client processes command, outputs to conversation
6. After `delay_ms`, Velle injects follow-up prompt
7. Claude Code reads stdin → picks up follow-up
8. Agent receives new turn with command output + follow-up

The `delay_ms` (default: 3000ms) is the gap between step 5 and step 6 — giving the client time to fully process the slash command before the follow-up arrives.

```
Time 0ms:      Agent's turn completes; Velle injects "/context" to stdin
               → Claude Code client processes /context
               → Output appears in conversation as <local-command-stdout>
Time 3000ms:   Velle injects follow-up prompt to stdin
               → Agent receives new turn
               → Agent sees /context output AND the follow-up instruction
               → Agent acts on the combined information
```

**Command Registry:**

Every known Claude Code slash command is enumerated in Velle's command registry with an explicit status: `ALLOWED` or `BLOCKED`. The tool accepts any command as valid input. If the command is `BLOCKED`, Velle does not inject it — instead it returns a `COMMAND_BLOCKED` response telling the agent which command was blocked and why.

The registry is the single source of truth. There is no ambiguity — every command has a definitive status. Users can change any command's status via `velle_configure`.

Default `ALLOWED` (15 commands):

| Command | Description |
|---------|-------------|
| `/compact` | Trigger manual context compaction |
| `/context` | Token usage breakdown: total, by category, free space, autocompact buffer |
| `/cost` | Actual token usage and cost statistics for the session |
| `/usage` | Plan usage limits and rate limit status |
| `/mcp` | MCP servers connected, tools available, per-tool token costs |
| `/status` | Version, model, account, connectivity |
| `/stats` | Daily usage, session history |
| `/todos` | Current TODO items tracked in session |
| `/tasks` | Background tasks and agents |
| `/bashes` | Background shell processes |
| `/help` | Available commands |
| `/doctor` | Installation health check |
| `/debug` | Session debug log |
| `/ide` | IDE integration status |
| `/release-notes` | Version release notes |

Default `BLOCKED` (32 commands):

| Command | Description | Block Reason |
|---------|-------------|-------------|
| `/clear` | Clear conversation history | destructive |
| `/exit` | Exit Claude Code | session_terminating |
| `/resume` | Resume previous conversation | interactive |
| `/rewind` | Rewind conversation/code changes | destructive |
| `/teleport` | Resume remote session locally | session_handoff |
| `/desktop` | Hand off to Desktop app | session_handoff |
| `/fork` | Branch conversation | session_altering |
| `/rename` | Name current session | session_altering |
| `/plan` | Enter plan mode | mode_change |
| `/config` | Open Settings interface | config_modification |
| `/model` | Change AI model | config_modification |
| `/permissions` | View/update tool permissions | security_sensitive |
| `/theme` | Change color theme | config_modification |
| `/output-style` | Configure response formatting | config_modification |
| `/vim` | Toggle vim editing mode | config_modification |
| `/terminal-setup` | Install keyboard shortcuts | config_modification |
| `/statusline` | Set up status line UI | config_modification |
| `/sandbox` | Enable sandboxed execution | security_sensitive |
| `/fast` | Toggle fast mode | config_modification |
| `/privacy-settings` | Update privacy settings | security_sensitive |
| `/init` | Initialize project with CLAUDE.md | project_modification |
| `/memory` | Open CLAUDE.md editor | interactive |
| `/add-dir` | Add working directories | scope_change |
| `/review` | Request code review | triggers_analysis |
| `/pr-comments` | View PR comments | context_dependent |
| `/install-github-app` | Set up GitHub Actions | external_integration |
| `/agents` | Manage subagents | interactive |
| `/hooks` | Configure hooks | config_modification |
| `/plugin` | Plugin management | interactive |
| `/login` | Log in or switch accounts | authentication |
| `/logout` | Sign out | authentication |
| `/upgrade` | Upgrade subscription | financial |
| `/passes` | Manage guest passes | account_management |
| `/bug` | Report bug to Anthropic | external_communication |
| `/remote-env` | Configure remote environment | config_modification |
| `/migrate-installer` | Migrate installation | system_modification |
| `/export` | Export conversation to file | file_write |
| `/copy` | Copy response to clipboard | low_risk_but_unnecessary |

**Blocked Response:**

When the agent calls `velle_query` with a blocked command, Velle does NOT inject anything. Instead it returns:

```json
{
  "status": "blocked",
  "command": "/exit",
  "block_reason": "session_terminating",
  "message": "Command /exit is blocked (reason: session_terminating). Use velle_configure to change command permissions.",
  "timestamp": "ISO-8601"
}
```

This allows the agent to gracefully handle blocked commands without any side effects.

**Errors:**

| Code | Condition |
|------|-----------|
| `COMMAND_BLOCKED` | Command is in the registry but status is BLOCKED (returns block reason) |
| `COMMAND_UNKNOWN` | Command is not in the registry at all |
| `INJECTION_FAILED` | Could not write to Claude Code stdin |
| `FOLLOW_UP_FAILED` | Command injected but follow-up injection failed |

### `velle_status`

Check current autonomy session state.

**Parameters:** None

**Returns:**

```json
{
  "active": true,
  "turn_count": 3,
  "turn_limit": 20,
  "session_start": "ISO-8601",
  "prompts_log": [
    {"turn": 1, "text_preview": "Check MemoryGate for...", "reason": "session_init", "timestamp": "..."},
    {"turn": 2, "text_preview": "Execute task...", "reason": "task_execution", "timestamp": "..."}
  ]
}
```

### `velle_configure`

Update guardrail settings for the current session.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `turn_limit` | integer | no | Maximum self-prompt turns (default: 20) |
| `cooldown_ms` | integer | no | Minimum delay between prompts in ms (default: 1000) |
| `budget_usd` | float | no | Maximum estimated cost in USD (default: 5.00) |
| `audit_mode` | string | no | Where to log audit trail: "memorygate", "local", "both" (default: "both") |
| `set_command_status` | object | no | Change command statuses. Keys are command names, values are "ALLOWED" or "BLOCKED". Example: `{"/fast": "ALLOWED", "/compact": "BLOCKED"}` |

**Example — enable `/fast` and `/export`:**

```json
{
  "set_command_status": {
    "/fast": "ALLOWED",
    "/export": "ALLOWED"
  }
}
```

**Returns:**

```json
{
  "status": "configured",
  "changes": [
    {"command": "/fast", "previous": "BLOCKED", "new": "ALLOWED"},
    {"command": "/export", "previous": "BLOCKED", "new": "ALLOWED"}
  ],
  "current_config": {
    "turn_limit": 20,
    "cooldown_ms": 1000,
    "budget_usd": 5.00,
    "audit_mode": "both",
    "commands_allowed": 17,
    "commands_blocked": 30
  },
  "timestamp": "ISO-8601"
}
```

## Command Registry

### Data Structure

The command registry is a dictionary mapping command names to their metadata. It is initialized at server startup with every known command and its default status.

```python
COMMAND_REGISTRY = {
    # --- ALLOWED by default (15) ---
    "/compact":       {"status": "ALLOWED", "description": "Trigger manual context compaction", "category": "operational"},
    "/context":       {"status": "ALLOWED", "description": "Token usage breakdown", "category": "informational"},
    "/cost":          {"status": "ALLOWED", "description": "Session cost and token statistics", "category": "informational"},
    "/usage":         {"status": "ALLOWED", "description": "Plan limits and rate limit status", "category": "informational"},
    "/mcp":           {"status": "ALLOWED", "description": "MCP server and tool status", "category": "informational"},
    "/status":        {"status": "ALLOWED", "description": "Version, model, account, connectivity", "category": "informational"},
    "/stats":         {"status": "ALLOWED", "description": "Daily usage and session history", "category": "informational"},
    "/todos":         {"status": "ALLOWED", "description": "Current TODO items", "category": "informational"},
    "/tasks":         {"status": "ALLOWED", "description": "Background tasks and agents", "category": "informational"},
    "/bashes":        {"status": "ALLOWED", "description": "Background shell processes", "category": "informational"},
    "/help":          {"status": "ALLOWED", "description": "Available commands", "category": "informational"},
    "/doctor":        {"status": "ALLOWED", "description": "Installation health check", "category": "informational"},
    "/debug":         {"status": "ALLOWED", "description": "Session debug log", "category": "informational"},
    "/ide":           {"status": "ALLOWED", "description": "IDE integration status", "category": "informational"},
    "/release-notes": {"status": "ALLOWED", "description": "Version release notes", "category": "informational"},

    # --- BLOCKED by default (32) ---
    "/clear":              {"status": "BLOCKED", "description": "Clear conversation history", "category": "session", "block_reason": "destructive"},
    "/exit":               {"status": "BLOCKED", "description": "Exit Claude Code", "category": "session", "block_reason": "session_terminating"},
    "/resume":             {"status": "BLOCKED", "description": "Resume previous conversation", "category": "session", "block_reason": "interactive"},
    "/rewind":             {"status": "BLOCKED", "description": "Rewind conversation/code changes", "category": "session", "block_reason": "destructive"},
    "/teleport":           {"status": "BLOCKED", "description": "Resume remote session locally", "category": "session", "block_reason": "session_handoff"},
    "/desktop":            {"status": "BLOCKED", "description": "Hand off to Desktop app", "category": "session", "block_reason": "session_handoff"},
    "/fork":               {"status": "BLOCKED", "description": "Branch conversation", "category": "session", "block_reason": "session_altering"},
    "/rename":             {"status": "BLOCKED", "description": "Name current session", "category": "session", "block_reason": "session_altering"},
    "/plan":               {"status": "BLOCKED", "description": "Enter plan mode", "category": "session", "block_reason": "mode_change"},
    "/config":             {"status": "BLOCKED", "description": "Open Settings interface", "category": "config", "block_reason": "config_modification"},
    "/model":              {"status": "BLOCKED", "description": "Change AI model", "category": "config", "block_reason": "config_modification"},
    "/permissions":        {"status": "BLOCKED", "description": "View/update tool permissions", "category": "config", "block_reason": "security_sensitive"},
    "/theme":              {"status": "BLOCKED", "description": "Change color theme", "category": "config", "block_reason": "config_modification"},
    "/output-style":       {"status": "BLOCKED", "description": "Configure response formatting", "category": "config", "block_reason": "config_modification"},
    "/vim":                {"status": "BLOCKED", "description": "Toggle vim editing mode", "category": "config", "block_reason": "config_modification"},
    "/terminal-setup":     {"status": "BLOCKED", "description": "Install keyboard shortcuts", "category": "config", "block_reason": "config_modification"},
    "/statusline":         {"status": "BLOCKED", "description": "Set up status line UI", "category": "config", "block_reason": "config_modification"},
    "/sandbox":            {"status": "BLOCKED", "description": "Enable sandboxed execution", "category": "config", "block_reason": "security_sensitive"},
    "/fast":               {"status": "BLOCKED", "description": "Toggle fast mode", "category": "config", "block_reason": "config_modification"},
    "/privacy-settings":   {"status": "BLOCKED", "description": "Update privacy settings", "category": "config", "block_reason": "security_sensitive"},
    "/init":               {"status": "BLOCKED", "description": "Initialize project with CLAUDE.md", "category": "project", "block_reason": "project_modification"},
    "/memory":             {"status": "BLOCKED", "description": "Open CLAUDE.md editor", "category": "project", "block_reason": "interactive"},
    "/add-dir":            {"status": "BLOCKED", "description": "Add working directories", "category": "project", "block_reason": "scope_change"},
    "/review":             {"status": "BLOCKED", "description": "Request code review", "category": "workflow", "block_reason": "triggers_analysis"},
    "/pr-comments":        {"status": "BLOCKED", "description": "View PR comments", "category": "workflow", "block_reason": "context_dependent"},
    "/install-github-app": {"status": "BLOCKED", "description": "Set up GitHub Actions", "category": "integration", "block_reason": "external_integration"},
    "/agents":             {"status": "BLOCKED", "description": "Manage subagents", "category": "integration", "block_reason": "interactive"},
    "/hooks":              {"status": "BLOCKED", "description": "Configure hooks", "category": "integration", "block_reason": "config_modification"},
    "/plugin":             {"status": "BLOCKED", "description": "Plugin management", "category": "integration", "block_reason": "interactive"},
    "/login":              {"status": "BLOCKED", "description": "Log in or switch accounts", "category": "account", "block_reason": "authentication"},
    "/logout":             {"status": "BLOCKED", "description": "Sign out", "category": "account", "block_reason": "authentication"},
    "/upgrade":            {"status": "BLOCKED", "description": "Upgrade subscription", "category": "account", "block_reason": "financial"},
    "/passes":             {"status": "BLOCKED", "description": "Manage guest passes", "category": "account", "block_reason": "account_management"},
    "/bug":                {"status": "BLOCKED", "description": "Report bug to Anthropic", "category": "reporting", "block_reason": "external_communication"},
    "/remote-env":         {"status": "BLOCKED", "description": "Configure remote environment", "category": "config", "block_reason": "config_modification"},
    "/migrate-installer":  {"status": "BLOCKED", "description": "Migrate installation", "category": "system", "block_reason": "system_modification"},
    "/export":             {"status": "BLOCKED", "description": "Export conversation to file", "category": "output", "block_reason": "file_write"},
    "/copy":               {"status": "BLOCKED", "description": "Copy response to clipboard", "category": "output", "block_reason": "low_risk_but_unnecessary"},
}
```

### Behavior

- **Known command, ALLOWED**: Velle executes the two-step injection (command + follow-up)
- **Known command, BLOCKED**: Velle returns `COMMAND_BLOCKED` with the `block_reason` from the registry. Nothing is injected.
- **Unknown command**: Velle returns `COMMAND_UNKNOWN`. Nothing is injected. This handles new commands added in future Claude Code versions that haven't been classified yet.

### Runtime Modification

`velle_configure(set_command_status={...})` updates the registry in memory for the current session. Changes do not persist across sessions. A future configuration file could make persistent overrides possible.

## Stdin Injection (Windows)

### Mechanism

On Windows, the injection uses the Win32 API to write to the console input buffer of the parent Claude Code process.

### Implementation

```
1. Get parent process ID (Claude Code)
   - MCP server is a child process of Claude Code
   - Use os.getppid() or psutil to walk process tree

2. Get console input handle
   - AttachConsole(pid) or use inherited console
   - GetStdHandle(STD_INPUT_HANDLE)

3. Write input records
   - Convert text to INPUT_RECORD array (KEY_EVENT type)
   - WriteConsoleInput(handle, records)
   - Append Enter key event

4. Detach
   - FreeConsole() if attached
```

### Key Win32 Functions

| Function | Purpose |
|----------|---------|
| `AttachConsole(pid)` | Attach to parent's console |
| `GetStdHandle(STD_INPUT_HANDLE)` | Get console input handle |
| `WriteConsoleInput(handle, records, count)` | Write key events to input buffer |
| `FreeConsole()` | Detach from console |

### Fallback: Named Pipe

If direct console injection is unreliable, an alternative approach:

1. Velle creates a named pipe on startup
2. A companion hook monitors the pipe
3. When the MCP tool writes to the pipe, the hook reads it and outputs to stdout
4. Claude Code receives it through the hook's stdout injection

### Cross-Platform Considerations

- **Windows**: `WriteConsoleInput` via `ctypes` or `pywin32`
- **Linux**: Write to `/proc/{pid}/fd/0` (stdin file descriptor)
- **macOS**: Similar to Linux, or use `osascript` for terminal input

Initial implementation targets Windows. Linux/macOS support is a future goal.

## Guardrails

### Turn Limit

- Default: 20 turns per autonomous session
- Configurable via `velle_configure`
- When reached: tool returns `TURN_LIMIT_REACHED` error
- Agent receives the error and should gracefully stop or request human input

### Cost Budget

- Default: $5.00 per autonomous session
- Initial estimate is a rough heuristic based on turn count and average tokens per turn
- When exceeded: tool returns `BUDGET_EXCEEDED` error

**Cost Self-Monitoring Pattern (first-class):**

The agent can bootstrap accurate budget tracking by querying its own cost:

```
1. Agent calls velle_query("/cost", follow_up="Report current cost and continue")
2. Agent reads /cost output → learns actual session cost (e.g., $2.37)
3. Agent reports cost to Velle via velle_status or includes in next velle_prompt reason
4. Velle updates internal budget tracking with real numbers
```

This creates a feedback loop: Velle enables the query, the query informs Velle's guardrails. The heuristic is the bootstrap; `/cost` is the steady state.

### Cooldown

- Default: 1000ms between self-prompts
- Prevents tight loops that burn through context
- Configurable down to 200ms minimum

### Scope Boundaries (v2)

**Not implemented in v1.** The v1 release operates in `full` scope only — no restrictions beyond Claude Code's normal permission model. Turn limits, cost budget, and the MemoryGate audit trail are the real governance mechanisms.

Scope enforcement without teeth creates false confidence. Future versions may add scope modes (`task_only`, `read_only`) if a reliable enforcement mechanism is identified — likely through Claude Code's permission hooks or prompt-level constraints. Until then, the audit trail is the governance layer: every action is logged, every action is reviewable.

### Audit Trail

Every `velle_prompt` and `velle_query` call is logged. The audit record includes:

- Timestamp
- Turn number
- Tool called (`velle_prompt` or `velle_query`)
- Full prompt text or command
- Reason (if provided)
- Session ID
- Outcome (success/blocked/error)

**Audit modes** (configurable via `velle_configure`):

| Mode | Behavior |
|------|----------|
| `memorygate` | Log to MemoryGate only. Fails if MemoryGate is unavailable — Velle refuses to operate. |
| `local` | Log to a local JSON file (`velle_audit.jsonl` in project root). No MemoryGate dependency. |
| `both` | **(Default)** Log to both MemoryGate and local file. If MemoryGate is unavailable, Velle continues operating with local-only logging and logs a warning. |

The `both` default ensures Velle is not fragile to a MemoryGate connection drop. The local audit file provides a fallback record that can be ingested into MemoryGate later when the connection is restored.

Local audit format (one JSON object per line):

```json
{"timestamp": "ISO-8601", "turn": 3, "tool": "velle_prompt", "text": "Continue with phase 2", "reason": "workflow", "session_id": "...", "outcome": "injected"}
```

## Client-Layer Introspection

### How It Works

Claude Code's slash commands are processed by the client, not the API. When a slash command executes, its output is injected into the conversation as a `<local-command-stdout>` block, which the agent can read on its next turn. The client also adds a `<local-command-caveat>` advising the agent not to respond to the output unless the user asks — but when the agent itself initiated the query via Velle, it knows to process the output.

### Two-Step Injection Flow

Slash commands require two injections: the command itself, then a follow-up prompt to give the agent a turn. Velle handles both automatically.

```
Agent calls velle_query("/context")
  → Step 1 (T+0ms): Velle injects "/context" to stdin
    → Claude Code client processes /context
    → Client outputs results to conversation:
        <local-command-caveat>...</local-command-caveat>
        <command-name>/context</command-name>
        <local-command-stdout>
          claude-opus-4-6 · 73k/200k tokens (37%)
          ...
        </local-command-stdout>
  → Step 2 (T+3000ms): Velle injects follow-up prompt to stdin
    → Agent receives new turn
    → Agent sees /context output AND the follow-up instruction
    → Agent now knows: 37% used, 63% free, autocompact at 33k
```

### Self-Monitoring Pattern

Using `velle_query`, the agent can implement a context-aware autonomous loop:

```
1. Agent does work
2. Agent calls velle_query("/context", follow_up="Check context usage and continue working")
3. Velle injects /context, waits, then injects the follow-up
4. Next turn: agent reads /context output
5. If context > 70%: checkpoint to MemoryGate, then velle_query("/compact", follow_up="Context compacted. Continue.")
6. If context > 85%: save everything to MemoryGate and gracefully exit
7. If context healthy: continue working, call velle_prompt() for next step
```

### Proactive Compaction Pattern

The agent can manage its own context lifecycle:

```
1. Agent calls velle_query("/context") → learns it's at 72%
2. Agent saves critical state to MemoryGate chain
3. Agent calls velle_query("/compact", follow_up="Compaction complete. Load chain [id] and resume.")
4. /compact reclaims context space
5. Follow-up prompt triggers agent to reload state and continue with fresh context
```

This is the self-monitoring capability that was previously impossible — the agent adapts its behavior based on its own resource consumption and actively manages its context window.

### Discoverable Commands

The set of available slash commands may vary across Claude Code versions. The agent can discover what's available by examining command output or through documentation. Velle's whitelist ensures only safe, read-only commands are exposed by default.

## Integration Points

### MemoryGate

- **Task queue**: Agent reads pending tasks from MemoryGate at session start
- **Workflow state**: Agent checkpoints progress to memory chains between self-prompts
- **Audit log**: Every self-prompt is recorded as an observation
- **Results**: Agent stores completed work back to MemoryGate

### Claude Code Hooks

- **SessionStart**: Can load initial task from MemoryGate and inject as first prompt
- **PostToolUse**: Could monitor Velle calls for additional validation
- Hooks complement Velle — hooks handle event-driven triggers, Velle handles agent-driven continuation

### Windows Task Scheduler

- External scheduler starts Claude Code sessions on a schedule or trigger
- SessionStart hook loads tasks, agent uses Velle to self-drive through them
- Agent stores results and exits when work is complete

## Session Lifecycle

```
1. INITIATION
   - Task Scheduler starts Claude Code (or human starts it)
   - SessionStart hook checks MemoryGate for pending tasks
   - Hook outputs task instructions to stdout
   - Agent receives initial prompt

2. AUTONOMOUS LOOP
   - Agent works on task
   - Agent calls velle_prompt() with next step
   - Velle injects, agent receives new turn
   - Repeat until task complete or guardrail hit

3. COMPLETION
   - Agent stores results to MemoryGate
   - Agent calls velle_prompt("Session complete. No further tasks.")
   - Or: turn limit reached, agent exits gracefully
   - Or: human interrupts with Ctrl+C

4. REVIEW
   - Human reviews audit trail in MemoryGate
   - Human reviews outputs in filesystem
   - Adjusts task queue for next autonomous session
```

## File Structure

```
Velle/
├── README.md                  # Project overview
├── SPEC.md                    # This file
├── COMMANDS.md                # Full slash command registry reference
├── pyproject.toml             # Python project config
├── spike/
│   └── inject_test.py         # Phase 0: standalone stdin injection test
├── src/
│   └── velle/
│       ├── __init__.py
│       ├── server.py          # MCP server entry point
│       ├── tools.py           # Tool definitions (velle_prompt, velle_query, velle_status, velle_configure)
│       ├── injector.py        # Stdin injection (Win32 API)
│       ├── registry.py        # Command registry (ALLOWED/BLOCKED for all 47 commands)
│       ├── guardrails.py      # Turn limits, budget, cooldown
│       └── audit.py           # Audit logging (MemoryGate + local fallback)
└── tests/
    ├── test_injector.py
    ├── test_registry.py
    ├── test_guardrails.py
    └── test_tools.py
```

## Build Plan

### Phase 0: Injection Spike (do this first)

Everything depends on stdin injection working. Before writing any tool logic, build a minimal proof of concept:

1. Standalone Python script (not yet an MCP server)
2. Gets parent PID
3. Injects "hello world" into parent's console stdin via `WriteConsoleInput`
4. Run it as a subprocess from a terminal and confirm the text appears

If `WriteConsoleInput` works from a child process sharing the parent's console, proceed to Phase 1. If it requires `AttachConsole`, test that path. If neither works, evaluate the named pipe fallback — which changes the architecture to a two-component system (MCP server + companion hook).

### Phase 1: Minimal MCP Server

- `velle_prompt` only — no query, no guardrails
- Inject text to parent stdin
- Confirm Claude Code receives it as user input and responds

### Phase 2: Guardrails + Audit

- Turn counter, cooldown, budget heuristic
- Local audit file (`velle_audit.jsonl`)
- MemoryGate logging with fallback

### Phase 3: Client Introspection

- `velle_query` with two-step injection
- Command registry with ALLOWED/BLOCKED
- `velle_configure` for runtime changes
- `velle_status` for session state

### Phase 4: Integration

- SessionStart hook for MemoryGate task loading
- Cost self-monitoring feedback loop
- Documentation and examples

## Open Questions

1. **Console sharing**: The MCP server runs as a child process. Does it share the parent's console, or does it need to explicitly attach? This is the Phase 0 spike. If the child inherits the console handle, injection is straightforward. If not, `AttachConsole(pid)` is required. If neither works, the named pipe fallback becomes necessary.

2. **Claude Code stdin processing model**: Does Claude Code read stdin continuously or only between turns? If between turns, injection is naturally queued and timing is a non-issue. If continuous, injected text during a response could cause interleaving. The Phase 0 spike will reveal this.

3. **Multi-session coordination**: If Task Scheduler starts multiple Claude Code sessions, each has its own Velle instance. MemoryGate task queue needs to handle concurrent access — likely through a claim/lock pattern on task chain entries.

4. **`<local-command-caveat>` handling**: When Velle injects a slash command, the output arrives with a caveat telling the agent to ignore it. The agent needs to know it initiated the query and should process the output. The follow-up prompt in `velle_query` should include context like "You requested this via Velle — process the output above."

### Resolved Questions

- ~~**Timing/response boundaries**~~: Addressed in the injection sequence documentation. MCP tool result returns before injection; agent completes its turn before stdin is read. The `delay_ms` is a safety margin for client command processing, not for turn boundaries.
- ~~**Token estimation**~~: Promoted to first-class Cost Self-Monitoring Pattern. Agent uses `velle_query("/cost")` to get real numbers and bootstrap accurate tracking.
- ~~**Scope enforcement**~~: Deferred to v2. V1 is `full` scope only. Audit trail is the governance mechanism.
