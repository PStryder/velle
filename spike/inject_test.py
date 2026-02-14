"""
Velle Phase 0 Spike: Stdin Injection Test

Tests whether a child process can inject text into the parent's console
stdin buffer using Win32 WriteConsoleInput.

Usage:
    Run from a REAL TERMINAL (cmd, PowerShell, or Windows Terminal):
        python spike/inject_test.py

    Test as a subprocess (simulates MCP server being a child):
        python spike/inject_parent.py

    NOTE: This will NOT work when run through piped I/O (e.g., from Claude Code's
    Bash tool, IDE terminals with redirected I/O, etc.). WriteConsoleInput requires
    an actual console handle, not a pipe.

What should happen:
    The script injects "hello from velle" + Enter into the console input buffer.
    If successful, the text appears as if the user typed it.
"""

import ctypes
import ctypes.wintypes as wintypes
import os
import sys
import time

# Load kernel32 with error tracking
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

# Win32 constants
STD_INPUT_HANDLE = -10
KEY_EVENT = 0x0001
INVALID_HANDLE_VALUE = -1
FILE_TYPE_CHAR = 0x0002  # Console device


# Win32 structures
class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", wintypes.BOOL),
        ("wRepeatCount", wintypes.WORD),
        ("wVirtualKeyCode", wintypes.WORD),
        ("wVirtualScanCode", wintypes.WORD),
        ("uChar", wintypes.WCHAR),
        ("dwControlKeyState", wintypes.DWORD),
    ]


class INPUT_RECORD_Event(ctypes.Union):
    _fields_ = [
        ("KeyEvent", KEY_EVENT_RECORD),
    ]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [
        ("EventType", wintypes.WORD),
        ("Event", INPUT_RECORD_Event),
    ]


def get_console_handle():
    """Get the console input handle and verify it's a real console."""
    handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
    if handle == INVALID_HANDLE_VALUE:
        error = ctypes.get_last_error()
        raise OSError(f"GetStdHandle failed (error {error})")

    # Check if this is actually a console handle (not a pipe)
    file_type = kernel32.GetFileType(handle)
    if file_type != FILE_TYPE_CHAR:
        type_names = {0: "UNKNOWN", 1: "DISK", 2: "CHAR (console)", 3: "PIPE"}
        actual = type_names.get(file_type, f"type={file_type}")
        raise OSError(
            f"Stdin handle is {actual}, not a console. "
            f"WriteConsoleInput requires a real console. "
            f"Run from cmd/PowerShell/Windows Terminal, not piped I/O."
        )

    # Double check with GetConsoleMode
    mode = wintypes.DWORD()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        error = ctypes.get_last_error()
        raise OSError(f"GetConsoleMode failed (error {error}) — handle may not be a console")

    return handle


def make_key_event(char, key_down=True):
    """Create an INPUT_RECORD for a single character key event."""
    record = INPUT_RECORD()
    record.EventType = KEY_EVENT
    record.Event.KeyEvent.bKeyDown = key_down
    record.Event.KeyEvent.wRepeatCount = 1
    record.Event.KeyEvent.wVirtualKeyCode = 0  # Not needed for character input
    record.Event.KeyEvent.wVirtualScanCode = 0
    record.Event.KeyEvent.uChar = char
    record.Event.KeyEvent.dwControlKeyState = 0
    return record


def make_enter_event(key_down=True):
    """Create an INPUT_RECORD for the Enter key."""
    record = INPUT_RECORD()
    record.EventType = KEY_EVENT
    record.Event.KeyEvent.bKeyDown = key_down
    record.Event.KeyEvent.wRepeatCount = 1
    record.Event.KeyEvent.wVirtualKeyCode = 0x0D  # VK_RETURN
    record.Event.KeyEvent.wVirtualScanCode = 0x1C
    record.Event.KeyEvent.uChar = '\r'
    record.Event.KeyEvent.dwControlKeyState = 0
    return record


