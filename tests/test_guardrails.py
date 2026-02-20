"""Tests for velle.guardrails — guardrail check functions."""

from datetime import datetime, timezone, timedelta

from velle.guardrails import check_budget, check_cooldown, check_turn_limit


def _make_state(**overrides):
    state = {
        "turn_count": 0,
        "turn_limit": 20,
        "cooldown_ms": 1000,
        "budget_usd": 5.00,
        "last_prompt_time": None,
    }
    state.update(overrides)
    return state


class TestCheckTurnLimit:
    def test_under_limit(self):
        ok, err = check_turn_limit(_make_state(turn_count=5, turn_limit=20))
        assert ok is True
        assert err is None

    def test_at_limit(self):
        ok, err = check_turn_limit(_make_state(turn_count=20, turn_limit=20))
        assert ok is False
        assert err["error_code"] == "TURN_LIMIT_REACHED"

    def test_over_limit(self):
        ok, err = check_turn_limit(_make_state(turn_count=25, turn_limit=20))
        assert ok is False


class TestCheckCooldown:
    def test_no_previous_prompt(self):
        ok, err = check_cooldown(_make_state())
        assert ok is True

    def test_cooldown_elapsed(self):
        old_time = datetime.now(timezone.utc) - timedelta(seconds=5)
        ok, err = check_cooldown(_make_state(last_prompt_time=old_time, cooldown_ms=1000))
        assert ok is True

    def test_cooldown_active(self):
        recent = datetime.now(timezone.utc) - timedelta(milliseconds=100)
        ok, err = check_cooldown(_make_state(last_prompt_time=recent, cooldown_ms=1000))
        assert ok is False
        assert err["error_code"] == "COOLDOWN_ACTIVE"


class TestCheckBudget:
    def test_under_budget(self):
        ok, err = check_budget(_make_state(turn_count=5, budget_usd=5.00), cost_per_turn=0.15)
        assert ok is True

    def test_at_budget(self):
        # 34 turns * $0.15 = $5.10 > $5.00
        ok, err = check_budget(_make_state(turn_count=34, budget_usd=5.00), cost_per_turn=0.15)
        assert ok is False
        assert err["error_code"] == "BUDGET_EXCEEDED"
        assert err["estimated_cost_usd"] == 5.10

    def test_no_budget(self):
        ok, err = check_budget(_make_state(budget_usd=0))
        assert ok is True

    def test_custom_cost_per_turn(self):
        ok, err = check_budget(_make_state(turn_count=10, budget_usd=5.00), cost_per_turn=0.50)
        assert ok is False
        assert err["estimated_cost_usd"] == 5.00
