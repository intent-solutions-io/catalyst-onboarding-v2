"""A Content-Security-Policy for every Catalyst response (003 "Security implications"; 026 section 8; 6B.2).

Django 5.2 has no built-in CSP. Catalyst pages carry no script at all and one inline style block (the staff
screens), so the policy allows only same-origin resources and inline styles, and forbids framing, plugins, base
rewriting and posting forms elsewhere. A view that sets its own policy (the audited PDF download) keeps it.
"""

POLICY = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
          "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


class ContentSecurityPolicy:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", POLICY)
        return response
