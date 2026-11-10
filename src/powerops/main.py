"""HTTP application entry point."""

from fastapi import FastAPI

from powerops import __version__
from powerops.config import get_settings

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Advisory feeder and transformer intelligence for distribution utilities.",
)


@app.get("/health/live", tags=["operations"])
def liveness() -> dict[str, str]:
    """Process liveness only; does not imply dependency readiness."""
    return {"status": "alive", "service": "powerops"}


@app.get("/health/ready", tags=["operations"])
def readiness() -> dict[str, str]:
    """Report bootstrap readiness without implying unimplemented dependencies are healthy.

    The foundation has no database or utility connectors to probe. When required
    dependencies are introduced, this endpoint must check them and return a
    non-2xx response whenever a required dependency is unavailable.
    """
    return {
        "status": "ready",
        "stage": "foundation",
        "readiness_scope": "bootstrap_only",
        "dependency_checks": "not_configured",
    }
