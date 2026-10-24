#!/usr/bin/env bash
# The measured restore drill (026 sections 6 and 11; 6B.13): synthetic data only, on this host, removed afterwards.
#
#   scripts/restore_drill.sh
#
# A source stack takes synthetic applicants through its public form and is backed up as the backup role. The set is
# archived on the host (0700) and restored from that archive into a second, separate stack, as the owner with the
# bootstrap administrator's credential, after every restore negative control has been refused. The post-restore step
# runs (review, then lift), the stack starts, and the drill shows the restored data, the closed links and a working
# form. RPO and RTO are measured and printed for the owner's targets (P6-D-7). Cases: TEST-P6-21 (in part), 22, 23, 29.
# 9kg.33: an effect after the backup (a staff account created) is journaled outside the backup; the journal is carried
# to the recovery host like the archive; the review replays it and opens its staff item, the lift is refused until the
# owner resolves it, and the restored stack has no such account.
# 9kg.34: a fourth stack stores one synthetic document sealed under its own key (keys in their own volumes, outside the
# backup), backs it up, destroys the key after the backup (the erasure's step), restores the set into a fresh database
# and shows the restored document cannot be opened; the set holds no key material and no plaintext. The off-site,
# object-locked leg of the real chain cannot run from this repository: reported NOT RUN.
set -uo pipefail
cd "$(dirname "$0")/.."
work="$(mktemp -d)"
fail=0
export CATALYST_PUBLIC_HOST=catalyst.staging.test CATALYST_STAFF_HOST=staff.staging.test \
  CATALYST_PUBLIC_PUBLISH=127.0.0.1 CATALYST_STAFF_PUBLISH=127.0.0.2 CATALYST_STAGING_SECRETS="$work/secrets" \
  CATALYST_IMAGE="catalyst-restore-drill:$$"
