#!/usr/bin/env bash
set -Eeuo pipefail

: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=postgres}"
: "${PGUSER:=postgres}"
: "${PGPASSWORD:=postgres}"
admin() {
  PGPASSWORD="$PGPASSWORD" psql -X -q -v ON_ERROR_STOP=1 \
    -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$@"
}

echo "[Gate PS-02.1A.8] Create three independent revocation-control logins"
admin <<'SQL'
DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'pwr_gate_ps021a8_provisioner') THEN
        EXECUTE 'CREATE ROLE pwr_gate_ps021a8_provisioner LOGIN '
            'NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'pwr_gate_ps021a8_termination') THEN
        EXECUTE 'CREATE ROLE pwr_gate_ps021a8_termination LOGIN '
            'NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'pwr_gate_ps021a8_audit') THEN
        EXECUTE 'CREATE ROLE pwr_gate_ps021a8_audit LOGIN '
            'NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'pwr_gate_ps021a8_unexpected') THEN
        EXECUTE 'CREATE ROLE pwr_gate_ps021a8_unexpected NOLOGIN '
            'NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS';
    END IF;
END
$roles$;

ALTER ROLE pwr_gate_ps021a8_provisioner PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
ALTER ROLE pwr_gate_ps021a8_termination PASSWORD 'Gate1E-Disposable-Only-ChangeMe';
ALTER ROLE pwr_gate_ps021a8_audit PASSWORD 'Gate1E-Disposable-Only-ChangeMe';

GRANT USAGE ON SCHEMA powerops_security
    TO pwr_gate_ps021a8_provisioner,
       pwr_gate_ps021a8_termination,
       pwr_gate_ps021a8_audit;
GRANT EXECUTE ON FUNCTION
    powerops_security.retire_human_session_login(uuid, text)
    TO pwr_gate_ps021a8_provisioner;
GRANT EXECUTE ON FUNCTION
    powerops_security.terminate_human_session_backends(uuid),
    powerops_security.count_human_session_backends(uuid)
    TO pwr_gate_ps021a8_termination;
GRANT EXECUTE ON FUNCTION
    powerops_security.record_human_session_revocation_audit(
        text, text, uuid, text, integer, boolean, boolean, boolean, jsonb, text
    )
    TO pwr_gate_ps021a8_audit;
SQL

echo "[Gate PS-02.1A.8] Verify real session_user/current_user and least-privilege grants"
PYTHONPATH=src .venv/bin/python <<'PY'
from __future__ import annotations

import os

import psycopg

from powerops.postgres_principal_verification import (
    PostgresPrincipalVerificationError,
    verify_revocation_postgres_principals,
)

PASSWORD = "Gate1E-Disposable-Only-ChangeMe"
PROVISIONER = "pwr_gate_ps021a8_provisioner"
TERMINATION = "pwr_gate_ps021a8_termination"
AUDIT = "pwr_gate_ps021a8_audit"
EXPECTED = {
    "expected_provisioner_login": PROVISIONER,
    "expected_termination_login": TERMINATION,
    "expected_audit_login": AUDIT,
}


def connect_as(role: str):
    return psycopg.connect(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "postgres"),
        user=role,
        password=PASSWORD,
        connect_timeout=5,
    )


def factory(role: str):
    return lambda: connect_as(role)


def verify_all(*, provisioner=None, termination=None, audit=None, **expected):
    verify_revocation_postgres_principals(
        provisioner_connection_factory=provisioner or factory(PROVISIONER),
        termination_connection_factory=termination or factory(TERMINATION),
        audit_connection_factory=audit or factory(AUDIT),
        **{**EXPECTED, **expected},
    )


verify_all()
print("PASS: three actual PostgreSQL login identities and function grants verified")

try:
    verify_all(expected_provisioner_login="pwr_wrong_expected_login")
except PostgresPrincipalVerificationError:
    pass
else:
    raise AssertionError("wrong expected provisioner login was accepted")
print("PASS: wrong expected login rejected")

def set_role_factory():
    connection = connect_as(PROVISIONER)
    connection.execute("SET ROLE pwr_gate_ps021a8_unexpected")
    return connection

try:
    verify_all(provisioner=set_role_factory)
except PostgresPrincipalVerificationError:
    pass
else:
    raise AssertionError("SET ROLE identity substitution was accepted")
print("PASS: current_user substitution rejected")

admin = psycopg.connect(
    host=os.environ.get("PGHOST", "127.0.0.1"),
    port=int(os.environ.get("PGPORT", "5432")),
    dbname=os.environ.get("PGDATABASE", "postgres"),
    user=os.environ.get("PGUSER", "postgres"),
    password=os.environ.get("PGPASSWORD", "postgres"),
    connect_timeout=5,
)
try:
    admin.execute(
        "GRANT pwr_gate_ps021a8_unexpected TO pwr_gate_ps021a8_provisioner"
    )
    admin.commit()
    try:
        verify_all(provisioner=set_role_factory)
    except PostgresPrincipalVerificationError:
        pass
    else:
        raise AssertionError("SET ROLE through an added membership was accepted")
    admin.execute(
        "REVOKE pwr_gate_ps021a8_unexpected FROM pwr_gate_ps021a8_provisioner"
    )
    admin.commit()

    admin.execute(
        "GRANT SELECT ON powerops_security.human_session_actor_binding "
        "TO pwr_gate_ps021a8_termination"
    )
    admin.commit()
    try:
        verify_all()
    except PostgresPrincipalVerificationError:
        pass
    else:
        raise AssertionError("direct session-binding table access was accepted")
    admin.execute(
        "REVOKE SELECT ON powerops_security.human_session_actor_binding "
        "FROM pwr_gate_ps021a8_termination"
    )
    admin.commit()

    admin.execute("GRANT pg_read_all_stats TO pwr_gate_ps021a8_audit")
    admin.commit()
    try:
        verify_all()
    except PostgresPrincipalVerificationError:
        pass
    else:
        raise AssertionError("elevated pg_stat visibility was accepted")
    admin.execute("REVOKE pg_read_all_stats FROM pwr_gate_ps021a8_audit")
    admin.commit()

    admin.execute(
        "GRANT EXECUTE ON FUNCTION "
        "powerops_security.record_human_session_revocation_audit("
        "text,text,uuid,text,integer,boolean,boolean,boolean,jsonb,text) "
        "TO pwr_gate_ps021a8_termination"
    )
    admin.commit()
    try:
        verify_all()
    except PostgresPrincipalVerificationError:
        pass
    else:
        raise AssertionError("termination/audit privilege overlap was accepted")
    admin.execute(
        "REVOKE EXECUTE ON FUNCTION "
        "powerops_security.record_human_session_revocation_audit("
        "text,text,uuid,text,integer,boolean,boolean,boolean,jsonb,text) "
        "FROM pwr_gate_ps021a8_termination"
    )
    admin.commit()
finally:
    admin.close()

verify_all()
print("PASS: direct table access, elevated monitoring and privilege overlap rejected")
PY

echo "PS-02.1A.8 PASS — real PostgreSQL identity, SET ROLE, direct-access and privilege-overlap checks"
