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
    """Process liveness only; does not imply database or integration readiness."""
    return {"status": "alive", "service": "powerops"}


@app.get("/health/ready", tags=["operations"])
def readiness() -> dict[str, str]:
    """Bootstrap readiness; dependency checks will be added with infrastructure."""
    return {"status": "ready", "stage": "foundation"}
