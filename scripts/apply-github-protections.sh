#!/usr/bin/env bash
# Apply the `main` ruleset and the protected `release` environment (009 section 5.5, P6-D-5, bead 9kg.35).
#
# Run by the owner, by hand, with the owner's own GitHub credentials. An agent session must not run the apply
# mode (council record 030, Q7 and Q9). Dry-run by default: it prints what it would send and reads back the
# current state. `--apply` sends the changes, then reads back. Idempotent: an existing ruleset of the same name
# is updated, not duplicated; the environment is upserted.
#
# What it configures:
#   - ruleset "main-protections" on refs/heads/main, enforcement active, empty bypass list: pull request required
#     (0 approvals: one maintainer, see 009), the required checks pinned to the GitHub Actions app, strict
#     (up to date with main), linear history, no force-push, no deletion;
#   - environment "release": wait timer, the owner as reviewer (recorded as not independent), self-review allowed,
#     deployments limited to the branch `main`.
# What it does not do: it never touches the merge-guard registration (kept outside this repository) and never
# creates a deploy credential. Verify afterwards with a probe pull request that has no checks: it must not merge.
set -euo pipefail

REPO="${REPO:-intent-solutions-io/catalyst-onboarding-v2}"
RULESET_NAME="${RULESET_NAME:-main-protections}"
ENVIRONMENT="${ENVIRONMENT:-release}"
WAIT_TIMER="${WAIT_TIMER:-5}"
GITHUB_ACTIONS_APP_ID=15368
APPLY=0
WITH_SCAN=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --with-scan) WITH_SCAN=1 ;;   # bead 9kg.36: add the image scan to the required contract
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

checks='[{"context":"Markdown lint and doc index check","integration_id":'"$GITHUB_ACTIONS_APP_ID"'},{"context":"Runtime checks (Python 3.14.8, PostgreSQL 16.15)","integration_id":'"$GITHUB_ACTIONS_APP_ID"'}'
if [ "$WITH_SCAN" = 1 ]; then
  checks="$checks"',{"context":"Build and scan the image","integration_id":'"$GITHUB_ACTIONS_APP_ID"'}'
fi
checks="$checks]"

ruleset=$(cat <<EOF
{
  "name": "$RULESET_NAME",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "required_linear_history"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 0,
      "dismiss_stale_reviews_on_push": true,
      "require_code_owner_review": false,
      "require_last_push_approval": false,
      "required_review_thread_resolution": false}},
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": true,
      "required_status_checks": $checks}}
  ]
}
EOF
)

echo "== identity"
gh api user --jq '"login: " + .login' || { echo "gh is not authenticated" >&2; exit 1; }
owner_login=$(gh api user --jq .login)
owner_id=$(gh api user --jq .id)
if [ -n "${EXPECTED_LOGIN:-}" ] && [ "$owner_login" != "$EXPECTED_LOGIN" ]; then
  echo "authenticated as $owner_login, expected $EXPECTED_LOGIN; the reviewer would be the wrong account" >&2; exit 1
fi
perm=$(gh api "repos/$REPO" --jq '.permissions.admin')
echo "admin on $REPO: $perm"
[ "$perm" = "true" ] || { echo "this needs the owner's administration right; an agent token must not have it" >&2; exit 1; }

