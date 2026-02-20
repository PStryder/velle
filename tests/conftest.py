"""Shared fixtures for Velle tests — centralizes injector mock."""

import sys
from unittest.mock import MagicMock

import pytest

# Create a single mock injector shared across all test modules
mock_injector = MagicMock()
mock_injector.check_console.return_value = {
    "available": True, "handle": 1, "handle_type": "CONIN$",
    "console_mode": "0x01f7", "error": None,
}
mock_injector.inject.return_value = 10
mock_injector.ConsoleNotAvailable = type("ConsoleNotAvailable", (Exception,), {})
mock_injector.InjectionError = type("InjectionError", (Exception,), {})

# Install the mock before any velle.server imports
if "velle.server" not in sys.modules:
    sys.modules["velle.injector"] = mock_injector
