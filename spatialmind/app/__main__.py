"""Launch SpatialMind Studio: `python -m spatialmind.app`.

Same three modes as the packaged app -- native window, plain browser, or
headless server -- so what you run from a checkout is what ships.
"""

import argparse
import logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SpatialMind Studio locally.")
    parser.add_argument("--data-root", default=None,
                        help="Folder scanned for Xenium bundles. Defaults to the saved config, then ./data.")
    parser.add_argument("--output-root", default=None, help="Where run artifacts are written.")
    parser.add_argument("--port", type=int, default=0, help="Bind port; 0 picks a free one near 8765.")
    parser.add_argument("--browser", action="store_true", help="Open the default browser instead of a window.")
    parser.add_argument("--headless", action="store_true", help="Serve only; open nothing.")
    args = parser.parse_args()

    from . import config, desktop

    desktop.setup_logging()
    app = desktop.create_app_for(data_root=args.data_root, output_root=args.output_root)
    port = args.port or desktop.choose_port()
    url = "http://localhost:%d/" % port
    print("SpatialMind Studio -> %s" % url)
    print("  data root   : %s" % app.state.studio.data_root)
    print("  output root : %s" % app.state.studio.output_root)

    if args.headless:
        raise SystemExit(desktop.run_headless(app, port, url))
    if args.browser:
        raise SystemExit(desktop.run_browser(app, port, url))
    try:
        import webview  # noqa: F401
    except ImportError:
        logging.warning("pywebview is not installed; opening the default browser instead")
        raise SystemExit(desktop.run_browser(app, port, url))
    raise SystemExit(desktop.run_windowed(app, port, url))


if __name__ == "__main__":
    main()
