"""Long model explanations retain provenance and unsafe-text validation."""

import pytest

from tests.test_assessment import a, assessed, ev, p2, tls, valid  # noqa: F401 (shared fixtures)


@pytest.mark.parametrize("fault", ["", "quote", "unsafe_text"])
def test_p3_long_narratives_keep_provenance_checks_without_wasting_a_repair(
    a, monkeypatch, fault
):
    output = valid()
    output["criteria"][0]["summary"] = (
        "The sample describes parser implementation and validation. " * 20
    )
    output["recommendation_basis"] = (
        "The work sample supports this finding while the remaining criteria need evidence. "
        * 20
    )
    if fault == "quote":
        output["criteria"][0]["citations"][0]["quote"] = (
            "A passage absent from the evidence."
        )
    elif fault == "unsafe_text":
        output["recommendation_basis"] += " Contact someone@example.test."
    app, run, seen = assessed(a, monkeypatch, output)
    if not fault:
        assert run.status == "succeeded" and seen["calls"] == 1
        assert run.output["criteria"][0]["summary"] == output["criteria"][0]["summary"]
        assert run.output["recommendation_basis"] == output["recommendation_basis"]
        assert app.stage == "awaiting_decision"
    else:
        expected = (
            "quote_not_found_verbatim"
            if fault == "quote"
            else "free_text_contains_a_link_contact_or_markup"
        )
        assert run.status == "invalid_output" and seen["calls"] == 2
        assert expected in run.validation_codes
        assert run.output is None and app.stage == "assessing"
