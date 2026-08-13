class NativeExecutionError(RuntimeError):
    pass

class CapabilityUnavailable(NativeExecutionError):
    pass

class PermissionDenied(NativeExecutionError):
    pass

class ToolNotGranted(PermissionDenied):
    pass

class ProviderUnavailable(NativeExecutionError):
    pass

class AreaIsolationError(NativeExecutionError):
    pass

class InvalidStateTransition(NativeExecutionError):
    pass

class ValidationError(NativeExecutionError):
    pass

class LegacyEngineReviewRequired(NativeExecutionError):
    pass

class ExactRagAdapterError(NativeExecutionError):
    pass

class ExactRagDependencyError(ExactRagAdapterError):
    pass

class ExactRagProvenanceError(ExactRagAdapterError):
    pass

class StaleProposalError(NativeExecutionError):
    pass

class ResourceLimitError(ValidationError):
    pass
