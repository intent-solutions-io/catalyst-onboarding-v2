"""Staff talent search over confirmed submissions; no duplicate store or credential verification."""

from django import forms
from django.contrib.postgres.search import SearchQuery, SearchVectorField
from django.core.paginator import Paginator
from django.db.models import F, Func, JSONField, Value
from django.db.models.functions import JSONObject
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .staff_views import APPLICATION, staff_page

from applications.models import VersionAdoption

PAGE_SIZE = 25


class TalentSearchForm(forms.Form):
    q = forms.CharField(required=False, max_length=200, label="Search talent")
    page = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)


def profiles(query=""):
    """One immutable adoption per application. Erasure clears the source, with no index copy to purge.

    Only string values in the named talent fields enter the vector (not JSON keys, contact details,
    private-work descriptions, consent, or later unconfirmed versions). Plain AND queries use the
    simple dictionary so credential names are not English-stemmed. There is no ranking of applicants.
    """
    rows = VersionAdoption.objects.select_related(
        "application", "submission_version"
    ).exclude(application__email_key__startswith="erased:")
    if query:
        fields = "submission_version__submitted_fields__"
        document = JSONObject(
            name=F(fields + "name"),
            education=F(fields + "education"),
            credentials=F(fields + "claims__credentials"),
            contribution=F(fields + "claims__contribution"),
            experience=F(fields + "claims__experience"),
        )
        rows = rows.alias(
            talent_vector=Func(
                Value("simple"),
                document,
                Value(["string"], output_field=JSONField()),
                function="jsonb_to_tsvector",
                output_field=SearchVectorField(),
            )
        ).filter(talent_vector=SearchQuery(query, config="simple", search_type="plain"))
    return rows.order_by("-adopted_at", "-pk")


@require_GET
@staff_page(*APPLICATION)
def search(request):
    form = TalentSearchForm(request.GET)
    page = None
    query = ""
    if form.is_valid():
        query = form.cleaned_data["q"]
        page = Paginator(profiles(query), PAGE_SIZE).get_page(
            form.cleaned_data["page"] or 1
        )
    return render(
        request,
        "correspondence/staff/talent.html",
        {"form": form, "page": page, "query": query},
        status=200 if form.is_valid() else 400,
    )