env_body=$(cat <<EOF
{"wait_timer": $WAIT_TIMER, "prevent_self_review": false, "can_admins_bypass": false,
 "reviewers": [{"type": "User", "id": $owner_id}],
 "deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
EOF
)

echo "== current state (read-only)"
rulesets_json=$(gh api "repos/$REPO/rulesets") || { echo "could not list rulesets; not continuing" >&2; exit 1; }
existing_id=$(printf '%s' "$rulesets_json" | jq -r ".[] | select(.name==\"$RULESET_NAME\") | .id")
echo "rulesets: $(printf '%s' "$rulesets_json" | jq -r 'map(.name) | join(", ")')"
echo "rules effective on main: $(gh api "repos/$REPO/rules/branches/main" --jq 'map(.type) | join(", ")' 2>/dev/null || echo none)"
if env_now=$(gh api "repos/$REPO/environments/$ENVIRONMENT" --jq '"present, reviewer rules: " + (.protection_rules|map(select(.type=="required_reviewers"))|length|tostring)' 2>/dev/null); then
  echo "environment $ENVIRONMENT: $env_now"
else
  echo "environment $ENVIRONMENT: absent"
fi

if [ "$APPLY" != 1 ]; then
  echo "== dry run: would send this ruleset ($( [ -n "$existing_id" ] && echo "update $existing_id" || echo create ))"
  echo "$ruleset" | jq .
  echo "== dry run: would upsert environment $ENVIRONMENT"
  echo "$env_body" | jq .
  echo "run again with --apply to send (owner only)."
  exit 0
fi

echo "== applying ruleset"
if [ -n "$existing_id" ]; then
  echo "$ruleset" | gh api -X PUT "repos/$REPO/rulesets/$existing_id" --input - --jq '"updated ruleset " + (.id|tostring)'
else
  echo "$ruleset" | gh api -X POST "repos/$REPO/rulesets" --input - --jq '"created ruleset " + (.id|tostring)'
fi

echo "== applying environment"
echo "$env_body" | gh api -X PUT "repos/$REPO/environments/$ENVIRONMENT" --input - --jq '"environment " + .name'
if ! gh api "repos/$REPO/environments/$ENVIRONMENT/deployment-branch-policies" --jq '.branch_policies[].name' | grep -qx main; then
  gh api -X POST "repos/$REPO/environments/$ENVIRONMENT/deployment-branch-policies" \
    --input - --jq '"branch policy " + .name' <<< '{"name":"main","type":"branch"}'
fi

echo "== readback"
gh api "repos/$REPO/rules/branches/main" --jq '.[] | .type + (if .parameters.required_status_checks then ": " + (.parameters.required_status_checks|map(.context)|join(" | ")) else "" end)'
gh api "repos/$REPO/rulesets" --jq ".[] | select(.name==\"$RULESET_NAME\") | \"bypass actors: \" + (.bypass_actors|length|tostring) + \", enforcement: \" + .enforcement"
gh api "repos/$REPO/environments/$ENVIRONMENT" --jq '"environment " + .name + ": " + (.protection_rules|map(.type)|join(", ")) + "; branch policy custom=" + (.deployment_branch_policy.custom_branch_policies|tostring)'
gh api "repos/$REPO/environments/$ENVIRONMENT/deployment-branch-policies" --jq '"deployment branches: " + (.branch_policies|map(.name)|join(", "))'
echo "== assertions"
fail=0
bypass=$(gh api "repos/$REPO/rulesets" --jq ".[] | select(.name==\"$RULESET_NAME\") | .bypass_actors | length")
enf=$(gh api "repos/$REPO/rulesets" --jq ".[] | select(.name==\"$RULESET_NAME\") | .enforcement")
got_checks=$(gh api "repos/$REPO/rules/branches/main" --jq '[.[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context] | sort | join("|")')
want_checks=$(printf '%s' "$checks" | jq -r 'map(.context) | sort | join("|")')
policies=$(gh api "repos/$REPO/environments/$ENVIRONMENT/deployment-branch-policies" --jq '[.branch_policies[] | select(.type=="branch") | .name] | sort | join("|")')
types=$(gh api "repos/$REPO/rules/branches/main" --jq '[.[] | .type] | sort | join("|")')
[ "$bypass" = "0" ] || { echo "ASSERT FAILED: bypass actors = $bypass (want 0)"; fail=1; }
[ "$enf" = "active" ] || { echo "ASSERT FAILED: enforcement = $enf (want active)"; fail=1; }
[ "$got_checks" = "$want_checks" ] || { echo "ASSERT FAILED: required checks = $got_checks (want $want_checks)"; fail=1; }
[ "$policies" = "main" ] || { echo "ASSERT FAILED: deployment branch policies = $policies (want exactly main)"; fail=1; }
for t in deletion non_fast_forward required_linear_history pull_request required_status_checks; do
  case "|$types|" in *"|$t|"*) ;; *) echo "ASSERT FAILED: rule $t not effective on main"; fail=1 ;; esac
done
[ "$fail" = 0 ] && echo "all assertions passed" || { echo "readback does not match the intended controls; fix before any deploy credential" >&2; exit 1; }
echo "note: the required checks are pinned to the GitHub Actions app, not to a workflow file; a pull request that edits ci.yml can emit a job of the same name, a residual accepted with one maintainer and merges through the merge guard (record it in 009 section 5.5). Linear history means merges use squash."
echo "next: open a probe pull request without checks and confirm it cannot merge; record the readback in 009 section 5.5; issue the scoped agent token (contents, pull requests, checks; no administration, environments, secrets or variables)."
