"""The client identity the public limits key on (9kg.29; 026 section 8; 029 section 4.1).

One value, from one place, decided by CATALYST_CLIENT_IDENTITY (fixed in code, config.guards):

- `proxy`: the `X-Forwarded-For` header. The web process listens only on the proxy's unix socket and the proxy
  overwrites that header with the validated client address on every request (`header_up X-Forwarded-For {client_ip}`,
  with only explicitly configured upstream proxies trusted), so the header is trusted because of where the process listens, not because of anything the
  client sent. It must be exactly one IP literal: a list (a hop that was not the proxy), an empty value or anything
  that is not an address is "no identity", and issuance is then refused (config.throttle).
- `direct`: the peer address (`REMOTE_ADDR`), for the local environments, where the test client or the development
  server is the peer. A forwarded header is ignored there.

The identity is a bucket, never stored as such: IPv4 is the address, IPv6 is its /64 (one subscriber holds a /64, so
a per-address bucket there would be no limit at all). Only a hash of it reaches the database (config.throttle).
"""

import ipaddress

from django.conf import settings

FORWARDED_FOR = "HTTP_X_FORWARDED_FOR"
PEER = "REMOTE_ADDR"
IPV6_BUCKET_BITS = 64


def client_identity(request) -> str | None:
    """The request's client bucket, or None when the configured source gives no single valid address."""
    source = FORWARDED_FOR if settings.CATALYST_CLIENT_IDENTITY == "proxy" else PEER
    return bucket(request.META.get(source, ""))


def bucket(raw: str) -> str | None:
    """One IP literal to its bucket; a list, blank, or anything that is not an address is None."""
    raw = (raw or "").strip()
    if not raw or "," in raw or any(c.isspace() for c in raw):
        return None
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return None
    if address.version == 6:
        mapped = address.ipv4_mapped
        if mapped is not None:
            return str(mapped)
        return str(ipaddress.ip_network((address, IPV6_BUCKET_BITS), strict=False))
    return str(address)
