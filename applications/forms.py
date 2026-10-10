from django import forms

from .identity import email_key

# S1 synthetic placeholder field set (POL-03): name, email, reason. Limits match the model columns.
NAME_MAX = 200
EMAIL_MAX = 320
REASON_MAX = 2000


class AccessRequestForm(forms.Form):
    name = forms.CharField(max_length=NAME_MAX)
    email = forms.EmailField(max_length=EMAIL_MAX)
    reason = forms.CharField(max_length=REASON_MAX, widget=forms.Textarea)

    def clean_email(self):
        email = self.cleaned_data["email"]
        try:
            key = email_key(email)
        except ValueError:
            raise forms.ValidationError("Enter a valid email address.", code="invalid")
        if len(key) > EMAIL_MAX:  # normalization (NFKC, IDNA) can lengthen an address past the column
            raise forms.ValidationError("Enter a valid email address.", code="invalid")
        return email