def inject_text(text, handle=None):
    """
    Inject text into the console input buffer as if the user typed it.

    Each character gets a key-down and key-up event.
    An Enter key is appended at the end.
    """
    if handle is None:
        handle = get_console_handle()

    # Build the input record array
    records = []
    for char in text:
        records.append(make_key_event(char, key_down=True))
        records.append(make_key_event(char, key_down=False))

    # Append Enter key
    records.append(make_enter_event(key_down=True))
    records.append(make_enter_event(key_down=False))

    # Create array and write
    record_array = (INPUT_RECORD * len(records))(*records)
    written = wintypes.DWORD(0)

    success = kernel32.WriteConsoleInputW(
        handle,
        record_array,
        len(records),
        ctypes.byref(written),
    )

    if not success:
        error = ctypes.get_last_error()
        raise OSError(f"WriteConsoleInputW failed (error {error})")

    return written.value


def inject_with_attach(pid, text):
    """
    Attach to another process's console and inject text.

    Use this if the child process does NOT share the parent's console
    (e.g., started with CREATE_NEW_CONSOLE or detached).
    """
    # Free our own console first (required before AttachConsole)
    kernel32.FreeConsole()

    # Attach to target process console
    if not kernel32.AttachConsole(pid):
        error = ctypes.get_last_error()
        raise OSError(f"AttachConsole({pid}) failed (error {error})")

    try:
        handle = get_console_handle()
        written = inject_text(text, handle)
        return written
    finally:
        kernel32.FreeConsole()


def diagnose():
    """Print diagnostic info about the console environment."""
    print(f"  PID:          {os.getpid()}")
    print(f"  Parent PID:   {os.getppid()}")

    handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
    print(f"  Stdin handle: {handle}")

    if handle == INVALID_HANDLE_VALUE:
        print(f"  Status:       INVALID HANDLE")
        return

    file_type = kernel32.GetFileType(handle)
    type_names = {0: "UNKNOWN", 1: "DISK", 2: "CHAR (console)", 3: "PIPE"}
    print(f"  Handle type:  {type_names.get(file_type, f'unknown ({file_type})')}")

    if file_type == FILE_TYPE_CHAR:
        mode = wintypes.DWORD()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            print(f"  Console mode: 0x{mode.value:04x}")
            print(f"  Status:       REAL CONSOLE — injection should work")
        else:
            error = ctypes.get_last_error()
            print(f"  Console mode: failed (error {error})")
    elif file_type == 3:  # PIPE
        print(f"  Status:       PIPE — injection will NOT work")
        print(f"  Reason:       Process is running with redirected I/O")
        print(f"  Fix:          Run from a real terminal (cmd, PowerShell, Windows Terminal)")
    else:
        print(f"  Status:       UNEXPECTED TYPE — injection unlikely to work")


def main():
    text = "hello from velle"

    print(f"Velle Injection Spike")
    print(f"=====================")
    print()

    # Determine mode
    mode = sys.argv[1] if len(sys.argv) > 1 else "direct"

    if mode == "diagnose":
        print(f"Diagnostics:")
        diagnose()
        return

    if mode == "test":
        print(f"Handle test:")
        diagnose()
        print()
        try:
            handle = get_console_handle()
            print(f"Result: Console handle is valid and ready for injection.")
        except OSError as e:
            print(f"Result: {e}")
        return

    print(f"Text to inject: {text!r}")
    print()

    if mode == "direct":
        print(f"Method: direct (shared console handle)")
        print(f"Diagnostics:")
        diagnose()
        print()
        print(f"Injecting in 2 seconds...")
        time.sleep(2)
        try:
            written = inject_text(text)
            print(f"SUCCESS: Wrote {written} input records to console stdin.")
        except OSError as e:
            print(f"FAILED: {e}")
            sys.exit(1)

    elif mode == "attach":
        ppid = int(sys.argv[2]) if len(sys.argv) > 2 else os.getppid()
        print(f"Method: AttachConsole to PID {ppid}")
        print(f"Diagnostics:")
        diagnose()
        print()
        print(f"Injecting in 2 seconds...")
        time.sleep(2)
        try:
            written = inject_with_attach(ppid, text)
            print(f"SUCCESS: Wrote {written} input records via AttachConsole({ppid}).")
        except OSError as e:
            print(f"FAILED: {e}")
            sys.exit(1)

    else:
        print(f"Unknown mode: {mode}")
        print(f"Usage: python inject_test.py [direct|attach|diagnose|test]")
        sys.exit(1)


if __name__ == "__main__":
    main()
