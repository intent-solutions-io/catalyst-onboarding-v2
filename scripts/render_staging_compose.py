#!/usr/bin/env python
"""Render deploy/staging/compose.yaml (026 sections 4 and 5; 6B.5b) from the definition below.

The output is JSON, which is YAML, so Docker Compose reads it and the tests read it with the standard library. Run
`python scripts/render_staging_compose.py --write` after changing the definition; tests/test_staging_compose.py fails
while the committed file and this rendering differ.

The rules the definition encodes (each pinned by a test):
- **Secrets are files, never environment.** Each process kind mounts only its own secrets, read-only, under
  /run/secrets (CATALYST_SECRETS_DIR); no `env_file`, and no secret value in any `environment`. The database password
  each process sees is its own role's: the application role for web and worker, the fetcher role for the fetcher,
  the owner for migrate. The admin bootstrap password reaches only the database and the operator-run provisioning.
- **Every Catalyst container** runs as 10001, with a read-only root, every capability dropped, no new privileges,
  tmpfs at /tmp and /dev/shm, `CATALYST_ENV=staging` fixed, and a fixed command (no GUNICORN_CMD_ARGS).
- **The web socket** lives on a volume shared only with the proxy, which joins group 10001 to reach the 0660 socket.
- **The proxy** drops every capability except binding a low port. The staff site listens on its own container port,
  published only on the private staff address (CATALYST_STAFF_PUBLISH, never all interfaces).
- **The fetcher** runs only `fetch_evidence`, as the fetcher role, on a network that reaches the database alone; its
  egress to approved evidence hosts goes through the host-level egress proxy and deny (a host task, 6B.11).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "deploy" / "staging" / "compose.yaml"

POSTGRES = "postgres:16.15@sha256:ca0bd484cb98bf4b24eb1010e73fb3fcbd6714d240fbc1a10eea5b7dbecb641d"
CADDY = "caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d"
IMAGE = "${CATALYST_IMAGE:?the attested staging image digest}"
SECRET_FILES = ("secret_key", "verification_key", "admin_password", "owner_password", "app_password",
                "retention_password", "backup_password", "fetcher_password")
STAFF_PORT = 8444


def mount(source: str, target: str | None = None) -> dict:
    """A file secret, bind-mounted read-only at /run/secrets/<target>. Compose ignores a mode on file secrets, so the
    host files' own permissions govern (the deploy unit: a 0700 directory, files readable by the containers)."""
    return {"source": source, "target": target or source}


COMMON_ENV = {
    "CATALYST_ENV": "staging",
    "CATALYST_SECRETS_DIR": "/run/secrets",
    "CATALYST_DB_HOST": "db",
    "CATALYST_DB_PORT": "5432",
    "CATALYST_DB_NAME": "catalyst",
    "CATALYST_PUBLIC_BASE_URL": "https://${CATALYST_PUBLIC_HOST:?}",
    # localhost: the health paths through the socket; HostGuard serves it nothing else, and the proxy never forwards it.
    "CATALYST_ALLOWED_HOSTS": "${CATALYST_PUBLIC_HOST:?},${CATALYST_STAFF_HOST:?},localhost",
    "CATALYST_STAFF_HOST": "${CATALYST_STAFF_HOST:?}",
    "CATALYST_LOCAL_HOSTS": "localhost",
    "CATALYST_CHALLENGE_LIFETIME_SECONDS": "3600",  # synthetic; POL-02 open
    "CATALYST_EMAIL_FILE_PATH": "/var/lib/catalyst/mail",
    # Staging requires the setting in every process; only the worker and the fetcher write it, each in its own /tmp.
    "CATALYST_WORKER_HEARTBEAT_FILE": "/tmp/catalyst-worker.beat",
}


def catalyst(command: list, role: str, secrets: list, *, process_role: str = "", volumes=(), networks=("backend",),
             depends=None) -> dict:
    environment = {**COMMON_ENV, "CATALYST_DB_USER": role}
    if process_role:
        environment["CATALYST_PROCESS_ROLE"] = process_role
    service = {
        "image": IMAGE,
        "user": "10001:10001",
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "tmpfs": ["/tmp:mode=1777,size=64m", "/dev/shm:mode=1777,size=64m"],
        "environment": environment,
        "secrets": secrets,
        "command": command,
        "networks": list(networks),
        "restart": "unless-stopped",
    }
    if volumes:
        service["volumes"] = list(volumes)
    if depends:
        service["depends_on"] = depends
    return service


