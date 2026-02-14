# Claude Code Slash Commands Reference

Complete inventory of Claude Code CLI slash commands for the Velle command registry.

Every command is enumerated with an explicit status: **ALLOWED** or **BLOCKED**. There is no ambiguous middle tier. The agent can request any command — if it's blocked, Velle returns an informative response without injecting anything. Users can change any command's status at runtime via `velle_configure`.

## Session Management

| Command | Aliases | Description | Status | Block Reason |
|---------|---------|-------------|--------|-------------|
| `/clear` | `reset`, `new` | Clear conversation history and start fresh | BLOCKED | destructive |
| `/compact [instructions]` | | Compact conversation to free context; optional focus instructions | ALLOWED | — |
| `/exit` | `quit` | Exit the Claude Code REPL | BLOCKED | session_terminating |
| `/resume [session]` | | Resume a previous conversation by ID or name | BLOCKED | interactive |
| `/rename <name>` | | Give the current session a name | BLOCKED | session_altering |
| `/rewind` | | Rewind conversation and/or code changes | BLOCKED | destructive |
| `/plan` | | Enter plan mode (read-only analysis) | BLOCKED | mode_change |
| `/teleport` | | Resume a remote session locally | BLOCKED | session_handoff |
| `/desktop` | | Hand off session to Desktop app | BLOCKED | session_handoff |
| `/fork` | | Branch conversation into a new session | BLOCKED | session_altering |

## Information and Diagnostics

| Command | Description | Status | Block Reason |
|---------|-------------|--------|-------------|
| `/help` | Show all available commands | BLOCKED | interactive |
| `/cost` | Show token usage statistics | BLOCKED | does_not_exist |
| `/context` | Visualize context window usage | ALLOWED | — |
| `/status` | Show version, model, account, connectivity | ALLOWED | — |
| `/stats` | Visualize daily usage, session history | ALLOWED | — |
| `/usage` | Show plan usage limits and rate limits | ALLOWED | — |
| `/doctor` | Check installation health | ALLOWED | — |
| `/debug [description]` | Read session debug log | ALLOWED | — |
| `/release-notes` | View release notes | ALLOWED | — |

## Configuration and Settings

| Command | Aliases | Description | Status | Block Reason |
|---------|---------|-------------|--------|-------------|
| `/config` | `settings` | Open interactive Settings interface | BLOCKED | config_modification |
| `/model` | | Change AI model | BLOCKED | config_modification |
| `/permissions` | `allowed-tools` | View or update tool permissions | BLOCKED | security_sensitive |
| `/theme` | | Change color theme | BLOCKED | config_modification |
| `/output-style` | | Configure response formatting | BLOCKED | config_modification |
| `/vim` | | Toggle vim editing mode | BLOCKED | config_modification |
| `/terminal-setup` | | Install keyboard shortcuts | BLOCKED | config_modification |
| `/statusline` | | Set up status line UI | BLOCKED | config_modification |
| `/sandbox` | | Enable sandboxed bash execution | BLOCKED | security_sensitive |
| `/fast` | | Toggle fast mode | BLOCKED | config_modification |
| `/privacy-settings` | | View and update privacy settings | BLOCKED | security_sensitive |

## Project and Memory

| Command | Description | Status | Block Reason |
|---------|-------------|--------|-------------|
| `/init` | Initialize project with CLAUDE.md | BLOCKED | project_modification |
| `/memory` | Open CLAUDE.md editor | BLOCKED | interactive |
| `/add-dir` | Add working directories | BLOCKED | scope_change |
| `/todos` | Show current TODO items | ALLOWED | — |

## Development Workflow

| Command | Description | Status | Block Reason |
|---------|-------------|--------|-------------|
| `/review` | Request code review of recent changes | BLOCKED | triggers_analysis |
| `/pr-comments` | View pull request comments | BLOCKED | context_dependent |
| `/install-github-app` | Set up GitHub Actions integration | BLOCKED | external_integration |

## Tools and Integrations

| Command | Description | Status | Block Reason |
|---------|-------------|--------|-------------|
| `/mcp` | Manage MCP server connections | BLOCKED | interactive |
| `/ide` | View IDE integrations and status | ALLOWED | — |
| `/agents` | Manage custom subagents | BLOCKED | interactive |
| `/hooks` | Configure hooks | BLOCKED | config_modification |
| `/plugin` | Plugin management interface | BLOCKED | interactive |

