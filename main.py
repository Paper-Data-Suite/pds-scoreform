"""Backward-compatibility wrapper for scoreform CLI.

This module maintains compatibility with direct `python main.py` invocations
while the actual implementation has moved to scoreform.cli.
"""

from scoreform.cli import main

if __name__ == "__main__":
    raise SystemExit(main(default_to_menu=False))
