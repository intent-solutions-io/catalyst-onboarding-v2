#!/usr/bin/env python
"""Render deploy/staging/compose.yaml and deploy/production/compose.yaml (026 sections 4, 5 and 18; 6B.5b, 9kg.31.11)
from the one definition below.

The output is JSON, which is YAML, so Docker Compose reads it and the tests read it with the standard library. Run
`python scripts/render_staging_compose.py --write` after changing the definition; tests/test_staging_compose.py fails
while a committed file and its rendering differ.

Production is the same definition with these inputs, and only these (a test pins the difference): `CATALYST_ENV`, the
project name, the secrets directory variable, the owner's challenge lifetime (no synthetic default, POL-02), the live
mail rules every process checks at start-up (the allow-listed mail host, the pinned v2 login, the denied first-generation
login, the Sent-folder evidence source; 9kg.49), the journal's ship-lag threshold (9kg.60), the sender address and
the paging values (no defaults), the egress deny list, which the operator supplies instead of the committed synthetic
one (9kg.39), and the effect journal on an external volume. Starting it on a host is the owner's go.

Production also adds a mail route (9kg.79; 032 section 3.4): a `mail` network that is not internal, joined by the
worker (SMTP and IMAP, the kinds that may send) and by a `post-restore` service (the reconcile kind, which may read
the Sent folder and never send), and by no other Catalyst process. The mail host settings, the mailbox login and the
`mail_password` secret reach those two only. The post-restore step runs there instead of in `restore`, which holds
the administrator password and so never gets a route out. The host firewall restricts the network's destinations
to the mail host (9kg.28).

The rules the definition encodes (each pinned by a test):
- **Secrets are files, never environment.** Each process kind mounts only its own secrets, read-only, under
  /run/secrets (CATALYST_SECRETS_DIR); no `env_file`, and no secret value in any `environment`. The database password
  each process sees is its own role's: the application role for web and worker, the fetcher role for the fetcher,
  the owner for migrate. The admin bootstrap password reaches only the database and the operator-run provisioning.
- **Every Catalyst container** runs as 10001, with a read-only root, every capability dropped, no new privileges,
  tmpfs at /tmp and /dev/shm, `CATALYST_ENV` fixed per definition, and a fixed command (no GUNICORN_CMD_ARGS).
- **The web socket** lives on a volume shared only with the proxy, which joins group 10001 to reach the 0660 socket.
- **The proxy** runs as 10001 on high container ports with the socket volume read-only, keeping only the bind
  capability its binary's file capability needs in order to run.
  The staff site listens on its own container port, published only on the private staff address
  (CATALYST_STAFF_PUBLISH, never all interfaces).
- **The fetcher** runs only `fetch_evidence`, as the fetcher role. It shares `backend` (the database) with the other
  processes and an internal `fetch` network with the egress proxy alone, so no other process can reach the proxy; every fetch is a CONNECT tunnel through that proxy (assessments.egress), which refuses every
  address outside global unicast and every host on its deny list (`deploy/staging/egress-deny`, mounted into it
  alone; 9kg.39). The proxy holds no secret and alone joins the outbound network.
"""

import functools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = {"staging": ROOT / "deploy" / "staging" / "compose.yaml",
           "production": ROOT / "deploy" / "production" / "compose.yaml"}
TARGET = TARGETS["staging"]
SENT_FOLDER_SOURCE = "correspondence.sent_reader.SentFolderSource"  # config.guards.SENT_FOLDER_SOURCE

POSTGRES = "postgres:16.15@sha256:ca0bd484cb98bf4b24eb1010e73fb3fcbd6714d240fbc1a10eea5b7dbecb641d"
CADDY = "caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d"
IMAGE = "${CATALYST_IMAGE:?the attested image digest}"
SECRET_FILES = ("secret_key", "verification_key", "verification_fallback_keys", "admin_password", "owner_password", "app_password",
                "retention_password", "backup_password", "fetcher_password")
