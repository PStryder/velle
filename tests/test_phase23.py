"""Tests for Velle Phase 2-3 features: budget, velle_query, velle_configure."""

import json

import pytest

from tests.conftest import mock_injector
from velle import server as srv
from velle.registry import COMMAND_REGISTRY, ALLOWED, BLOCKED


def _parse(result):
    return json.loads(result[0].text)


@pytest.fixture(autouse=True)
def reset_state():
    srv._state["turn_count"] = 0
    srv._state["turn_limit"] = 20
    srv._state["cooldown_ms"] = 0  # disable cooldown for tests
    srv._state["budget_usd"] = 5.00
    srv._state["cost_per_turn"] = 0.15
    srv._state["audit_mode"] = "local"
    srv._state["session_start"] = None
    srv._state["last_prompt_time"] = None
    srv._state["prompts_log"] = []
    srv._state["console_available"] = None
    mock_injector.check_console.return_value = {
        "available": True, "handle": 1, "handle_type": "CONIN$",
        "console_mode": "0x01f7", "error": None,
    }
    yield


class TestBudgetEnforcement:
    @pytest.mark.asyncio
    async def test_budget_blocks_when_exceeded(self):
        srv._state["turn_count"] = 34  # 34 * 0.15 = $5.10 > $5.00
        srv._state["turn_limit"] = 100  # raise limit so budget check fires first
        result = await srv._handle_prompt({"text": "hello"})
        data = _parse(result)
        assert data["error_code"] == "BUDGET_EXCEEDED"

    @pytest.mark.asyncio
    async def test_budget_allows_when_under(self):
        srv._state["turn_count"] = 5
        result = await srv._handle_prompt({"text": "hello"})
        data = _parse(result)
        assert data["status"] == "injected"


class TestVelleQuery:
    @pytest.mark.asyncio
    async def test_query_allowed_command(self):
        result = await srv._handle_query({"command": "/compact"})
        data = _parse(result)
        assert data["status"] == "injected"

    @pytest.mark.asyncio
    async def test_query_blocked_command(self):
        result = await srv._handle_query({"command": "/clear"})
        data = _parse(result)
        assert data["error_code"] == "COMMAND_BLOCKED"
        assert data["block_reason"] == "destructive"

    @pytest.mark.asyncio
    async def test_query_unknown_command(self):
        result = await srv._handle_query({"command": "/nonexistent"})
        data = _parse(result)
        assert data["error_code"] == "COMMAND_UNKNOWN"

    @pytest.mark.asyncio
    async def test_query_counts_against_turn_limit(self):
        assert srv._state["turn_count"] == 0
        await srv._handle_query({"command": "/compact"})
        assert srv._state["turn_count"] == 1


class TestVelleConfigure:
    @pytest.mark.asyncio
    async def test_configure_turn_limit(self):
        result = await srv._handle_configure({"turn_limit": 50})
        data = _parse(result)
        assert data["status"] == "configured"
        assert data["changes"]["turn_limit"] == 50
        assert srv._state["turn_limit"] == 50

    @pytest.mark.asyncio
    async def test_configure_cooldown(self):
        result = await srv._handle_configure({"cooldown_ms": 2000})
        data = _parse(result)
        assert data["changes"]["cooldown_ms"] == 2000
        assert srv._state["cooldown_ms"] == 2000

    @pytest.mark.asyncio
    async def test_configure_budget(self):
        result = await srv._handle_configure({"budget_usd": 10.00})
        data = _parse(result)
        assert data["changes"]["budget_usd"] == 10.00
        assert srv._state["budget_usd"] == 10.00

    @pytest.mark.asyncio
    async def test_configure_audit_mode(self):
        result = await srv._handle_configure({"audit_mode": "local"})
        data = _parse(result)
        assert data["changes"]["audit_mode"] == "local"

    @pytest.mark.asyncio
    async def test_configure_command_status(self):
        original = COMMAND_REGISTRY["/review"]["status"]
        try:
            result = await srv._handle_configure({
                "set_command_status": {"/review": "ALLOWED"}
            })
            data = _parse(result)
            assert data["changes"]["command_status"]["/review"] == "ALLOWED"
            assert COMMAND_REGISTRY["/review"]["status"] == "ALLOWED"
        finally:
            COMMAND_REGISTRY["/review"]["status"] = original

    @pytest.mark.asyncio
    async def test_configure_unknown_command(self):
        result = await srv._handle_configure({
            "set_command_status": {"/fake": "ALLOWED"}
        })
        data = _parse(result)
        assert data["changes"]["command_status"]["/fake"] == "not_found"

    @pytest.mark.asyncio
    async def test_configure_returns_current_config(self):
        result = await srv._handle_configure({"turn_limit": 30})
        data = _parse(result)
        assert data["current_config"]["turn_limit"] == 30
        assert "turn_count" in data["current_config"]
        assert "budget_usd" in data["current_config"]
