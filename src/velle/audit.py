"""Audit logging for Velle — local JSONL and optional MemoryGate integration."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("velle.audit")

AUDIT_FILE = Path("velle_audit.jsonl")

# MemoryGate HTTP endpoint (used when audit_mode includes "memorygate")
MEMORYGATE_ENDPOINT = "http://127.0.0.1:8000/memory_store"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def audit_log(
    entry: dict[str, Any],
    state: dict[str, Any],
    audit_path: Path | None = None,
) -> None:
    """Write an audit entry to local file and/or MemoryGate.

    Args:
        entry: The audit data to log.
        state: Current Velle session state (needs audit_mode, session_start).
        audit_path: Override path for local JSONL file.
    """
    entry["timestamp"] = _now_iso()
    entry["session_start"] = state.get("session_start")

    mode = state.get("audit_mode", "local")
    path = audit_path or AUDIT_FILE

    # Local file logging
    if mode in ("local", "both"):
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            logger.warning(f"Failed to write audit log: {e}")

    # MemoryGate logging
    if mode in ("memorygate", "both"):
        _log_to_memorygate(entry, mode)


def _log_to_memorygate(entry: dict[str, Any], mode: str) -> None:
    """Attempt to log an audit entry to MemoryGate via HTTP."""
    try:
        import aiohttp
        import asyncio

        async def _post():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        MEMORYGATE_ENDPOINT,
                        json={
                            "observation": json.dumps(entry),
                            "confidence": 0.9,
                            "domain": "velle_audit",
                            "evidence": [f"velle_turn_{entry.get('turn', '?')}"],
                        },
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status != 200:
                            logger.warning(f"MemoryGate audit failed: HTTP {resp.status}")
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if mode == "memorygate":
                    # If memorygate-only mode and it's unavailable, log error
                    logger.error(f"MemoryGate unavailable (mode=memorygate): {e}")
                else:
                    logger.warning(f"MemoryGate audit failed (continuing with local): {e}")

        # Try to use the running event loop
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_post())
        except RuntimeError:
            # No event loop running, skip async logging
            logger.debug("No event loop available for MemoryGate audit")

    except ImportError:
        logger.warning("aiohttp not available for MemoryGate audit")
