#!/usr/bin/env bash
# Starts one of the deploy pipeline's builds in AWS CodeBuild and waits for it to end: run by the deploy workflow's
# jobs (.github/workflows/deploy.yml), signed in as the job's OIDC role, which may only start that build and read its
# status (DP3). It never reads the build's log, which stays in the account (D270, DP6): the job's summary gets only the
# build's exported variables (the plan's counts) and a link to the build in the AWS console, which has no account
# number in it. Not aws-actions/aws-codebuild-run-build, which copies the build's log into Actions.
#
#   deploy/pipeline/run-build.sh plan|apply   with ENVIRONMENT, COMMIT, AWS_REGION and, for apply, PLAN_ID
set -euo pipefail

mode="${1:-}"
case "$mode" in plan|apply) ;; *) echo "Usage: run-build.sh plan|apply" >&2; exit 2 ;; esac
: "${ENVIRONMENT:?}" "${COMMIT:?}" "${AWS_REGION:?}" "${GITHUB_STEP_SUMMARY:?}" "${GITHUB_OUTPUT:?}"
project="pipeline-$ENVIRONMENT-$mode"

overrides=()
if [ "$mode" = apply ]; then
  case "${PLAN_ID:-}" in ""|*[!0-9a-f-]*) echo "PLAN_ID isn't a plan build's ID." >&2; exit 1 ;; esac
  overrides=(--environment-variables-override "name=PLAN_ID,value=$PLAN_ID,type=PLAINTEXT")
fi

id="$(aws codebuild start-build --project-name "$project" --source-version "$COMMIT" ${overrides[@]+"${overrides[@]}"} \
  --query build.id --output text)"
link="$(ID="$id" PROJECT="$project" python3 -c '
import os
from urllib.parse import quote
region, project, build = os.environ["AWS_REGION"], os.environ["PROJECT"], quote(os.environ["ID"], safe="")
print("https://%s.console.aws.amazon.com/codesuite/codebuild/projects/%s/build/%s/log?region=%s"
      % (region, project, build, region))')"
echo "Started the $mode build $id at commit $COMMIT; waiting for it to end."

status=IN_PROGRESS
while [ "$status" = IN_PROGRESS ]; do
  sleep 20
  status="$(aws codebuild batch-get-builds --ids "$id" --query 'builds[0].buildStatus' --output text)" || status=IN_PROGRESS
done
echo "The $mode build ended: $status."

aws codebuild batch-get-builds --ids "$id" --query 'builds[0].exportedEnvironmentVariables' --output json |
  MODE="$mode" STATUS="$status" LINK="$link" python3 -c '
import json, os, sys
mode, status, link = os.environ["MODE"], os.environ["STATUS"], os.environ["LINK"]
env, commit = os.environ["ENVIRONMENT"], os.environ["COMMIT"][:12]
found = {v["name"]: v.get("value", "") for v in (json.load(sys.stdin) or [])}
console = "In the AWS console (sign in first): [the %s build](%s)" % (mode, link)
lines = ["### The %s for %s at %s" % (mode, env, commit), ""]
if status != "SUCCEEDED":
    lines += ["**The build ended: %s.** Its log says why." % status.lower(), "", console]
elif mode == "plan":
    plan = found.get("PLAN_STATUS", "")
    lines += ["| | |", "| --- | --- |",
              "| Image repositories and certificate | %s |" % (found.get("REGISTRY_CHANGES") or "no changes"),
              "| Serena | %s |" % (found.get("ROOT_CHANGES") or "not planned this run"), ""]
    if found.get("REMOVED_MUSEUMS"):
        lines += ["> [!CAUTION]", "> This plan removes the museum(s) %s: their buckets (every cached file) and secrets "
                  "are deleted." % found["REMOVED_MUSEUMS"], ""]
    lines += [{
        "changes": "Read the plan in the build log, then approve the deploy if it is what you expect.",
        "registry-only": "Only the image repositories and certificate change this time: approve, then run the deploy "
                         "again for the rest.",
        "no-changes": "No changes: the environment matches this commit. Nothing to approve.",
        "certificate-pending": "The certificate waits for its DNS validation record, which is in the build log. Run "
                               "the deploy again once it is issued.",
    }.get(plan, "Unexpected result: %r." % plan), "", console]
    with open(os.environ["GITHUB_OUTPUT"], "a") as out:
        out.write("plan_id=%s\nstatus=%s\n" % (found.get("PLAN_ID", ""), plan))
else:
    applied = found.get("APPLY_STATUS", "")
    lines += [{"applied": "Applied.",
               "registry-only": "The image repositories and certificate are applied: run the deploy again for the rest.",
               }.get(applied, "Unexpected result: %r." % applied), "", console]
with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
    summary.write("\n".join(lines) + "\n")
'
[ "$status" = SUCCEEDED ]
