"""9kg.68: one real browser check of the public applicant pages at a phone width and a desktop width.

The screen walkthrough (9kg.41, tests/test_screen_walkthrough.py) could only read the rendered HTML for phone fit. This
module renders the same pages in a real headless Chromium (Playwright, pinned in requirements/browser.txt; the browser
image in compose.browser.yaml) and measures them: the request-access form in open mode and in invitation mode (with the
data notice), the request-received page, the confirm-your-address page and its result, the set-your-own-password page
(with its refusal and its result) and the withdrawal page and its result.

On each page, at each width, it asserts:
- the viewport declaration is honoured: the phone context is a mobile one (Chromium ignores the declaration on a
  desktop context and lays a page without it out 980 px wide), so the layout width equals the device width only if the
  page declares `width=device-width`;
- no horizontal scroll: the document is no wider than the layout viewport;
- every form control is visible, lies inside the viewport horizontally, accepts a pointer once scrolled to (Playwright's
  actionability checks: visible, stable, enabled, not covered) and is reached by the Tab key.
The forms are then filled and submitted in the browser, so the pages that follow are the real next pages.

How the page reaches the browser: every request the page makes is intercepted (`page.route`) and answered in-process
through Django's test client with CSRF checks enforced, so the views, middleware, templates and response headers are
the application's own and the data is the suite's synthetic data in the test transaction. The browser container never
reaches the application, the database or anything else: a request for any other origin is aborted and fails the test.

Not collected by the full suite (the file name does not start with `test_`; a skip fails the suite, tests/conftest.py)
because it needs the browser service. Run it with scripts/browser_check.sh (009 section 5.3).
"""

import contextlib
import os
import re
from importlib.metadata import version
from urllib.parse import urlsplit

import pytest
from django.conf import settings
from django.core import mail
from django.db import connections
from django.test import Client
from playwright.sync_api import sync_playwright

from applications.models import Application
from applications.identity import email_key
from provisioning import closure
from tests.support import ROOT
from tests.test_closure import WITHDRAW_LINK, complete
from tests.test_confirmation import link_for, path_of
from tests.test_credentials import PASSWORD, invited
from tests.test_invitation import closed
from tests.test_outbound import FORM, run_worker
from tests.test_closure import cl  # noqa: F401  (fixture chain)
from tests.test_provisioning import a, c, d, ev, g, h, k, p2, pv, tls  # noqa: F401

ORIGIN = settings.CATALYST_PUBLIC_BASE_URL  # http://catalyst.example.test: synthetic, never contacted
PHONE = {"viewport": {"width": 375, "height": 667}, "is_mobile": True, "has_touch": True, "device_scale_factor": 2}
DESKTOP = {"viewport": {"width": 1280, "height": 800}}
WIDTHS = {"phone": PHONE, "desktop": DESKTOP}
LONG_LINK = "https://work.example.test/" + "unbrokensyntheticpathsegment" * 8  # no hyphen or slash to break at
CONTROLS = "main input:not([type=hidden]), main textarea, main select, main button"


@contextlib.contextmanager
def chromium():
    """The browser server's Chromium, opened after a test has built its synthetic data. While the synchronous Playwright
    client runs, its event loop sits on this thread and Django's guard against database access from async code would
    refuse the ORM calls made by the request handler and the assertions, so the guard is lifted for exactly that span
    (one thread, one request at a time) and restored after. Fixtures and workers run before it, guard intact.

    Once the client runs, Django's context-local connection storage reads as empty, both here and in the request
    handler (Playwright's own greenlet), and a query would open a second connection outside the test's transaction:
    its writes committed past the test, and a session the provisioning reset refuses to run beside. So the test's own
    connection is put back here, and handed to the handler with each request (Session)."""
    endpoint = os.environ.get("CATALYST_BROWSER_WS")
    assert endpoint, "no browser service: run this module with scripts/browser_check.sh"
    image = re.search(r"playwright/python:v([\d.]+)-", (ROOT / "compose.browser.yaml").read_text()).group(1)
    assert version("playwright") == image, "requirements/browser.txt and the image in compose.browser.yaml differ"
    database = connections["default"]  # the test's connection, captured before the client changes the context
    previous = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
    try:
        with sync_playwright() as playwright:
            connections["default"] = database
            browser = playwright.chromium.connect(endpoint, timeout=120_000)
            try:
                yield browser
            finally:
                browser.close()
    finally:
        if previous is None:
            os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
        else:
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = previous


