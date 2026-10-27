"""6B.5b (026 sections 4 and 5; TEST-P6-04, 11): the staging compose definition. What the running containers expose
(`docker inspect`, `docker exec env`) is checked against the live stack by scripts/staging_check.sh (6B.11)."""

import importlib.util
import json

from config import guards
from tests.support import ROOT

CATALYST = ("web", "worker", "fetcher", "migrate", "provision-roles", "collect-static", "egress", "backup", "restore")
SECRET_WORDS = ("PASSWORD", "SECRET_KEY", "VERIFICATION_KEY", "TOKEN", "API_KEY")


def renderer():
    spec = importlib.util.spec_from_file_location("render_staging_compose", ROOT / "scripts" / "render_staging_compose.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def services():
    return renderer().definition()["services"]


def secrets_of(service) -> dict:
    return {s["target"]: s["source"] for s in service.get("secrets", [])}


def test_6b5b_the_committed_compose_file_is_exactly_the_rendering():
    committed = (ROOT / "deploy" / "staging" / "compose.yaml").read_text()
    assert committed == renderer().render(), "run `python scripts/render_staging_compose.py --write`"
    json.loads(committed.split("\n", 2)[2])  # JSON after the two comment lines, so YAML and JSON alike


def test_6b5b_no_secret_is_ever_in_an_environment_or_an_env_file():
    for name, service in services().items():
        assert "env_file" not in service, name
        for key, value in service.get("environment", {}).items():
            assert not any(word in key for word in SECRET_WORDS) or key == "POSTGRES_PASSWORD_FILE", (name, key)
            assert "GUNICORN_CMD_ARGS" != key, name


def test_6b5b_each_process_mounts_only_its_own_secrets_and_its_own_database_password():
    s = services()
    assert secrets_of(s["web"]) == {"secret_key": "secret_key", "verification_key": "verification_key",
                                    "verification_fallback_keys": "verification_fallback_keys",
                                    "db_password": "app_password"}
    assert secrets_of(s["worker"]) == secrets_of(s["web"])
    assert secrets_of(s["fetcher"]) == {"secret_key": "secret_key", "db_password": "fetcher_password"}  # no link key
    assert secrets_of(s["migrate"]) == {"secret_key": "secret_key", "verification_key": "verification_key",
                                        "verification_fallback_keys": "verification_fallback_keys",
                                        "db_password": "owner_password"}
    assert secrets_of(s["db"]) == {"admin_password": "admin_password"}
    assert "admin_password" in secrets_of(s["provision-roles"]) and s["provision-roles"]["profiles"] == ["provision"]
    assert "secrets" not in s["collect-static"] and "secrets" not in s["proxy"] and "secrets" not in s["egress"]
    holders = [name for name, svc in s.items() if "admin_password" in secrets_of(svc).values()]
    assert sorted(holders) == ["db", "provision-roles", "restore"]  # the bootstrap credential reaches nothing else
    for name in ("web", "worker", "fetcher"):  # 6hl.10: no administrator or probe variable either
        assert not [k for k in s[name]["environment"] if k.startswith(("CATALYST_DB_ADMIN", "CATALYST_TEST_SUPERUSER"))]
    assert sorted(n for n, svc in s.items() if "backup_password" in secrets_of(svc).values()) == ["backup", "provision-roles"]
    assert secrets_of(s["backup"])["db_password"] == "backup_password"  # the backup reads as the backup role only
    assert s["backup"]["profiles"] == s["restore"]["profiles"] == ["ops"]  # operator-run, never started by `up`
    assert "catalyst-custody:/var/lib/catalyst/custody:ro" in s["backup"]["volumes"]


def test_6b5b_every_catalyst_container_is_locked_down_and_pinned_to_staging():
    s = services()
    for name in CATALYST:
        svc = s[name]
        assert svc["user"] == "10001:10001" and svc["read_only"] is True, name
        assert svc["cap_drop"] == ["ALL"] and "cap_add" not in svc, name
        assert svc["security_opt"] == ["no-new-privileges:true"], name
        assert {t.split(":")[0] for t in svc["tmpfs"]} == {"/tmp", "/dev/shm"}, name
        assert svc["environment"]["CATALYST_ENV"] == "staging", name
        assert svc["image"].startswith("${CATALYST_IMAGE:?"), name  # the attested digest, never a tag
    assert "command" not in s["web"]  # the image's fixed gunicorn command
    assert s["worker"]["command"][-2:] == ["--exclude", "fetch_evidence"]
    assert s["fetcher"]["command"][-2:] == ["--only", "fetch_evidence"]
    assert s["fetcher"]["environment"]["CATALYST_PROCESS_ROLE"] == "fetcher"
    assert s["fetcher"]["environment"]["CATALYST_DB_USER"] == "catalyst_fetcher"
    assert s["web"]["environment"]["CATALYST_DB_USER"] == s["worker"]["environment"]["CATALYST_DB_USER"] == "catalyst_app"
    assert s["migrate"]["environment"]["CATALYST_DB_USER"] == "catalyst_owner"
    for name, default in (("CATALYST_QUALIFICATION_AUTHORITY", ""), ("CATALYST_VERIFICATION_RESEND_LIMIT", "3"),
                          ("CATALYST_HEALTH_AGED_WAITS_PAGE", "replies_awaiting_processing,issued_agreements,provisioning_activation"),
                          ("CATALYST_HEALTH_PENDING_AGE_SECONDS", "3600")):  # PR #87 review: the launch values reach every container
        for svc in ("web", "worker", "migrate"):
            assert s[svc]["environment"][name] == f"${{{name}:-{default}}}", (svc, name)


def test_6b5b_the_socket_is_shared_only_with_the_proxy_and_only_the_proxy_has_an_open_network():
    definition = renderer().definition()
    s = definition["services"]
    sharing = [name for name, svc in s.items() if any(v.startswith("catalyst-run:") for v in svc.get("volumes", []))]
    assert sorted(sharing) == ["proxy", "web"]
    proxy = s["proxy"]
    assert proxy["user"] == "10001:10001" and proxy["cap_drop"] == ["ALL"] and proxy["cap_add"] == ["NET_BIND_SERVICE"]
    assert proxy["read_only"] is True  # no-new-privileges would stop the binary's file capability from running it
    assert "catalyst-run:/run/catalyst:ro" in proxy["volumes"]  # it connects to the socket, never replaces it
    assert s["fetcher"]["networks"] == ["backend", "fetch"]  # internal only: its way out is the egress proxy
    assert [n for n, svc in s.items() if "fetch" in svc.get("networks", [])] == ["fetcher", "egress"]
    assert "backend" not in s["egress"]["networks"]  # no other process can use the proxy (PR #76 review)
    assert renderer().definition()["networks"]["fetch"] == {"internal": True}
    assert s["fetcher"]["environment"]["CATALYST_EVIDENCE_PROXY"] == "egress:3128"
    assert [n for n, svc in s.items() if "egress" in svc.get("networks", [])] == ["egress"]  # alone on the way out
    assert s["egress"]["command"] == ["python", "-m", "assessments.egress"] and "ports" not in s["egress"]
    assert definition["networks"]["backend"] == {"internal": True}  # web, worker, fetcher and db reach nothing outside
    assert [n for n, svc in s.items() if "edge" in svc.get("networks", [])] == ["proxy"]
    assert s["collect-static"]["network_mode"] == "none"
    assert [n for n, svc in s.items() if "ports" in svc] == ["proxy"]


def test_6b5b_the_staff_site_is_published_only_on_a_named_private_address():
    proxy = services()["proxy"]
    public, staff = proxy["ports"]
    assert public == "${CATALYST_PUBLIC_PUBLISH:?}:${CATALYST_PUBLIC_PORT:-443}:8443"
    assert staff.startswith("${CATALYST_STAFF_PUBLISH:?") and staff.endswith("}:${CATALYST_STAFF_PORT:-443}:8444")  # no default address
    caddyfile = (ROOT / "deploy" / "staging" / "Caddyfile").read_text()
    assert "{$CATALYST_STAFF_HOST:staff.staging.test}:{$CATALYST_STAFF_PORT:8444}" in caddyfile
    assert ":{$CATALYST_HTTPS_PORT:443} {\n\ttls internal\n\tabort\n}" in caddyfile
    assert ":{$CATALYST_STAFF_PORT:8444} {\n\tbind {$CATALYST_STAFF_BIND:127.0.0.1}\n\ttls internal\n\tabort\n}" in caddyfile
    assert "https_port {$CATALYST_HTTPS_PORT:443}" in caddyfile and proxy["environment"]["CATALYST_HTTPS_PORT"] == "8443"
    assert proxy["environment"]["CATALYST_STAFF_PORT"] == "8444"


def test_6b5b_each_port_is_exactly_one_caddy_server():
    """Two servers on one port share it at random (6B.5b staging check): every site on a port binds the same way."""
    import re

    caddyfile = (ROOT / "deploy" / "staging" / "Caddyfile").read_text()
    blocks = re.findall(r"^(\S[^\n]*) \{\n(.*?)^\}", caddyfile, flags=re.M | re.S)
    staff_port = [body for address, body in blocks if "CATALYST_STAFF_PORT" in address]
    assert len(staff_port) == 2 and all("bind {$CATALYST_STAFF_BIND:127.0.0.1}" in body for body in staff_port)
    assert all("bind" not in body for address, body in blocks
               if "CATALYST_HTTPS_PORT" in address or "CATALYST_PUBLIC_HOST" in address)


def test_6b5b_the_database_never_logs_statements_or_parameters():
    command = services()["db"]["command"]
    for setting in ("log_statement=none", "log_parameter_max_length=0", "log_parameter_max_length_on_error=0",
                    "log_min_error_statement=panic"):
        assert setting in command


def test_6b5b_the_image_creates_the_mount_points_with_their_owners_and_modes():
    dockerfile = (ROOT / "Dockerfile").read_text()
    for line in ("install -d -o catalyst -g catalyst -m 0750 /run/catalyst",
                 "install -d -o catalyst -g catalyst -m 0700 /var/lib/catalyst/mail",
                 "install -d -o catalyst -g catalyst -m 0700 /var/lib/catalyst/effects",  # 9kg.33: the effect journal
                 "COPY scripts/provision_db_roles.py scripts/provision_db_roles.py"):
        assert line in dockerfile, line


# --- 9kg.31.11: the production definition is the staging definition with reviewed inputs only -----------------------

def _differences(left, right, path=""):
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            yield from _differences(left.get(key), right.get(key), f"{path}/{key}")
    elif left != right:
        yield path


def test_9kg_31_11_the_committed_production_file_is_exactly_the_rendering():
    committed = (ROOT / "deploy" / "production" / "compose.yaml").read_text()
    assert committed == renderer().render("production"), "run `python scripts/render_staging_compose.py --write`"
    json.loads(committed.split("\n", 2)[2])


def test_9kg_31_11_production_differs_from_staging_only_in_the_reviewed_inputs():
    module = renderer()
    staging, production = module.definition("staging"), module.definition("production")
    django = ("web", "worker", "fetcher", "migrate", "backup", "restore")  # the processes that load the settings
    live = ("CATALYST_CHALLENGE_LIFETIME_SECONDS", "CATALYST_MAIL_ALLOWED_HOSTS", "CATALYST_MAIL_USER_SHA256",
            "CATALYST_MAIL_DENIED_USER_SHA256", "CATALYST_SEND_EVIDENCE_SOURCE", "CATALYST_JOURNAL_SHIP_LAG_SECONDS",
            "CATALYST_FROM_EMAIL", "CATALYST_HEALTH_AGED_WAITS_PAGE", "CATALYST_HEALTH_PENDING_AGE_SECONDS")
    mail_route = ({"/networks/mail", "/services/post-restore", "/services/worker/networks", "/services/worker/secrets",
                   "/secrets/mail_password", "/services/journal-ship", "/services/egress/environment/CATALYST_EGRESS_FETCHING"}
                  | {f"/services/worker/environment/{key}" for key in module.MAIL_ENV})  # 9kg.79
    expected = ({"/name", "/services/egress/volumes", "/volumes/catalyst-effects/external", "/volumes/catalyst-effects/name"}
                | mail_route
                | {f"/secrets/{name}/file" for name in module.SECRET_FILES}
                | {f"/services/{name}/environment/CATALYST_ENV" for name in CATALYST}
                | {f"/services/{name}/environment/{key}" for name in django for key in live})
    assert set(_differences(staging, production)) == expected
    assert production["name"] == "catalyst-production"
    for name in CATALYST:
        assert production["services"][name]["environment"]["CATALYST_ENV"] == "production", name
    for name in django:
        environment = production["services"][name]["environment"]
        # Owner values have no default: a missing one stops `docker compose` before anything starts.
        for key in live:
            value = environment[key]
            assert value == module.SENT_FOLDER_SOURCE or (value.startswith(f"${{{key}:?") and value.endswith("}")), key
    assert production["services"]["egress"]["volumes"] == [
        "${CATALYST_EGRESS_DENY_FILE:?the operator-supplied deny list}:/etc/catalyst/egress-deny:ro"]
    assert all(s["file"].startswith("${CATALYST_PRODUCTION_SECRETS:?}/") for s in production["secrets"].values())
    # The journal is the restore's evidence: `down -v` cannot remove an external volume (032 section 3.3).
    assert production["volumes"]["catalyst-effects"] == {"external": True, "name": "catalyst-production-effects"}
    assert module.SENT_FOLDER_SOURCE == guards.SENT_FOLDER_SOURCE  # the renderer runs without Django, so it keeps a copy
    try:
        module.definition("prod")
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown environment rendered")


def test_9kg_79_only_the_worker_and_the_post_restore_step_reach_the_mail_host():
    module = renderer()
    production, staging = module.definition("production"), module.definition("staging")
    services = production["services"]
    assert production["networks"]["mail"] == {} and "mail" not in staging["networks"]  # staging stays loopback-only
    on_mail = {name for name, service in services.items() if "mail" in service.get("networks", [])}
    assert on_mail == {"worker", "post-restore"}
    for name, service in services.items():
        holds = {s["source"] for s in service.get("secrets", [])}
        environment = service.get("environment", {})
        if name in on_mail:
            assert "mail_password" in holds and environment["CATALYST_MAIL_HOST"].startswith("${CATALYST_MAIL_HOST:?")
        else:
            assert "mail_password" not in holds, name
            assert not any(key in environment for key in module.MAIL_ENV), name
    # The post-restore step reads the Sent folder only (the reconcile kind; RD-1) and never holds the administrator
    # password; `restore`, which does, has no route out.
    post, restore = services["post-restore"], services["restore"]
    assert post["environment"]["CATALYST_PROCESS_ROLE"] == "reconcile" and post["profiles"] == ["ops"]
    assert "admin_password" not in {s["source"] for s in post["secrets"]}
    assert "admin_password" in {s["source"] for s in restore["secrets"]} and restore["networks"] == ["backend"]
    assert services["web"]["networks"] == ["backend"] and services["fetcher"]["networks"] == ["backend", "fetch"]


def test_9kg_78_2_the_journal_ship_service_reaches_only_the_journal_and_its_destination():
    module = renderer()
    services = module.definition("production")["services"]
    ship = services["journal-ship"]
    assert ship["command"] == ["python", "manage.py", "catalyst_journal_ship", "--to", "/var/lib/catalyst/ship"]
    assert ship["network_mode"] == "none" and "networks" not in ship  # it never connects to anything
    assert ship["volumes"] == ["catalyst-effects:/var/lib/catalyst/effects",
                               "${CATALYST_JOURNAL_SHIP_DIR:?the off-host journal destination}:/var/lib/catalyst/ship"]
    assert {s["source"] for s in ship["secrets"]} == {"secret_key", "verification_key", "verification_fallback_keys",
                                                      "fetcher_password"}  # the least-privileged login, never used
    assert ship["profiles"] == ["ops"] and ship["restart"] == "no"
    assert services["egress"]["environment"]["CATALYST_EGRESS_FETCHING"] == "disabled"
    staging = module.definition("staging")["services"]
    assert "journal-ship" not in staging and "CATALYST_EGRESS_FETCHING" not in staging["egress"]["environment"]


def test_9kg_78_3_the_stack_check_takes_only_a_known_stack():
    import subprocess

    result = subprocess.run(["bash", str(ROOT / "scripts" / "staging_check.sh")], cwd=ROOT, capture_output=True,
                            text=True, timeout=60, env={"PATH": "/usr/bin:/bin", "CATALYST_STACK_ENV": "live"})
    assert result.returncode == 2 and "CATALYST_STACK_ENV must be staging or production" in result.stderr
    text = (ROOT / "scripts" / "staging_check.sh").read_text()
    # A real production journal volume on the host is never touched: the run refuses before creating its own.
    assert text.index("docker volume inspect catalyst-production-effects") < text.index("docker volume create")
    assert 'compose=(docker compose --project-name "$project" -f "deploy/$stack/compose.yaml")' in text
