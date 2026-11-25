"""Applicants can recover errors in optional rows without losing their entries, and the public pages state the terms of
joining and link the policies (bgl.24)."""

import pytest
from django.test import Client
from django.urls import reverse

from tests.test_intake import EMPTY, FORM, RECEIVED, counts, post


@pytest.mark.django_db
def test_error_in_extra_education_opens_its_section_and_keeps_the_answer(client):
    response = post(client, no_degree="", edu_institution_2="Synthetic College")
    assert response.status_code == 200
    assert "edu_credential_2" in response.context["form"].errors
    page = response.content.decode()
    assert "<details open>\n          <summary>Additional education" in page
    assert 'href="#id_edu_credential_2"' in page
    assert 'value="Synthetic College"' in page
    assert counts() == EMPTY


@pytest.mark.django_db
def test_bgl24_the_public_pages_state_the_terms_of_joining_the_next_email_and_the_policies(
    settings,
):
    settings.CATALYST_INTAKE_MODE = "open"
    client = Client()
    form = client.get(FORM).content.decode()
    assert (
        "Applying is free. Requests are reviewed. Accepted members sign a mutual NDA and a User Agreement, receive a "
        "company mailbox, and use it to register for Claude Certified Architect (CCA): Foundations. The exam fee is "
        "paid by the member. Joining creates no employment relationship and guarantees no work, no certification and "
        "no partner-program standing."
    ) in form
    assert (
        "free to join" not in form and 'name="form_token"' in form
    )  # the fields and the data notice stay
    received = client.get(RECEIVED).content.decode()
    assert (
        "Your receipt email arrives within a few minutes from agreements@intentsolutions.io. If your request "
        "advances, the next email is the NDA. Questions: reply to the receipt."
    ) in received
    signed = client.get(reverse("signing_return")).content.decode()
    assert (
        "Thanks, your signature is recorded." in signed
        and "Our countersignature is automatic, usually within minutes." in signed
    )
    assert (
        "If you just signed the NDA, the next email is the User Agreement." in signed
    )  # the page cannot tell which
    assert (
        "If you just signed the User Agreement, the next email is your welcome with your company mailbox."
        in signed
    )
    how = '<a href="https://intentsolutions.io/how-it-works/">How joining works</a>'
    for page in (form, received, signed):
        assert 'alt="Claude Partner Network: Select Services Partner"' in page
        assert (
            '<a href="https://intentsolutions.io/privacy/">Privacy Policy</a>' in page
        )
        assert (
            '<a href="https://intentsolutions.io/data-retention/">Data Retention Policy</a>'
            in page
        )
        assert '<a href="https://intentsolutions.io/terms/">Terms</a>' in page
        assert (
            '<a href="https://intentsolutions.io/acceptable-use/">Acceptable use</a>'
            in page
        )
    for page in (received, signed):
        assert how in page and "Back to Learn" not in page
    assert (
        "Back to Learn" in form and how not in form
    )  # the other pages keep the footer link they had
