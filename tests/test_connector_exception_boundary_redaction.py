from __future__ import annotations

import traceback
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from powerops.human_sessions import HumanSessionPrincipal, HumanSessionRejected
from powerops.postgres_certificate_connector import (
    HumanPostgresCredentials,
    PsycopgHumanSessionConnector,
)


SECRET_MARKER = "SYNTHETIC_CONNECTOR_PROVIDER_SECRET"


class ChainedRejectedProvider:
    @contextmanager
    def materialize_credentials(self, principal):
        try:
            raise RuntimeError(SECRET_MARKER)
        except RuntimeError as exc:
            raise HumanSessionRejected("provider rejected credentials") from exc
        yield  # pragma: no cover


def test_connector_sanitizes_already_translated_provider_exception_chain() -> None:
    principal = HumanSessionPrincipal(
        session_id=uuid4(),
        issuer="https://identity.customer.example",
        subject="operator-1",
        tenant_id=uuid4(),
        business_unit_id=uuid4(),
        finance_verifier=True,
    )
    connector = PsycopgHumanSessionConnector(ChainedRejectedProvider())

    with pytest.raises(HumanSessionRejected) as captured:
        with connector.connect(principal):
            pytest.fail("Provider rejection must prevent connection admission")

    rendered = "".join(
        traceback.format_exception(
            type(captured.value), captured.value, captured.value.__traceback__
        )
    )
    assert str(captured.value) == "Customer human-session credentials are unavailable"
    assert SECRET_MARKER not in str(captured.value)
    assert SECRET_MARKER not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True
