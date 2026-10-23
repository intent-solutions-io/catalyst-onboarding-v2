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
- **The proxy** runs as 10001 on high container ports with the socket volume read-only, keeping only the bind
  capability its binary's file capability needs in order to run.
  The staff site listens on its own container port, published only on the private staff address
  (CATALYST_STAFF_PUBLISH, never all interfaces).
- **The fetcher** runs only `fetch_evidence`, as the fetcher role. It shares `backend` (the database) with the other
  processes and an internal `fetch` network with the egress proxy alone, so no other process can reach the proxy; every fetch is a CONNECT tunnel through that proxy (assessments.egress), which refuses every
  address outside global unicast. The proxy holds no secret and alone joins the outbound network.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "deploy" / "staging" / "compose.yaml"

POSTGRES = "postgres:16.15@sha256:ca0bd484cb98bf4b24eb1010e73fb3fcbd6714d240fbc1a10eea5b7dbecb641d"
CADDY = "caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d"
IMAGE = "${CATALYST_IMAGE:?the attested staging image digest}"
SECRET_FILES = ("secret_key", "verification_key", "verification_fallback_keys", "admin_password", "owner_password", "app_password",
                "retention_password", "backup_password", "fetcher_password")
STAFF_PORT = 8444
PUBLIC_PORT = 8443


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
    # 9kg.30, 9kg.50, 9kg.51 (PR #87 review): the launch values the host sets without a release. Unset keeps the
    # code defaults: the authority unset (everyone refused), three resends, the three paging wait classes.
    "CATALYST_QUALIFICATION_AUTHORITY": "${CATALYST_QUALIFICATION_AUTHORITY:-}",
    "CATALYST_VERIFICATION_RESEND_LIMIT": "${CATALYST_VERIFICATION_RESEND_LIMIT:-3}",
    "CATALYST_HEALTH_AGED_WAITS_PAGE": "${CATALYST_HEALTH_AGED_WAITS_PAGE:-replies_awaiting_processing,issued_agreements,provisioning_activation}",
    "CATALYST_HEALTH_PENDING_AGE_SECONDS": "${CATALYST_HEALTH_PENDING_AGE_SECONDS:-3600}",
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
    # The fallback file is empty except during a routine link-key rotation (027): it holds the previous key.
    keys = [mount("secret_key"), mount("verification_key"), mount("verification_fallback_keys")]
    migrated = {"migrate": {"condition": "service_completed_successfully"}}
    web = catalyst([], "catalyst_app", [*keys, mount("app_password", "db_password")],
                   volumes=["catalyst-run:/run/catalyst"], depends=migrated)
    del web["command"]  # the image's fixed gunicorn command (no access log, 0660 socket)
    worker = catalyst(["python", "manage.py", "run_worker", "--exclude", "fetch_evidence"], "catalyst_app",
                      [*keys, mount("app_password", "db_password")], volumes=["catalyst-mail:/var/lib/catalyst/mail"],
                      depends=migrated)
    fetcher = catalyst(["python", "manage.py", "run_worker", "--only", "fetch_evidence"], "catalyst_fetcher",
                       [mount("secret_key"), mount("fetcher_password", "db_password")], process_role="fetcher",
                       networks=("backend", "fetch"), depends=migrated)
    fetcher["environment"]["CATALYST_WORKER_HEARTBEAT_FILE"] = "/tmp/catalyst-fetcher.beat"
    fetcher["environment"]["CATALYST_EVIDENCE_PROXY"] = "egress:3128"  # its only way out (6B.11)
    # The egress proxy (assessments.egress): no secret, no database login. It alone joins the outbound network; it
    # resolves names and refuses every address outside global unicast, as the fetcher's own classify does.
    # On the `fetch` network with the fetcher alone, never on `backend`: no other process can reach it (PR #76 review).
    egress = catalyst(["python", "-m", "assessments.egress"], "", [], networks=("fetch", "egress"))
    egress["environment"] = {"CATALYST_ENV": "staging", "CATALYST_EGRESS_LISTEN": "0.0.0.0:3128"}
    del egress["secrets"]
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
    # Operator-run (profile `ops`, 6B.13): the backup as the backup role, the restore as the owner with the bootstrap
    # administrator's credential, which the restore alone uses. Sets are 0700 in their own volume.
    # The restore stages custody files beside its target directory, so its target lives inside the custody volume
    # (--storage-dir /var/lib/catalyst/custody/<name>): the image root is read-only. Staging holds no custody files
    # until the pilot connects Documenso.
    backup = catalyst(["python", "manage.py", "catalyst_backup", "--out", "/var/lib/catalyst/backups",
                       "--storage-dir", "/var/lib/catalyst/custody"], "catalyst_backup",
                      [*keys, mount("backup_password", "db_password")],
                      volumes=["catalyst-backups:/var/lib/catalyst/backups", "catalyst-custody:/var/lib/catalyst/custody:ro"],
                      depends={"db": {"condition": "service_healthy"}})
    restore = catalyst(["python", "manage.py", "catalyst_restore", "--help"], "catalyst_owner",
                       [*keys, mount("owner_password", "db_password"), mount("admin_password")],
                       volumes=["catalyst-custody:/var/lib/catalyst/custody"],
                       depends={"db": {"condition": "service_healthy"}})
    restore["environment"]["CATALYST_DB_ADMIN_USER"] = "catalyst_admin"
    for service in (backup, restore):
        service["restart"] = "no"
        service["profiles"] = ["ops"]
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
                            "-c", "log_parameter_max_length_on_error=0", "-c", "log_min_error_statement=panic"],
                "security_opt": ["no-new-privileges:true"],
                "volumes": ["catalyst-db:/var/lib/postgresql/data"],
                "networks": ["backend"],
                # -h: over TCP, so the image's temporary init-time server (socket only) never looks ready.
                "healthcheck": {"test": ["CMD", "pg_isready", "-h", "127.0.0.1", "-U", "catalyst_admin", "-d", "catalyst"],
                                "interval": "2s", "timeout": "5s", "retries": 30},
                "restart": "unless-stopped",
            },
            "provision-roles": provision,
            "migrate": migrate,
            "collect-static": static,
            "backup": backup,
            "restore": restore,
            "web": web,
            "worker": worker,
            "fetcher": fetcher,
            "egress": egress,
            "proxy": {
                "image": CADDY,
                # Not root: group 10001 reaches the 0660 socket, and it listens on high ports (6B.5b review). The
                # official binary carries the file capability cap_net_bind_service, and the kernel refuses to run a
                # binary whose file capability it cannot grant, so that one capability stays in the bounding set
                # and no-new-privileges is off for this container alone. It binds no low port.
                "user": "10001:10001",
                "read_only": True,
                "cap_drop": ["ALL"],
                "cap_add": ["NET_BIND_SERVICE"],
                "environment": {"CATALYST_HTTPS_PORT": str(PUBLIC_PORT),
                                "CATALYST_PUBLIC_HOST": "${CATALYST_PUBLIC_HOST:?}",
                                "CATALYST_STAFF_HOST": "${CATALYST_STAFF_HOST:?}",
                                "CATALYST_STAFF_PORT": str(STAFF_PORT),
                                # Inside the container every interface is the container's own: the host publish
                                # address below is what keeps the staff site private.
                                "CATALYST_STAFF_BIND": "0.0.0.0"},
                # The host port defaults to 443; a host whose own proxy holds 443 (the dev box) publishes elsewhere.
                "ports": [f"${{CATALYST_PUBLIC_PUBLISH:?}}:${{CATALYST_PUBLIC_PORT:-443}}:{PUBLIC_PORT}",
                          f"${{CATALYST_STAFF_PUBLISH:?a private address, never all interfaces}}:${{CATALYST_STAFF_PORT:-443}}:{STAFF_PORT}"],
                "volumes": ["./Caddyfile:/etc/caddy/Caddyfile:ro", "catalyst-run:/run/catalyst:ro",
                            "catalyst-static:/srv/catalyst/static:ro"],
                # Caddy's state in tmpfs it owns: the internal CA is re-created at each start (dev-box staging uses
                # curl -k; a persistent, host-owned directory is a 6B.11 deploy-unit item).
                "tmpfs": ["/tmp:mode=1777,size=16m", "/data:uid=10001,gid=10001,mode=0700,size=16m",
                          "/config:uid=10001,gid=10001,mode=0700,size=4m"],
                "depends_on": {"web": {"condition": "service_started"},
                               "collect-static": {"condition": "service_completed_successfully"}},
                "networks": ["edge"],
                "restart": "unless-stopped",
            },
        },
        "networks": {"backend": {"internal": True}, "fetch": {"internal": True}, "edge": {}, "egress": {}},
        "volumes": {name: {} for name in ("catalyst-db", "catalyst-run", "catalyst-static", "catalyst-mail",
                                          "catalyst-backups", "catalyst-custody")},
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
