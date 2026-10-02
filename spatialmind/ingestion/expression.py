"""Explicit expression-layer semantics; never normalize an unknown matrix."""


def resolve_expression_semantics(requested="auto", counts_layer=None, has_log1p=False, declared=None, log_base=None):
    allowed = {"raw_counts", "log_normalized"}
    if requested not in allowed | {"auto"}:
        raise ValueError("expression_semantics must be auto, raw_counts or log_normalized")
    if counts_layer:
        if requested == "log_normalized":
            raise ValueError("A counts layer cannot be declared log_normalized")
        return "raw_counts"
    if has_log1p and log_base is not None:
        raise ValueError("Only natural-log log1p expression is supported; convert other log bases explicitly.")
    if requested in allowed:
        return requested
    if declared in allowed:
        return declared
    if has_log1p:
        return "log_normalized"
    raise ValueError("H5AD X has unknown expression semantics. Supply expression_semantics=raw_counts "
                     "or log_normalized, or declare uns['spatialmind']['expression_semantics']; "
                     "scaled matrices require a separate counts/log-normalized layer.")
