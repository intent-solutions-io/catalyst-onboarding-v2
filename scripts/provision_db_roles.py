#!/usr/bin/env python
"""Provision the Catalyst database roles (ADR-14, D-17; 6B.6, 026 sections 3 and 6).

Privileged, cluster-level work kept outside the application: it connects with the bootstrap administrator and
creates, idempotently:

  owner      LOGIN, owns tables and functions, runs migrations; CREATEDB in test and development only (test
             databases)
  app        LOGIN, no other attribute; the web, worker and fetcher login
  retention  LOGIN, no other attribute; the separately authorized retention path
  backup     LOGIN, no other attribute; reads every table but the session table, for the backup job (6B.7)
  fetcher    LOGIN, no other attribute; only what the evidence fetch touches (9kg.24)

None is a superuser, none can create roles, and no role is a member of another. In staging the owner role also
becomes the database's owner, which PostgreSQL 15 and later require for creating tables in `public`.

Where the passwords come from:
- test and development: CATALYST_DB_OWNER_PASSWORD, CATALYST_DB_APP_PASSWORD, CATALYST_DB_RETENTION_PASSWORD,
  CATALYST_DB_BACKUP_PASSWORD, CATALYST_DB_FETCHER_PASSWORD and CATALYST_DB_ADMIN_PASSWORD in the environment;
- staging: files in CATALYST_SECRETS_DIR named owner_password, app_password, retention_password, backup_password,
  fetcher_password and admin_password, never the environment (026 section 5).

Production provisioning is not authorized yet: the script refuses any environment but these three.
"""

import os
import sys

import psycopg
from psycopg import sql

ENVIRONMENTS = ("development", "test", "staging")
KEYS = ("owner", "app", "retention", "backup", "fetcher")
DEFAULT_NAMES = {"owner": "catalyst_owner", "app": "catalyst_app", "retention": "catalyst_retention",
                 "backup": "catalyst_backup", "fetcher": "catalyst_fetcher"}


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


def check(conn, names: list[str], createdb_role: str | None) -> list[str]:
    """What the docstring promises, read back from the catalogue (PR #66 review): no superuser, no role creation, no
    replication, no RLS bypass, every role can log in, CREATEDB only for the test owner, and no memberships."""
    problems = []
    rows = conn.execute("SELECT rolname, rolsuper, rolcreaterole, rolreplication, rolbypassrls, rolcanlogin, rolcreatedb"
                        " FROM pg_roles WHERE rolname = ANY(%s)", [names]).fetchall()
    for name, superuser, createrole, replication, bypassrls, login, createdb in rows:
        if superuser or createrole or replication or bypassrls or not login or createdb != (name == createdb_role):
            problems.append(f"role {name} has unexpected attributes")
    members = conn.execute("SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member"
                           " WHERE r.rolname = ANY(%s)", [names]).fetchone()[0]
    if members:
        problems.append("a Catalyst role is a member of another role")
    return problems


def main() -> int:
    environment = os.environ.get("CATALYST_ENV", "")
    if environment not in ENVIRONMENTS:
        print(f"provision_db_roles: only for CATALYST_ENV in {', '.join(ENVIRONMENTS)}", file=sys.stderr)
        return 2
    if environment == "staging":  # refuse every password in the environment before reading any file
        named = [f"CATALYST_DB_{k.upper()}_PASSWORD" for k in (*KEYS, "admin")]
        present = [name for name in named if name in os.environ]
        if present:
            print(f"provision_db_roles: {', '.join(present)} may not be in the environment in staging", file=sys.stderr)
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
        # The statements below carry password hashes; keep them out of the server log either way (PR #66 review).
        conn.execute("SET log_statement = 'none'")
        conn.execute("SET log_min_error_statement = 'panic'")
        for name, (secret, extra) in roles.items():
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [name]).fetchone()
            attributes = sql.SQL(" ").join(
                [sql.SQL(a) for a in ["LOGIN", "NOSUPERUSER", "NOCREATEROLE", "NOREPLICATION", "NOBYPASSRLS", "INHERIT"]]
                + [sql.SQL(a) for a in (extra or ["NOCREATEDB"])]
            )
            verb = sql.SQL("ALTER ROLE") if exists else sql.SQL("CREATE ROLE")
            # Hashed here, so the clear password never reaches the server, its log or pg_stat_activity (PR #66 review).
            verifier = conn.pgconn.encrypt_password(secret.encode(), name.encode(), b"scram-sha-256").decode()
            conn.execute(sql.SQL("{} {} WITH {} PASSWORD {}").format(verb, sql.Identifier(name), attributes, sql.Literal(verifier)))
        if environment == "staging":
            # PostgreSQL 15 and later let only the database's owner create in `public`; the bootstrap administrator
            # created this database, so the migration owner takes it over (6B.5b; tests create their own database).
            database = sql.Identifier(os.environ["CATALYST_DB_NAME"])
            conn.execute(sql.SQL("ALTER DATABASE {} OWNER TO {}").format(database, sql.Identifier(next(iter(roles)))))
            # Only the Catalyst roles may connect, and none but the owner may create in `public` (6B.5b review).
            conn.execute(sql.SQL("REVOKE CONNECT, TEMPORARY ON DATABASE {} FROM PUBLIC").format(database))
            conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                database, sql.SQL(", ").join(sql.Identifier(name) for name in roles)))
            conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        problems = check(conn, list(roles), next(iter(roles)) if environment != "staging" else None)
        if problems:
            print("provision_db_roles: " + "; ".join(problems), file=sys.stderr)
            return 3
        print(f"provision_db_roles: {len(roles)} roles ready: {', '.join(sorted(roles))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
