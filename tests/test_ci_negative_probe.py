"""Deliberate failure for the CI negative-path probe. Never merged."""


def test_deliberate_failure_probe():
    assert False, "probe: the runtime job must fail and the required check must not succeed"
