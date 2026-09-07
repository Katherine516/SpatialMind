#!/usr/bin/env python3
"""Render the app icon to Apple's macOS template, then build the .icns.

The source art is a full-bleed square with opaque black corners. macOS draws
that edge to edge, so next to Claude Code, Codex or any system app the icon
looks oversized and square-shouldered -- those follow the template, where the
artwork is an 824x824 rounded square centred on a 1024x1024 transparent canvas.
The ~20% of empty margin is what makes every Dock icon read as the same size.

The corner is a superellipse, not a circular-arc rounded rectangle: macOS uses a
continuously curving corner, and an arc corner is visibly "pinched" where it
meets the straight edge at these sizes.
"""

from pathlib import Path
import argparse
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "docs" / "icon.png"
DEFAULT_PNG = ROOT / "packaging" / "SpatialMindStudio.png"
DEFAULT_ICNS = ROOT / "packaging" / "SpatialMindStudio.icns"

CANVAS = 1024
BODY = 824              # Apple's macOS app-icon body on a 1024 canvas
SUPERELLIPSE_N = 5.0    # approximates the macOS continuous corner
SUPERSAMPLE = 4         # mask is built large and downsampled for clean edges


def squircle_mask(size: int, exponent: float = SUPERELLIPSE_N):
    """Alpha mask for a superellipse: |x|^n + |y|^n <= 1 over [-1, 1]."""
    from PIL import Image
    import numpy as np

    big = size * SUPERSAMPLE
    axis = (np.arange(big) + 0.5) / big * 2.0 - 1.0
    x = np.abs(axis)[None, :] ** exponent
    y = np.abs(axis)[:, None] ** exponent
    inside = (x + y) <= 1.0
    mask = Image.fromarray((inside * 255).astype("uint8"))
    return mask.resize((size, size), Image.LANCZOS)


def build_png(source: Path, out: Path, crop: float, shadow: bool = True) -> Path:
    from PIL import Image, ImageFilter

    art = Image.open(source).convert("RGBA")
    if crop > 0:
        # The source draws its own thin rounded frame inside a black square.
        # Trimming it lets the template's corner be the only one visible.
        inset = int(min(art.size) * crop)
        art = art.crop((inset, inset, art.width - inset, art.height - inset))
    art = art.resize((BODY, BODY), Image.LANCZOS)

    mask = squircle_mask(BODY)
    body = Image.new("RGBA", (BODY, BODY), (0, 0, 0, 0))
    body.paste(art, (0, 0), mask)

    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    offset = (CANVAS - BODY) // 2
    if shadow:
        # macOS bakes a soft shadow into the artwork; without it the icon sits
        # flat against the Dock while its neighbours have depth.
        layer = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
        layer.paste(Image.new("RGBA", (BODY, BODY), (0, 0, 0, 110)), (offset, offset + 8), mask)
        canvas = Image.alpha_composite(canvas, layer.filter(ImageFilter.GaussianBlur(10)))
    canvas.paste(body, (offset, offset), body)

    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out


def build_icns(png: Path, icns: Path) -> bool:
    if shutil.which("iconutil") is None or shutil.which("sips") is None:
        print("sips/iconutil unavailable; wrote the PNG only.")
        return False
    iconset = icns.with_suffix(".iconset")
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            pixels = size * scale
            name = "icon_%dx%d%s.png" % (size, size, "@2x" if scale == 2 else "")
            subprocess.run(["sips", "-z", str(pixels), str(pixels), str(png), "--out", str(iconset / name)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)], check=True)
    shutil.rmtree(iconset, ignore_errors=True)
    return icns.exists()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the macOS app icon.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--png", default=str(DEFAULT_PNG))
    parser.add_argument("--icns", default=str(DEFAULT_ICNS))
    parser.add_argument("--crop", type=float, default=0.035,
                        help="Fraction trimmed from each edge of the source before masking.")
    parser.add_argument("--no-shadow", action="store_true")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        print("No source icon at %s" % source)
        return 1
    try:
        from PIL import Image  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        print("Pillow and numpy are needed to build the icon.")
        return 1

    png = build_png(source, Path(args.png), args.crop, shadow=not args.no_shadow)
    print("icon png : %s (%dx%d canvas, %dpx body)" % (png, CANVAS, CANVAS, BODY))
    icns = Path(args.icns)
    if build_icns(png, icns):
        print("icon icns: %s (%.0f KB)" % (icns, icns.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
