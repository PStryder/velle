"""Guardrail checks for Velle prompt injection.

Each check returns (ok: bool, error_dict: dict | None).
If ok is True, error_dict is None. If False, error_dict contains
the error response to return to the caller.
"""

from datetime import datetime, timezone
from typing import Any


def check_turn_limit(state: dict[str, Any]) -> tuple[bool, dict | None]:
    """Check if turn limit has been reached."""
    if state["turn_count"] >= state["turn_limit"]:
        return False, {
            "status": "error",
            "error_code": "TURN_LIMIT_REACHED",
            "message": (
                f"Turn limit reached ({state['turn_limit']}). "
                f"Use velle_configure to increase or end the autonomous session."
            ),
            "turn_count": state["turn_count"],
            "turn_limit": state["turn_limit"],
        }
    return True, None


def check_cooldown(state: dict[str, Any]) -> tuple[bool, dict | None]:
    """Check if enough time has passed since the last prompt."""
    if state["last_prompt_time"] is None:
        return True, None
    elapsed = (datetime.now(timezone.utc) - state["last_prompt_time"]).total_seconds() * 1000
    if elapsed < state["cooldown_ms"]:
        return False, {
            "status": "error",
            "error_code": "COOLDOWN_ACTIVE",
            "message": f"Cooldown active ({state['cooldown_ms']}ms between prompts).",
        }
    return True, None


# Default cost-per-turn estimate for Opus ($0.15/turn rough heuristic)
DEFAULT_COST_PER_TURN = 0.15


def check_budget(
    state: dict[str, Any],
    cost_per_turn: float = DEFAULT_COST_PER_TURN,
) -> tuple[bool, dict | None]:
    """Check if estimated cost exceeds budget.

    Uses a rough heuristic: turn_count * cost_per_turn.
    The cost_per_turn can be overridden in config.
    """
    budget = state.get("budget_usd", 0)
    if budget <= 0:
        return True, None  # No budget set, skip check

    estimated_cost = state["turn_count"] * cost_per_turn
    if estimated_cost >= budget:
        return False, {
            "status": "error",
            "error_code": "BUDGET_EXCEEDED",
            "message": (
                f"Estimated cost ${estimated_cost:.2f} exceeds budget ${budget:.2f}. "
                f"Use velle_configure to increase budget_usd."
            ),
            "estimated_cost_usd": round(estimated_cost, 2),
            "budget_usd": budget,
            "turn_count": state["turn_count"],
        }
    return True, None
