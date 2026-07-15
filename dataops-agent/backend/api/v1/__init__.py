from . import (
    # Phase 1
    auth, uploads,
    # Phase 2
    sources, pipelines, runs, quality, incidents,
    # Phase 3
    governance, approvals, analytics,
    # Phase 4
    transformations,
    # Agent
    chat,
    # Frontend Phase 4 (onboarding)
    onboarding,
)

__all__ = [
    "auth", "uploads",
    "sources", "pipelines", "runs", "quality", "incidents",
    "governance", "approvals", "analytics",
    "transformations",
    "chat",
    "onboarding",
]