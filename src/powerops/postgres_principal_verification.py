"""Runtime verification of dedicated PostgreSQL revocation principals.

A distinct Python factory is not an identity boundary. This module verifies
what PostgreSQL actually authenticated and the narrowly assigned function
privileges before the coordinator is returned to the application.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


class PostgresPrincipalVerificationError(RuntimeError):
    """A customer PostgreSQL connection does not match its declared purpose."""


_PRINCIPAL_QUERY = """
SELECT pg_catalog.jsonb_build_object(
    'session_user', session_user::text,
    'current_user', current_user::text,
    'session_control_member',
        pg_catalog.pg_has_role(
            session_user, 'powerops_session_control', 'MEMBER'
        ),
    'revocation_auditor_member',
        pg_catalog.pg_has_role(
            session_user, 'powerops_revocation_auditor', 'MEMBER'
        ),
    'can_retire',
        pg_catalog.has_function_privilege(
            session_user,
            'powerops_security.retire_human_session_login(uuid,text)',
            'EXECUTE'
        ),
    'can_terminate',
        pg_catalog.has_function_privilege(
            session_user,
            'powerops_security.terminate_human_session_backends(uuid)',
            'EXECUTE'
        ),
    'can_count',
        pg_catalog.has_function_privilege(
            session_user,
            'powerops_security.count_human_session_backends(uuid)',
            'EXECUTE'
        ),
    'can_audit',
        pg_catalog.has_function_privilege(
            session_user,
            'powerops_security.record_human_session_revocation_audit('
            'text,text,uuid,text,integer,boolean,boolean,boolean)',
            'EXECUTE'
        ),
    'registry_direct_access',
        pg_catalog.has_table_privilege(
            session_user,
            'powerops_security.human_session_backend_registry', 'SELECT'
        )
        OR pg_catalog.has_table_privilege(
            session_user,
            'powerops_security.human_session_backend_registry', 'INSERT'
        )
        OR pg_catalog.has_table_privilege(
            session_user,
            'powerops_security.human_session_backend_registry', 'UPDATE'
        )
        OR pg_catalog.has_table_privilege(
            session_user,
            'powerops_security.human_session_backend_registry', 'DELETE'
        )
        OR pg_catalog.has_table_privilege(
            session_user,
            'powerops_security.human_session_backend_registry', 'TRUNCATE'
        ),
    'backend_audit_direct_access',
        pg_catalog.has_table_privilege(
            session_user,
            'powerops_security.human_session_backend_audit', 'SELECT'
        )
        OR pg_catalog.has_table_privilege(
            session_user,
            'powerops_security.human_session_backend_audit', 'INSERT'
        )
        OR pg_catalog.has_table_privilege(
            session_user,
            'powerops_security.human_session_backend_audit', 'UPDATE'
        )
        OR pg_catalog.has_table_privilege(
            session_user,
            'powerops_security.human_session_backend_audit', 'DELETE'
        )
        OR pg_catalog.has_table_privilege(
            session_user,
            'powerops_security.human_session_backend_audit', 'TRUNCATE'
        ),
    'revocation_audit_direct_access',
        pg_catalog.has_table_privilege(
            session_user,
            'powerops_security.human_session_revocation_audit', 'SELECT'
        )
        OR pg_catalog.has_table_privilege(
            session_user,
            'powerops_security.human_session_revocation_audit', 'INSERT'
        )
        OR pg_catalog.has_table_privilege(
            session_user,
            'powerops_security.human_session_revocation_audit', 'UPDATE'
        )
        OR pg_catalog.has_table_privilege(
            session_user,
            'powerops_security.human_session_revocation_audit', 'DELETE'
        )
        OR pg_catalog.has_table_privilege(
            session_user,
            'powerops_security.human_session_revocation_audit', 'TRUNCATE'
        )
)
"""


def _verify_one(
    *,
    factory: Callable[[], Any],
    expected_login: str,
    purpose: str,
) -> None:
    connection = None
    try:
        connection = factory()
        cursor = connection.cursor()
        try:
            cursor.execute(_PRINCIPAL_QUERY, ())
            row = cursor.fetchone()
        finally:
            cursor.close()
        connection.rollback()
    except Exception:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
        raise PostgresPrincipalVerificationError(
            f"PostgreSQL {purpose} principal verification could not be completed"
        ) from None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    if isinstance(row, (tuple, list)) and len(row) == 1:
        row = row[0]
    if not isinstance(row, Mapping):
        raise PostgresPrincipalVerificationError(
            f"PostgreSQL {purpose} principal returned an invalid identity result"
        )

    required_booleans = (
        "session_control_member",
        "revocation_auditor_member",
        "can_retire",
        "can_terminate",
        "can_count",
        "can_audit",
        "registry_direct_access",
        "backend_audit_direct_access",
        "revocation_audit_direct_access",
    )
    if (
        row.get("session_user") != expected_login
        or row.get("current_user") != expected_login
        or any(not isinstance(row.get(key), bool) for key in required_booleans)
    ):
        raise PostgresPrincipalVerificationError(
            f"PostgreSQL {purpose} principal identity or privilege result is invalid"
        )

    allowed = {
        "provisioner": (True, False, False, False),
        "termination": (False, True, True, False),
        "audit": (False, False, False, True),
    }.get(purpose)
    actual = tuple(
        row[key] for key in ("can_retire", "can_terminate", "can_count", "can_audit")
    )
    if (
        allowed is None
        or actual != allowed
        or row["session_control_member"]
        or row["revocation_auditor_member"]
        or row["registry_direct_access"]
        or row["backend_audit_direct_access"]
        or row["revocation_audit_direct_access"]
    ):
        raise PostgresPrincipalVerificationError(
            f"PostgreSQL {purpose} principal violates its least-privilege contract"
        )


def verify_revocation_postgres_principals(
    *,
    provisioner_connection_factory: Callable[[], Any],
    termination_connection_factory: Callable[[], Any],
    audit_connection_factory: Callable[[], Any],
    expected_provisioner_login: str,
    expected_termination_login: str,
    expected_audit_login: str,
) -> None:
    """Verify actual authenticated identities and privilege separation.

    Expected login names are customer deployment configuration, never values
    inferred from a caller-controlled DSN. No credentials are accepted here.
    """
    expected = (
        expected_provisioner_login,
        expected_termination_login,
        expected_audit_login,
    )
    if any(not isinstance(name, str) or not name.strip() for name in expected):
        raise ValueError("Three explicit customer PostgreSQL login names are required")
    if len(set(expected)) != 3:
        raise ValueError("PostgreSQL provisioner, termination and audit logins must differ")

    _verify_one(
        factory=provisioner_connection_factory,
        expected_login=expected_provisioner_login,
        purpose="provisioner",
    )
    _verify_one(
        factory=termination_connection_factory,
        expected_login=expected_termination_login,
        purpose="termination",
    )
    _verify_one(
        factory=audit_connection_factory,
        expected_login=expected_audit_login,
        purpose="audit",
    )
