"""Frozen entry point. Kept tiny so the bundle's boot path is easy to reason about."""

import multiprocessing
import sys

if __name__ == "__main__":
    # PyInstaller apps must call this before anything may spawn a process,
    # otherwise a child re-runs the bundle's entry point and forks forever.
    multiprocessing.freeze_support()

    # Before any other import: numba reads NUMBA_CACHE_DIR when it is imported,
    # so anything that pulls numba in first makes this a no-op. It does not by
    # itself restore caching inside a frozen bundle -- see the docstring -- but
    # it is the right destination when caching can work at all.
    from spatialmind.app.config import configure_numba_cache

    configure_numba_cache()

    from spatialmind.app.desktop import main

    sys.exit(main())
