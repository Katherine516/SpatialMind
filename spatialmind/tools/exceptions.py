class ToolExecutionError(RuntimeError):
    pass


class InsufficientDataError(ToolExecutionError):
    pass


class MissingPreconditionError(ToolExecutionError):
    pass


class AlgorithmConvergenceError(ToolExecutionError):
    pass


class InvalidParameterError(ToolExecutionError):
    pass


class DataModalityError(ToolExecutionError):
    """Raised when a tool is called on an incompatible data modality."""

    def __init__(self, tool: str, got: str, expected: str) -> None:
        super().__init__("%s requires %s data, got %s." % (tool, expected, got or "unknown"))
