"""HTTP application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from powerops import __version__
from powerops.auth import OidcJwtVerifier
from powerops.config import get_settings
from powerops.postgres_repository import PostgresRevenueAssuranceRepository
from powerops.revenue_assurance import router as revenue_assurance_router

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Drain application-owned resources when the ASGI application shuts down."""
    try:
        yield
    finally:
        _close_database_pool()


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Evidence-led utility revenue assurance and distribution-network intelligence.",
    lifespan=lifespan,
)


# Customer broker adapters are injected by deployment configuration. No test or
# in-memory implementation is enabled by default.
app.state.human_session_issuer = None
app.state.revenue_assurance_repository = (
    PostgresRevenueAssuranceRepository(
        settings.database_url.get_secret_value(),
        pool_min_size=settings.database_pool_min_size,
        pool_max_size=settings.database_pool_max_size,
        pool_timeout=settings.database_pool_timeout_seconds,
    )
    if settings.database_url is not None
    else None
)
app.state.jwt_verifier = (
    OidcJwtVerifier(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        jwks_url=settings.oidc_jwks_url,
    )
    if (
        settings.oidc_issuer is not None
        and settings.oidc_audience is not None
        and settings.oidc_jwks_url is not None
    )
    else None
)
app.include_router(revenue_assurance_router)


@app.get("/health/live", tags=["operations"])
def liveness() -> dict[str, str]:
    """Process liveness only; does not imply dependency readiness."""
    return {"status": "alive", "service": "powerops"}


@app.get("/health/pool", tags=["operations"])
def pool_health() -> dict[str, object]:
    """Expose non-secret connection-pool telemetry; never expose tenant IDs or DSNs."""
    repository = app.state.revenue_assurance_repository
    if not isinstance(repository, PostgresRevenueAssuranceRepository):
        raise HTTPException(
            status_code=503,
            detail="BU-scoped PostgreSQL repository is not configured",
        )
    return repository.pool_health()


@app.get("/health/ready", tags=["operations"])
def readiness() -> dict[str, str]:
    """Report ready only when authentication and scoped persistence are configured."""
    if app.state.jwt_verifier is None or settings.database_url is None:
        raise HTTPException(
            status_code=503,
            detail="OIDC authentication and BU-scoped PostgreSQL must be configured",
        )
    try:
        import psycopg

        with psycopg.connect(
            settings.database_url.get_secret_value(), connect_timeout=3
        ) as connection:
            identity = connection.execute(
                "SELECT scope_kind FROM powerops_security.resolve_authenticated_scope()"
            ).fetchone()
            connection.execute("SELECT 1 FROM revenue_assurance.findings LIMIT 0")
        if identity is None or identity[0] != "business_unit":
            raise RuntimeError("Database identity is not business-unit scoped")
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Configured PostgreSQL dependency or business-unit scope is unavailable",
        ) from exc
    return {
        "status": "ready",
        "stage": "database_and_authentication_configured",
        "readiness_scope": "oidc_and_postgresql_business_unit_scope",
        "dependency_checks": "oidc_configured_and_postgresql_scope_verified",
    }


def _close_database_pool() -> None:
    """Drain the application-owned PostgreSQL pool on process shutdown."""
    repository = app.state.revenue_assurance_repository
    if isinstance(repository, PostgresRevenueAssuranceRepository):
        repository.close()
