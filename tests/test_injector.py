"""Tests for velle.injector — struct construction (no Win32 API calls needed)."""

import importlib
import sys

import pytest

# Skip entire module on non-Windows
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only injector")


@pytest.fixture(autouse=True)
def real_injector():
    """Ensure we import the REAL injector module, not a mock from test_server."""
    saved = sys.modules.pop("velle.injector", None)
    mod = importlib.import_module("velle.injector")
    sys.modules["velle.injector"] = mod
    yield mod
    if saved is not None:
        sys.modules["velle.injector"] = saved


def test_make_key_event_structure(real_injector):
    """Verify INPUT_RECORD fields for a character event."""
    record = real_injector._make_key_event("A", key_down=True)
    assert record.EventType == real_injector.KEY_EVENT
    assert record.Event.KeyEvent.bKeyDown == 1
    assert record.Event.KeyEvent.uChar == "A"
    assert record.Event.KeyEvent.wRepeatCount == 1


def test_make_key_event_key_up(real_injector):
    record = real_injector._make_key_event("x", key_down=False)
    assert record.EventType == real_injector.KEY_EVENT
    assert record.Event.KeyEvent.bKeyDown == 0
    assert record.Event.KeyEvent.uChar == "x"


def test_make_enter_events(real_injector):
    """Verify Enter produces 2 records (key-down + key-up), VK_RETURN, \\r char."""
    events = real_injector._make_enter_events()
    assert len(events) == 2

    # First event: key-down
    assert events[0].Event.KeyEvent.bKeyDown == 1
    assert events[0].Event.KeyEvent.wVirtualKeyCode == 0x0D  # VK_RETURN
    assert events[0].Event.KeyEvent.uChar == "\r"

    # Second event: key-up
    assert events[1].Event.KeyEvent.bKeyDown == 0
    assert events[1].Event.KeyEvent.wVirtualKeyCode == 0x0D
    assert events[1].Event.KeyEvent.uChar == "\r"
