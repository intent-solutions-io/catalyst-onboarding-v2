#!/usr/bin/env bash
# Verify a CI-built image before it may be deployed (026 section 9, H6; 6B.10), then load it and print its image id
# for deploy/staging/adapters/deploy.sh. Run by the host's deploy step, which accepts only a commit and this artifact.
#
#   scripts/verify_image_attestation.sh <dir with catalyst-image.tar and catalyst-image.id> <commit>
#
# Refuses unless the tarball's attestation was made by this repository's image workflow on refs/heads/main for exactly
# <commit>, and the loaded image's id and commit label match. Needs the GitHub CLI (gh attestation verify).
set -euo pipefail
dir="${1:?usage: verify_image_attestation.sh <artifact dir> <commit>}"
commit="${2:?the commit being deployed}"
repo="intent-solutions-io/catalyst-onboarding-v2"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo "refused: the commit must be a full 40-character sha" >&2; exit 1; }
tar="$dir/catalyst-image.tar"
expected_id="$(<"$dir/catalyst-image.id")"
[[ "$expected_id" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "refused: the recorded image id is malformed" >&2; exit 1; }

gh attestation verify "$tar" --repo "$repo" --signer-workflow "$repo/.github/workflows/image.yml" \
  --source-ref refs/heads/main --source-digest "$commit" --deny-self-hosted-runners >/dev/null \
  || { echo "refused: no valid attestation from the main-branch image workflow for $commit" >&2; exit 1; }

loaded="$(docker load -i "$tar" | sed -n 's/^Loaded image ID: //p; s/^Loaded image: //p' | tail -1)"
id="$(docker image inspect --format '{{.Id}}' "$loaded")"
[ "$id" = "$expected_id" ] || { echo "refused: the loaded image id differs from the attested build's" >&2; exit 1; }
label="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$id")"
[ "$label" = "$commit" ] || { echo "refused: the image's commit label is not $commit" >&2; exit 1; }
printf '%s\n' "$id"
