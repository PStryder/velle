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

logger = logging.getLogger("velle")

# Config file path — lives next to the project root
CONFIG_FILE = Path(__file__).parent.parent.parent / "velle.json"

# Default configuration
_DEFAULTS = {
    "turn_limit": 20,
    "cooldown_ms": 1000,
    "budget_usd": 5.00,
    "audit_mode": "both",
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
    entry["timestamp"] = _now_iso()
    entry["session_start"] = _state["session_start"]

    mode = _state["audit_mode"]

    # Local file logging
    if mode in ("local", "both"):
        try:
            with open(AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            logger.warning(f"Failed to write audit log: {e}")

    # MemoryGate logging would go here in Phase 2
    # For now, local-only is sufficient


def _check_cooldown() -> bool:
    """Check if enough time has passed since the last prompt."""
    if _state["last_prompt_time"] is None:
        return True
    elapsed = (datetime.now(timezone.utc) - _state["last_prompt_time"]).total_seconds() * 1000
    return elapsed >= _state["cooldown_ms"]


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
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "velle_prompt":
            return await _handle_prompt(arguments)
        elif name == "velle_status":
            return await _handle_status(arguments)
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
    if _state["turn_count"] >= _state["turn_limit"]:
        result = {
            "status": "error",
            "error_code": "TURN_LIMIT_REACHED",
            "message": f"Turn limit reached ({_state['turn_limit']}). "
            f"Use velle_configure to increase or end the autonomous session.",
            "turn_count": _state["turn_count"],
            "turn_limit": _state["turn_limit"],
            "timestamp": _now_iso(),
        }
        _audit_log({"tool": "velle_prompt", "text": text, "reason": reason,
                     "outcome": "turn_limit_reached"})
        return [TextContent(type="text", text=json.dumps(result))]

    # Check cooldown
    if not _check_cooldown():
        result = {
            "status": "error",
            "error_code": "COOLDOWN_ACTIVE",
            "message": f"Cooldown active ({_state['cooldown_ms']}ms between prompts).",
            "timestamp": _now_iso(),
        }
        return [TextContent(type="text", text=json.dumps(result))]

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
    # The delay ensures the agent's current response finishes before injection
    async def _delayed_inject():
        await asyncio.sleep(delay_ms / 1000.0)
        try:
            inject(text)
        except (InjectionError, ConsoleNotAvailable) as e:
            logger.error(f"Injection failed: {e}")
            return

        # If there's a follow_up, wait for the first command to complete
        # then inject the follow_up to start a new agent turn
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

    result = {
        "active": _state["session_start"] is not None,
        "turn_count": _state["turn_count"],
        "turn_limit": _state["turn_limit"],
        "cooldown_ms": _state["cooldown_ms"],
        "budget_usd": _state["budget_usd"],
        "audit_mode": _state["audit_mode"],
        "config_file": str(CONFIG_FILE),
        "session_start": _state["session_start"],
        "console_available": diag["available"],
        "console_diagnostics": diag,
        "recent_prompts": _state["prompts_log"][-10:],
        "timestamp": _now_iso(),
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _run():
    server = _create_server()
    async with stdio_server() as (read_stream, write_stream):
        logger.info("Velle MCP server starting")
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())


if __name__ == "__main__":
    main()
