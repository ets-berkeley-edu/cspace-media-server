#!/usr/bin/env bash
# The deploy pipeline's builds, before ./serena aws runs (buildspec-plan.yml, buildspec-apply.yml): Terraform at the
# buildspec's version, checked against its SHA256 (DP17), and the commit being deployed checked to be on main (DP4).
# The second is a second check only: what stops another commit is that only a job from main, in the environment's
# protected GitHub environments, can start a build (DP3, DP9).
set -euo pipefail
cd "$(dirname "$0")/../.."

: "${TERRAFORM_VERSION:?}" "${TERRAFORM_SHA256:?}" "${CODEBUILD_RESOLVED_SOURCE_VERSION:?}" "${CODEBUILD_SOURCE_REPO_URL:?}"

zip="$(mktemp -d)/terraform.zip"
curl -fsSL -o "$zip" "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_arm64.zip"
echo "${TERRAFORM_SHA256}  $zip" | sha256sum --check --strict -
unzip -o -q "$zip" -d /usr/local/bin terraform
terraform version

commit="$CODEBUILD_RESOLVED_SOURCE_VERSION"
[ "$(git rev-parse HEAD)" = "$commit" ] || { echo "The checkout isn't the commit asked for ($commit)." >&2; exit 1; }
git fetch --quiet --no-tags "$CODEBUILD_SOURCE_REPO_URL" main
git merge-base --is-ancestor "$commit" FETCH_HEAD || {
  echo "Commit $commit isn't on main: the pipeline deploys only main (DP4, DP8)." >&2; exit 1; }
echo "Deploying commit $commit, which is on main."
