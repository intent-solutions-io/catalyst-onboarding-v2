"""An in-process fake of the documented MXroute mailbox operations (023 section 3), behind
`provisioning.adapter.MailHost`. Synthetic only; nothing is contacted.

`FakeMailHost.mailboxes` maps (domain, lower(local part)) to a Mailbox. `FakeMailHost.faults` queues behaviours for the
next calls:

- "create_unknown": the create lands but the answer is lost; "create_lost": no create, an unknown answer;
- "create_conflict", "create_rejected"; "create_429": the create lands, then a gateway throttles the answer;
- "read_500": MXroute's failed or ambiguous lookup; "read_500_after_create": the same, only once a create was made;
- "create_appears_first": someone creates the address in the panel just before our create.
"""

from provisioning.adapter import AdapterError, MailHost, Mailbox


class FakeMailHost(MailHost):
    mailboxes: dict = {}
    faults: list = []
    calls: list = []
    passwords_seen: list = []  # only to prove the test never sees one in a record

    @classmethod
    def reset(cls):
        cls.mailboxes, cls.faults, cls.calls, cls.passwords_seen = {}, [], [], []

    def _fault(self, *names):
        for name in names:
            if name in self.faults:
                self.faults.remove(name)
                return name
        return None

    def read(self, domain, local_part):
        self.calls.append(("read", domain, local_part))
        if self._fault("read_500") or (any(c[0] == "create" for c in self.calls) and self._fault("read_500_after_create")):
            raise AdapterError("SERVER_ERROR", sent=True, status=500)
        return self.mailboxes.get((domain.lower(), local_part.lower()))

    def create(self, domain, local_part, password, quota_mb, send_limit):
        self.calls.append(("create", domain, local_part))
        self.passwords_seen.append(password)
        key = (domain.lower(), local_part.lower())
        if self._fault("create_appears_first"):
            self.mailboxes[key] = Mailbox(local_part, domain, 512, 50, False)
        fault = self._fault("create_unknown", "create_lost", "create_conflict", "create_rejected", "create_429")
        if fault == "create_rejected":
            raise AdapterError("VALIDATION_ERROR", sent=True, status=400)
        if key in self.mailboxes or fault == "create_conflict":
            raise AdapterError("CONFLICT", sent=True, status=409)
        if fault == "create_lost":
            raise AdapterError("timeout", sent=True, status=None)
        self.mailboxes[key] = Mailbox(local_part, domain, quota_mb, send_limit, False)
        if fault in ("create_unknown", "create_429"):  # the create landed; the answer was lost or throttled
            raise AdapterError("RATE_LIMITED" if fault == "create_429" else "timeout", sent=True,
                               status=429 if fault == "create_429" else None, retry_after=1)
