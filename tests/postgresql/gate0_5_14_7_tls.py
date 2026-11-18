"""Read-only Gate 0.5.14.7 customer TLS acceptance check.

Run only from an approved customer test runner. No passwords or DSNs are
accepted: authentication must use the supplied client certificate and key.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import UUID


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def main() -> int:
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("Install the project's pinned psycopg binary dependency") from exc

    host = required("POWEROPS_TLS_HOST")
    port = int(os.environ.get("POWEROPS_TLS_PORT", "5432"))
    database = required("POWEROPS_TLS_DATABASE")
    role = required("POWEROPS_TLS_DATABASE_ROLE")
    cert = Path(required("POWEROPS_TLS_CLIENT_CERT"))
    key = Path(required("POWEROPS_TLS_CLIENT_KEY"))
    root = Path(required("POWEROPS_TLS_ROOT_CERT"))
    expected_actor = required("POWEROPS_TLS_EXPECTED_ACTOR")  # https://issuer|subject
    tenant_id = UUID(required("POWEROPS_TLS_EXPECTED_TENANT_ID"))
    business_unit_id = UUID(required("POWEROPS_TLS_EXPECTED_BUSINESS_UNIT_ID"))
    entitlement = required("POWEROPS_TLS_EXPECTED_ENTITLEMENT")
    if entitlement not in {"finance_operator", "finance_verifier"}:
        raise SystemExit("Expected entitlement must be finance_operator or finance_verifier")
    if not role.startswith("pwr_") or not all(p.is_file() for p in (cert, key, root)):
        raise SystemExit("Invalid database role or missing TLS certificate file")

    conn = psycopg.connect(
        host=host,
        port=port,
        dbname=database,
        user=role,
        sslmode="verify-full",
        sslrootcert=str(root),
        sslcert=str(cert),
        sslkey=str(key),
        connect_timeout=5,
        application_name="cephas-powerops-gate-0.5.14.7-acceptance",
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT session_user, current_user,
                       ssl.ssl, ssl.version, ssl.cipher,
                       actor.actor_subject, actor.tenant_id,
                       actor.business_unit_id, actor.finance_operator,
                       actor.finance_verifier
                  FROM powerops_security.resolve_authenticated_human_actor_v2() AS actor
                  JOIN pg_catalog.pg_stat_ssl AS ssl
                    ON ssl.pid = pg_catalog.pg_backend_pid()
                """
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("Database identity/TLS resolver returned no row")
            (
                session_user, current_user, tls_active, tls_version, tls_cipher,
                actor_subject, actual_tenant, actual_bu, finance_operator,
                finance_verifier,
            ) = row
            checks = {
                "session_role_matches": session_user == role and current_user == role,
                "tls_active": tls_active is True,
                "tls_version_present": bool(tls_version),
                "tls_cipher_present": bool(tls_cipher),
                "actor_matches": actor_subject == expected_actor,
                "tenant_matches": actual_tenant == tenant_id,
                "business_unit_matches": actual_bu == business_unit_id,
                "exclusive_entitlement": (
                    (finance_operator is True and finance_verifier is False)
                    or (finance_operator is False and finance_verifier is True)
                ),
                "requested_entitlement_matches": (
                    finance_operator is (entitlement == "finance_operator")
                    and finance_verifier is (entitlement == "finance_verifier")
                ),
            }
            for name, passed in checks.items():
                print(f"{name}={'PASS' if passed else 'FAIL'}")
            print(f"database_role={role}")
            print(f"tls_version={tls_version}")
            print(f"tls_cipher={tls_cipher}")
            if not all(checks.values()):
                return 1
            print("GATE_0_5_14_7_TLS_ACCEPTANCE=PASS")
            return 0
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Avoid printing exception details that may contain customer endpoints
        # or driver-provided connection metadata.
        print(f"GATE_0_5_14_7_TLS_ACCEPTANCE=FAIL ({type(exc).__name__})", file=sys.stderr)
        raise SystemExit(1)