class Session:
    """One browser context at one width, served by one test client (its own cookies and CSRF token)."""

    def __init__(self, browser, width):
        self.width = width
        self.client = Client(enforce_csrf_checks=True)
        self.outside, self.failures = [], []
        self.database = connections["default"]  # the test's connection (chromium()), for the handler
        self.context = browser.new_context(**WIDTHS[width])
        self.page = self.context.new_page()
        self.page.route("**/*", self.answer)

    def answer(self, route, request):
        parts = urlsplit(request.url)
        if f"{parts.scheme}://{parts.netloc}" != ORIGIN:
            self.outside.append(request.url)
            route.abort()
            return
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        try:
            connections["default"] = self.database
            response = self.client.generic(request.method, path, data=request.post_data_buffer or b"",
                                           content_type=request.headers.get("content-type", "application/octet-stream"))
            # Chromium does not hand a redirect of a fulfilled request back to the route, so a redirect within the
            # origin is followed here, as the browser would follow it, and the page it leads to is the one fulfilled.
            for _ in range(5):
                location = response.get("Location", "") if response.status_code in (301, 302, 303) else ""
                if not location or (location.startswith("http") and not location.startswith(ORIGIN + "/")):
                    break
                response = self.client.get(location.removeprefix(ORIGIN))
        except Exception as exc:  # reported by close(), never swallowed
            self.failures.append(f"{request.method} {path}: {exc!r}")
            route.abort()
            return
        # The client keeps the cookies; the browser gets every other header the application sent.
        headers = {name: value for name, value in response.items() if name.lower() != "set-cookie"}
        route.fulfill(status=response.status_code, headers=headers, body=response.content)

    def open(self, path):
        response = self.page.goto(ORIGIN + path)
        assert response.status == 200, (path, response.status, self.failures)

    def close(self):
        self.context.close()
        assert self.failures == [], f"the application raised while answering the browser: {self.failures}"
        assert self.outside == [], f"the page asked for another origin: {self.outside}"


def check_fit(session, heading):
    """The layout assertions for the page now shown. Returns the measurements, for the report."""
    page = session.page
    assert page.locator("h1").inner_text() == heading
    measured = page.evaluate("""() => ({
        inner: window.innerWidth,
        client: document.documentElement.clientWidth,
        scroll: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
        viewport: document.querySelector('meta[name=viewport]')?.content || null,
    })""")
    expected = WIDTHS[session.width]["viewport"]["width"]
    where = f"{session.width} {page.url} {measured}"
    assert measured["viewport"] == "width=device-width, initial-scale=1", where
    assert measured["inner"] == measured["client"] == expected, where  # the declaration is honoured
    assert measured["scroll"] <= measured["client"], where  # no horizontal scroll
    controls = page.locator(CONTROLS)
    count = controls.count()
    page.evaluate(f"() => document.querySelectorAll({CONTROLS!r}).forEach((e, i) => e.dataset.reach = i)")
    for index in range(count):
        control = controls.nth(index)
        control.scroll_into_view_if_needed()
        assert control.is_visible(), (where, index)
        box = control.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= measured["client"] + 0.5, (where, index, box)
        control.click(trial=True)  # visible, stable, enabled and not covered: a pointer can use it
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    reached = set()
    for _ in range(count + 5):
        page.keyboard.press("Tab")
        reached.add(page.evaluate("() => document.activeElement?.dataset.reach ?? null"))
    assert {str(i) for i in range(count)} <= reached, (where, "a control is not reached by the Tab key", reached)
    # The evidence line for the report (shown for passing tests by the script's `-rP`).
    print(f"{session.width:7} {heading!r}: layout {measured['client']} px of {expected}, document {measured['scroll']} px"
          f" wide, {count} control(s) visible, inside, clickable and Tab-reached")
    return {**measured, "controls": count}


