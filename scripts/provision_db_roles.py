#!/usr/bin/env python
"""Provision the Catalyst database roles (ADR-14, D-17; 6B.6, 026 sections 3 and 6).

Privileged, cluster-level work kept outside the application: it connects with the bootstrap administrator and
creates, idempotently:

  owner      LOGIN, owns tables and functions, runs migrations; CREATEDB in test and development only (test
             databases)
  app        LOGIN, no other attribute; the web, worker and fetcher login
  retention  LOGIN, no other attribute; the separately authorized retention path
  backup     LOGIN, no other attribute; reads every table but the session table, for the backup job (6B.7)

None is a superuser, none can create roles, and no role is a member of another.

Where the passwords come from:
- test and development: CATALYST_DB_OWNER_PASSWORD, CATALYST_DB_APP_PASSWORD, CATALYST_DB_RETENTION_PASSWORD,
  CATALYST_DB_BACKUP_PASSWORD and CATALYST_DB_ADMIN_PASSWORD in the environment;
- staging: files in CATALYST_SECRETS_DIR named owner_password, app_password, retention_password, backup_password and
  admin_password, never the environment (026 section 5).

Production provisioning is not authorized yet: the script refuses any environment but these three.
"""

import os
import sys

import psycopg
from psycopg import sql

ENVIRONMENTS = ("development", "test", "staging")
KEYS = ("owner", "app", "retention", "backup")
DEFAULT_NAMES = {"owner": "catalyst_owner", "app": "catalyst_app", "retention": "catalyst_retention",
                 "backup": "catalyst_backup"}


def password(key: str, environment: str) -> str:
    if environment != "staging":
        return os.environ[f"CATALYST_DB_{key.upper()}_PASSWORD"]
    if f"CATALYST_DB_{key.upper()}_PASSWORD" in os.environ:
        raise SystemExit(f"provision_db_roles: CATALYST_DB_{key.upper()}_PASSWORD may not be in the environment in staging")
    directory = os.environ.get("CATALYST_SECRETS_DIR", "")
    if not directory.startswith("/"):
        raise SystemExit("provision_db_roles: staging needs CATALYST_SECRETS_DIR (an absolute path)")
    try:
        with open(os.path.join(directory, f"{key}_password"), encoding="utf-8") as handle:
            value = handle.read().rstrip("\r\n")
    except OSError as exc:
        raise SystemExit(f"provision_db_roles: {key}_password cannot be read ({type(exc).__name__})") from None
    if not value:
        raise SystemExit(f"provision_db_roles: {key}_password is empty")
    return value


def main() -> int:
    environment = os.environ.get("CATALYST_ENV", "")
    if environment not in ENVIRONMENTS:
        print(f"provision_db_roles: only for CATALYST_ENV in {', '.join(ENVIRONMENTS)}", file=sys.stderr)
        return 2
    roles = {
        os.environ.get(f"CATALYST_DB_{key.upper()}_ROLE", DEFAULT_NAMES[key]): (
            password(key, environment), ["CREATEDB"] if key == "owner" and environment != "staging" else [])
        for key in KEYS
    }
    with psycopg.connect(
        host=os.environ["CATALYST_DB_HOST"], port=os.environ.get("CATALYST_DB_PORT", "5432"),
        dbname=os.environ["CATALYST_DB_NAME"], user=os.environ["CATALYST_DB_ADMIN_USER"],
        password=password("admin", environment), autocommit=True,
    ) as conn:
        for name, (secret, extra) in roles.items():
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [name]).fetchone()
            attributes = sql.SQL(" ").join(
                [sql.SQL(a) for a in ["LOGIN", "NOSUPERUSER", "NOCREATEROLE", "NOREPLICATION", "NOBYPASSRLS", "INHERIT"]]
                + [sql.SQL(a) for a in (extra or ["NOCREATEDB"])]
            )
            verb = sql.SQL("ALTER ROLE") if exists else sql.SQL("CREATE ROLE")
            conn.execute(sql.SQL("{} {} WITH {} PASSWORD {}").format(verb, sql.Identifier(name), attributes, sql.Literal(secret)))
        print(f"provision_db_roles: {len(roles)} roles ready: {', '.join(sorted(roles))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
