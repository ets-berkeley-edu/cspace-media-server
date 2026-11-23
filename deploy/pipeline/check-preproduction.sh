#!/usr/bin/env bash
# The deploy workflow's first job (.github/workflows/deploy.yml): an environment whose committed settings file names
# PREPRODUCTION (production: docs/design.md, Infrastructure and operations › Deploys) is deployed only at a commit
# whose latest deployment to that environment succeeded. GitHub records one when the pre-production run's apply job,
# in the GitHub environment of that name, ends. Runs before any job names a GitHub environment or signs in to AWS.
#
#   deploy/pipeline/check-preproduction.sh   with ENVIRONMENT, COMMIT, REPOSITORY and GH_TOKEN (deployments: read)
set -euo pipefail

: "${ENVIRONMENT:?}" "${COMMIT:?}" "${REPOSITORY:?}"
case "$ENVIRONMENT" in ""|*[!a-z0-9-]*) echo "ENVIRONMENT isn't an environment's name." >&2; exit 2 ;; esac
case "$COMMIT" in *[!0-9a-f]*) echo "COMMIT isn't a commit." >&2; exit 2 ;; esac
summary="${GITHUB_STEP_SUMMARY:-/dev/null}"
conf="deploy/environments/$ENVIRONMENT.conf"
[ -f "$conf" ] || { echo "No settings file $conf." >&2; exit 1; }

# The committed file only (aws.sh refuses PREPRODUCTION in a .local.conf), read as text, never run.
pre="$(sed -n 's/^PREPRODUCTION=\([a-z0-9-]*\).*$/\1/p' "$conf" | tail -n 1)"
if [ -z "$pre" ]; then
  echo "$ENVIRONMENT has no pre-production environment: any commit on main may be deployed."
  exit 0
fi

# The latest status of each deployment of the commit to $pre (none yet: an empty line). One that succeeded is enough:
# a later run at the same commit that failed, or a newer commit deployed there since, doesn't undo it.
urls="$(gh api "repos/$REPOSITORY/deployments?sha=$COMMIT&environment=$pre&per_page=100" --jq '.[].statuses_url')"
states=""
while read -r url; do
  [ -n "$url" ] || continue
  states+="$(gh api "$url?per_page=1" --jq '.[0].state // ""')"$'\n'
done <<<"$urls"
if [[ $'\n'"$states" == *$'\n'success$'\n'* ]]; then
  echo "Commit $COMMIT was deployed to $pre: $ENVIRONMENT may take it."
  echo "Commit \`${COMMIT:0:12}\` was deployed to \`$pre\` first." >>"$summary"
  exit 0
fi
echo "Commit $COMMIT hasn't been deployed to $pre successfully ($(printf '%s' "$states" | grep -c . || true) attempt(s) there)." >&2
echo "Deploy it to $pre first, then run this deploy again." >&2
echo "Refused: commit \`${COMMIT:0:12}\` hasn't been deployed to \`$pre\` first." >>"$summary"
exit 1
