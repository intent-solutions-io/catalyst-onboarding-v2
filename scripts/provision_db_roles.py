#!/usr/bin/env python
"""Provision the three Catalyst database roles in a disposable development or test cluster (ADR-14, D-17).

Privileged, cluster-level work kept outside the application: it connects with the bootstrap administrator
(CATALYST_DB_ADMIN_USER / CATALYST_DB_ADMIN_PASSWORD) and creates, idempotently:

  owner      LOGIN, CREATEDB (test databases only), owns tables and functions, runs migrations
  app        LOGIN, no other attribute; the web and worker login
  retention  LOGIN, no other attribute; the separately authorized retention path

None is a superuser, none can create roles, and no role is a member of another. Passwords come from
CATALYST_DB_OWNER_PASSWORD, CATALYST_DB_APP_PASSWORD and CATALYST_DB_RETENTION_PASSWORD. Production
provisioning is a later, separately authorized phase (P6); this script refuses CATALYST_ENV=production.
"""

import os
import sys

import psycopg
from psycopg import sql


def main() -> int:
    if os.environ.get("CATALYST_ENV") not in {"development", "test"}:
        print("provision_db_roles: only for CATALYST_ENV=development or test", file=sys.stderr)
        return 2
    roles = {
        os.environ.get("CATALYST_DB_OWNER_ROLE", "catalyst_owner"): (os.environ["CATALYST_DB_OWNER_PASSWORD"], ["CREATEDB"]),
        os.environ.get("CATALYST_DB_APP_ROLE", "catalyst_app"): (os.environ["CATALYST_DB_APP_PASSWORD"], []),
        os.environ.get("CATALYST_DB_RETENTION_ROLE", "catalyst_retention"): (os.environ["CATALYST_DB_RETENTION_PASSWORD"], []),
    }
    with psycopg.connect(
        host=os.environ["CATALYST_DB_HOST"], port=os.environ.get("CATALYST_DB_PORT", "5432"),
        dbname=os.environ["CATALYST_DB_NAME"], user=os.environ["CATALYST_DB_ADMIN_USER"],
        password=os.environ["CATALYST_DB_ADMIN_PASSWORD"], autocommit=True,
    ) as conn:
        for name, (password, extra) in roles.items():
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [name]).fetchone()
            attributes = sql.SQL(" ").join(
                [sql.SQL(a) for a in ["LOGIN", "NOSUPERUSER", "NOCREATEROLE", "NOREPLICATION", "NOBYPASSRLS", "INHERIT"]]
                + [sql.SQL(a) for a in (extra or ["NOCREATEDB"])]
            )
            verb = sql.SQL("ALTER ROLE") if exists else sql.SQL("CREATE ROLE")
            conn.execute(sql.SQL("{} {} WITH {} PASSWORD {}").format(verb, sql.Identifier(name), attributes, sql.Literal(password)))
        print(f"provision_db_roles: {len(roles)} roles ready: {', '.join(sorted(roles))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
