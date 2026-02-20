"""Tests for velle.registry — command registry."""

from velle.registry import (
    ALLOWED,
    BLOCKED,
    COMMAND_REGISTRY,
    get_command,
    is_allowed,
    set_status,
)


class TestGetCommand:
    def test_known_allowed_command(self):
        cmd = get_command("/compact")
        assert cmd is not None
        assert cmd["status"] == ALLOWED

    def test_known_blocked_command(self):
        cmd = get_command("/clear")
        assert cmd is not None
        assert cmd["status"] == BLOCKED
        assert cmd["block_reason"] == "destructive"

    def test_unknown_command(self):
        assert get_command("/nonexistent") is None

    def test_auto_prefixes_slash(self):
        cmd = get_command("compact")
        assert cmd is not None
        assert cmd["status"] == ALLOWED


class TestIsAllowed:
    def test_allowed_command(self):
        assert is_allowed("/compact") is True
        assert is_allowed("/status") is True
        assert is_allowed("/todos") is True

    def test_blocked_command(self):
        assert is_allowed("/clear") is False
        assert is_allowed("/exit") is False

    def test_unknown_command(self):
        assert is_allowed("/fake") is False


class TestSetStatus:
    def test_set_status_allowed(self):
        # Save original
        original = COMMAND_REGISTRY["/review"]["status"]
        try:
            assert set_status("/review", ALLOWED) is True
            assert COMMAND_REGISTRY["/review"]["status"] == ALLOWED
        finally:
            COMMAND_REGISTRY["/review"]["status"] = original

    def test_set_status_unknown(self):
        assert set_status("/nonexistent", ALLOWED) is False


class TestRegistryCounts:
    def test_allowed_count(self):
        allowed = [k for k, v in COMMAND_REGISTRY.items() if v["status"] == ALLOWED]
        assert len(allowed) == 12

    def test_blocked_count(self):
        blocked = [k for k, v in COMMAND_REGISTRY.items() if v["status"] == BLOCKED]
        assert len(blocked) == 41
