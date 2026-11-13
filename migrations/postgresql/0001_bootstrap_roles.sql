-- Run once by the customer PostgreSQL cluster administrator.
-- This establishes non-login ownership principals; it does not create runtime logins.
DO $bootstrap$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'powerops_provisioner') THEN
        CREATE ROLE powerops_provisioner NOLOGIN NOSUPERUSER NOCREATEDB CREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'powerops_scope_resolver') THEN
        CREATE ROLE powerops_scope_resolver NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
END
$bootstrap$;

-- Verify the effective role attributes; do not proceed if an existing role
-- has broader attributes or unexpected memberships.
DO $verify$
DECLARE
    provisioner pg_catalog.pg_roles%ROWTYPE;
    resolver pg_catalog.pg_roles%ROWTYPE;
BEGIN
    SELECT * INTO STRICT provisioner FROM pg_catalog.pg_roles
    WHERE rolname = 'powerops_provisioner';
    SELECT * INTO STRICT resolver FROM pg_catalog.pg_roles
    WHERE rolname = 'powerops_scope_resolver';

    IF provisioner.rolcanlogin OR provisioner.rolsuper OR provisioner.rolbypassrls
       OR provisioner.rolcreatedb OR provisioner.rolreplication THEN
        RAISE EXCEPTION 'powerops_provisioner has unsafe role attributes';
    END IF;
    IF resolver.rolcanlogin OR resolver.rolsuper OR resolver.rolbypassrls
       OR resolver.rolcreatedb OR resolver.rolcreaterole OR resolver.rolreplication THEN
        RAISE EXCEPTION 'powerops_scope_resolver has unsafe role attributes';
    END IF;
END
$verify$;