PRODUCTION_SECRET_FILES = (*SECRET_FILES, "mail_password")  # 9kg.79: the v2 mailbox, for the worker and post-restore
# 9kg.79: the mail host settings, given only to the processes on the `mail` network.
MAIL_ENV = {
    "CATALYST_MAIL_HOST": "${CATALYST_MAIL_HOST:?the production mail host}",
    "CATALYST_MAIL_PORT": "${CATALYST_MAIL_PORT:?the mail host's submission port (587, STARTTLS; implicit TLS is not supported)}",
    "CATALYST_MAIL_USER": "${CATALYST_MAIL_USER:?the v2 mailbox login}",
    "CATALYST_MAIL_SENT_FOLDER": "${CATALYST_MAIL_SENT_FOLDER:?the v2 mailbox's Sent folder}",
    # The mail host's Authentication-Results identity: unset, every inbound reply's evidence reads untrusted (review of
    # PR #121), so collection would mark every reply unverified.
    "CATALYST_MAIL_TRUSTED_AUTHSERV_ID": "${CATALYST_MAIL_TRUSTED_AUTHSERV_ID:?the mail host's authserv-id}",
}
STAFF_PORT = 8444
PUBLIC_PORT = 8443


def mount(source: str, target: str | None = None) -> dict:
    """A file secret, bind-mounted read-only at /run/secrets/<target>. Compose ignores a mode on file secrets, so the
    host files' own permissions govern (the deploy unit: a 0700 directory, files readable by the containers)."""
    return {"source": source, "target": target or source}


COMMON_ENV = {
    "CATALYST_ENV": "staging",  # replaced per environment (environment_inputs)
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
    # 9kg.33: the effect journal, one volume outside the database's rollback domain, shared by every process that
    # makes or reconciles effects (web, worker, the owner-run commands, backup and restore). Never the fetcher.
    "CATALYST_EFFECT_JOURNAL_DIR": "/var/lib/catalyst/effects",
    # 9kg.30, 9kg.50, 9kg.51 (PR #87 review): the launch values the host sets without a release. Unset keeps the
    # code defaults: the authority unset (everyone refused), three resends, the three paging wait classes.
    "CATALYST_QUALIFICATION_AUTHORITY": "${CATALYST_QUALIFICATION_AUTHORITY:-}",
    "CATALYST_VERIFICATION_RESEND_LIMIT": "${CATALYST_VERIFICATION_RESEND_LIMIT:-3}",
    # bgl.2 (034 row 2): who may apply, the host's switch without a release. Unset is invitation-only; "open" is the
    # public entry; anything else refuses start-up (config.guards). Every process reads it, so web and worker agree.
    "CATALYST_INTAKE_MODE": "${CATALYST_INTAKE_MODE:-invitation}",
    # bgl.2: the learning host's names for the public request pages (config.settings); empty is none.
    "CATALYST_PUBLIC_HOST_ALIASES": "${CATALYST_PUBLIC_HOST_ALIASES:-}",
    "CATALYST_HEALTH_AGED_WAITS_PAGE": "${CATALYST_HEALTH_AGED_WAITS_PAGE:-replies_awaiting_processing,issued_agreements,provisioning_activation}",
    "CATALYST_HEALTH_PENDING_AGE_SECONDS": "${CATALYST_HEALTH_PENDING_AGE_SECONDS:-3600}",
    # bgl.6 (034 section 3.2): the sender's display name and Reply-To, and the mailbox takeover (the swap act). Unset
    # keeps today's headers and the first-generation denial; every Catalyst process checks them at start-up.
    "CATALYST_FROM_DISPLAY_NAME": "${CATALYST_FROM_DISPLAY_NAME:-}",
    "CATALYST_REPLY_TO": "${CATALYST_REPLY_TO:-}",
    "CATALYST_MAIL_TAKEOVER": "${CATALYST_MAIL_TAKEOVER:-}",
}
EFFECTS = "catalyst-effects:/var/lib/catalyst/effects"
# The inputs production adds to, or replaces in, every Catalyst process's environment (see the module docstring).
PRODUCTION_ENV = {
    "CATALYST_ENV": "production",
    "CATALYST_CHALLENGE_LIFETIME_SECONDS": "${CATALYST_CHALLENGE_LIFETIME_SECONDS:?the owner's POL-02 link lifetime}",
    "CATALYST_MAIL_ALLOWED_HOSTS": "${CATALYST_MAIL_ALLOWED_HOSTS:?the production mail host}",
    "CATALYST_MAIL_USER_SHA256": "${CATALYST_MAIL_USER_SHA256:?the pinned v2 mailbox login digest}",
    "CATALYST_MAIL_DENIED_USER_SHA256": "${CATALYST_MAIL_DENIED_USER_SHA256:?the first-generation mailbox digest}",
    "CATALYST_SEND_EVIDENCE_SOURCE": SENT_FOLDER_SOURCE,
    "CATALYST_JOURNAL_SHIP_LAG_SECONDS": "${CATALYST_JOURNAL_SHIP_LAG_SECONDS:?the journal ship-lag threshold}",
    # Owner values with no synthetic default in production (review of PR #118): the v2 sender address and the
    # paging values (211.7.2).
    "CATALYST_FROM_EMAIL": "${CATALYST_FROM_EMAIL:?the v2 sender address}",
    "CATALYST_HEALTH_AGED_WAITS_PAGE": "${CATALYST_HEALTH_AGED_WAITS_PAGE:?the owner's page list (211.7.2)}",
    "CATALYST_HEALTH_PENDING_AGE_SECONDS": "${CATALYST_HEALTH_PENDING_AGE_SECONDS:?the owner's pending-age target (211.7.2)}",
}


