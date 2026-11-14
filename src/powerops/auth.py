"""Authentication integration boundary for PowerOps.

An OIDC/JWT verifier must populate request.state.authenticated_principal only
after issuer, audience, signature, expiry and role claims are validated.
This module intentionally does not accept tenant or business-unit headers.
"""
from powerops.revenue_assurance import AuthenticatedPrincipal, get_current_principal

__all__ = ["AuthenticatedPrincipal", "get_current_principal"]
