"""Frozen entry point. Kept tiny so the bundle's boot path is easy to reason about."""

import multiprocessing
import sys

if __name__ == "__main__":
    # PyInstaller apps must call this before anything may spawn a process,
    # otherwise a child re-runs the bundle's entry point and forks forever.
    multiprocessing.freeze_support()
    from spatialmind.app.desktop import main

    sys.exit(main())
