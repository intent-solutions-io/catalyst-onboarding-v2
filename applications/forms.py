from django import forms

from .identity import email_key

# S1 synthetic placeholder field set (POL-03): name, email, reason. Limits match the model columns.
NAME_MAX = 200
EMAIL_MAX = 320
REASON_MAX = 2000
# P3 claim fields (018 section 2, P3-D-1; synthetic wording until POL-17). All optional; stored in the same
# versioned, adopted submission under "claims", and only when at least one is given.
URL_MAX, NOTE_MAX, TEXT_MAX, CLAIM_MAX = 2048, 200, 2000, 200
SLOTS = (1, 2, 3)


def _https_url(value):
    if value and not value.lower().startswith("https://"):
        raise forms.ValidationError("Enter a link that starts with https://.", code="invalid")
    return value


class AccessRequestForm(forms.Form):
    name = forms.CharField(max_length=NAME_MAX)
    email = forms.EmailField(max_length=EMAIL_MAX)
    reason = forms.CharField(max_length=REASON_MAX, widget=forms.Textarea)
    contribution = forms.CharField(max_length=TEXT_MAX, required=False, widget=forms.Textarea,
                                   label="What you personally did in the work you list")
    experience = forms.CharField(max_length=TEXT_MAX, required=False, widget=forms.Textarea, label="Relevant experience")
    confidential = forms.BooleanField(required=False, label="My relevant work is private or covered by confidentiality obligations")
    confidential_description = forms.CharField(
        max_length=TEXT_MAX, required=False, widget=forms.Textarea,
        label="Describe the kind of work only: no client names, secrets or confidential material")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for n in SLOTS:
            self.fields[f"work_url_{n}"] = forms.CharField(max_length=URL_MAX, required=False, validators=[_https_url],
                                                           label=f"Work sample {n}: link")
            self.fields[f"work_note_{n}"] = forms.CharField(max_length=NOTE_MAX, required=False,
                                                            label=f"Work sample {n}: one-line description")
        for n in SLOTS:
            self.fields[f"cred_name_{n}"] = forms.CharField(max_length=CLAIM_MAX, required=False, label=f"Credential {n}: name")
            self.fields[f"cred_issuer_{n}"] = forms.CharField(max_length=CLAIM_MAX, required=False, label=f"Credential {n}: issuer")
            self.fields[f"cred_identifier_{n}"] = forms.CharField(max_length=CLAIM_MAX, required=False,
                                                                  label=f"Credential {n}: identifier")
            self.fields[f"cred_url_{n}"] = forms.CharField(max_length=URL_MAX, required=False, validators=[_https_url],
                                                           label=f"Credential {n}: issuer's verification link")

    def claims(self) -> dict | None:
        """The claim fields as stored in the submission, or None when none was given (an S1-shaped submission)."""
        d = self.cleaned_data
        work = [{"url": d[f"work_url_{n}"], "note": d[f"work_note_{n}"]} for n in SLOTS
                if d[f"work_url_{n}"] or d[f"work_note_{n}"]]
        credentials = [{"name": d[f"cred_name_{n}"], "issuer": d[f"cred_issuer_{n}"], "identifier": d[f"cred_identifier_{n}"],
                        "url": d[f"cred_url_{n}"]} for n in SLOTS
                       if any(d[f"cred_{f}_{n}"] for f in ("name", "issuer", "identifier", "url"))]
        claims = {"work": work, "contribution": d["contribution"], "experience": d["experience"],
                  "credentials": credentials, "confidential": d["confidential"],
                  "confidential_description": d["confidential_description"]}
        given = work or credentials or d["contribution"] or d["experience"] or d["confidential"] or d["confidential_description"]
        return claims if given else None

    def clean_email(self):
        email = self.cleaned_data["email"]
        try:
            key = email_key(email)
        except ValueError:
            raise forms.ValidationError("Enter a valid email address.", code="invalid")
        if len(key) > EMAIL_MAX:  # normalization (NFKC, IDNA) can lengthen an address past the column
            raise forms.ValidationError("Enter a valid email address.", code="invalid")
        return email
