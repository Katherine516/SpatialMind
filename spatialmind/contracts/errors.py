class SpatialMindError(RuntimeError):
    """Base class for typed SpatialMind failures."""


class ContractViolationError(SpatialMindError):
    """Raised when a layer attempts to emit an invalid boundary contract."""


class PlanValidationError(SpatialMindError):
    """Raised when an execution plan references unknown tools or invalid params."""


class SpatialToolError(SpatialMindError):
    """Base class for typed tool failures."""


class InsufficientDataError(SpatialToolError):
    pass


class MissingPreconditionError(SpatialToolError):
    pass


class DataModalityError(SpatialToolError):
    pass
