# Catalyst v2 image (026 section 4; 6B.5). One image, several process kinds: web (gunicorn on the proxy's unix
# socket, no access log), worker and fetcher (manage.py run_worker with --exclude / --only), migrate (manage.py
# migrate as the owner role). Two targets: `production` carries the application only; `staging` adds the two
# synthetic fakes staging is allowed to use (6B.1). Secrets never enter a layer; they are mounted at run time.
FROM python:3.14.8-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings CATALYST_STATIC_ROOT=/app/static
RUN groupadd --system --gid 10001 catalyst \
    && useradd --system --uid 10001 --gid catalyst --no-create-home --shell /usr/sbin/nologin catalyst
WORKDIR /app
COPY requirements/base.txt requirements/base.txt
RUN pip install --require-hashes --no-deps -r requirements/base.txt
COPY manage.py ./
COPY accounts/ accounts/
COPY agreements/ agreements/
COPY applications/ applications/
COPY assessments/ assessments/
COPY config/ config/
COPY correspondence/ correspondence/
COPY provisioning/ provisioning/
COPY workflow/ workflow/
COPY scripts/provision_db_roles.py scripts/provision_db_roles.py
# Static files are collected at build time with throwaway values: collectstatic reads no secret and no database.
RUN CATALYST_ENV=development CATALYST_SECRET_KEY=build-only-not-a-secret CATALYST_VERIFICATION_KEY=build-only-other \
    CATALYST_DB_NAME=x CATALYST_DB_USER=x CATALYST_DB_PASSWORD=x CATALYST_DB_HOST=x CATALYST_CHALLENGE_LIFETIME_SECONDS=3600 \
    CATALYST_PUBLIC_BASE_URL=https://build.invalid python manage.py collectstatic --noinput --verbosity 0
ARG CATALYST_COMMIT=unknown
LABEL org.opencontainers.image.revision=$CATALYST_COMMIT \
      org.opencontainers.image.source=https://github.com/intent-solutions-io/catalyst-onboarding-v2
RUN echo "$CATALYST_COMMIT" > /app/COMMIT && chmod -R a-w /app \
    && install -d -o catalyst -g catalyst -m 0750 /run/catalyst \
    && install -d -o catalyst -g catalyst -m 0700 /var/lib/catalyst/mail \
    && install -d -o catalyst -g catalyst -m 0755 /srv/static \
    && install -d -o catalyst -g catalyst -m 0700 /var/lib/catalyst/backups /var/lib/catalyst/custody
# Mount points (6B.5b): the web socket's directory, shared only with the proxy's group; the private file mail sink;
# the static copy the proxy serves. A named volume takes these owners and modes on first use.
USER catalyst
# No --access-logfile: gunicorn writes no access log unless told to, and links carry bearer tokens (026 section 8).
# --umask 0o117 (octal: gunicorn reads a bare 117 as decimal) makes the socket 0660 (the proxy's group only, 026 section 4); --worker-tmp-dir /dev/shm because the
# root filesystem is read-only; errors go to stderr at warning level (PR #65 review).
CMD ["gunicorn", "config.wsgi:application", "--bind", "unix:/run/catalyst/web.sock", "--umask", "0o117", \
     "--worker-tmp-dir", "/dev/shm", "--workers", "3", "--timeout", "30", "--error-logfile", "-", "--log-level", "warning"]

FROM base AS staging
USER root
COPY tests/__init__.py tests/mxroute_fake.py tests/documenso_fake.py tests/
RUN chmod -R a-w /app/tests
USER catalyst

FROM base AS production