def definition() -> dict:
    keys = [mount("secret_key"), mount("verification_key")]
    migrated = {"migrate": {"condition": "service_completed_successfully"}}
    web = catalyst([], "catalyst_app", [*keys, mount("app_password", "db_password")],
                   volumes=["catalyst-run:/run/catalyst"], depends=migrated)
    del web["command"]  # the image's fixed gunicorn command (no access log, 0660 socket)
    worker = catalyst(["python", "manage.py", "run_worker", "--exclude", "fetch_evidence"], "catalyst_app",
                      [*keys, mount("app_password", "db_password")], volumes=["catalyst-mail:/var/lib/catalyst/mail"],
                      depends=migrated)
    fetcher = catalyst(["python", "manage.py", "run_worker", "--only", "fetch_evidence"], "catalyst_fetcher",
                       [mount("secret_key"), mount("fetcher_password", "db_password")], process_role="fetcher",
                       depends=migrated)
    fetcher["environment"]["CATALYST_WORKER_HEARTBEAT_FILE"] = "/tmp/catalyst-fetcher.beat"
    migrate = catalyst(["sh", "-c", "python manage.py migrate --noinput && python manage.py schedule_session_cleanup"],
                       "catalyst_owner", [*keys, mount("owner_password", "db_password")],
                       depends={"db": {"condition": "service_healthy"}})
    migrate["restart"] = "no"
    provision = catalyst(["python", "scripts/provision_db_roles.py"], "catalyst_admin",
                         [mount(name) for name in ("admin_password", "owner_password", "app_password",
                                                   "retention_password", "backup_password", "fetcher_password")],
                         depends={"db": {"condition": "service_healthy"}})
    provision["environment"] = {"CATALYST_ENV": "staging", "CATALYST_SECRETS_DIR": "/run/secrets", "CATALYST_DB_HOST": "db",
                                "CATALYST_DB_PORT": "5432", "CATALYST_DB_NAME": "catalyst",
                                "CATALYST_DB_ADMIN_USER": "catalyst_admin"}
    provision["restart"] = "no"
    provision["profiles"] = ["provision"]  # operator-run, once per database (026 section 4)
    static = catalyst(["sh", "-c", "cp -a /app/static/. /srv/static/"], "catalyst_app", [],
                      volumes=["catalyst-static:/srv/static"], networks=())
    static["restart"] = "no"
    del static["networks"], static["secrets"]
    static["environment"] = {"CATALYST_ENV": "staging"}
    static["network_mode"] = "none"
    return {
        "name": "catalyst-staging",
        "services": {
            "db": {
                "image": POSTGRES,
                "environment": {"POSTGRES_DB": "catalyst", "POSTGRES_USER": "catalyst_admin",
                                "POSTGRES_PASSWORD_FILE": "/run/secrets/admin_password"},
                "secrets": [mount("admin_password")],
                "command": ["postgres", "-c", "log_statement=none", "-c", "log_parameter_max_length=0",
                            "-c", "log_parameter_max_length_on_error=0"],
                "volumes": ["catalyst-db:/var/lib/postgresql/data"],
                "networks": ["backend"],
                "healthcheck": {"test": ["CMD", "pg_isready", "-U", "catalyst_admin", "-d", "catalyst"],
                                "interval": "2s", "timeout": "5s", "retries": 30},
                "restart": "unless-stopped",
            },
            "provision-roles": provision,
            "migrate": migrate,
            "collect-static": static,
            "web": web,
            "worker": worker,
            "fetcher": fetcher,
            "proxy": {
                "image": CADDY,
                "read_only": True,
                "cap_drop": ["ALL"],
                "cap_add": ["NET_BIND_SERVICE"],
                "group_add": ["10001"],
                "environment": {"CATALYST_PUBLIC_HOST": "${CATALYST_PUBLIC_HOST:?}",
                                "CATALYST_STAFF_HOST": "${CATALYST_STAFF_HOST:?}",
                                "CATALYST_STAFF_PORT": str(STAFF_PORT),
                                # Inside the container every interface is the container's own: the host publish
                                # address below is what keeps the staff site private.
                                "CATALYST_STAFF_BIND": "0.0.0.0"},
                # The host port defaults to 443; a host whose own proxy holds 443 (the dev box) publishes elsewhere.
                "ports": ["${CATALYST_PUBLIC_PUBLISH:?}:${CATALYST_PUBLIC_PORT:-443}:443",
                          f"${{CATALYST_STAFF_PUBLISH:?a private address, never all interfaces}}:${{CATALYST_STAFF_PORT:-443}}:{STAFF_PORT}"],
                "volumes": ["./Caddyfile:/etc/caddy/Caddyfile:ro", "catalyst-run:/run/catalyst",
                            "catalyst-static:/srv/catalyst/static:ro", "catalyst-proxy-data:/data",
                            "catalyst-proxy-config:/config"],
                "tmpfs": ["/tmp:mode=1777,size=16m"],
                "depends_on": {"web": {"condition": "service_started"},
                               "collect-static": {"condition": "service_completed_successfully"}},
                "networks": ["edge"],
                "restart": "unless-stopped",
            },
        },
        "networks": {"backend": {"internal": True}, "edge": {}},
        "volumes": {name: {} for name in ("catalyst-db", "catalyst-run", "catalyst-static", "catalyst-mail",
                                          "catalyst-proxy-data", "catalyst-proxy-config")},
        "secrets": {name: {"file": f"${{CATALYST_STAGING_SECRETS:?}}/{name}"} for name in SECRET_FILES},
    }


def render() -> str:
    return ("# Generated by scripts/render_staging_compose.py (026 sections 4 and 5; 6B.5b). Do not edit by hand.\n"
            "# JSON is YAML: docker compose reads this file as it is.\n"
            + json.dumps(definition(), indent=2) + "\n")


if __name__ == "__main__":
    if sys.argv[1:] == ["--write"]:
        TARGET.write_text(render())
    else:
        sys.stdout.write(render())
