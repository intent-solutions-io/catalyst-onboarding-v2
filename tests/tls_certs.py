"""Throwaway TLS material for the synthetic mail servers (016 section 6; owner decision M6). Generated at run
time with the `openssl` binary of the pinned test image into a private temporary directory, so no key is
ever committed. Two certificate authorities: the trusted one (whose certificate the transports are told to
trust) and an untrusted one.

- `good`: IP 127.0.0.1, signed by the trusted authority.
- `wrong_host`: DNS other.example.test only, signed by the trusted authority (hostname check fails).
- `untrusted`: IP 127.0.0.1, signed by the untrusted authority (chain check fails).
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

EXTENSIONS = ("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n"
              "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\nsubjectAltName={san}\n")


@dataclass(frozen=True)
class Pair:
    cert: str
    key: str


@dataclass(frozen=True)
class TLSMaterial:
    ca: str
    good: Pair
    wrong_host: Pair
    untrusted: Pair


def _openssl(*args, cwd):
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def _authority(directory: Path, name: str) -> tuple[str, str]:
    key, cert = directory / f"{name}.key", directory / f"{name}.pem"
    _openssl("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-keyout", str(key),
             "-out", str(cert), "-days", "2", "-subj", f"/CN=Catalyst synthetic {name}",
             "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign",
             "-addext", "subjectKeyIdentifier=hash", cwd=directory)
    return str(cert), str(key)


def _leaf(directory: Path, name: str, san: str, authority: tuple[str, str]) -> Pair:
    key, csr, cert, ext = (directory / f"{name}{suffix}" for suffix in (".key", ".csr", ".pem", ".ext"))
    ext.write_text(EXTENSIONS.format(san=san))
    _openssl("req", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-keyout", str(key), "-out", str(csr),
             "-subj", "/CN=synthetic mail server", cwd=directory)
    _openssl("x509", "-req", "-in", str(csr), "-CA", authority[0], "-CAkey", authority[1], "-CAcreateserial",
             "-out", str(cert), "-days", "2", "-extfile", str(ext), cwd=directory)
    return Pair(str(cert), str(key))


def generate(directory: Path) -> TLSMaterial:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    trusted, other = _authority(directory, "trusted-ca"), _authority(directory, "untrusted-ca")
    return TLSMaterial(
        ca=trusted[0],
        good=_leaf(directory, "good", "IP:127.0.0.1", trusted),
        wrong_host=_leaf(directory, "wrong-host", "DNS:other.example.test", trusted),
        untrusted=_leaf(directory, "untrusted", "IP:127.0.0.1", other),
    )