## Account Management

| Command | Description | Status | Block Reason |
|---------|-------------|--------|-------------|
| `/login` | Log in or switch accounts | BLOCKED | authentication |
| `/logout` | Sign out | BLOCKED | authentication |
| `/upgrade` | Upgrade subscription | BLOCKED | financial |
| `/passes` | Manage guest passes | BLOCKED | account_management |

## Export and Output

| Command | Description | Status | Block Reason |
|---------|-------------|--------|-------------|
| `/export [filename]` | Export conversation to file/clipboard | BLOCKED | file_write |
| `/copy` | Copy last response to clipboard | BLOCKED | low_risk_but_unnecessary |

## Background Tasks

| Command | Description | Status | Block Reason |
|---------|-------------|--------|-------------|
| `/tasks` | List and manage background tasks | ALLOWED | — |
| `/bashes` | List and manage background shells | ALLOWED | — |

## Reporting

| Command | Description | Status | Block Reason |
|---------|-------------|--------|-------------|
| `/bug` | Report a bug to Anthropic | BLOCKED | external_communication |

## Remote Sessions

| Command | Description | Status | Block Reason |
|---------|-------------|--------|-------------|
| `/remote-env` | Configure remote environment | BLOCKED | config_modification |

## Migration

| Command | Description | Status | Block Reason |
|---------|-------------|--------|-------------|
| `/migrate-installer` | Migrate from npm to local install | BLOCKED | system_modification |

## Input Prefixes (Not Slash Commands)

These are input prefixes, not slash commands. Not part of the command registry but noted for completeness.

| Prefix | Description | Velle Relevance |
|--------|-------------|-----------------|
| `!` | Bash mode — run shell commands directly | Could be used with `velle_prompt` to execute shell commands as user input |
| `@` | File path mention — triggers autocomplete | Could be used to reference files in self-prompts |

## Summary

| Status | Count | Commands |
|--------|-------|----------|
| ALLOWED | 12 | `/compact`, `/context`, `/usage`, `/status`, `/stats`, `/todos`, `/tasks`, `/bashes`, `/doctor`, `/debug`, `/ide`, `/release-notes` |
| BLOCKED | 32 | `/clear`, `/exit`, `/resume`, `/rewind`, `/teleport`, `/desktop`, `/fork`, `/rename`, `/plan`, `/config`, `/model`, `/permissions`, `/theme`, `/output-style`, `/vim`, `/terminal-setup`, `/statusline`, `/sandbox`, `/fast`, `/privacy-settings`, `/init`, `/memory`, `/add-dir`, `/review`, `/pr-comments`, `/install-github-app`, `/agents`, `/hooks`, `/plugin`, `/login`, `/logout`, `/upgrade`, `/passes`, `/bug`, `/remote-env`, `/migrate-installer`, `/export`, `/copy` |
| **Total** | **47** | |

## Block Reason Taxonomy

| Reason | Meaning |
|--------|---------|
| `destructive` | Irreversibly destroys data or state |
| `session_terminating` | Ends the session |
| `session_handoff` | Transfers session to another environment |
| `session_altering` | Changes session identity or structure |
| `mode_change` | Switches interaction mode |
| `interactive` | Requires interactive UI that stdin injection can't drive |
| `config_modification` | Changes Claude Code configuration |
| `security_sensitive` | Affects permissions, sandboxing, or privacy |
| `project_modification` | Creates or modifies project files |
| `scope_change` | Expands agent's working scope |
| `triggers_analysis` | Triggers potentially expensive analysis |
| `context_dependent` | Behavior depends on external context (PRs, etc.) |
| `external_integration` | Modifies integrations with external services |
| `authentication` | Affects login/authentication state |
| `financial` | Triggers financial actions |
| `account_management` | Modifies account settings |
| `external_communication` | Sends data to external parties |
| `system_modification` | Modifies system-level installation |
| `file_write` | Writes files to disk |
| `low_risk_but_unnecessary` | Not harmful but no autonomous use case |
