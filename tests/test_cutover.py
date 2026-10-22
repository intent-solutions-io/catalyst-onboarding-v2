"""TEST-P6-26 (026 section 9): the cutover's route snippets. The rehearsal itself (switch, R1 rollback with R2 kept,
LMS paths byte-identical) runs in scripts/cutover_rehearsal.sh on the dev box."""

import importlib.util
import re

from config.redaction import PRIVATE_PATHS
from tests.support import ROOT

CUTOVER = ROOT / "deploy" / "cutover"


def matcher(name: str) -> list[str]:
    return re.search(r"^@catalyst_\w+ path (.+)$", (CUTOVER / name).read_text(), flags=re.M).group(1).split()


def staging_renderer():
    spec = importlib.util.spec_from_file_location("render_caddyfile", ROOT / "scripts" / "render_caddyfile.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_6b11_r2_is_exactly_the_token_return_paths():
    assert matcher("catalyst-r2.caddy") == [prefix + "*" for prefix in PRIVATE_PATHS]


def test_6b11_r1_is_exactly_the_entry_pages_the_staging_proxy_serves():
    assert matcher("catalyst-r1.caddy") == list(staging_renderer().PUBLIC_EXACT)


def test_6b11_r1_and_r2_together_are_every_applicant_route_and_nothing_more():
    staging = re.search(r"@applicant path (.+)", staging_renderer().render()).group(1).split()
    assert sorted(matcher("catalyst-r1.caddy") + matcher("catalyst-r2.caddy")) == sorted(staging)
    for name in ("catalyst-r1.caddy", "catalyst-r2.caddy"):
        text = (CUTOVER / name).read_text()
        assert "reverse_proxy {$CATALYST_UPSTREAM:" in text and "/staff" not in text and "healthz" not in text


def test_6b11_the_learn_log_snippet_is_the_rendering_and_redacts_every_token_path():
    renderer = staging_renderer()
    committed = (CUTOVER / "catalyst-learn-log.caddy").read_text()
    assert committed == renderer.render_learn_log(), "run `python scripts/render_caddyfile.py --write`"
    assert f"request>uri regexp {renderer.redaction_pattern()} /$1/REDACTED" in committed


def test_6b11_the_snippets_overwrite_the_forwarded_headers_and_default_to_the_web_socket():
    for name in ("catalyst-r1.caddy", "catalyst-r2.caddy"):
        text = (CUTOVER / name).read_text()
        assert "reverse_proxy {$CATALYST_UPSTREAM:unix//run/catalyst/web.sock}" in text  # a reload needs no new variable
        for line in ("header_up X-Forwarded-Proto {scheme}", "header_up X-Forwarded-For {remote_host}",
                     "header_up -X-Forwarded-Host"):
            assert line in text, (name, line)

