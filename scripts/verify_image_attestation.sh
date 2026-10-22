#!/usr/bin/env bash
# Verify a CI-built image before it may be deployed (026 section 9, H6; 6B.10), then load it and print its image id
# for deploy/staging/adapters/deploy.sh. Run by the host's deploy step, which accepts only a commit and this artifact.
#
#   scripts/verify_image_attestation.sh <catalyst-image.tar> <commit>
#
# The tarball is first copied into a private directory; that copy is the one verified and the one loaded, so nothing
# can be swapped between the two (PR #73 review). Refuses unless the copy's attestation was made by this repository's
# image workflow on refs/heads/main for exactly <commit>, on a GitHub-hosted runner, and the loaded image's commit label
# is <commit>. Needs the GitHub CLI (gh attestation verify).
set -euo pipefail
source_tar="${1:?usage: verify_image_attestation.sh <catalyst-image.tar> <commit>}"
commit="${2:?the commit being deployed}"
repo="intent-solutions-io/catalyst-onboarding-v2"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo "refused: the commit must be a full 40-character sha" >&2; exit 1; }

private="$(mktemp -d)"  # 0700, this user's own
trap 'rm -rf "$private"' EXIT
cp -- "$source_tar" "$private/image.tar"
tar="$private/image.tar"

gh attestation verify "$tar" --repo "$repo" --signer-workflow "$repo/.github/workflows/image.yml" \
  --source-ref refs/heads/main --source-digest "$commit" --deny-self-hosted-runners >/dev/null \
  || { echo "refused: no valid attestation from the main-branch image workflow for $commit" >&2; exit 1; }

loaded="$(docker load -i "$tar" | sed -n 's/^Loaded image ID: //p; s/^Loaded image: //p' | tail -1)"
[ -n "$loaded" ] || { echo "refused: the verified tarball loaded no image" >&2; exit 1; }
id="$(docker image inspect --format '{{.Id}}' "$loaded")"
label="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$id")"
[ "$label" = "$commit" ] || { echo "refused: the image's commit label is not $commit" >&2; exit 1; }
printf '%s\n' "$id"
