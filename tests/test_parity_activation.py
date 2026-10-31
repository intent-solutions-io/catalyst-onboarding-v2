"""Production admission needs the pinned profile; ordinary synthetic refusals stay intact."""
import hashlib
import json
from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured

from config import guards, parity


def load(tmp_path, values, *, environment='production', digest=None):
    path = tmp_path / 'profile.json'
    raw = json.dumps({'decision': 'd54', 'settings': values}).encode()
    path.write_bytes(raw)
    namespace = {'CATALYST_ENV': environment}
    parity.configure(namespace, {'CATALYST_PARITY_CONFIG': str(path),
                                 'CATALYST_PARITY_SHA256': digest or hashlib.sha256(raw).hexdigest()},
                     lambda name, default: default)
    return namespace


def test_production_profile_is_digest_bound_and_does_not_contain_secrets(tmp_path):
    namespace = load(tmp_path, {'CATALYST_ASSESSMENT_MODEL': 'minimax:MiniMax-M3'})
    assert namespace['CATALYST_PARITY_ACTIVE']
    assert namespace['CATALYST_AGREEMENT_PROVIDER_TOKEN'] == ''
    with pytest.raises(ImproperlyConfigured, match='invalid'):
        load(tmp_path, {}, digest='0' * 64)
    with pytest.raises(ImproperlyConfigured):
        load(tmp_path, {}, environment='staging')
    for key in ('CATALYST_AGREEMENT_PROVIDER_TOKEN', 'CATALYST_ACTION_HANDLERS', 'CATALYST_PARITY_ACTIVE'):
        with pytest.raises(ImproperlyConfigured):
            load(tmp_path, {key: 'not permitted'})


def provider(**extra):
    return SimpleNamespace(**{'CATALYST_ENV': 'production', 'CATALYST_PARITY_ACTIVE': True,
                             'CATALYST_PROVIDER_ALLOWED_HOSTS': ['sign.example.org'],
                             'CATALYST_AGREEMENT_PROVIDER_URL': 'https://sign.example.org/api/v2',
                             'CATALYST_AGREEMENT_PROVIDER_ADDRESS': '8.8.8.8',
                             'CATALYST_AGREEMENT_PROVIDER_CA_FILE': '/etc/ssl/certs/ca-certificates.crt', **extra})


def test_production_provider_admission_preserves_target_and_secret_boundaries():
    assert guards.agreement_problems(provider(), {}) == []
    assert guards.agreement_problems(provider(CATALYST_PARITY_ACTIVE=False), {})
    assert guards.agreement_problems(provider(CATALYST_AGREEMENT_PROVIDER_ADDRESS='127.0.0.1'), {})
    assert guards.agreement_problems(provider(CATALYST_AGREEMENT_PROVIDER_URL='https://unknown.example.org/api/v2'), {})
    assert guards.agreement_problems(provider(CATALYST_AGREEMENT_PROVIDER_URL='http://sign.example.org/api/v2'), {})
    assert guards.agreement_problems(provider(CATALYST_AGREEMENT_PROVIDER_CA_FILE=''), {})
    assert parity.process_problems(provider(CATALYST_AGREEMENT_PROVIDER_TOKEN='synthetic'), 'web')
    assert parity.process_problems(provider(CATALYST_AGREEMENT_PROVIDER_TOKEN='synthetic'), 'worker') == []


def test_absent_profile_preserves_existing_wave_one_defaults():
    namespace = {'CATALYST_ENV': 'production', 'CATALYST_ASSESSMENT_MODEL': 'none'}
    parity.configure(namespace, {}, lambda name, default: default)
    assert namespace == {'CATALYST_ENV': 'production', 'CATALYST_ASSESSMENT_MODEL': 'none', 'CATALYST_PARITY_ACTIVE': False}


def test_the_production_mailbox_adapter_is_specific_and_scoped():
    configured = provider(CATALYST_PROVISIONING_ADAPTER='provisioning.mxroute.MXrouteHost',
                          CATALYST_PROVISIONING_DOMAIN='intentsolutions.io',
                          CATALYST_PROVISIONING_API_URL='https://sign.example.org',
                          CATALYST_PROVISIONING_API_SERVER='synthetic', CATALYST_PROVISIONING_API_ACCOUNT='synthetic',
                          CATALYST_PROVISIONING_API_KEY_FILE='/run/secrets/provisioning_api_key',
                          CATALYST_PROVISIONING_IMAP_HOST='mail.example.org', CATALYST_MAIL_ALLOWED_HOSTS=['mail.example.org'])
    assert parity.provisioning_problems(configured) == []
    configured.CATALYST_PROVISIONING_ADAPTER = 'arbitrary.module'
    assert parity.provisioning_problems(configured)
