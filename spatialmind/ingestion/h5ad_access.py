"""Explicit HDF5 matrix selection and bounded observation-column reads."""

from .expression import resolve_expression_semantics


def scalar(handle, path, default=None):
    import h5py

    node = handle.get(path)
    if node is None or not isinstance(node, h5py.Dataset) or node.shape != ():
        return default
    if node.attrs.get("encoding-type") in {"null", b"null"}:
        return default
    value = node[()]
    return value.decode("utf-8") if isinstance(value, bytes) else value


def select_matrix(handle, expression_layer="auto", expression_semantics="auto"):
    """Return matrix, matching var, path and semantics; raw.X is not assumed raw."""
    layer = expression_layer
    if layer == "auto":
        layer = next(("layers/" + k for k in ("counts", "raw_counts") if "layers/" + k in handle), "X")
    if layer == "raw.X":
        layer = "raw/X"
    if layer not in {"X", "raw/X"} and not (layer.startswith("layers/") and layer.count("/") == 1):
        raise ValueError("expression_layer must be auto, X, raw.X or layers/<name>.")
    var_path = "raw/var" if layer == "raw/X" else "var"
    if layer not in handle or var_path not in handle:
        raise ValueError("Requested expression layer or its feature metadata is missing: %s" % layer)
    counts_key = layer.split("/")[-1] if layer in {"layers/counts", "layers/raw_counts"} else None
    # X's log metadata does not describe raw.X or an unrelated named layer.
    semantics = resolve_expression_semantics(
        expression_semantics, counts_key,
        has_log1p=layer == "X" and "uns/log1p" in handle,
        declared=scalar(handle, "uns/spatialmind/expression_semantics") if layer == "X" else None,
        log_base=scalar(handle, "uns/log1p/base") if layer == "X" else None,
    )
    return handle[layer], handle[var_path], layer, semantics


def column_values(group, name, rows=None):
    """Decode only requested rows, including categorical columns with missing codes."""
    import h5py

    node = group.get(name)
    if node is None:
        return []
    def read(dataset):
        if rows is None:
            return dataset[:]
        if not len(rows):
            return []
        if len(rows) == len(dataset) and rows[0] == 0 and rows[-1] == len(dataset) - 1:
            return dataset[:]
        # HDF5 fancy indexing becomes expensive for huge index lists. Bound each
        # selection without logically reading excluded donors' label values.
        values = []
        for start in range(0, len(rows), 1024):
            values.extend(dataset[rows[start:start + 1024]])
        return values
    def decode(value):
        if value is None:
            return ""
        return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
    if isinstance(node, h5py.Group):
        if "codes" not in node or "categories" not in node:
            raise ValueError("Unsupported observation column encoding: %s" % name)
        codes = read(node["codes"])
        # Read only categories actually used by selected observations.
        lookup = {int(c): decode(node["categories"][int(c)]) for c in set(codes) if c >= 0}
        return [lookup.get(int(c), "") for c in codes]
    return [decode(value) for value in read(node)]
