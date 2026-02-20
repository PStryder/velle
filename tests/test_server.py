"""Tests for velle.server — MCP tool handlers with mocked injector."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import mock_injector
from velle import server as srv


def _parse(result):
    return json.loads(result[0].text)


@pytest.fixture(autouse=True)
def reset_state():
    """Reset server state between tests."""
    srv._state["turn_count"] = 0
    srv._state["turn_limit"] = 20
    srv._state["cooldown_ms"] = 1000
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


class TestHandlePrompt:
    @pytest.mark.asyncio
    async def test_prompt_increments_turn_count(self):
        result = await srv._handle_prompt({"text": "hello"})
        data = _parse(result)
        assert data["status"] == "injected"
        assert data["turn_count"] == 1
        assert srv._state["turn_count"] == 1

    @pytest.mark.asyncio
    async def test_prompt_turn_limit_reached(self):
        srv._state["turn_count"] = 20
        srv._state["turn_limit"] = 20
        result = await srv._handle_prompt({"text": "hello"})
        data = _parse(result)
        assert data["status"] == "error"
        assert data["error_code"] == "TURN_LIMIT_REACHED"

    @pytest.mark.asyncio
    async def test_prompt_cooldown_active(self):
        # First prompt succeeds
        await srv._handle_prompt({"text": "first"})
        # Second prompt immediately should trigger cooldown
        result = await srv._handle_prompt({"text": "second"})
        data = _parse(result)
        assert data["status"] == "error"
        assert data["error_code"] == "COOLDOWN_ACTIVE"

    @pytest.mark.asyncio
    async def test_prompt_console_unavailable(self):
        mock_injector.check_console.return_value = {
            "available": False, "handle": None, "handle_type": "no_parent_console",
            "console_mode": None, "error": "No console",
        }
        result = await srv._handle_prompt({"text": "hello"})
        data = _parse(result)
        assert data["status"] == "error"
        assert data["error_code"] == "CONSOLE_NOT_AVAILABLE"


class TestHandleStatus:
    @pytest.mark.asyncio
    async def test_status_returns_state(self):
        result = await srv._handle_status({})
        data = _parse(result)
        assert "turn_count" in data
        assert "turn_limit" in data
        assert "cooldown_ms" in data
        assert "budget_usd" in data
        assert "audit_mode" in data
        assert "console_available" in data
        assert "recent_prompts" in data
        assert "estimated_cost_usd" in data


class TestConfigLoading:
    def test_config_loading_defaults(self):
        """When no config file exists, defaults apply."""
        with patch.object(srv, "CONFIG_FILE", type(srv.CONFIG_FILE)("nonexistent_path.json")):
            config = srv._load_config()
        assert config["turn_limit"] == 20
        assert config["cooldown_ms"] == 1000
        assert config["budget_usd"] == 5.00

    def test_config_loading_from_file(self, tmp_path):
        """Custom config file overrides defaults."""
        config_file = tmp_path / "velle.json"
        config_file.write_text(json.dumps({"turn_limit": 50, "cooldown_ms": 2000}))
        with patch.object(srv, "CONFIG_FILE", config_file):
            config = srv._load_config()
        assert config["turn_limit"] == 50
        assert config["cooldown_ms"] == 2000
        assert config["budget_usd"] == 5.00  # default preserved


class TestAuditLog:
    def test_audit_log_writes_file(self, tmp_path):
        """Verify JSONL entry written with correct encoding."""
        audit_file = tmp_path / "test_audit.jsonl"
        original_audit_file = srv.AUDIT_FILE
        srv.AUDIT_FILE = str(audit_file)
        srv._state["audit_mode"] = "local"
        srv._state["session_start"] = "2026-01-01T00:00:00+00:00"
        try:
            srv._audit_log({"tool": "velle_prompt", "text": "test", "outcome": "ok"})
            content = audit_file.read_text(encoding="utf-8")
            lines = content.strip().splitlines()
            assert len(lines) == 1
            data = json.loads(lines[0])
            assert data["tool"] == "velle_prompt"
            assert "timestamp" in data
            assert data["session_start"] == "2026-01-01T00:00:00+00:00"
        finally:
            srv.AUDIT_FILE = original_audit_file
