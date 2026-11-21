from __future__ import annotations

import ast
import traceback
from pathlib import Path
from uuid import uuid4

import pytest

from powerops.human_sessions import HumanSessionPrincipal
from powerops.postgres_certificate_connector import (
    VaultBackedHumanPostgresCredentialProvider,
)


ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_BOUNDARIES = (
    "src/powerops/human_session_issuer.py",
    "src/powerops/postgres_certificate_connector.py",
    "src/powerops/identity_broker.py",
)


@pytest.mark.parametrize("relative_path", SENSITIVE_BOUNDARIES)
def test_sensitive_boundary_handlers_suppress_original_exception_chains(
    relative_path: str,
) -> None:
    """Translated provider errors must not expose original exception context."""
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))

    for handler in (
        node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)
    ):
        for statement in ast.walk(handler):
            if isinstance(statement, ast.Raise) and statement.exc is not None:
                assert isinstance(statement.cause, ast.Constant), (
                    f"{relative_path}:{statement.lineno} must explicitly suppress "
                    "the original exception context"
                )
                assert statement.cause.value is None, (
                    f"{relative_path}:{statement.lineno} must use 'raise ... from None'"
                )


class SecretLeakingStore:
    def get_session(self, session_id):
        raise RuntimeError("provider response contained SYNTHETIC_SECRET_MARKER")


def test_vault_lookup_redacts_secret_from_formatted_traceback(tmp_path: Path) -> None:
    principal = HumanSessionPrincipal(
        session_id=uuid4(),
        issuer="https://identity.customer.example",
        subject="finance.user.17",
        tenant_id=uuid4(),
        business_unit_id=uuid4(),
        finance_verifier=True,
    )
    provider = VaultBackedHumanPostgresCredentialProvider(
        SecretLeakingStore(),
        host="db.customer.example",
        port=5432,
        database_name="powerops",
        root_certificate_path=tmp_path / "root.crt",
        secure_temp_directory=tmp_path,
    )

    with pytest.raises(Exception) as captured:
        with provider.materialize_credentials(principal):
            pytest.fail("credential lookup must fail closed")

    rendered = "".join(
        traceback.format_exception(
            type(captured.value), captured.value, captured.value.__traceback__
        )
    )
    assert "SYNTHETIC_SECRET_MARKER" not in str(captured.value)
    assert "SYNTHETIC_SECRET_MARKER" not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True
