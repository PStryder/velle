"""
Read raw console input events and dump them.
Run this directly in a terminal, type some characters + Enter, and see
exactly what KEY_EVENT records the console produces.

Press Ctrl+C to exit.
"""

import ctypes
import ctypes.wintypes as wintypes
import msvcrt

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

STD_INPUT_HANDLE = -10
KEY_EVENT = 0x0001


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


def main():
    handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)

    # Show current console mode
    mode = wintypes.DWORD()
    kernel32.GetConsoleMode(handle, ctypes.byref(mode))
    print(f"Console mode: 0x{mode.value:04x}")
    print(f"Handle: {handle}")
    print(f"FileType: {kernel32.GetFileType(handle)}")
    print()
    print("Type characters and Enter. Ctrl+C to exit.")
    print("=" * 80)

    records = (INPUT_RECORD * 1)()
    read_count = wintypes.DWORD()

    try:
        while True:
            success = kernel32.ReadConsoleInputW(
                handle, records, 1, ctypes.byref(read_count)
            )
            if not success or read_count.value == 0:
                continue

            rec = records[0]
            if rec.EventType == KEY_EVENT:
                ke = rec.Event.KeyEvent
                char_val = ord(ke.uChar) if ke.uChar else 0
                print(
                    f"KEY  down={ke.bKeyDown:<5}  "
                    f"VK=0x{ke.wVirtualKeyCode:04x}  "
                    f"scan=0x{ke.wVirtualScanCode:04x}  "
                    f"char=0x{char_val:04x} ({repr(ke.uChar)})  "
                    f"repeat={ke.wRepeatCount}  "
                    f"ctrl=0x{ke.dwControlKeyState:08x}"
                )
            else:
                print(f"EVENT type={rec.EventType}")
    except KeyboardInterrupt:
        print("\nDone.")


if __name__ == "__main__":
    main()