def catalyst(command: list, role: str, secrets: list, *, process_role: str = "", volumes=(), networks=("backend",),
             depends=None, env: str = "staging") -> dict:
    environment = {**COMMON_ENV, **(PRODUCTION_ENV if env == "production" else {}), "CATALYST_DB_USER": role}
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


def definition(env: str = "staging") -> dict:
    if env not in TARGETS:
        raise ValueError(f"no compose definition for {env!r}")
    make = functools.partial(catalyst, env=env)  # every Catalyst service of this definition runs in `env`
    # The fallback file is empty except during a routine link-key rotation (027): it holds the previous key.
    keys = [mount("secret_key"), mount("verification_key"), mount("verification_fallback_keys")]
    migrated = {"migrate": {"condition": "service_completed_successfully"}}
    web = make([], "catalyst_app", [*keys, mount("app_password", "db_password")], process_role="web",
                   volumes=["catalyst-run:/run/catalyst", EFFECTS], depends=migrated)
    del web["command"]  # the image's fixed gunicorn command (no access log, 0660 socket)
    worker = make(["python", "manage.py", "run_worker", "--exclude", "fetch_evidence"], "catalyst_app",
                      [*keys, mount("app_password", "db_password")], process_role="worker",
                      volumes=["catalyst-mail:/var/lib/catalyst/mail", EFFECTS], depends=migrated)
    fetcher = make(["python", "manage.py", "run_worker", "--only", "fetch_evidence"], "catalyst_fetcher",
                       [mount("secret_key"), mount("fetcher_password", "db_password")], process_role="fetcher",
                       networks=("backend", "fetch"), depends=migrated)
    fetcher["environment"]["CATALYST_WORKER_HEARTBEAT_FILE"] = "/tmp/catalyst-fetcher.beat"
    fetcher["environment"]["CATALYST_EVIDENCE_PROXY"] = "egress:3128"  # its only way out (6B.11)
    # The fetcher makes no effect and holds no journal: the setting names a directory it never mounts, so a write
    # there fails loudly rather than landing in the read-only image.
    fetcher["environment"]["CATALYST_EFFECT_JOURNAL_DIR"] = "/var/lib/catalyst/effects-none"
    # The egress proxy (assessments.egress): no secret, no database login. It alone joins the outbound network; it
    # resolves names and refuses every address outside global unicast, as the fetcher's own classify does.
    # On the `fetch` network with the fetcher alone, never on `backend`: no other process can reach it (PR #76 review).
    egress = make(["python", "-m", "assessments.egress"], "", [], networks=("fetch", "egress"))
    # 9kg.39: its deny list of production hosts, a secret-free file mounted read-only into this service alone. Staging
    # carries synthetic names and a public stand-in; production mounts the operator-supplied list at the same path.
    egress["environment"] = {"CATALYST_ENV": env, "CATALYST_EGRESS_LISTEN": "0.0.0.0:3128",
                             "CATALYST_EGRESS_DENY_FILE": "/etc/catalyst/egress-deny"}
    deny = "${CATALYST_EGRESS_DENY_FILE:?the operator-supplied deny list}" if env == "production" else "./egress-deny"
    egress["volumes"] = [f"{deny}:/etc/catalyst/egress-deny:ro"]
    # Healthy only while the mounted list loads (PR #101 review): a broken list is visible, not just refused per request.
    egress["healthcheck"] = {"test": ["CMD", "python", "-m", "assessments.egress", "--check"],
                             "interval": "10s", "timeout": "5s", "retries": 3}
    del egress["secrets"]
    migrate = make(["sh", "-c", "python manage.py migrate --noinput && python manage.py schedule_session_cleanup"
                       " && python manage.py schedule_verification_sweep"],
                       "catalyst_owner", [*keys, mount("owner_password", "db_password")], volumes=[EFFECTS],
                       depends={"db": {"condition": "service_healthy"}})
    migrate["restart"] = "no"
    provision = make(["python", "scripts/provision_db_roles.py"], "catalyst_admin",
                         [mount(name) for name in ("admin_password", "owner_password", "app_password",
                                                   "retention_password", "backup_password", "fetcher_password")],
                         depends={"db": {"condition": "service_healthy"}})
    provision["environment"] = {"CATALYST_ENV": env, "CATALYST_SECRETS_DIR": "/run/secrets", "CATALYST_DB_HOST": "db",
                                "CATALYST_DB_PORT": "5432", "CATALYST_DB_NAME": "catalyst",
                                "CATALYST_DB_ADMIN_USER": "catalyst_admin"}
    provision["restart"] = "no"
    provision["profiles"] = ["provision"]  # operator-run, once per database (026 section 4)
    # Operator-run (profile `ops`, 6B.13): the backup as the backup role, the restore as the owner with the bootstrap
    # administrator's credential, which the restore alone uses. Sets are 0700 in their own volume.
    # The restore stages custody files beside its target directory, so its target lives inside the custody volume
    # (--storage-dir /var/lib/catalyst/custody/<name>): the image root is read-only. Staging holds no custody files
    # until the pilot connects Documenso.
    backup = make(["python", "manage.py", "catalyst_backup", "--out", "/var/lib/catalyst/backups",
                       "--storage-dir", "/var/lib/catalyst/custody"], "catalyst_backup",
                      [*keys, mount("backup_password", "db_password")],
                      volumes=["catalyst-backups:/var/lib/catalyst/backups", "catalyst-custody:/var/lib/catalyst/custody:ro",
                               EFFECTS + ":ro"],  # the backup only reads the journal's head into its receipt
                      depends={"db": {"condition": "service_healthy"}})
    # In staging the restore service also runs the post-restore step: the `reconcile` role (9kg.49, RD-1) may read the
    # Sent folder and never send; it never runs as web or worker. In production the review runs in `post-restore`
    # (the mail route), and the lift runs here with the erasure key added for that run only, never beside the mail
    # password (9kg.79).
    restore = make(["python", "manage.py", "catalyst_restore", "--help"], "catalyst_owner",
                       [*keys, mount("owner_password", "db_password"), mount("admin_password")], process_role="reconcile",
                       volumes=["catalyst-custody:/var/lib/catalyst/custody", EFFECTS],  # it writes the restore marker
                       depends={"db": {"condition": "service_healthy"}})
    restore["environment"]["CATALYST_DB_ADMIN_USER"] = "catalyst_admin"
    for service in (backup, restore):
        service["restart"] = "no"
        service["profiles"] = ["ops"]
    extra = {}
    if env == "production":
        # 9kg.79: the worker alone among the long-running processes reaches the mail host.
        worker["networks"] = ["backend", "mail"]
        worker["environment"].update(MAIL_ENV)
        worker["secrets"] = [*worker["secrets"], mount("mail_password")]
        # The post-restore step (owner-run, the reconcile kind): the Sent-folder read only, never SMTP (RD-1), with the
        # owner's login and no administrator password; `restore` keeps the administrator password and no route out.
        post = make(["python", "manage.py", "catalyst_post_restore", "--help"], "catalyst_owner",
                    [*keys, mount("owner_password", "db_password"), mount("mail_password")], process_role="reconcile",
                    volumes=["catalyst-custody:/var/lib/catalyst/custody", EFFECTS], networks=("backend", "mail"),
                    depends={"db": {"condition": "service_healthy"}})
        post["environment"].update(MAIL_ENV)
        post["restart"], post["profiles"] = "no", ["ops"]
        extra["post-restore"] = post
        # 9kg.78.2 (032 section 3.5; 9kg.60): the off-host copy of the effect journal, run by a host timer
        # (`docker compose --profile ops run --rm journal-ship`). It reads the journal and records the shipped head
        # beside it, so the journal is mounted read-write; the destination is the host's off-host mount. It never
        # connects to the database: no network at all, and the least-privileged login only because settings need one.
        ship = make(["python", "manage.py", "catalyst_journal_ship", "--to", "/var/lib/catalyst/ship"], "catalyst_fetcher",
                    [*keys, mount("fetcher_password", "db_password")],
                    volumes=[EFFECTS, "${CATALYST_JOURNAL_SHIP_DIR:?the off-host journal destination}:/var/lib/catalyst/ship"],
                    networks=())
        del ship["networks"]
        ship["network_mode"] = "none"
        ship["restart"], ship["profiles"] = "no", ["ops"]
        extra["journal-ship"] = ship
        # 9kg.78.2: fetching is disabled in production, so an empty deny list is the intended state; the health check
        # passes on it there and still fails on a broken one (assessments.egress.check).
        egress["environment"]["CATALYST_EGRESS_FETCHING"] = "disabled"
    static = make(["sh", "-c", "cp -a /app/static/. /srv/static/"], "catalyst_app", [],
                      volumes=["catalyst-static:/srv/static"], networks=())
    static["restart"] = "no"
    del static["networks"], static["secrets"]
    static["environment"] = {"CATALYST_ENV": env}
    static["network_mode"] = "none"
    return {
        "name": f"catalyst-{env}",
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
            **extra,
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
                                # bgl.2: the alias site needs an address; a placeholder name when none is set.
                                "CATALYST_PUBLIC_HOST_ALIASES": "${CATALYST_PUBLIC_HOST_ALIASES:-alias.staging.test}",
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
        "networks": {"backend": {"internal": True}, "fetch": {"internal": True}, "edge": {}, "egress": {},
                     **({"mail": {}} if env == "production" else {})},
        "volumes": {**{name: {} for name in ("catalyst-db", "catalyst-run", "catalyst-static", "catalyst-mail",
                                             "catalyst-backups", "catalyst-custody", "catalyst-effects")},
                    # Production's journal is the restore's evidence: an external volume the operator creates, which
                    # `docker compose down -v` cannot remove (032 section 3.3; review of PR #118).
                    **({"catalyst-effects": {"external": True, "name": "catalyst-production-effects"}}
                       if env == "production" else {})},
        "secrets": {name: {"file": f"${{CATALYST_{env.upper()}_SECRETS:?}}/{name}"}
                    for name in (PRODUCTION_SECRET_FILES if env == "production" else SECRET_FILES)},
    }


def render(env: str = "staging") -> str:
    return ("# Generated by scripts/render_staging_compose.py (026 sections 4, 5 and 18; 6B.5b, 9kg.31.11). Do not edit by"
            " hand.\n# JSON is YAML: docker compose reads this file as it is.\n"
            + json.dumps(definition(env), indent=2) + "\n")


if __name__ == "__main__":
    if sys.argv[1:] == ["--write"]:
        for env, target in TARGETS.items():
            target.parent.mkdir(exist_ok=True)
            target.write_text(render(env))
    elif sys.argv[1:] in ([], ["staging"], ["production"]):
        sys.stdout.write(render(*sys.argv[1:]))
    else:
        raise SystemExit("usage: render_staging_compose.py [--write | staging | production]")
