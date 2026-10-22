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
    depth, i = 0, text.index(" {\n", start) + 1  # the site block opens at the end of its address line
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[start:j + 1]
    raise AssertionError("unterminated site block")


def test_6b8_the_committed_caddyfile_is_exactly_the_rendering():
    committed = (ROOT / "deploy" / "staging" / "Caddyfile").read_text()
    assert committed == renderer().render(), "run `python scripts/render_caddyfile.py --write` after a route change"


def test_6b8_token_segments_are_redacted_in_every_log_including_errors():
    module = renderer()
    assert module.PRIVATE_PATHS == PRIVATE_PATHS  # the proxy and the application never drift
    text = module.render()
    pattern = module.redaction_pattern()
    assert text.count(f"request>uri regexp {pattern} /$1/REDACTED") == 2  # the default (error) log and each site's
    assert "log default {" in text and "log_skip" not in text  # lines kept for the audit trail, tokens removed
    for path in PRIVATE_PATHS:
        name = path.strip("/")
        encoded = "".join(f"%{ord(ch):02X}" for ch in name)
        for variant in (f"{path}SENTINEL-TOKEN", f"/{path}SENTINEL-TOKEN", f"{path.upper()}SENTINEL-TOKEN",
                        f"/{encoded}/SENTINEL-TOKEN", f"/%{ord(name[0]):02x}{name[1:]}/SENTINEL-TOKEN",
                        f"/{name}%2FSENTINEL-TOKEN", f"/{name}/SENTINEL-TOKEN?x=1"):
            redacted = re.sub(pattern.replace("(?i)", ""), r"/\1/REDACTED", variant, flags=re.I)
            assert "SENTINEL-TOKEN" not in redacted, variant


def test_6b8_every_token_bearing_route_is_a_private_path():
    from django.urls import get_resolver

    def walk(patterns, prefix=""):
        for entry in patterns:
            route = prefix + str(entry.pattern)
            if hasattr(entry, "url_patterns"):
                yield from walk(entry.url_patterns, route)
            else:
                yield "/" + route
    token_routes = [r for r in walk(get_resolver().url_patterns) if "<str:token>" in r]
    assert token_routes, "the walk found no token routes"
    assert all(r.startswith(PRIVATE_PATHS) for r in token_routes), token_routes


def test_6b8_the_public_site_serves_only_the_applicant_routes():
    public = site(renderer().render(), "CATALYST_PUBLIC_HOST")
    allowed = re.search(r"@applicant path (.+)", public).group(1).split()
    assert allowed == ["/request-access/", "/request-access/received/", *(p + "*" for p in PRIVATE_PATHS)]
    for absent in ("/staff", "/admin", "/healthz", "/readyz", "/static", "/hooks"):
        assert absent not in public
    assert "import catalyst_not_found" in public and "max_size 128KB" in public


def test_6b8_the_staff_site_binds_privately_and_carries_only_staff_and_static():
    staff = site(renderer().render(), "CATALYST_STAFF_HOST")
    assert "bind {$CATALYST_STAFF_BIND:127.0.0.1}" in staff  # a tailnet address in staging, never all interfaces
    assert "@staff path /staff /staff/*" in staff and "handle_path /static/*" in staff and "import catalyst_not_found" in staff
    for absent in ("/healthz", "/readyz", "/request-access", "/confirm"):
        assert absent not in staff


def test_6b8_caddy_trusts_no_proxy_and_sets_the_forwarded_values_itself():
    text = renderer().render()
    assert "trusted_proxies" not in text  # the edge: no client's forwarded headers are believed
    assert "header_up X-Forwarded-Proto {scheme}" in text and "header_up X-Forwarded-For {remote_host}" in text
    assert "header_up -X-Forwarded-Host" in text and "unix//run/catalyst/web.sock" in text


def test_6b8_caddy_responses_carry_safe_headers_and_slow_clients_time_out():
    text = renderer().render()
    for line in ("?X-Content-Type-Options nosniff", "?Referrer-Policy no-referrer", "-Server", "header_down -Server",
                 "header Cache-Control no-store", "read_header 10s", "read_body 30s", "idle 2m", "hide .*"):
        assert line in text, line
    assert "Never import it into the shared estate Caddyfile" in text  # a dedicated staging instance (admin off)


def test_6b8_there_is_no_webhook_site():
    text = renderer().render()
    assert "documenso" not in text.lower() and "/hooks/" not in text  # not mounted until the pilot (P6-D-4)
