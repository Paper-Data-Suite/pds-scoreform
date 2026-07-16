"""Build one deterministic unsupported-schema QR image for CLI smoke tests."""

from __future__ import annotations

import sys
from pathlib import Path

import qrcode

UNSUPPORTED_PAYLOAD = "PDS1|module=scoreform|class=class1"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Usage: build_unsupported_qr_smoke.py <output.png>")
        return 2
    output = Path(args[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(UNSUPPORTED_PAYLOAD).save(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
