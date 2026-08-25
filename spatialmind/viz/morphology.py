"""Morphology image and segmentation boundary loading for Xenium review views.

Xenium output bundles ship a multi-resolution OME-TIFF morphology pyramid and
per-cell segmentation polygons. Both are optional heavy assets, so every loader
here degrades to an explicit ``status`` payload instead of raising when the file
or the optional dependency is missing.

Coordinate convention: cell centroids and boundary vertices are in microns, and
the morphology image is in pixels. ``pixel = micron / pixel_size``, where
``pixel_size`` comes from ``experiment.xenium``.
"""

import base64
import io
import json
import os
from typing import Any, Dict, List, Optional, Sequence

MORPHOLOGY_PREFERENCE = (
    "morphology_focus.ome.tif",
    "morphology_mip.ome.tif",
    "morphology.ome.tif",
)
DEFAULT_MAX_DIMENSION = 1600
DEFAULT_MAX_BOUNDARY_CELLS = 3000


def _resolve_directory(dataset_path: str) -> str:
    if str(dataset_path).lower().endswith(".xenium"):
        return os.path.dirname(os.path.abspath(dataset_path))
    return dataset_path


def read_pixel_size(dataset_path: str) -> Optional[float]:
    """Microns per pixel from experiment.xenium, or None when unavailable."""
    directory = _resolve_directory(dataset_path)
    experiment_path = os.path.join(directory, "experiment.xenium")
    if not os.path.exists(experiment_path):
        return None
    try:
        with open(experiment_path, encoding="utf-8") as handle:
            experiment = json.load(handle)
        value = float(experiment.get("pixel_size"))
    except (ValueError, TypeError, OSError, json.JSONDecodeError):
        return None
    return value if value > 0 else None


def find_morphology_image(dataset_path: str) -> Optional[str]:
    directory = _resolve_directory(dataset_path)
    for name in MORPHOLOGY_PREFERENCE:
        candidate = os.path.join(directory, name)
        if os.path.exists(candidate):
            return candidate
    return None


def load_morphology_thumbnail(
    dataset_path: str,
    max_dimension: int = DEFAULT_MAX_DIMENSION,
) -> Dict[str, Any]:
    """Render a downsampled morphology image as an embeddable PNG data URI.

    Reads the smallest pyramid level whose largest edge still exceeds
    ``max_dimension`` so the returned image is detailed enough to review without
    decoding the full-resolution plane (which is hundreds of megabytes).
    """
    image_path = find_morphology_image(dataset_path)
    if not image_path:
        return {"status": "unavailable", "reason": "No morphology OME-TIFF was found in the Xenium bundle."}
    pixel_size = read_pixel_size(dataset_path)
    if not pixel_size:
        return {"status": "unavailable", "reason": "experiment.xenium did not provide a usable pixel_size."}
    try:
        import numpy as np  # type: ignore
        import tifffile  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError as exc:
        return {"status": "unavailable", "reason": "Morphology rendering needs tifffile, numpy, and Pillow (%s)." % exc}

    try:
        with tifffile.TiffFile(image_path) as handle:
            series = handle.series[0]
            levels = list(series.levels)
            level_index = _choose_level(levels, max_dimension)
            array = levels[level_index].asarray()
            full_height, full_width = _plane_shape(levels[0].shape)
        array = _to_2d_plane(array)
        thumbnail = _to_display_uint8(array, np, max_dimension, Image)
        buffer = io.BytesIO()
        thumbnail.save(buffer, format="PNG", optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception as exc:  # pragma: no cover - depends on local image files
        return {"status": "unavailable", "reason": "Morphology image could not be decoded: %s" % exc}

    return {
        "status": "loaded",
        "source": os.path.basename(image_path),
        "pyramid_level": level_index,
        "pyramid_levels": len(levels),
        "thumbnail_width": thumbnail.width,
        "thumbnail_height": thumbnail.height,
        "pixel_size_um": pixel_size,
        # Extent of the FULL-resolution plane in microns; the viewer stretches the
        # thumbnail across this extent so cells in micron space align with tissue.
        "width_um": round(full_width * pixel_size, 4),
        "height_um": round(full_height * pixel_size, 4),
        "data_uri": "data:image/png;base64,%s" % encoded,
    }


def _choose_level(levels: Sequence[Any], max_dimension: int) -> int:
    """Smallest level whose largest edge is still >= max_dimension.

    When no level reaches ``max_dimension`` the full-resolution level 0 is used,
    since that is the most detailed image available.
    """
    best = 0
    for index in range(len(levels) - 1, -1, -1):
        height, width = _plane_shape(levels[index].shape)
        if max(height, width) >= max_dimension:
            best = index
            break
    return best


def _plane_shape(shape: Sequence[int]) -> tuple:
    dims = [int(value) for value in shape]
    if len(dims) >= 2:
        return dims[-2], dims[-1]
    raise ValueError("Unexpected morphology plane shape: %s" % (shape,))


def _to_2d_plane(array: Any) -> Any:
    while getattr(array, "ndim", 2) > 2:
        array = array[0]
    return array


def _to_display_uint8(array: Any, np: Any, max_dimension: int, Image: Any) -> Any:
    """Percentile contrast stretch to 8-bit, then fit within max_dimension."""
    data = np.asarray(array, dtype="float32")
    low, high = np.percentile(data, [1.0, 99.5])
    if high <= low:
        low, high = float(data.min()), float(data.max())
    if high <= low:
        scaled = np.zeros(data.shape, dtype="uint8")
    else:
        scaled = np.clip((data - low) / (high - low), 0.0, 1.0)
        scaled = (scaled * 255.0).astype("uint8")
    image = Image.fromarray(scaled)
    if max(image.width, image.height) > max_dimension:
        scale = max_dimension / float(max(image.width, image.height))
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
            Image.BILINEAR,
        )
    return image


