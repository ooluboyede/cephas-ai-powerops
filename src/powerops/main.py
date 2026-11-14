"""HTTP application entry point."""

from fastapi import FastAPI, HTTPException

from powerops import __version__
from powerops.auth import OidcJwtVerifier
from powerops.config import get_settings
from powerops.postgres_repository import PostgresRevenueAssuranceRepository
from powerops.revenue_assurance import router as revenue_assurance_router

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Evidence-led utility revenue assurance and distribution-network intelligence.",
)


app.state.revenue_assurance_repository = (
    PostgresRevenueAssuranceRepository(settings.database_url.get_secret_value())
    if settings.database_url is not None
    else None
)
app.state.jwt_verifier = (
    OidcJwtVerifier(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        jwks_url=settings.oidc_jwks_url,
    )
    if settings.oidc_issuer and settings.oidc_audience and settings.oidc_jwks_url
    else None
)
app.include_router(revenue_assurance_router)


@app.get("/health/live", tags=["operations"])
def liveness() -> dict[str, str]:
    """Process liveness only; does not imply dependency readiness."""
    return {"status": "alive", "service": "powerops"}


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
