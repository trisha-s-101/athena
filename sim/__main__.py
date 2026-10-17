"""
sim/__main__.py  --  Dispatch for `python -m sim.<subcommand>`.

Allows:
    python -m sim.run   ...   (handled by sim/run.py's own __main__ block)
    python -m sim.live  ...   (handled by sim/live.py's own __main__ block)

This file is the entry point for `python -m sim` with no subcommand.
"""

import sys


def main() -> None:
    print("Usage: python -m sim.run [--days N] [--seed N]")
    print("       python -m sim.live [--api URL] [--speed N]")
    sys.exit(1)


if __name__ == "__main__":
    main()
