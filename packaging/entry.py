"""Frozen entry point. Kept tiny so the bundle's boot path is easy to reason about."""

import multiprocessing
import sys

if __name__ == "__main__":
    # PyInstaller apps must call this before anything may spawn a process,
    # otherwise a child re-runs the bundle's entry point and forks forever.
    multiprocessing.freeze_support()

    # Before any other import: numba reads NUMBA_CACHE_DIR when it is imported,
    # and inside an installed .app its default cache location is not writable.
    # Without this it recompiles scanpy's kernels on every launch -- 35 seconds
    # before the first result, every time.
    from spatialmind.app.config import configure_numba_cache

    configure_numba_cache()

    from spatialmind.app.desktop import main

    sys.exit(main())
