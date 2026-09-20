"""Where a packaged Studio keeps its settings and looks for data.

Run from a checkout, `data/` sits next to the code and everything is obvious.
Inside a `.app` the working directory is `/`, so the data root has to be
remembered somewhere durable and be changeable without editing a file by hand.
"""

from pathlib import Path
from typing import Any, Dict
import json
import os
import sys

APP_NAME = "SpatialMind"


def is_frozen() -> bool:
    """True inside a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def support_dir() -> Path:
    # The override exists so a test can be given its own directory: without it
    # anything exercising the review sidecar writes into the real
    # ~/Library/Application Support and leaves it there.
    override = os.environ.get("SPATIALMIND_SUPPORT_DIR")
    if override:
        base = Path(override).expanduser()
        base.mkdir(parents=True, exist_ok=True)
        return base
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":  # pragma: no cover - packaged target is macOS
        base = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    else:  # pragma: no cover
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path() -> Path:
    return support_dir() / "config.json"


def load() -> Dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        # A corrupt config must not stop the app booting; defaults are fine.
        return {}


def save(values: Dict[str, Any]) -> Path:
    path = config_path()
    current = load()
    current.update(values)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return path


def default_data_root() -> str:
    """Env var, then saved config, then a sensible home folder we create."""
    env = os.environ.get("SPATIALMIND_DATA_ROOT")
    if env:
        return str(Path(env).expanduser())
    saved = load().get("data_root")
    if saved:
        return str(Path(saved).expanduser())
    if not is_frozen() and Path("data").is_dir():
        return str(Path("data").resolve())
    # Not ~/Documents: macOS gates it behind a TCC consent prompt, so a packaged
    # app pointed there on first launch appears to hang instead of listing data.
    # The home folder itself is not gated. A user who keeps data in Documents can
    # still point the app there from the Datasets screen and answer the prompt.
    chosen = Path.home() / APP_NAME / "data"
    chosen.mkdir(parents=True, exist_ok=True)
    return str(chosen)


def default_output_root() -> str:
    env = os.environ.get("SPATIALMIND_OUTPUT_ROOT")
    if env:
        return str(Path(env).expanduser())
    saved = load().get("output_root")
    if saved:
        return str(Path(saved).expanduser())
    if not is_frozen() and Path("outputs").is_dir():
        return str((Path("outputs") / "studio").resolve())
    path = Path.home() / APP_NAME / "outputs"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)
