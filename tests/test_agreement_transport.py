"""Real TLS response completion at the signing provider boundary."""

import pytest

from agreements import provider
from tests.documenso_fake import TOKEN, FakeDocumenso
from tests.test_inbound import tls  # noqa: F401


def configure(settings, fake, tls):
    settings.CATALYST_AGREEMENT_PROVIDER_URL = (
        f"https://documenso.example.test:{fake.port}/api/v2"
    )
    settings.CATALYST_AGREEMENT_PROVIDER_ADDRESS = "127.0.0.1"
    settings.CATALYST_AGREEMENT_PROVIDER_CA_FILE = tls.ca
    settings.CATALYST_AGREEMENT_PROVIDER_TOKEN = TOKEN


@pytest.mark.parametrize("status", [200, 404])
def test_provider_consumes_a_response_that_closes_the_connection(tls, settings, status):
    fake = FakeDocumenso(tls.documenso).start()
    try:
        configure(settings, fake, tls)
        fake.fault("GET /envelope/", ("status", status, {"Connection": "close"}))
        if status == 200:
            response = provider.exchange("GET", "/envelope/synthetic")
            assert response.status == 200 and response.body == b"{}"
        else:
            with pytest.raises(provider.ProviderError, match="http_404") as raised:
                provider.exchange("GET", "/envelope/synthetic")
            assert raised.value.status == 404 and raised.value.sent
        assert len(fake.requests) == 1
    finally:
        fake.stop()
