import os
from collections.abc import Callable
from typing import Any, TypeVar


F = TypeVar('F', bound=Callable[..., Any])

# Try importing braintrust, but don't fail if it's not available
try:
    from braintrust import traced as braintrust_traced

    BRAINTRUST_AVAILABLE = True
except ImportError:
    BRAINTRUST_AVAILABLE = False


def traced(type: str | None = None) -> Callable[[F], F]:
    """No-op replacement for braintrust.traced when braintrust is not available."""

    def decorator(func: F) -> F:
        if BRAINTRUST_AVAILABLE and os.getenv('BRAINTRUST_API_KEY'):
            return braintrust_traced(type=type)(func)  # type: ignore
        return func

    return decorator
