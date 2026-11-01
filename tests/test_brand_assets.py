"""The two public artwork paths retain their exact bytes without application state."""

import hashlib

import pytest
from django.test import Client

from applications.brand_assets import ASSETS


@pytest.mark.parametrize("name", ASSETS)
def test_the_exact_artwork_is_read_only_and_immutable_on_public_and_alias_hosts(
    name, settings
):
    settings.ALLOWED_HOSTS = ["catalyst.example.test", "learn.example.test"]
    settings.CATALYST_PUBLIC_HOST_ALIASES = ["learn.example.test"]
    mime, digest = ASSETS[name]
    assert digest[:12] in name
    client = Client()
    path = f"/request-access/assets/{name}"
    for host in settings.ALLOWED_HOSTS:
        response = client.get(path, HTTP_HOST=host)
        assert response.status_code == 200
        raw = b"".join(response.streaming_content)
        assert hashlib.sha256(raw).hexdigest() == digest
        assert response["Content-Type"] == mime
        assert response["Content-Length"] == str(len(raw))
        assert response["ETag"] == f'"{digest}"'
        assert response["Cache-Control"] == "public, max-age=31536000, immutable"
        assert response["X-Content-Type-Options"] == "nosniff"
        assert not response.cookies
        head = client.head(path, HTTP_HOST=host)
        assert head.status_code == 200 and b"".join(head.streaming_content) == b""
        assert (
            head["Content-Length"] == str(len(raw)) and head["ETag"] == response["ETag"]
        )
        assert client.post(path, HTTP_HOST=host).status_code == 405


def test_asset_siblings_directories_and_traversal_are_not_routes(settings):
    settings.ALLOWED_HOSTS = ["catalyst.example.test"]
    client = Client(HTTP_HOST="catalyst.example.test")
    for name in ("", "unknown.svg", "manifest.json", "../urls.py", "%2e%2e/urls.py"):
        response = client.get(f"/request-access/assets/{name}")
        assert response.status_code == 404
