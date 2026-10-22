"""6B.8 (026 section 8; TEST-P6-12, 13, 33): the staging proxy configuration, generated from the application's own
path lists. What Caddy does with real requests (path normalization, the forged header, logs) is checked against the
running stack in 6B.11; here the configuration itself is pinned."""

import importlib.util
import re

from config.redaction import PRIVATE_PATHS
from tests.support import ROOT


def renderer():
    spec = importlib.util.spec_from_file_location("render_caddyfile", ROOT / "scripts" / "render_caddyfile.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def site(text: str, host_variable: str) -> str:
    start = text.index("{$" + host_variable)
    depth, i = 0, text.index("{", text.index("}", start) + 1)
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[start:j + 1]
    raise AssertionError("unterminated site block")


def test_6b8_the_committed_caddyfile_is_exactly_the_rendering():
    committed = (ROOT / "deploy" / "staging" / "Caddyfile").read_text()
    assert committed == renderer().render(), "run `python scripts/render_caddyfile.py --write` after a route change"


def test_6b8_token_paths_are_skipped_from_every_log_and_match_the_redaction_list():
    module = renderer()
    assert module.PRIVATE_PATHS == PRIVATE_PATHS  # the proxy and the application never drift
    text = module.render()
    assert f"@private_paths path {' '.join(p + '*' for p in PRIVATE_PATHS)}" in text
    assert text.count("import catalyst_logs") == 2 and "log_skip @private_paths" in text  # both sites


def test_6b8_the_public_site_serves_only_the_applicant_routes():
    public = site(renderer().render(), "CATALYST_PUBLIC_HOST")
    allowed = re.search(r"@applicant path (.+)", public).group(1).split()
    assert allowed == ["/request-access/", "/request-access/received/", *(p + "*" for p in PRIVATE_PATHS)]
    for absent in ("/staff", "/admin", "/healthz", "/readyz", "/static", "/hooks"):
        assert absent not in public
    assert "respond 404" in public and "max_size 128KB" in public


def test_6b8_the_staff_site_binds_privately_and_carries_only_staff_and_static():
    staff = site(renderer().render(), "CATALYST_STAFF_HOST")
    assert "bind {$CATALYST_STAFF_BIND:127.0.0.1}" in staff  # a tailnet address in staging, never all interfaces
    assert "@staff path /staff /staff/*" in staff and "handle_path /static/*" in staff and "respond 404" in staff
    for absent in ("/healthz", "/readyz", "/request-access", "/confirm"):
        assert absent not in staff


def test_6b8_the_forwarded_headers_are_overwritten_and_there_is_no_webhook_site():
    text = renderer().render()
    assert "header_up X-Forwarded-Proto {scheme}" in text and "header_up -X-Forwarded-Host" in text
    assert "unix//run/catalyst/web.sock" in text and "admin off" in text
    assert "documenso" not in text.lower() and "/hooks/" not in text  # not mounted until the pilot (P6-D-4)
