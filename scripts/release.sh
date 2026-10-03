#!/bin/bash
# Cut a release the same way every time.
#
#   scripts/release.sh 0.2.1            release exactly this version
#   scripts/release.sh patch|minor|major   bump from the latest version
#   options:  --dry-run   run every check and show what would happen, change nothing
#             --yes       do not ask for confirmation
#             --no-wait   stop after publishing; do not wait for the build or verify the assets
#
# Steps: preflight checks (clean tree, on main, not behind origin, tests, lint) -> bump py/core/version.py -> move the
# CHANGELOG "Unreleased" notes under the new version -> commit -> push -> wait for CI on that commit -> publish the GitHub
# release (its notes come from the CHANGELOG) -> wait for the Release build workflow -> check the attached files and their
# checksums -> if PANEL_HOST and PANEL_TOKEN are set, ask a panel to look for the update.
# Needs: git, gh (logged in), python3, node. Run from anywhere inside the repository.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

DRY=0; YES=0; WAIT=1; ARG=""
for a in "$@"; do
    case $a in
        --dry-run) DRY=1;; --yes) YES=1;; --no-wait) WAIT=0;;
        -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
        -*) echo "Unknown option $a" >&2; exit 2;;
        *) ARG=$a;;
    esac
done
[ -n "$ARG" ] || { echo "Usage: $0 <x.y.z|patch|minor|major> [--dry-run] [--yes] [--no-wait]" >&2; exit 2; }

say() { printf '\n== %s\n' "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }
run() { if [ $DRY = 1 ]; then echo "[dry run] $*"; else "$@"; fi; }

command -v gh >/dev/null || die "gh (GitHub CLI) is required"
gh auth status >/dev/null 2>&1 || die "gh is not logged in (gh auth login)"
REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)

