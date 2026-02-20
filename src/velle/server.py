"""
Velle MCP Server.

Exposes self-prompting and client introspection tools to Claude Code
via the Model Context Protocol.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from velle.injector import (
    ConsoleNotAvailable,
    InjectionError,
    check_console,
    inject,
)
from velle.audit import audit_log as _audit_log_impl
from velle.guardrails import check_budget, check_cooldown, check_turn_limit
from velle.registry import (
    ALLOWED,
    BLOCKED,
    COMMAND_REGISTRY,
    get_command,
    is_allowed,
    set_status,
)

logger = logging.getLogger("velle")

# Config file path — lives next to the project root
CONFIG_FILE = Path(__file__).parent.parent.parent / "velle.json"

# Default configuration
_DEFAULTS = {
    "turn_limit": 20,
    "cooldown_ms": 1000,
    "budget_usd": 5.00,
    "audit_mode": "both",
    "cost_per_turn": 0.15,
    "sidecar_enabled": False,
    "sidecar_port": 7839,
}


def _load_config() -> dict:
    """Load configuration from velle.json, falling back to defaults."""
    config = dict(_DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            for key in _DEFAULTS:
                if key in user_config:
                    config[key] = user_config[key]
            logger.info(f"Loaded config from {CONFIG_FILE}: {config}")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load config from {CONFIG_FILE}: {e}")
    return config


_config = _load_config()

# Session state — turn_limit comes from config file
_state = {
    "turn_count": 0,
    "turn_limit": _config["turn_limit"],
    "cooldown_ms": _config["cooldown_ms"],
    "budget_usd": _config["budget_usd"],
    "audit_mode": _config["audit_mode"],
    "cost_per_turn": _config["cost_per_turn"],
    "session_start": None,
    "last_prompt_time": None,
    "prompts_log": [],
    "console_available": None,
}

# Audit log file path
AUDIT_FILE = "velle_audit.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_log(entry: dict):
    """Write an audit entry to local file and/or MemoryGate."""
    _audit_log_impl(entry, _state, audit_path=Path(AUDIT_FILE))


def _create_server() -> Server:
    server = Server("velle")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="velle_prompt",
                description=(
                    "Inject text as user input into the current Claude Code session. "
                    "The text will appear as if the user typed it, giving the agent a new turn. "
                    "Use this to create autonomous work loops — decide what to do next, "
                    "call velle_prompt with that instruction, and continue on the next turn.\n\n"
                    "For slash commands, use the follow_up parameter to chain a second injection "
                    "that runs after the command completes, giving the agent a turn to see the output.\n\n"
                    "Allowed slash commands (validated for this Claude Code version):\n"
                    "  /compact - Compact conversation to free context\n"
                    "  /context - Visualize context window usage\n"
                    "  /usage - Show plan usage limits and rate limits\n"
                    "  /status - Show version, model, account, connectivity\n"
                    "  /stats - Visualize daily usage, session history\n"
                    "  /todos - Show active todo items\n"
                    "  /tasks - Show running background tasks\n"
                    "  /bashes - Show running background bash commands\n"
                    "  /doctor - Check installation health\n"
                    "  /debug - Read session debug log\n"
                    "  /ide - Show IDE connection status\n"
                    "  /release-notes - View release notes\n"
                    "Do NOT inject interactive commands (/help, /mcp, /config, etc.) or "
                    "commands that don't exist (/cost)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The text to inject as user input",
                        },
                        "delay_ms": {
                            "type": "integer",
                            "description": "Delay in milliseconds before injection (default: 500). "
                            "The injection happens after the tool returns, so this is a safety margin "
                            "for the agent's response to finish transmitting.",
                            "default": 500,
                        },
                        "follow_up": {
                            "type": "string",
                            "description": "Optional second injection sent after the first. "
                            "Use for slash commands: inject the command first, wait for it to "
                            "complete, then inject the follow_up to start a new agent turn that "
                            "can see the command output. The follow_up is sent after follow_up_delay_ms.",
                        },
                        "follow_up_delay_ms": {
                            "type": "integer",
                            "description": "Delay in milliseconds between the first injection and the "
                            "follow_up injection (default: 3000). Must be long enough for the slash "
                            "command to execute and render its output.",
                            "default": 3000,
                        },
                        "reason": {
                            "type": "string",
                            "description": "Why this self-prompt is being issued (logged to audit trail)",
                        },
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="velle_status",
                description=(
                    "Check the current Velle session state: turn count, limits, "
                    "recent prompt log, and console availability."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="velle_query",
                description=(
                    "Execute a Claude Code slash command with validation. "
                    "Looks up the command in the registry — if BLOCKED, returns "
                    "the block reason without injecting. If ALLOWED, injects the "
                    "command and schedules a follow_up to give the agent a turn "
                    "to see the output."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The slash command to execute (e.g. '/compact', '/status')",
                        },
                        "follow_up": {
                            "type": "string",
                            "description": "Text to inject after the command completes. "
                            "Defaults to a generic 'review output' prompt.",
                            "default": "Review the output of the previous command and continue.",
                        },
                        "delay_ms": {
                            "type": "integer",
                            "description": "Delay before injecting the command (default: 500ms).",
                            "default": 500,
                        },
                        "follow_up_delay_ms": {
                            "type": "integer",
                            "description": "Delay between command injection and follow_up (default: 3000ms).",
                            "default": 3000,
                        },
                        "reason": {
                            "type": "string",
                            "description": "Why this command is being queried.",
                        },
                    },
                    "required": ["command"],
                },
            ),
            Tool(
                name="velle_configure",
                description=(
                    "Update Velle session configuration at runtime. "
                    "Can adjust turn limits, cooldown, budget, audit mode, "
                    "and command registry statuses."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "turn_limit": {
                            "type": "integer",
                            "description": "New turn limit for the session.",
                        },
                        "cooldown_ms": {
                            "type": "integer",
                            "description": "New cooldown between prompts in milliseconds.",
                        },
                        "budget_usd": {
                            "type": "number",
                            "description": "New cost budget in USD.",
                        },
                        "audit_mode": {
                            "type": "string",
                            "enum": ["local", "memorygate", "both"],
                            "description": "Audit logging mode.",
                        },
                        "set_command_status": {
                            "type": "object",
                            "description": "Map of command name → new status (ALLOWED/BLOCKED). "
                            "Example: {\"/review\": \"ALLOWED\"}",
                        },
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "velle_prompt":
            return await _handle_prompt(arguments)
        elif name == "velle_status":
            return await _handle_status(arguments)
        elif name == "velle_query":
            return await _handle_query(arguments)
        elif name == "velle_configure":
            return await _handle_configure(arguments)
        else:
            return [TextContent(type="text", text=json.dumps({
                "status": "error",
                "error": f"Unknown tool: {name}",
            }))]

    return server


async def _handle_prompt(args: dict) -> list[TextContent]:
    """Handle a velle_prompt tool call."""
    text = args.get("text", "")
    delay_ms = args.get("delay_ms", 500)
    follow_up = args.get("follow_up", "")
    follow_up_delay_ms = args.get("follow_up_delay_ms", 3000)
    reason = args.get("reason", "")

    # Initialize session on first call
    if _state["session_start"] is None:
        _state["session_start"] = _now_iso()

    # Check turn limit
    ok, err = check_turn_limit(_state)
    if not ok:
        err["timestamp"] = _now_iso()
        _audit_log({"tool": "velle_prompt", "text": text, "reason": reason,
                     "outcome": "turn_limit_reached"})
        return [TextContent(type="text", text=json.dumps(err))]

    # Check budget
    ok, err = check_budget(_state, cost_per_turn=_state.get("cost_per_turn", 0.15))
    if not ok:
        err["timestamp"] = _now_iso()
        _audit_log({"tool": "velle_prompt", "text": text, "reason": reason,
                     "outcome": "budget_exceeded"})
        return [TextContent(type="text", text=json.dumps(err))]

    # Check cooldown
    ok, err = check_cooldown(_state)
    if not ok:
        err["timestamp"] = _now_iso()
        return [TextContent(type="text", text=json.dumps(err))]

    # Check console availability (check each time since we attach/detach per injection)
    diag = check_console()
    _state["console_available"] = diag["available"]
    if not diag["available"]:
        result = {
            "status": "error",
            "error_code": "CONSOLE_NOT_AVAILABLE",
            "message": f"No console available for injection: {diag['error']}",
            "diagnostics": diag,
            "timestamp": _now_iso(),
        }
        _audit_log({"tool": "velle_prompt", "text": text, "reason": reason,
                     "outcome": "console_not_available"})
        return [TextContent(type="text", text=json.dumps(result))]

    # Schedule the injection after a delay
    async def _delayed_inject():
        await asyncio.sleep(delay_ms / 1000.0)
        try:
            inject(text)
        except (InjectionError, ConsoleNotAvailable) as e:
            logger.error(f"Injection failed: {e}")
            return

        if follow_up:
            await asyncio.sleep(follow_up_delay_ms / 1000.0)
            try:
                inject(follow_up)
            except (InjectionError, ConsoleNotAvailable) as e:
                logger.error(f"Follow-up injection failed: {e}")

    asyncio.create_task(_delayed_inject())

    # Update state
    _state["turn_count"] += 1
    _state["last_prompt_time"] = datetime.now(timezone.utc)

    log_entry = {
        "turn": _state["turn_count"],
        "text_preview": text[:100],
        "reason": reason,
        "timestamp": _now_iso(),
    }
    _state["prompts_log"].append(log_entry)

    # Audit
    _audit_log({"tool": "velle_prompt", "turn": _state["turn_count"],
                "text": text, "reason": reason, "outcome": "injected"})

    result = {
        "status": "injected",
        "turn_count": _state["turn_count"],
        "turn_limit": _state["turn_limit"],
        "delay_ms": delay_ms,
        "has_follow_up": bool(follow_up),
        "follow_up_delay_ms": follow_up_delay_ms if follow_up else None,
        "timestamp": _now_iso(),
    }

    return [TextContent(type="text", text=json.dumps(result))]


async def _handle_status(args: dict) -> list[TextContent]:
    """Handle a velle_status tool call."""
    diag = check_console()

    estimated_cost = _state["turn_count"] * _state.get("cost_per_turn", 0.15)

    result = {
        "active": _state["session_start"] is not None,
        "turn_count": _state["turn_count"],
        "turn_limit": _state["turn_limit"],
        "cooldown_ms": _state["cooldown_ms"],
        "budget_usd": _state["budget_usd"],
        "estimated_cost_usd": round(estimated_cost, 2),
        "audit_mode": _state["audit_mode"],
        "config_file": str(CONFIG_FILE),
        "session_start": _state["session_start"],
        "console_available": diag["available"],
        "console_diagnostics": diag,
        "recent_prompts": _state["prompts_log"][-10:],
        "timestamp": _now_iso(),
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _handle_query(args: dict) -> list[TextContent]:
    """Handle a velle_query tool call — validated slash command execution."""
    command = args.get("command", "")
    follow_up = args.get("follow_up", "Review the output of the previous command and continue.")
    delay_ms = args.get("delay_ms", 500)
    follow_up_delay_ms = args.get("follow_up_delay_ms", 3000)
    reason = args.get("reason", "")

    # Look up command in registry
    cmd_entry = get_command(command)

    if cmd_entry is None:
        result = {
            "status": "error",
            "error_code": "COMMAND_UNKNOWN",
            "message": f"Unknown command: {command}. Not in the Velle command registry.",
            "timestamp": _now_iso(),
        }
        _audit_log({"tool": "velle_query", "command": command, "reason": reason,
                     "outcome": "command_unknown"})
        return [TextContent(type="text", text=json.dumps(result))]

    if cmd_entry["status"] == BLOCKED:
        result = {
            "status": "error",
            "error_code": "COMMAND_BLOCKED",
            "message": f"Command {command} is BLOCKED.",
            "block_reason": cmd_entry["block_reason"],
            "description": cmd_entry["description"],
            "hint": "Use velle_configure with set_command_status to change this.",
            "timestamp": _now_iso(),
        }
        _audit_log({"tool": "velle_query", "command": command, "reason": reason,
                     "outcome": "command_blocked",
                     "block_reason": cmd_entry["block_reason"]})
        return [TextContent(type="text", text=json.dumps(result))]

    # Command is ALLOWED — delegate to _handle_prompt
    # This counts against turn limit
    return await _handle_prompt({
        "text": command,
        "delay_ms": delay_ms,
        "follow_up": follow_up,
        "follow_up_delay_ms": follow_up_delay_ms,
        "reason": reason or f"velle_query:{command}",
    })


async def _handle_configure(args: dict) -> list[TextContent]:
    """Handle a velle_configure tool call — runtime config updates."""
    changes = {}

    if "turn_limit" in args:
        _state["turn_limit"] = args["turn_limit"]
        changes["turn_limit"] = args["turn_limit"]

    if "cooldown_ms" in args:
        _state["cooldown_ms"] = args["cooldown_ms"]
        changes["cooldown_ms"] = args["cooldown_ms"]

    if "budget_usd" in args:
        _state["budget_usd"] = args["budget_usd"]
        changes["budget_usd"] = args["budget_usd"]

    if "audit_mode" in args:
        if args["audit_mode"] in ("local", "memorygate", "both"):
            _state["audit_mode"] = args["audit_mode"]
            changes["audit_mode"] = args["audit_mode"]

    if "set_command_status" in args:
        cmd_changes = {}
        for cmd_name, new_status in args["set_command_status"].items():
            if new_status in (ALLOWED, BLOCKED):
                if set_status(cmd_name, new_status):
                    cmd_changes[cmd_name] = new_status
                else:
                    cmd_changes[cmd_name] = "not_found"
            else:
                cmd_changes[cmd_name] = f"invalid_status:{new_status}"
        changes["command_status"] = cmd_changes

    _audit_log({"tool": "velle_configure", "changes": changes, "outcome": "configured"})

    result = {
        "status": "configured",
        "changes": changes,
        "current_config": {
            "turn_limit": _state["turn_limit"],
            "turn_count": _state["turn_count"],
            "cooldown_ms": _state["cooldown_ms"],
            "budget_usd": _state["budget_usd"],
            "audit_mode": _state["audit_mode"],
        },
        "timestamp": _now_iso(),
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _run():
    server = _create_server()
    sidecar_runner = None

    if _config.get("sidecar_enabled"):
        from velle.http_sidecar import start_sidecar
        port = _config.get("sidecar_port", 7839)
        try:
            sidecar_runner = await start_sidecar(_handle_prompt, _handle_status, port)
        except OSError as e:
            logger.warning(f"Failed to start HTTP sidecar on port {port}: {e}")

    try:
        async with stdio_server() as (read_stream, write_stream):
            logger.info("Velle MCP server starting")
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        if sidecar_runner:
            await sidecar_runner.cleanup()


def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())


if __name__ == "__main__":
    main()
