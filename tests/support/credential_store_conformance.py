"""Reusable conformance assertions for HumanSessionCredentialStore adapters.

Concrete adapter test modules should call this helper with an isolated adapter
and a factory that returns a fresh, valid credential mapping. Provider-specific
tests must separately prove encryption, workload identity, IAM, audit and live
revocation behavior; these assertions cover only the application contract.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from powerops.human_session_issuer import (
    HumanSessionCredentialConflict,
    HumanSessionCredentialStore,
    StoredHumanSessionCredential,
)


CredentialFactory = Callable[..., dict[str, Any]]


def assert_human_session_store_conformance(
    adapter: HumanSessionCredentialStore,
    credential_factory: CredentialFactory,
) -> None:
    """Assert immutable exact-session, conflict, expiry and revocation semantics."""
    first = credential_factory()
    second = credential_factory(subject="finance.user.conformance.second")

    adapter.store_session(**first)
    adapter.store_session(**first)  # identical retry must be idempotent

    session_id = first["session_id"]
    stored = adapter.get_session(session_id)
    assert isinstance(stored, StoredHumanSessionCredential)
    assert stored.session_id == session_id
    assert adapter.get_session(uuid4()) is None  # exact UUID; no fallback

    changed = dict(first)
    changed["subject"] = "finance.user.changed"
    try:
        adapter.store_session(**changed)
    except HumanSessionCredentialConflict:
        pass
    else:
        raise AssertionError("changed content reused an immutable session UUID")

    # A conflicting retry must not mutate the original record.
    after_conflict = adapter.get_session(session_id)
    assert after_conflict == stored

    adapter.store_session(**second)
    adapter.revoke_session(session_id)
    adapter.revoke_session(session_id)  # revocation must be idempotent
    assert adapter.get_session(session_id) is None
    assert adapter.get_session(second["session_id"]) is not None

    expired = credential_factory(
        expires_at=credential_factory.expired_timestamp()
    )
    adapter.store_session(**expired)
    assert adapter.get_session(expired["session_id"]) is None
