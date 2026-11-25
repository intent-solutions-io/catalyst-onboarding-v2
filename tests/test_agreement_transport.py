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


def test_legacy_credentials_are_exactly_scoped_and_never_a_fallback(tls, settings):
    fake = FakeDocumenso(tls.documenso).start()
    try:
        configure(settings, fake, tls)
        ref, _, _ = fake.template()
        raw = fake.add_envelope(
            template_ref=ref,
            external_id="onb_existing",
            recipients=[
                {
                    "id": 7001,
                    "email": "applicant@example.test",
                    "name": "Applicant",
                    "signingOrder": 1,
                }
            ],
        )
        envelope_id = raw["id"]
        settings.CATALYST_AGREEMENT_PROVIDER_TOKEN = "separate-v2-account"
        settings.CATALYST_AGREEMENT_LEGACY_TOKEN = TOKEN
        settings.CATALYST_AGREEMENT_LEGACY_ENVELOPES = {
            envelope_id: {
                "external_key": "onb_existing",
                "company_email": "company@example.test",
                "company_role": "APPROVER",
            }
        }
        assert provider.read(envelope_id).external_id == "onb_existing"
        assert provider.read_fields(envelope_id) == ()
        assert provider.signing_token(envelope_id, "applicant@example.test")
        assert provider.download(
            raw["envelopeItems"][0]["id"], envelope_id=envelope_id
        ).startswith(b"%PDF-")
        with pytest.raises(provider.ProviderError, match="legacy_item_not_in_envelope"):
            provider.download("foreign_item", envelope_id=envelope_id)
        provider.distribute(envelope_id)
        provider.cancel(envelope_id)
        # Creation, listing, unlisted IDs and unbound downloads use V2 only. No retry with the old key.
        for call in (
            lambda: provider.read("foreign_envelope"),
            lambda: provider.download("foreign_item"),
            lambda: provider.create_from_template(ref, "ag_new", []),
            lambda: provider.find_recent(1),
        ):
            before = len(fake.requests)
            with pytest.raises(provider.ProviderError, match="http_401"):
                call()
            assert len(fake.requests) == before + 1
        settings.CATALYST_AGREEMENT_LEGACY_TOKEN = ""
        before = len(fake.requests)
        with pytest.raises(
            provider.ProviderError, match="legacy_credential_missing"
        ) as raised:
            provider.read(envelope_id)
        assert not raised.value.sent and len(fake.requests) == before
    finally:
        fake.stop()