source_project="catalyst-restore-source-$$" target_project="catalyst-restore-target-$$"
archive="$work/archive"
a() { CATALYST_PUBLIC_PORT=18443 CATALYST_STAFF_PORT=18444 docker compose --project-name "$source_project" -f deploy/staging/compose.yaml "$@"; }
b() { CATALYST_PUBLIC_PORT=19443 CATALYST_STAFF_PORT=19444 docker compose --project-name "$target_project" -f deploy/staging/compose.yaml "$@"; }
cleanup() {
  a --profile provision --profile ops down -v --remove-orphans >/dev/null 2>&1
  b --profile provision --profile ops down -v --remove-orphans >/dev/null 2>&1
  docker compose --project-name "catalyst-restore-empty-$$" -f deploy/staging/compose.yaml --profile provision --profile ops down -v --remove-orphans >/dev/null 2>&1
  docker compose --project-name "catalyst-restore-custody-$$" -f deploy/staging/compose.yaml --profile provision --profile ops down -v --remove-orphans >/dev/null 2>&1
  docker volume rm "catalyst-restore-custody-$$-keys" "catalyst-restore-custody-$$-keys-mirror" >/dev/null 2>&1
  docker run --rm --user 0 -v "$work:/w" "$CATALYST_IMAGE" sh -c 'rm -rf /w/archive /w/effects' >/dev/null 2>&1  # owned by 10001
  docker image rm "$CATALYST_IMAGE" >/dev/null 2>&1
  rm -rf "$work"
}
trap cleanup EXIT
check() { local name="$1"; shift; if "$@"; then echo "PASS $name"; else echo "FAIL $name"; fail=1; fi; }
check_not() { local name="$1"; shift; if "$@"; then echo "FAIL $name"; fail=1; else echo "PASS $name"; fi; }  # in this shell
as_root() { docker run --rm --user 0 -v "$archive:/archive" "$@"; }  # the archive is owned by the containers' 10001
count_applications() {  # count_applications <a|b>: the number of applications, as the owner (a count, never a row)
  "$1" run --rm --no-deps -T migrate python manage.py shell -c \
    "from applications.models import Application; print(Application.objects.count())" 2>/dev/null | tail -1
}
invite() {  # invite <a|b> <email>: 9kg.43, intake is invitation-only, so the owner invites the synthetic address first
  "$1" run --rm --no-deps -T migrate python manage.py catalyst_invite "$2" --issued-by "restore drill" \
    --note "synthetic drill applicant" 2>/dev/null | grep -q '"issued": true'
}
apply() {  # apply <port> <email>: one synthetic applicant through the public form; prints the response code
  local port="$1" jar="$work/jar" page csrf url="https://catalyst.staging.test:$1"
  rm -f "$jar"
  page="$(curl -sk -c "$jar" --resolve "catalyst.staging.test:$port:127.0.0.1" "$url/request-access/")"
  csrf="$(grep -oE 'name="csrfmiddlewaretoken" value="[^"]+"' <<<"$page" | head -1 | sed 's/.*value="//; s/"$//')"
  curl -sk -b "$jar" -o /dev/null -w '%{http_code}' --resolve "catalyst.staging.test:$port:127.0.0.1" \
    -H "Referer: $url/request-access/" -H "Origin: $url" --data-urlencode "csrfmiddlewaretoken=$csrf" \
    --data-urlencode "name=Synthetic Applicant" --data-urlencode "email=$2" \
    --data-urlencode "reason=Synthetic reason for access." "$url/request-access/"
}
offered() {  # offered <port> <path>: whether the confirmation page offers its form (the link still opens)
  curl -sk --resolve "catalyst.staging.test:$1:127.0.0.1" "https://catalyst.staging.test:$1$2" | grep -q 'name="version"'
}
closed() {  # closed <port> <path>: the application's own "not valid" answer for the link, not any failure or outage
  curl -sk --resolve "catalyst.staging.test:$1:127.0.0.1" "https://catalyst.staging.test:$1$2" | grep -q 'This link is not valid'
}

install -d -m 0700 "$work/secrets" "$archive"
for name in secret_key verification_key admin_password owner_password app_password retention_password \
            backup_password fetcher_password; do
  printf 'synthetic-%s-%s' "$name" "$(head -c 96 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 64)" > "$work/secrets/$name"
done
: > "$work/secrets/verification_fallback_keys"
# 9kg.34: the custody wrapping key, 64 hex characters (32 random bytes); only the custody leg's one-shot mounts it.
head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$work/secrets/custody_wrapping_key"
# 9kg.34: the erasure key, for the mac of each journaled key destruction (mounted only into the custody leg's one-shot).
printf 'synthetic-erasure-%s' "$(head -c 96 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 48)" > "$work/secrets/erasure_key"
chmod 0444 "$work/secrets"/*
docker build -q --target staging --build-arg "CATALYST_COMMIT=$(git rev-parse HEAD)" -t "$CATALYST_IMAGE" . >/dev/null || exit 1
as_root "$CATALYST_IMAGE" sh -c 'chown 10001:10001 /archive && chmod 0700 /archive'

# --- the source: synthetic applicants, a confirmation link in hand, the backup ----------------------------------
a up -d --wait db >/dev/null 2>&1
a --profile provision run --rm provision-roles >/dev/null 2>&1
a up -d --wait web worker fetcher egress proxy >/dev/null 2>&1 || { echo "FAIL the source stack did not come up"; exit 1; }
for n in 1 2 3; do
  check "the owner invites synthetic applicant $n (invitation-only intake)" invite a "before-$n@example.test"
  check "the source takes synthetic applicant $n through its form" test "$(apply 18443 "before-$n@example.test")" = 302
done
for _ in $(seq 30); do
  links="$(a exec -T worker sh -c 'cat /var/lib/catalyst/mail/* 2>/dev/null' | grep -oE '/confirm/[^/[:space:]]+/' | sort -u)"
  [ "$(wc -l <<<"$links")" -ge 3 ] && break; sleep 1
done
link="$(head -1 <<<"$links")"
check "a confirmation link from before the backup opens on the source" offered 18443 "$link"
backup_started=$(date +%s)
receipt="$(a --profile ops run --rm backup 2>/dev/null | tail -1)"
backup_finished=$(date +%s)
set_name="$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["name"])' "$receipt" 2>/dev/null)"
manifest="$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["manifest_sha256"])' "$receipt" 2>/dev/null)"
check "TEST-P6-21 the backup wrote a set with a manifest digest" test -n "$set_name" -a -n "$manifest"
check_not "TEST-P6-35 the backup receipt holds no personal data" grep -q '@' <<<"$receipt"
check "the source has three applications at the backup" test "$(count_applications a)" = 3
invite a after-backup@example.test
check "an applicant after the backup is accepted by the source" test "$(apply 18443 after-backup@example.test)" = 302
# 9kg.33: an effect after the backup point, journaled outside the backup (the owner-run command, as in production).
check "9kg.33 a staff account created after the backup is an effect the backup cannot know" test "$(a run --rm --no-deps -T \
  -e CATALYST_DRILL_STAFF_PASSWORD="synthetic-drill-$(head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)" \
  migrate python manage.py add_readonly_staff after-backup-staff --password-env CATALYST_DRILL_STAFF_PASSWORD \
  --approval-ref "restore drill (synthetic)" 2>/dev/null | tail -1)" = "created read-only staff account 'after-backup-staff'"

# The archive on the host: a copy of the set, private, read by the restore through a read-only mount.
volume="${source_project}_catalyst-backups"
docker run --rm --user 0 -v "$volume:/sets:ro" -v "$archive:/archive" "$CATALYST_IMAGE" \
  sh -c "cp -a /sets/$set_name /archive/ && chown -R 10001:10001 /archive"
check "TEST-P6-35 the archived set is 0700 and its files 0600" bash -c "[ \"\$(docker run --rm --user 0 -v '$archive:/archive:ro' '$CATALYST_IMAGE' sh -c 'stat -c %a /archive/$set_name; find /archive/$set_name -type f -exec stat -c %a {} + | sort -u')\" = \$'700\\n600' ]"
# The effect journal is carried to the recovery host like the archive: it lives outside the backup's rollback domain.
install -d -m 0700 "$work/effects"
docker run --rm --user 0 -v "${source_project}_catalyst-effects:/effects:ro" -v "$work/effects:/carry" "$CATALYST_IMAGE" \
  sh -c "cp -a /effects/. /carry/"
check "9kg.33 the effect journal was carried off the source host" \
  docker run --rm --user 0 -v "$work/effects:/carry:ro" "$CATALYST_IMAGE" sh -c 'test -s /carry/effects.jsonl'  # owned by 10001
a down -v >/dev/null 2>&1  # the source is gone: only the archive and the carried journal remain

# --- the target: a separate, migrated, empty stack ------------------------------------------------------------
recovery_started=$(date +%s)  # the RTO clock starts with an empty host: the target is part of the recovery
b up -d --wait db >/dev/null 2>&1
b --profile provision run --rm provision-roles >/dev/null 2>&1
b run --rm --no-deps -T migrate python manage.py migrate --noinput >/dev/null 2>&1
docker run --rm --user 0 -v "$work/effects:/carry:ro" -v "${target_project}_catalyst-effects:/effects" "$CATALYST_IMAGE" \
  sh -c "cp -a /carry/. /effects/ && chown -R 10001:10001 /effects && chmod 0700 /effects"
refused_with() { grep -q "restore refused: $1" "$work/restore.out"; }  # this exact refusal, not any failure
restore() {  # restore <set dir under /archive> [catalyst_restore arguments]: the restore's exit status
  b --profile ops run --rm --no-deps -T -v "$archive:/archive:ro" restore python manage.py catalyst_restore \
    --from "/archive/$1" --storage-dir /var/lib/catalyst/custody/restored "${@:2}" >"$work/restore.out" 2>&1
  echo $?
}
# TEST-P6-23: each negative control is refused, and leaves the target empty for the real restore.
as_root "$CATALYST_IMAGE" sh -c "cp -a /archive/$set_name /archive/tampered && f=\$(ls /archive/tampered/*.copy 2>/dev/null | head -1 || find /archive/tampered -type f -name '*.copy' | head -1); printf x >> \"\$f\"; cp -a /archive/$set_name /archive/loose && chmod 0755 /archive/loose; chown -R 10001:10001 /archive"
check "TEST-P6-23 a restore naming the wrong database is refused" test "$(restore "$set_name" --confirm-database not-this-one)" = 1
check "TEST-P6-23 ... for that reason" refused_with "--confirm-database must name the target database"
check "TEST-P6-23 a restore with the wrong manifest digest is refused" test "$(restore "$set_name" --confirm-database catalyst --expect-manifest-sha256 "$(printf '0%.0s' $(seq 64))")" = 1
check "TEST-P6-23 ... for that reason" refused_with "the manifest does not match the digest given on the command line"
check "TEST-P6-23 a tampered set is refused" test "$(restore tampered --confirm-database catalyst)" = 1
check "TEST-P6-23 ... because a copy differs from its manifest" refused_with "table copy does not match the manifest"
check "TEST-P6-23 a set that is not private is refused" test "$(restore loose --confirm-database catalyst)" = 1
check "TEST-P6-23 ... for that reason" refused_with "the set must be a private directory"
check "TEST-P6-23 the refused restores changed nothing" test "$(count_applications b)" = 0

# TEST-P6-22: the real restore, the post-restore step, and the stack back up, timed.
restore_started=$(date +%s)
check "TEST-P6-22 the set restores from the archive with its digest" test "$(restore "$set_name" --confirm-database catalyst --expect-manifest-sha256 "$manifest")" = 0
[ "$fail" = 0 ] || sed 's/^/  restore said: /' "$work/restore.out" | tail -3  # a reason code, never data
check "TEST-P6-23 a second restore into the now non-empty target is refused" test "$(restore "$set_name" --confirm-database catalyst)" = 1
check "TEST-P6-23 ... because the target is not empty" refused_with "the target database is not empty"
# The control for TEST-P6-29: restored as it was, the link would still open (the web process reads the restored rows).
b up -d --no-deps --wait web proxy >/dev/null 2>&1
for _ in $(seq 30); do offered 19443 "$link" && break; sleep 1; done
check "TEST-P6-29 control: before the post-restore step, the restored link still opens" offered 19443 "$link"
b stop web proxy >/dev/null 2>&1  # the post-restore step runs with nothing serving (026 section 6)
b --profile ops run --rm --no-deps -T restore python manage.py catalyst_post_restore --confirm-database catalyst >"$work/post.out" 2>&1
check "the post-restore review runs" test $? = 0
[ "$fail" = 0 ] || sed 's/^/  post-restore said: /' "$work/post.out" | tail -3
# 9kg.33: the review replayed the journal (the account created after the backup is a grant: the owner's act, so it
# is a staff item, never a replay), every provider read it needed completed, and the lift waits for the item.
report="$(tail -1 "$work/post.out")"
effect_item="$(python3 -c 'import json,sys;r=json.loads(sys.argv[1]);print(next((i.split(":",1)[1] for i in r["effect_items_open"] if i.startswith("restore_effect_staff_account:")), ""))' "$report" 2>/dev/null)"
check "9kg.33 the review read the journal and reconciled every provider it needed (no evidence missing)" \
  test "$(python3 -c 'import json,sys;r=json.loads(sys.argv[1]);print(r["effects"]["journal"], len(r["effects"]["blocked"]))' "$report" 2>/dev/null)" = "ok 0"
check "9kg.33 the account created after the backup is a staff item for the owner, not a replay" test -n "$effect_item"
b --profile ops run --rm --no-deps -T restore python manage.py catalyst_post_restore --confirm-database catalyst --lift \
  --outward-checked --no-closures-after-backup >"$work/lift-refused.out" 2>&1
check "9kg.33 the lift is refused while a restore_effect_ item is open" test $? = 1
check "9kg.33 ... for that reason" grep -q "effects are unresolved" "$work/lift-refused.out"
b --profile ops run --rm --no-deps -T restore python manage.py catalyst_post_restore --confirm-database catalyst \
  --resolve "$effect_item" --note "Drill: the owner re-creates the account after the restore" >"$work/resolve.out" 2>&1
check "9kg.33 the owner resolves the effect with a reason" test $? = 0
b --profile ops run --rm --no-deps -T restore python manage.py catalyst_post_restore --confirm-database catalyst --lift \
  --outward-checked --no-closures-after-backup >"$work/lift.out" 2>&1
check "the post-restore lift runs once the effects are reconciled and resolved (effects reconciled)" test $? = 0
check "9kg.33 the restored stack has no account created after the backup (a grant is never replayed from a file)" \
  test "$(b run --rm --no-deps -T migrate python manage.py shell -c \
    "from accounts.models import User; print(User.objects.filter(username='after-backup-staff').count())" 2>/dev/null | tail -1)" = 0
b up -d --wait web worker fetcher egress proxy >/dev/null 2>&1
ready=""
for _ in $(seq 60); do
  [ "$(curl -sk -o /dev/null -w '%{http_code}' --resolve catalyst.staging.test:19443:127.0.0.1 https://catalyst.staging.test:19443/request-access/)" = 200 ] && ready=1 && break
  sleep 1
done
restore_finished=$(date +%s)
check "TEST-P6-22 the restored stack serves the form" test -n "$ready"
check "TEST-P6-22 the restored data is the backup's (three applications, not the later one)" test "$(count_applications b)" = 3
check "TEST-P6-29 the confirmation link from before the backup is closed on the restored stack" closed 19443 "$link"
invite b after-restore@example.test
check "the restored stack takes a new applicant" test "$(apply 19443 after-restore@example.test)" = 302

# The restored stack's checks are done: take it down first, so the third stack's networks fit the host's address pools
# (a shared dev box can run out of predefined pools with three stacks up at once).
b --profile provision --profile ops down -v --remove-orphans >/dev/null 2>&1
# 9kg.33, a second leg: a third stack restores the same set with an empty effect journal; the restore refuses before
# the load, because the receipt's anchor is not in the journal (journal_mismatch), and the stack stays empty.
empty_project="catalyst-restore-empty-$$"
c() { CATALYST_PUBLIC_PORT=20443 CATALYST_STAFF_PORT=20444 docker compose --project-name "$empty_project" -f deploy/staging/compose.yaml "$@"; }
c up -d --wait db >/dev/null 2>&1
c --profile provision run --rm provision-roles >/dev/null 2>&1
c run --rm --no-deps -T migrate python manage.py migrate --noinput >/dev/null 2>&1
c --profile ops run --rm --no-deps -T -v "$archive:/archive:ro" restore python manage.py catalyst_restore \
  --from "/archive/$set_name" --storage-dir /var/lib/catalyst/custody/restored --confirm-database catalyst \
  --expect-manifest-sha256 "$manifest" >"$work/restore-empty.out" 2>&1
status=$?
check "9kg.33 the third stack came up (not an infrastructure failure)" bash -c "! grep -q 'address pools\|No space left' '$work/restore-empty.out'"
check "9kg.33 a restore with an empty effect journal is refused before the load" test "$status" = 1
check "9kg.33 ... because the receipt's anchor is not in the journal" grep -q "journal_mismatch" "$work/restore-empty.out"
grep -q "journal_mismatch" "$work/restore-empty.out" || grep -E "refused|failed" "$work/restore-empty.out" | sed 's/^/  empty-journal restore said: /' | tail -2
check "9kg.33 ... and the empty target stayed empty" test "$(count_applications c)" = 0
c --profile provision --profile ops down -v --remove-orphans >/dev/null 2>&1

# --- 9kg.34: crypto-shredding against an older backup, on a fourth stack ------------------------------------------
# The custody files are sealed under per-document keys kept in two volumes of their own (the key directory and its
# live mirror), which no backup reads. The drill command points custody at the volumes for its own run (staging stores
# no custody files otherwise) and the key is destroyed with the erasure's own step (the erasure command itself refuses
# while the POL-10 registry is undecided).
custody_project="catalyst-restore-custody-$$"
keys_vol="$custody_project-keys" mirror_vol="$custody_project-keys-mirror"
e() { CATALYST_PUBLIC_PORT=21443 CATALYST_STAFF_PORT=21444 docker compose --project-name "$custody_project" -f deploy/staging/compose.yaml "$@"; }
cdrill() {  # cdrill <custody dir> <action> [arguments]: the custody drill command in the owner's one-shot container
  local dir="$1"; shift
  # The project's own custody volume by its full name: a bare name given to `run -v` would make a global volume.
  e run --rm --no-deps -T -v "${custody_project}_catalyst-custody:/var/lib/catalyst/custody" -v "$keys_vol:/var/lib/catalyst/custody-keys" \
    -v "$mirror_vol:/var/lib/catalyst/custody-keys-mirror" -v "$archive:/archive:ro" \
    -v "$work/secrets/custody_wrapping_key:/run/secrets/custody_wrapping_key:ro" \
    -v "$work/secrets/erasure_key:/run/secrets/erasure_key:ro" migrate python manage.py \
    catalyst_custody_drill "$1" --storage-dir "$dir" --key-dir /var/lib/catalyst/custody-keys \
    --mirror-dir /var/lib/catalyst/custody-keys-mirror "${@:2}" 2>"$work/cdrill.err" | tail -1
}
field() { python3 -c 'import json,sys;print(json.loads(sys.argv[1]).get(sys.argv[2], ""))' "$1" "$2" 2>/dev/null; }
fresh_custody_db() {
  e up -d --wait db >/dev/null 2>&1
  e --profile provision run --rm provision-roles >/dev/null 2>&1
  e run --rm --no-deps -T migrate python manage.py migrate --noinput >/dev/null 2>&1
}
fresh_custody_db
e --profile ops create backup >/dev/null 2>&1 && e --profile ops rm -f backup >/dev/null 2>&1  # compose makes its volumes
docker run --rm --user 0 -v "$keys_vol:/k" -v "$mirror_vol:/m" "$CATALYST_IMAGE" sh -c 'chown 10001:10001 /k /m && chmod 0700 /k /m'
cdrill /var/lib/catalyst/custody provision >/dev/null  # the key volumes' explicit provisioning step (markers)
seeded="$(cdrill /var/lib/catalyst/custody seed)"
document="$(field "$seeded" document)" marker="$(field "$seeded" marker)"
check "9kg.34 a synthetic document is stored sealed under its own key (the real write path)" test -n "$document" -a -n "$marker"
[ -n "$document" ] || sed 's/^/  seed said: /' "$work/cdrill.err" | tail -3
check "9kg.34 control: before destruction it opens and its plaintext hash matches the recorded one" \
  test "$(field "$(cdrill /var/lib/catalyst/custody read --document "$document")" sha256_matches)" = True
custody_receipt="$(e --profile ops run --rm backup 2>/dev/null | tail -1)"
custody_set="$(field "$custody_receipt" name)"
check "9kg.34 the backup wrote a set holding the sealed custody file" test -n "$custody_set"
[ -n "$custody_set" ] || { echo "  backup said: $custody_receipt"; custody_set=missing; }
docker run --rm --user 0 -v "${custody_project}_catalyst-backups:/sets:ro" -v "$archive:/archive" "$CATALYST_IMAGE" \
  sh -c "cp -a /sets/$custody_set /archive/custody-$custody_set && chown -R 10001:10001 /archive"
absent="$(cdrill /var/lib/catalyst/custody absent --set "/archive/custody-$custody_set" --marker "$marker")"
check "9kg.34 the set holds no key material (no key file, no wrapped key, no data key, no wrapping key)" \
  test "$(field "$absent" key_material_found):$(field "$absent" key_files_in_set):$([ "$(field "$absent" files)" -ge 3 ] 2>/dev/null && echo read)" = "0:0:read"
check "9kg.34 ... and no plaintext (the document's marker is in no file of the set)" test "$(field "$absent" plaintext_marker_found)" = 0
check "9kg.34 the key is destroyed after the backup (journaled, then unlinked from the mirror and the key directory)" \
  test "$(field "$(cdrill /var/lib/catalyst/custody destroy --document "$document")" destroyed)" = 2
check "9kg.34 the live copy can no longer be opened" \
  test "$(field "$(cdrill /var/lib/catalyst/custody read --document "$document")" code)" = custody_key_destroyed
e rm -sf db >/dev/null 2>&1 && docker volume rm "${custody_project}_catalyst-db" >/dev/null 2>&1  # the database is lost
fresh_custody_db
e --profile ops run --rm --no-deps -T -v "$archive:/archive:ro" restore python manage.py catalyst_restore \
  --from "/archive/custody-$custody_set" --storage-dir /var/lib/catalyst/custody/restored --confirm-database catalyst \
  >"$work/restore-custody.out" 2>&1
check "9kg.34 the older set restores into a fresh database (rows and the sealed file come back)" test $? = 0
grep -q '"restored"' "$work/restore-custody.out" || grep -E "refused|failed" "$work/restore-custody.out" | sed 's/^/  custody restore said: /' | tail -2
check "9kg.34 the restored rows name the document and its envelope" test "$(e run --rm --no-deps -T migrate python manage.py shell -c \
  "from agreements.models import CustodyEnvelope, StoredDocument; print(StoredDocument.objects.count(), CustodyEnvelope.objects.count())" 2>/dev/null | tail -1)" = "1 1"
check "9kg.34 the restore of the older backup cannot open the destroyed subject's document" \
  test "$(field "$(cdrill /var/lib/catalyst/custody/restored read --document "$document")" code)" = custody_key_destroyed
check "9kg.34 ... and the restored file holds no plaintext" test "$(field "$(cdrill /var/lib/catalyst/custody absent \
  --set /var/lib/catalyst/custody/restored --marker "$marker")" plaintext_marker_found)" = 0
echo "NOT RUN 9kg.34 the off-site, object-locked copy: it is reached only through the host's backup fabric, not from this repository; the live-chain drill is a go/no-go evidence item"
e --profile provision --profile ops down -v --remove-orphans >/dev/null 2>&1
docker volume rm "$keys_vol" "$mirror_vol" >/dev/null 2>&1

# The drill's own checks between restore_started and restore_finished (the refused second restore, the control probe)
# add a few seconds; the figure is an upper bound for this step at synthetic scale.
echo "MEASURED backup: $((backup_finished - backup_started)) s"
echo "MEASURED recovery from an empty host to serving (target prepared, negative controls, restore, post-restore, start): $((restore_finished - recovery_started)) s"
echo "MEASURED restore, post-restore and start alone: $((restore_finished - restore_started)) s"
echo "BY DESIGN RPO: the backup's point (checked: the applicant accepted after the backup is absent from the restore)"
if [ -n "${CATALYST_DRILL_RECEIPTS:-}" ]; then  # the drill receipt the health check watches (overdue after 35 days)
  install -d -m 0700 "$CATALYST_DRILL_RECEIPTS"
  printf '{"at": "%s", "commit": "%s", "result": "%s", "backup_seconds": %d, "recovery_seconds": %d}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(git rev-parse HEAD)" "$([ "$fail" = 0 ] && echo pass || echo fail)" \
    "$((backup_finished - backup_started))" "$((restore_finished - recovery_started))" \
    > "$CATALYST_DRILL_RECEIPTS/$(date -u +%Y%m%dT%H%M%SZ).json"
fi
exit "$fail"
