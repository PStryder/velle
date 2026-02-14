"""
Win32 stdin injection for Velle.

Injects text into the parent process's console stdin buffer using
WriteConsoleInputW. The MCP server's own stdin is a pipe (MCP transport),
so we must FreeConsole + AttachConsole to the parent (Claude Code) process,
then open CONIN$ to get the real console input buffer handle.

Key insight: After AttachConsole, GetStdHandle still returns the process's
original piped handles. We must use CreateFile("CONIN$") to open the
console input buffer directly.

Platform: Windows only (for now).
"""

import ctypes
import ctypes.wintypes as wintypes
import sys

# Load kernel32 with error tracking
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Win32 constants
KEY_EVENT = 0x0001
INVALID_HANDLE_VALUE = ctypes.wintypes.HANDLE(-1).value
ATTACH_PARENT_PROCESS = wintypes.DWORD(-1).value  # Special PID for AttachConsole

# CreateFile access flags
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3


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


class InjectionError(Exception):
    """Raised when stdin injection fails."""
    pass


class ConsoleNotAvailable(InjectionError):
    """Raised when no real console is available for injection."""
    pass


NUMLOCK_ON = 0x0020  # Standard keyboard state flag


def _make_key_event(char: str, key_down: bool = True) -> INPUT_RECORD:
    record = INPUT_RECORD()
    record.EventType = KEY_EVENT
    record.Event.KeyEvent.bKeyDown = key_down
    record.Event.KeyEvent.wRepeatCount = 1
    record.Event.KeyEvent.wVirtualKeyCode = 0
    record.Event.KeyEvent.wVirtualScanCode = 0
    record.Event.KeyEvent.uChar = char
    record.Event.KeyEvent.dwControlKeyState = NUMLOCK_ON
    return record


def _make_enter_events() -> list[INPUT_RECORD]:
    """
    Create key events to simulate Enter.

    Real console Enter produces two \\r events (key-down with \\r, key-up with \\r).
    ConPTY/Claude Code expects both to trigger submission.
    """
    events = []
    for key_down in (True, False):
        record = INPUT_RECORD()
        record.EventType = KEY_EVENT
        record.Event.KeyEvent.bKeyDown = key_down
        record.Event.KeyEvent.wRepeatCount = 1
        record.Event.KeyEvent.wVirtualKeyCode = 0x0D  # VK_RETURN
        record.Event.KeyEvent.wVirtualScanCode = 0x1C
        record.Event.KeyEvent.uChar = "\r"
        record.Event.KeyEvent.dwControlKeyState = NUMLOCK_ON
        events.append(record)
    return events


def _attach_parent_console() -> bool:
    """
    Detach from current console (if any) and attach to the parent process's console.

    MCP servers have piped stdin/stdout (MCP transport), so our own stdin
    is never a console. We must attach to the parent (Claude Code) process's
    console to access the real input buffer.

    Returns True if successfully attached.
    """
    # Detach from any current console (may fail if we don't have one — that's fine)
    kernel32.FreeConsole()

    # Attach to parent process's console
    if not kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
        error = ctypes.get_last_error()
        raise ConsoleNotAvailable(
            f"AttachConsole(ATTACH_PARENT_PROCESS) failed (error {error}). "
            f"Parent process may not have a console."
        )
    return True


def _detach_console():
    """Detach from the attached console."""
    kernel32.FreeConsole()


def _open_conin():
    """
    Open the CONIN$ device — the console input buffer of the attached console.

    Unlike GetStdHandle, CONIN$ always refers to the real console input buffer
    regardless of process-level handle redirection (pipes, etc.).

    Returns the handle. Caller must CloseHandle when done.
    """
    handle = kernel32.CreateFileW(
        "CONIN$",
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,           # security attributes
        OPEN_EXISTING,
        0,              # flags
        None,           # template
    )
    if handle == INVALID_HANDLE_VALUE:
        error = ctypes.get_last_error()
        raise ConsoleNotAvailable(f"CreateFile('CONIN$') failed (error {error})")
    return handle


def get_console_handle():
    """
    Attach to parent console and open CONIN$ for the console input buffer.

    Returns the CONIN$ handle. Caller is responsible for closing it and
    detaching the console when done.
    Raises ConsoleNotAvailable if the parent has no console or CONIN$ fails.
    """
    _attach_parent_console()

    try:
        handle = _open_conin()
    except ConsoleNotAvailable:
        _detach_console()
        raise

    # Validate it's a real console by checking GetConsoleMode
    mode = wintypes.DWORD()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(handle)
        _detach_console()
        raise ConsoleNotAvailable(
            f"GetConsoleMode on CONIN$ failed (error {error}). Not a real console."
        )

    return handle


def check_console() -> dict:
    """
    Check if we can attach to the parent process's console and open CONIN$.

    Returns a dict with:
        available: bool
        handle: int or None
        handle_type: str
        console_mode: str or None
        error: str or None
    """
    try:
        _attach_parent_console()
    except ConsoleNotAvailable as e:
        return {"available": False, "handle": None, "handle_type": "no_parent_console",
                "console_mode": None, "error": str(e)}

    try:
        handle = _open_conin()
    except ConsoleNotAvailable as e:
        _detach_console()
        return {"available": False, "handle": None, "handle_type": "conin_failed",
                "console_mode": None, "error": str(e)}

    mode = wintypes.DWORD()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(handle)
        _detach_console()
        return {"available": False, "handle": handle, "handle_type": "CONIN$",
                "console_mode": None, "error": f"GetConsoleMode failed (error {error})"}

    console_mode = f"0x{mode.value:04x}"
    kernel32.CloseHandle(handle)
    _detach_console()
    return {"available": True, "handle": handle, "handle_type": "CONIN$",
            "console_mode": console_mode, "error": None}


def _write_records(handle, records: list[INPUT_RECORD]) -> int:
    """Write a batch of INPUT_RECORDs to the console input buffer."""
    if not records:
        return 0
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
        raise InjectionError(f"WriteConsoleInputW failed (error {error})")
    return written.value


def inject(text: str, append_enter: bool = True) -> int:
    """
    Inject text into the parent process's console stdin buffer.

    Attaches to the parent console, opens CONIN$, writes key events,
    then cleans up. Each character becomes a key-down + key-up event pair.
    If append_enter is True, Enter is sent in a separate write after a
    small delay to ensure ConPTY processes the text first.

    Returns the number of input records written.
    Raises InjectionError on failure.
    """
    if sys.platform != "win32":
        raise InjectionError("Stdin injection is only supported on Windows")

    handle = get_console_handle()  # attaches to parent console, opens CONIN$

    try:
        # Build text character events
        text_records = []
        for char in text:
            text_records.append(_make_key_event(char, key_down=True))
            text_records.append(_make_key_event(char, key_down=False))

        total_written = _write_records(handle, text_records)

        if append_enter:
            # Delay so ConPTY processes text chars before Enter arrives.
            # 50ms was insufficient when the console was busy with output
            # (e.g., agent response still streaming). 250ms handles that.
            import time
            time.sleep(0.50)

            enter_records = _make_enter_events()
            total_written += _write_records(handle, enter_records)

        return total_written
    finally:
        kernel32.CloseHandle(handle)
        _detach_console()
