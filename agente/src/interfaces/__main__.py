"""Permite `python -m interfaces` como atajo del CLI."""

from __future__ import annotations

from interfaces.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
