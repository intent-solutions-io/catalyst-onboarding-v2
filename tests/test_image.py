"""6B.5 (026 section 4; TEST-P6-01, 37): what the image is built from, read from the Dockerfile and the build context
rules. Building and inspecting the image needs Docker, which the test containers do not have; that check is recorded
on the pull request (built locally) and is part of staging (6B.11)."""

import platform
import re

from tests.support import ROOT


def dockerfile() -> str:
    return (ROOT / "Dockerfile").read_text()


def test_6b5_the_base_image_is_the_digest_the_tests_run_on():
    compose = (ROOT / "compose.yaml").read_text()
    # Any 3.x.y patch release: the version is asserted against the interpreter below, not hard-coded here (a
    # hard-coded 3.14.8 made the 3.14.10 bump fail on the regex instead of on the digest, PR #143).
    match = re.search(r"image: (python:(3\.\d+\.\d+)-slim@sha256:[0-9a-f]{64})", compose)
    assert match, "compose.yaml pins no python:3.x.y-slim image by digest"
    pinned, version = match.group(1), match.group(2)
    assert re.findall(r"^FROM (\S+)", dockerfile(), flags=re.M)[0] == pinned
    assert version == platform.python_version()  # the tests run on exactly the interpreter the image is built from


def test_6b5_dependencies_are_hash_locked_and_the_process_is_not_root():
    text = dockerfile()
    # 9kg.34 (review of PR #102): wheels only, so no dependency's build step runs in the image
    assert "pip install --require-hashes --no-deps --only-binary=:all: -r requirements/base.txt" in text
    assert re.search(r"^USER catalyst$", text, flags=re.M) and "--uid 10001" in text
    assert "chmod -R a-w /app" in text  # the application files are read-only at run time


def test_6b5_the_web_process_writes_no_access_log_and_listens_only_on_a_private_unix_socket():
    command = re.search(r'^CMD \[(.*?)\]$', dockerfile().replace("\\\n", ""), flags=re.M | re.S).group(1)
    assert '"unix:/run/catalyst/web.sock"' in command and "access-log" not in command
    assert '"--umask", "0o117"' in command  # a 0660 socket: the proxy's group only
    assert '"--worker-tmp-dir", "/dev/shm"' in command  # the root filesystem is read-only
    assert "0.0.0.0" not in dockerfile() and "EXPOSE" not in dockerfile()


def test_6b5_no_secret_reaches_a_layer():
    text = dockerfile()
    for word in ("SOPS", "secrets", "password", "token"):
        assert not re.search(rf"^(ENV|ARG).*{word}", text, flags=re.M | re.I), word
    assert "build-only-not-a-secret" in text  # collectstatic runs with throwaway values, never a real secret


def test_6b5_the_build_context_excludes_tests_history_and_the_tracker():
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    assert ignore[ignore.index("*")] == "*"  # deny by default
    allowed = [line[1:] for line in ignore if line.startswith("!")]
    assert not any(path.startswith((".git", ".beads", "000-docs", ".claude")) for path in allowed)
    assert [p for p in allowed if p.startswith("tests/")] == ["tests/__init__.py", "tests/mxroute_fake.py",
                                                            "tests/documenso_fake.py"]  # the staging fakes only
    production = dockerfile().split("FROM base AS production")[1]
    assert "tests" not in production  # the production target adds no test code
    base = dockerfile().split("FROM base AS staging")[0]
    assert not re.search(r"^COPY .*tests", base, flags=re.M)  # nor does the shared base stage
    for pattern in ("**/*.env", "**/.env*", "**/*.sops*", "**/*.pem", "**/*.key", "**/*.sqlite3"):
        assert pattern in ignore  # secret-shaped files never enter a layer, even inside an allowed directory


def test_6b5_every_path_the_dockerfile_copies_is_in_the_build_context():
    """A directory added to the image must also be allowed by `.dockerignore`, or the build fails with "not found"
    (PR #99: the new `erasure` app was copied but not allowed). Docker is not in the test containers; this catches it
    from the two files."""
    allowed = {line[1:] for line in (ROOT / ".dockerignore").read_text().splitlines() if line.startswith("!")}
    sources = []
    for line in dockerfile().splitlines():
        if line.startswith("COPY ") and "--from=" not in line:
            sources += line.split()[1:-1]
    assert sources and all(source in allowed for source in sources), sorted(set(sources) - allowed)
