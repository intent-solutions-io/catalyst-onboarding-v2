"""Applicants can recover errors in optional rows without losing their entries."""

import pytest

from tests.test_intake import EMPTY, counts, post


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