# ---- version -----------------------------------------------------------------------------------------------------------
CURRENT=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' py/core/version.py)
[ -n "$CURRENT" ] || die "cannot read VERSION from py/core/version.py"
LATEST_TAG=$(gh release list --limit 1 --json tagName --jq '.[0].tagName' 2>/dev/null || true)
BASE=${LATEST_TAG#v}; BASE=${BASE:-$CURRENT}
case $ARG in
    patch|minor|major)
        IFS=. read -r MA MI PA <<< "$BASE"
        case $ARG in patch) PA=$((PA + 1));; minor) MI=$((MI + 1)); PA=0;; major) MA=$((MA + 1)); MI=0; PA=0;; esac
        NEW="$MA.$MI.$PA";;
    *) NEW=${ARG#v};;
esac
[[ $NEW =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version must look like 1.2.3 (got '$NEW')"
TAG="v$NEW"
newer() { [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -n1)" = "$1" ] && [ "$1" != "$2" ]; }
if [ -n "$LATEST_TAG" ]; then newer "$NEW" "${LATEST_TAG#v}" || die "$TAG is not newer than the latest release $LATEST_TAG"; fi
gh release view "$TAG" >/dev/null 2>&1 && die "release $TAG already exists"
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null && die "tag $TAG already exists locally"
say "Releasing $TAG (was ${LATEST_TAG:-no release yet}; py/core/version.py says $CURRENT) on $REPO"

# ---- preflight -------------------------------------------------------------------------------------------------------
say "Preflight"
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || die "not on main"
[ -z "$(git status --porcelain)" ] || die "working tree is not clean; commit or stash first"
git fetch -q origin
git merge-base --is-ancestor origin/main HEAD || die "origin/main has commits you do not have (git pull --rebase first)"
AHEAD=$(git rev-list --count origin/main..HEAD)
[ "$AHEAD" = 0 ] || echo "note: $AHEAD local commit(s) not on origin yet; they are pushed with the release"
grep -q '^## Unreleased' CHANGELOG.md || die 'CHANGELOG.md needs a "## Unreleased" section'
NOTES=$(awk '/^## Unreleased/{f=1;next} /^## /{f=0} f' CHANGELOG.md | sed -e '/./,$!d')
[ -n "$NOTES" ] || die "the Unreleased section of CHANGELOG.md is empty: describe what changed first"
echo "Release notes:"; echo "$NOTES" | sed 's/^/    /'
(cd py && python3 -m unittest discover tests 2>&1 | tail -n 3)
(cd py && python3 -m pyflakes . 2>&1 | grep -v "undefined name 'ptr\(8\|16\|32\)'" | tee /tmp/release-flakes.$$ >/dev/null; [ ! -s /tmp/release-flakes.$$ ]) || { cat /tmp/release-flakes.$$; die "pyflakes found problems"; }
rm -f /tmp/release-flakes.$$
for f in py/www/app.js py/www/extras.js; do node --check "$f"; done
for f in *.sh scripts/*.sh; do bash -n "$f"; done
echo "checks passed"

if [ $YES = 0 ] && [ $DRY = 0 ]; then
    read -r -p "Publish $TAG now (commit, push, create the GitHub release)? [y/N] " ans
    [ "$ans" = y ] || [ "$ans" = Y ] || { echo "Cancelled."; exit 1; }
fi

# ---- bump, commit, push ------------------------------------------------------------------------------------------
say "Bump version and changelog"
if [ $DRY = 0 ]; then
    NEW="$NEW" python3 - <<'EOF'
import datetime, os, re
new = os.environ["NEW"]
p = "py/core/version.py"
s = open(p).read()
s = re.sub(r'^VERSION = ".*"', 'VERSION = "%s"' % new, s, count=1, flags=re.M)
open(p, "w").write(s)
p = "CHANGELOG.md"
s = open(p).read()
s = s.replace("## Unreleased", "## Unreleased\n\n## %s (%s)" % (new, datetime.date.today().isoformat()), 1)
open(p, "w").write(s)
EOF
    git add py/core/version.py CHANGELOG.md
    git commit -q -m "Release $TAG"
else
    echo "[dry run] set VERSION = \"$NEW\", date the changelog section, commit \"Release $TAG\""
fi
say "Push"
run git push origin main

# ---- CI on the release commit -----------------------------------------------------------------------------------
if [ $DRY = 0 ] && [ $WAIT = 1 ]; then
    say "Waiting for CI on $(git rev-parse --short HEAD)"
    SHA=$(git rev-parse HEAD)
    RID=""
    for _ in $(seq 1 30); do
        RID=$(gh run list --workflow CI --commit "$SHA" --limit 1 --json databaseId --jq '.[0].databaseId' 2>/dev/null || true)
        [ -n "$RID" ] && break
        sleep 4
    done
    [ -n "$RID" ] || die "CI did not start for $SHA"
    gh run watch "$RID" --exit-status >/dev/null || die "CI failed on the release commit: https://github.com/$REPO/actions/runs/$RID"
    echo "CI passed"
fi

# ---- publish -----------------------------------------------------------------------------------------------------------
say "Create the GitHub release $TAG"
BODY=$(printf '%s\n\nFiles: `sigen-pydashboard-factory.bin` flashes a blank board at offset 0 (erases settings and history); `sigen-pydashboard-ota.bin` is the firmware-only update; `sigen-pydashboard-app.tar` is the Python app only (panels can install it from Info > Check Updates). `SHA256SUMS` has the checksums.\n' "$NOTES")
run gh release create "$TAG" --target main --title "$TAG" --notes "$BODY"
[ $DRY = 1 ] && { say "Dry run finished: nothing was changed"; exit 0; }
[ $WAIT = 1 ] || { say "Published. The Release build workflow now attaches the files (about 25 minutes)."; exit 0; }

# ---- build and verify ------------------------------------------------------------------------------------------------
say "Waiting for the Release build workflow (about 25 minutes)"
RID=""
for _ in $(seq 1 30); do
    RID=$(gh run list --workflow "Release build" --event release --limit 1 --json databaseId,headSha --jq ".[] | select(.headSha==\"$(git rev-parse HEAD)\") | .databaseId" 2>/dev/null || true)
    [ -n "$RID" ] && break
    sleep 4
done
[ -n "$RID" ] || die "the Release build did not start (check the Actions tab)"
gh run watch "$RID" --exit-status >/dev/null || die "Release build failed: https://github.com/$REPO/actions/runs/$RID"

say "Verify the release files"
WANT="sigen-pydashboard-factory.bin sigen-pydashboard-ota.bin sigen-pydashboard-app.tar SHA256SUMS"
ASSETS=$(gh release view "$TAG" --json assets --jq '.assets[] | "\(.name) \(.size) \(.digest)"')
echo "$ASSETS"
for f in $WANT; do echo "$ASSETS" | grep -q "^$f " || die "missing release file: $f"; done
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
gh release download "$TAG" -p SHA256SUMS -D "$TMP" >/dev/null
while read -r sum name; do
    got=$(echo "$ASSETS" | awk -v n="$name" '$1==n {print $3}')
    [ "$got" = "sha256:$sum" ] || die "checksum mismatch for $name (SHA256SUMS says $sum, GitHub says $got)"
done < "$TMP/SHA256SUMS"
echo "all files present and checksums match"

if [ -n "${PANEL_HOST:-}" ] && [ -n "${PANEL_TOKEN:-}" ]; then
    say "Asking the panel at $PANEL_HOST to check for updates"
    curl -s -m 60 -X POST -H "X-OTA-Token: $PANEL_TOKEN" "http://$PANEL_HOST/api/update/check" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); s=d['state']; print('panel runs %s; latest %s; update available: %s; error: %s' % (d['current'], s['latest'], s['available'], s['error']))"
fi
say "Done: https://github.com/$REPO/releases/tag/$TAG"
