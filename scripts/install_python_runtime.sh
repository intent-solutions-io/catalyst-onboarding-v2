#!/bin/sh
# The Wolfi build includes CPython's 3.14 FIPS fix (python/cpython#160984).
# Install the same signed interpreter package for production and the test suite.
set -eu
apk add --no-cache python-3.14=3.14.10_git20261118-r0 py3.14-pip ca-certificates-bundle tzdata