def submit(session, label, heading):
    with session.page.expect_navigation(timeout=60_000):
        session.page.get_by_role("button", name=label).click()
    assert session.failures == [], session.failures
    return check_fit(session, heading)


@pytest.mark.django_db
@pytest.mark.parametrize("width", WIDTHS)
def test_request_access_in_open_mode_then_received_then_confirm_fit_and_work(width):
    address = f"ada-{width}@example.test"
    with chromium() as browser:
        session = Session(browser, width)
        session.open(FORM)
        assert check_fit(session, "Request access")["controls"] >= 4  # name, email, reason and the button at least
        session.page.locator("#id_name").fill("Ada Example")
        session.page.locator("#id_email").fill(address)
        session.page.locator("#id_reason").fill("Synthetic reason for access, long enough to wrap. " * 3)
        # bgl.3 (034 row 3): the first-generation answers the form requires.
        session.page.locator("#id_residence_country").select_option("GB")
        session.page.locator("#id_phone_country").select_option("GB")
        session.page.locator("#id_phone").fill("+44 20 7946 0958")
        session.page.locator("#id_interest_track").select_option("cert_only")
        for box in ("#id_no_degree", "#id_no_certifications", "#id_verification_consent", "#id_age_attested"):
            session.page.locator(box).check()
        # One unbroken link far wider than a phone: the confirm page must wrap it, not scroll sideways.
        session.page.locator("#id_work_url_1").fill(LONG_LINK)
        assert submit(session, "Send request", "Request received")["controls"] == 0
        app = Application.objects.get(email_key=email_key(address))
        session.open(path_of(link_for(app)))
        assert check_fit(session, "Confirm your email address")["controls"] == 1
        assert address in session.page.content() and LONG_LINK in session.page.content()
        assert submit(session, "Confirm", "Email address confirmed")["controls"] == 0
        session.close()


@pytest.mark.django_db
@pytest.mark.parametrize("width", WIDTHS)
def test_request_access_in_invitation_mode_with_the_data_notice_fits(width, settings):
    closed(settings)
    with chromium() as browser:
        session = Session(browser, width)
        session.open(FORM)
        check_fit(session, "Request access")
        assert session.page.get_by_text("Access is currently by invitation.").is_visible()
        assert session.page.locator("#data-notice").is_visible()
        session.close()


def test_set_your_own_password_fits_refuses_a_mismatch_and_completes(pv, monkeypatch):
    _, _, path = invited(pv, monkeypatch)
    with chromium() as browser:
        for width in WIDTHS:  # a GET never spends the link
            session = Session(browser, width)
            session.open(path)
            assert check_fit(session, "Set your mailbox password")["controls"] == 3
            session.close()
        session = Session(browser, "phone")
        session.open(path)
        session.page.get_by_label("Password (8 to 72 characters)").fill(PASSWORD)
        session.page.get_by_label("The same password again").fill(PASSWORD + "x")
        submit(session, "Set my password", "Set your mailbox password")
        assert session.page.get_by_role("alert").inner_text() == "The two entries do not match."
        session.page.get_by_label("Password (8 to 72 characters)").fill(PASSWORD)
        session.page.get_by_label("The same password again").fill(PASSWORD)
        assert submit(session, "Set my password", "Your password is set")["controls"] == 0
        session.close()


def test_withdrawal_fits_and_completes(cl, monkeypatch):
    app = complete(cl, monkeypatch)
    closure.request_withdrawal_link(app.pk, cl.closer, "Applicant asked to withdraw by email")
    run_worker()
    path = WITHDRAW_LINK.search(mail.outbox[-1].body).group(1)
    with chromium() as browser:
        for width in WIDTHS:  # a GET changes nothing
            session = Session(browser, width)
            session.open(path)
            assert check_fit(session, "Withdraw your application")["controls"] == 1
            session.close()
        session = Session(browser, "phone")
        session.open(path)
        assert submit(session, "Yes, withdraw my application", "Your application is withdrawn")["controls"] == 0
        session.close()
    assert Application.objects.get(pk=app.pk).stage == "withdrawn"
