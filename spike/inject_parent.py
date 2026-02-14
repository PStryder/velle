"""
Velle Phase 0 Spike: Parent Process Test

Simulates the Claude Code → MCP server relationship:
1. This script acts as the "parent" (like Claude Code)
2. It spawns inject_test.py as a child process (like the MCP server)
3. The child injects text into the shared console
4. This script reads stdin to verify the injection arrived

Run from a terminal:
    python spike/inject_parent.py
"""

import os
import subprocess
import sys
import time


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    inject_script = os.path.join(script_dir, "inject_test.py")

    method = sys.argv[1] if len(sys.argv) > 1 else "direct"

    print(f"Velle Injection Parent Test")
    print(f"===========================")
    print(f"Parent PID: {os.getpid()}")
    print(f"Spawning child with method: {method}")
    print(f"After injection, you should see 'hello from velle' appear as input.")
    print(f"Press Ctrl+C to exit.")
    print()

    # Spawn child process — inherits our console by default on Windows
    child = subprocess.Popen(
        [sys.executable, inject_script, method],
        # No stdin/stdout/stderr redirection — child inherits our console
    )

    # Wait for child to finish
    child.wait()
    print()
    print(f"Child exited with code {child.returncode}")
    print(f"If injection worked, 'hello from velle' should appear below as input.")
    print(f"Waiting for stdin (press Enter if nothing appeared)...")
    print()

    # Read from stdin to see if the injection arrived
    try:
        line = input("> ")
        if "hello from velle" in line:
            print(f"\n*** SUCCESS: Received injected text: {line!r} ***")
        else:
            print(f"\n*** RECEIVED: {line!r} (not the expected injection) ***")
    except KeyboardInterrupt:
        print(f"\nExiting.")
    except EOFError:
        print(f"\nEOF on stdin.")


if __name__ == "__main__":
    main()