def load_cell_boundaries(
    dataset_path: str,
    cell_ids: Optional[Sequence[str]] = None,
    max_cells: int = DEFAULT_MAX_BOUNDARY_CELLS,
) -> Dict[str, Any]:
    """Load per-cell segmentation polygons (microns) keyed by cell_id."""
    directory = _resolve_directory(dataset_path)
    parquet_path = os.path.join(directory, "cell_boundaries.parquet")
    if not os.path.exists(parquet_path):
        return {"status": "unavailable", "reason": "cell_boundaries.parquet was not found.", "polygons": {}}
    try:
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as exc:
        return {"status": "unavailable", "reason": "Boundary loading needs pyarrow (%s)." % exc, "polygons": {}}

    wanted = {str(value) for value in cell_ids} if cell_ids is not None else None
    polygons: Dict[str, List[List[float]]] = {}
    try:
        parquet_file = pq.ParquetFile(parquet_path)
        for batch in parquet_file.iter_batches(batch_size=65536, columns=["cell_id", "vertex_x", "vertex_y"]):
            data = batch.to_pydict()
            for cell_id, x, y in zip(data["cell_id"], data["vertex_x"], data["vertex_y"]):
                key = cell_id.decode("utf-8") if isinstance(cell_id, bytes) else str(cell_id)
                if wanted is not None and key not in wanted:
                    continue
                if key not in polygons:
                    if len(polygons) >= max_cells:
                        continue
                    polygons[key] = []
                polygons[key].append([round(float(x), 3), round(float(y), 3)])
            if wanted is not None and len(polygons) >= len(wanted):
                break
    except Exception as exc:  # pragma: no cover - depends on local parquet files
        return {"status": "unavailable", "reason": "Boundaries could not be read: %s" % exc, "polygons": {}}

    return {
        "status": "loaded" if polygons else "empty",
        "source": os.path.basename(parquet_path),
        "cell_count": len(polygons),
        "vertex_count": sum(len(value) for value in polygons.values()),
        "polygons": polygons,
    }
