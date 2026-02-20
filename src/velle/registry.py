"""Command registry for Claude Code slash commands.

Maps every known command to its status (ALLOWED/BLOCKED) and metadata.
Source of truth: docs/COMMANDS.md (12 ALLOWED, 32 BLOCKED, 3 NOT_FOUND).
"""

from typing import Any


# Status constants
ALLOWED = "ALLOWED"
BLOCKED = "BLOCKED"
NOT_FOUND = "NOT_FOUND"


def _cmd(status: str, description: str, block_reason: str = "") -> dict[str, Any]:
    return {"status": status, "description": description, "block_reason": block_reason}


# Full registry from COMMANDS.md
COMMAND_REGISTRY: dict[str, dict[str, Any]] = {
    # Session Management
    "/clear": _cmd(BLOCKED, "Clear conversation history and start fresh", "destructive"),
    "/compact": _cmd(ALLOWED, "Compact conversation to free context"),
    "/exit": _cmd(BLOCKED, "Exit the Claude Code REPL", "session_terminating"),
    "/resume": _cmd(BLOCKED, "Resume a previous conversation", "interactive"),
    "/rename": _cmd(BLOCKED, "Give the current session a name", "session_altering"),
    "/rewind": _cmd(BLOCKED, "Rewind conversation and/or code changes", "destructive"),
    "/plan": _cmd(BLOCKED, "Enter plan mode", "mode_change"),
    "/teleport": _cmd(BLOCKED, "Resume a remote session locally", "session_handoff"),
    "/desktop": _cmd(BLOCKED, "Hand off session to Desktop app", "session_handoff"),
    "/fork": _cmd(BLOCKED, "Branch conversation into a new session", "session_altering"),

    # Information and Diagnostics
    "/help": _cmd(BLOCKED, "Show all available commands", "interactive"),
    "/cost": _cmd(BLOCKED, "Show token usage statistics", "does_not_exist"),
    "/context": _cmd(ALLOWED, "Visualize context window usage"),
    "/status": _cmd(ALLOWED, "Show version, model, account, connectivity"),
    "/stats": _cmd(ALLOWED, "Visualize daily usage, session history"),
    "/usage": _cmd(ALLOWED, "Show plan usage limits and rate limits"),
    "/doctor": _cmd(ALLOWED, "Check installation health"),
    "/debug": _cmd(ALLOWED, "Read session debug log"),
    "/release-notes": _cmd(ALLOWED, "View release notes"),

    # Configuration and Settings
    "/config": _cmd(BLOCKED, "Open interactive Settings interface", "config_modification"),
    "/model": _cmd(BLOCKED, "Change AI model", "config_modification"),
    "/permissions": _cmd(BLOCKED, "View or update tool permissions", "security_sensitive"),
    "/theme": _cmd(BLOCKED, "Change color theme", "config_modification"),
    "/output-style": _cmd(BLOCKED, "Configure response formatting", "config_modification"),
    "/vim": _cmd(BLOCKED, "Toggle vim editing mode", "config_modification"),
    "/terminal-setup": _cmd(BLOCKED, "Install keyboard shortcuts", "config_modification"),
    "/statusline": _cmd(BLOCKED, "Set up status line UI", "config_modification"),
    "/sandbox": _cmd(BLOCKED, "Enable sandboxed bash execution", "security_sensitive"),
    "/fast": _cmd(BLOCKED, "Toggle fast mode", "config_modification"),
    "/privacy-settings": _cmd(BLOCKED, "View and update privacy settings", "security_sensitive"),

    # Project and Memory
    "/init": _cmd(BLOCKED, "Initialize project with CLAUDE.md", "project_modification"),
    "/memory": _cmd(BLOCKED, "Open CLAUDE.md editor", "interactive"),
    "/add-dir": _cmd(BLOCKED, "Add working directories", "scope_change"),
    "/todos": _cmd(ALLOWED, "Show current TODO items"),

    # Development Workflow
    "/review": _cmd(BLOCKED, "Request code review of recent changes", "triggers_analysis"),
    "/pr-comments": _cmd(BLOCKED, "View pull request comments", "context_dependent"),
    "/install-github-app": _cmd(BLOCKED, "Set up GitHub Actions integration", "external_integration"),

    # Tools and Integrations
    "/mcp": _cmd(BLOCKED, "Manage MCP server connections", "interactive"),
    "/ide": _cmd(ALLOWED, "View IDE integrations and status"),
    "/agents": _cmd(BLOCKED, "Manage custom subagents", "interactive"),
    "/hooks": _cmd(BLOCKED, "Configure hooks", "config_modification"),
    "/plugin": _cmd(BLOCKED, "Plugin management interface", "interactive"),

    # Account Management
    "/login": _cmd(BLOCKED, "Log in or switch accounts", "authentication"),
    "/logout": _cmd(BLOCKED, "Sign out", "authentication"),
    "/upgrade": _cmd(BLOCKED, "Upgrade subscription", "financial"),
    "/passes": _cmd(BLOCKED, "Manage guest passes", "account_management"),

    # Export and Output
    "/export": _cmd(BLOCKED, "Export conversation to file/clipboard", "file_write"),
    "/copy": _cmd(BLOCKED, "Copy last response to clipboard", "low_risk_but_unnecessary"),

    # Background Tasks
    "/tasks": _cmd(ALLOWED, "List and manage background tasks"),
    "/bashes": _cmd(ALLOWED, "List and manage background shells"),

    # Reporting
    "/bug": _cmd(BLOCKED, "Report a bug to Anthropic", "external_communication"),

    # Remote Sessions
    "/remote-env": _cmd(BLOCKED, "Configure remote environment", "config_modification"),

    # Migration
    "/migrate-installer": _cmd(BLOCKED, "Migrate from npm to local install", "system_modification"),
}


def get_command(name: str) -> dict[str, Any] | None:
    """Look up a command in the registry. Returns None if not found."""
    # Normalize: ensure leading slash
    if not name.startswith("/"):
        name = "/" + name
    return COMMAND_REGISTRY.get(name)


def is_allowed(name: str) -> bool:
    """Check if a command is allowed for injection."""
    cmd = get_command(name)
    return cmd is not None and cmd["status"] == ALLOWED


def set_status(name: str, status: str) -> bool:
    """Update a command's status in-memory. Returns True if command exists."""
    if not name.startswith("/"):
        name = "/" + name
    if name not in COMMAND_REGISTRY:
        return False
    COMMAND_REGISTRY[name]["status"] = status
    return True
