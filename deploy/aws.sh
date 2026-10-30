#!/usr/bin/env bash
# ./serena aws — deploy Serena to AWS and look after it (D181-D194). Run through ./serena (./serena aws help).
#
#   ./serena aws deploy        build the images, push them, then show Terraform's plan and apply it; prints the address
#   ./serena aws plan          show what a deploy of the running image would change, without changing anything
#   ./serena aws status        the services' tasks, the image they run, the allowed addresses, the museums and secrets
#   ./serena aws url           the address
#   ./serena aws logs web|worker|devtools   follow a service's logs (the last 30 minutes first)
#   ./serena aws pause         stop every service to save money (the data stays); ./serena aws resume starts them
#   ./serena aws allow-my-ip   add this computer's current address to the allowlist
#   ./serena aws etl MUSEUM [--rows N | --sizes BAND:COUNT,...] [--failed] [--json]   with the simulator: a whole daily refresh by the fake
#                              ETL, run once inside the environment; prints the refresh's result and sample image
#                              addresses (--json: only its summary, as JSON, for ./serena aws test)
#   ./serena aws list MUSEUM [--limit N] [--kind KIND]   what Serena may serve for a museum (its servability table),
#                              each with its address: the first 25, or N (0 for all)
#   ./serena aws test [pytest options]   the AWS tests (serenade/aws/) against this running environment: what
#                              Serena serves through CloudFront, the admin app, a recall that's cancelled, the logs
#                              (D222-D231); only the tests that look against a real CollectionSpace
#   ./serena aws replay --log MONTH.tsv.gz (--busiest hour|minute | --from TIME [--minutes N]) [--speed X]
#                              [--concurrency N] [--follow N] [--dry-run]   with the simulator only: replay a slice of
#                              the cleaned access logs (serenade/load/replay.py, D278-D288), then the web and worker
#                              services' CPU and memory from CloudWatch for the run. --dry-run prints the slice and
#                              the ./serena aws etl --sizes command to run first, sending nothing
#   ./serena aws cspace-secret MUSEUM   set a museum's read-only CollectionSpace account (asks; nothing is shown or saved)
#   ./serena aws etl-token MUSEUM       make a museum's new ETL token (the old one keeps working until the next);
#                              shows it once, for the ETL's token file
#   ./serena aws portal-key MUSEUM      make a new signing key for a museum's signed links (the old one keeps working
#                              until the next); shows it once, for the portal
#   ./serena aws cdn-key       make a new CloudFront signing key for the museums' files (the first deploy makes the
#                              first one); the old one stays trusted until the next. Nothing is shown
#   ./serena aws confirm-alerts   confirm the alert email's subscription (paste the link from AWS's email; don't click
#                              it), so that unsubscribing needs an AWS sign-in
#   ./serena aws destroy       delete everything in AWS for this environment, data included (asks first)
#   ./serena aws init          point Terraform at this environment's state, to run terraform commands yourself
#
# Which environment: --env NAME or SERENA_AWS_ENV (default personal-dev). Its settings are in
# deploy/environments/NAME.conf; NAME.local.conf (not committed) holds the account number and allowed addresses.
# TERRAFORM_ROOT says which Terraform builds it (D302): personal (the default: personal environments and stage 1,
# CloudFront in front of everything) or shared (QA and production, the split). A shared environment also needs
# VPC_ID, APP_SUBNET_IDS, LB_SUBNET_IDS, DOMAIN_NAME, ETL_CIDRS, ADMIN_CIDRS and APACHE_CIDRS, and is deployed here
# only while it uses only the simulator; otherwise by the pipeline, or as a break-glass deploy (D276, TQ8).
# CSPACE_TENANTS lists the museums the environment serves, each with its CollectionSpace server
# ("pahma=https://... cinefiles=https://..."). With SIMULATED_CSPACE=true the environment runs the simulated
# CollectionSpace instead, for the museums in SIMULATED_MUSEUMS, and ./serena aws etl runs the fake ETL; deploy then
# sets every secret itself (the simulator's account, random ETL tokens and portal keys). Never with data that matters.
# Sign in first with: aws sso login --profile <the environment's AWS_PROFILE>. Nothing here handles a password, token
# or key except cspace-secret, etl-token, portal-key and cdn-key, which pass them straight to AWS Secrets Manager.
# ALERT_EMAIL (in NAME.local.conf, never committed) is where alerts and alarms are emailed (D201).
# Terraform (deploy/terraform) creates everything; its state is in an S3 bucket in the same account, which the first
# deploy creates. SERENA_AWS_YES=1 skips Terraform's "yes" prompt. Works with the macOS bash (3.2) and needs python3.
# A deployed museum's CollectionSpace server never changes (check_museums). Deploying one with a real CollectionSpace
# asks the person deploying to confirm the account is UC Berkeley's (acknowledge_real_data). Modeled on the BMU's
# deploy/aws.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_DIR=deploy/environments
TF_DIR=deploy/terraform

die() { echo "$*" >&2; exit 1; }

# ---- arguments ---------------------------------------------------------------------------------------------------
ENV="${SERENA_AWS_ENV:-personal-dev}"
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --env) [ $# -ge 2 ] || die "--env needs a name"; ENV="$2"; shift 2 ;;
    --env=*) ENV="${1#--env=}"; shift ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
set -- ${ARGS[@]+"${ARGS[@]}"}
CMD="${1:-help}"; shift || true

# ---- settings -----------------------------------------------------------------------------------------------------
load_env() {
  CONF="$ENV_DIR/$ENV.conf"
  LOCAL="$ENV_DIR/$ENV.local.conf"
  URL_FILE="$ENV_DIR/$ENV.url"
  [ -f "$CONF" ] || die "No settings for environment '$ENV' ($CONF). Environments: $(ls "$ENV_DIR" | sed -n 's/\.conf$//p' | grep -v '\.local$' | tr '\n' ' ')"
  ACCOUNT_ID="" ALLOWED_CIDRS="" ETL_CIDRS="" ADMIN_CIDRS="" SIMULATED_CSPACE="" SIMULATED_MUSEUMS="" ENV_LABEL=""
  CSPACE_TENANTS="" OPEN_IMAGES="" WAF="" PROTECT_DATA="" WEB_COUNT="" ALERT_EMAIL=""
  TERRAFORM_ROOT="" APACHE_CIDRS="" VPC_ID="" APP_SUBNET_IDS="" LB_SUBNET_IDS="" CREATE_GATEWAY_ENDPOINTS="" DOMAIN_NAME=""
  # shellcheck disable=SC1090
  . "$CONF"
  # shellcheck disable=SC1090
  [ -f "$LOCAL" ] && . "$LOCAL"
  : "${AWS_PROFILE:?set AWS_PROFILE in $CONF}" "${AWS_REGION:?set AWS_REGION in $CONF}" "${SERENA_ENV_NAME:?set SERENA_ENV_NAME in $CONF}"
  NAME="serena-$SERENA_ENV_NAME"   # the cluster's name and the prefix of every resource
  ROOT="${TERRAFORM_ROOT:-personal}"
  case "$ROOT" in
    personal) ;;
    shared)
      local need
      for need in VPC_ID APP_SUBNET_IDS LB_SUBNET_IDS DOMAIN_NAME; do
        [ -n "$(eval echo "\$$need")" ] || die "'$ENV' is on the shared root: set $need in $LOCAL (D303, D293)."
      done ;;
    *) die "TERRAFORM_ROOT must be personal or shared ($CONF)." ;;
  esac
  [ "$ROOT" = shared ] && : "${WAF:=true}"
  local flag
  for flag in SIMULATED_CSPACE OPEN_IMAGES WAF PROTECT_DATA CREATE_GATEWAY_ENDPOINTS; do
    eval ": \"\${$flag:=false}\""
    case "$(eval echo "\$$flag")" in true|false) ;; *) die "$flag must be true or false ($CONF, $LOCAL)." ;; esac
  done
  if [ "$SIMULATED_CSPACE" = true ]; then
    [ "$PROTECT_DATA" != true ] ||
      die "SIMULATED_CSPACE=true can't be used with PROTECT_DATA=true: the simulator's data is synthetic and lost on every restart."
    local museum
    MUSEUMS=""
    for museum in ${SIMULATED_MUSEUMS:-pahma}; do
      check_museum_name "$museum"
      MUSEUMS="${MUSEUMS:+$MUSEUMS }$museum=$(sim_url)/$museum"   # CSPACE_TENANTS is ignored
    done
    [ -n "$ENV_LABEL" ] || ENV_LABEL="AWS · $ENV · simulator"
  else
    read_museums
  fi
  [ -n "$ENV_LABEL" ] || ENV_LABEL="AWS · $ENV"
  case "${WEB_COUNT:=1}" in [1-9]|[1-9][0-9]) ;; *) die "WEB_COUNT must be a number of web tasks, such as 2 ($CONF, $LOCAL)." ;; esac
  command -v python3 >/dev/null || die "python3 isn't installed (it comes with the Xcode command line tools on a Mac)."
  export AWS_PAGER="" AWS_PROFILE AWS_REGION   # Terraform signs in with the same profile
  # Keys in the shell would win over the profile in Terraform (though not in "aws --profile"): never use them here.
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
  export TF_IN_AUTOMATION=1
}

aws_() { aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"; }

# ---- the museums ----------------------------------------------------------------------------------------------------
check_museum_name() {
  [ -f "backend/serena/museums/$1.yaml" ] ||
    die "Serena has no configuration for the museum '$1' (backend/serena/museums/$1.yaml)."
}

# MUSEUMS is "museum=server museum=server", each server without a trailing /.
read_museums() {
  local entry museum url seen=" "
  [ -n "$CSPACE_TENANTS" ] || die "No museums: set CSPACE_TENANTS=\"pahma=https://...\" in $CONF or $LOCAL (or SIMULATED_CSPACE=true)."
  MUSEUMS=""
  for entry in $CSPACE_TENANTS; do
    museum="${entry%%=*}" url="${entry#*=}"
    url="${url%/}"
    [ "$museum" != "$entry" ] || die "CSPACE_TENANTS: '$entry' isn't museum=server."
    echo "$url" | grep -Eq '^https?://[A-Za-z0-9.-]+(:[0-9]+)?$' ||
      die "CSPACE_TENANTS: $museum's server '$url' must be an address alone, such as https://pahma.qa.collectionspace.org."
    check_museum_name "$museum"
    case "$seen" in *" $museum "*) die "CSPACE_TENANTS lists $museum twice." ;; esac
    seen="$seen$museum "
    MUSEUMS="${MUSEUMS:+$MUSEUMS }$museum=$url"
  done
}

museum_names() {  # museum_names [LIST]: the museums of a list (default MUSEUMS), one per line
  local entry
  for entry in ${1-$MUSEUMS}; do echo "${entry%%=*}"; done
}

server_of() {  # server_of MUSEUM [LIST]: the museum's server in a list (default MUSEUMS); fails if it isn't listed
  local entry
  for entry in ${2-$MUSEUMS}; do [ "${entry%%=*}" != "$1" ] || { echo "${entry#*=}"; return 0; }; done
  return 1
}

need_museum() {  # need_museum MUSEUM COMMAND
  [ -n "$1" ] || die "Which museum? ./serena aws $2 <museum>, one of: $(museum_names | tr '\n' ' ')"
  server_of "$1" >/dev/null || die "'$ENV' doesn't serve a museum '$1'. Its museums: $(museum_names | tr '\n' ' ')"
}

tenants_var() {  # MUSEUMS as a Terraform map: {"pahma"="https://..."}
  local entry out=""
  for entry in $MUSEUMS; do out="${out:+$out,}\"${entry%%=*}\"=\"${entry#*=}\""; done
  printf '{%s}' "$out"
}

# The simulator's address in the VPC (Cloud Map): local.simulator_url in deploy/terraform/modules/simulator/devtools.tf.
sim_url() { echo "http://fakecspace.$NAME.internal:8180"; }

signed_museum() {  # signed_museum MUSEUM: whether its configuration allows signed access (it then has a portal key;
  # local.signed_museums in deploy/terraform/modules/core/versions.tf)
  grep -Eq '^signed_access_kinds: *\[ *[A-Za-z0-9]' "backend/serena/museums/$1.yaml"
}

save_local() {  # save_local KEY VALUE: set one setting in the environment's .local.conf
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  { [ -f "$LOCAL" ] && grep -v "^$key=" "$LOCAL" || echo "# ./serena aws settings for '$ENV' on this computer only (not committed)."; } > "$tmp"
  echo "$key=\"$value\"" >> "$tmp"
  mv "$tmp" "$LOCAL"
}

# First use of an environment on this computer: if the account already holds Terraform state for this environment's
# name, it was deployed from somewhere else (another computer or clone, or someone sharing the account).
check_not_someone_elses() {  # check_not_someone_elses ACCOUNT
  local key ok found=""
  for key in personal shared registry; do
    aws_ s3api head-object --bucket "serena-tfstate-$1-$AWS_REGION" --key "serena/$SERENA_ENV_NAME/$key.tfstate" >/dev/null 2>&1 &&
      found="s3://serena-tfstate-$1-$AWS_REGION/serena/$SERENA_ENV_NAME/" && break
  done
  [ -n "$found" ] || return 0
  echo "This account already has a Serena environment named '$SERENA_ENV_NAME' (its Terraform state is in $found),"
  echo "deployed from another computer or clone, or deployed once and destroyed. If it's yours, carry on."
  echo "If it may be someone else's, answer no and set SERENA_ENV_NAME to a name of your own in $LOCAL."
  read -r -p "Is the '$SERENA_ENV_NAME' environment in this account yours? [y/N] " ok
  case "$ok" in y|Y|yes) ;; *) die "Stopped; nothing was changed." ;; esac
}

# Signed in, and to the account this environment was first deployed to.
check_account() {
  local who ok
  who="$(aws_ sts get-caller-identity --query Account --output text 2>/dev/null)" ||
    die "Not signed in to AWS for '$ENV'. Run: aws sso login --profile $AWS_PROFILE"
  if [ -z "$ACCOUNT_ID" ]; then
    echo "Profile $AWS_PROFILE is signed in to AWS account $who."
    read -r -p "Is that the account for the '$ENV' environment? [y/N] " ok
    case "$ok" in y|Y|yes) ;; *) die "Stopped; nothing was changed." ;; esac
    check_not_someone_elses "$who"
    save_local ACCOUNT_ID "$who"; ACCOUNT_ID="$who"
  elif [ "$who" != "$ACCOUNT_ID" ]; then
    die "Profile $AWS_PROFILE is signed in to account $who, but '$ENV' is account $ACCOUNT_ID ($LOCAL). Stopped."
  fi
  STATE_BUCKET="serena-tfstate-$ACCOUNT_ID-$AWS_REGION"
}

my_ip() {
  local ip
  ip="$(curl -fsS --max-time 10 https://checkip.amazonaws.com | tr -d '[:space:]')" || die "Couldn't find this computer's address (https://checkip.amazonaws.com)."
  echo "$ip" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$' || die "Unexpected address from checkip.amazonaws.com: $ip"
  echo "$ip"
}

ensure_allowlist() {
  [ -n "$ALLOWED_CIDRS" ] && return
  local ip; ip="$(my_ip)"
  echo "Serena in AWS is open only to listed addresses. Adding this computer's: $ip/32"
  echo "(More later with ./serena aws allow-my-ip, or edit ALLOWED_CIDRS in $LOCAL and deploy.)"
  save_local ALLOWED_CIDRS "$ip/32"; ALLOWED_CIDRS="$ip/32"
}

# ---- Terraform ----------------------------------------------------------------------------------------------------
need_terraform() {
  command -v terraform >/dev/null || die "Terraform isn't installed. On a Mac: brew tap hashicorp/tap && brew install hashicorp/tap/terraform"
}

# One state bucket per account and region, shared by the account's Serena environments (one key each). Versioned,
# private, encrypted. Terraform can't create the bucket its own state lives in.
ensure_state_bucket() {
  if ! aws_ s3api head-bucket --bucket "$STATE_BUCKET" >/dev/null 2>&1; then
    echo "Creating the Terraform state bucket s3://$STATE_BUCKET (once per account)"
    if [ "$AWS_REGION" = us-east-1 ]; then
      aws_ s3api create-bucket --bucket "$STATE_BUCKET" >/dev/null
    else
      aws_ s3api create-bucket --bucket "$STATE_BUCKET" --create-bucket-configuration "LocationConstraint=$AWS_REGION" >/dev/null
    fi
  fi
  # Set every time (they change nothing when already set), so an interrupted first run is completed by the next.
  aws_ s3api put-public-access-block --bucket "$STATE_BUCKET" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  aws_ s3api put-bucket-versioning --bucket "$STATE_BUCKET" --versioning-configuration Status=Enabled
  aws_ s3api put-bucket-tagging --bucket "$STATE_BUCKET" --tagging 'TagSet=[{Key=project,Value=serena}]'
}

tf() {  # tf registry|personal|shared <terraform arguments> (deploy/terraform/<part>; D302)
  local part="$1"; shift
  terraform -chdir="$TF_DIR/$part" "$@"
}

backend_config() {  # backend_config registry|personal|shared
  BACKEND=(-backend-config="bucket=$STATE_BUCKET" -backend-config="key=serena/$SERENA_ENV_NAME/$1.tfstate"
           -backend-config="region=$AWS_REGION" -backend-config="use_lockfile=true")
}

# Before D302 the personal root's state was app.tfstate. An environment deployed then and still holding resources there
# must be destroyed from main's earlier code (or moved by hand); this code would otherwise see an empty state and try
# to create everything again beside it.
check_no_old_state() {
  local dir="serena/$SERENA_ENV_NAME"
  aws_ s3api head-object --bucket "$STATE_BUCKET" --key "$dir/personal.tfstate" >/dev/null 2>&1 && return 0
  aws_ s3 cp "s3://$STATE_BUCKET/$dir/app.tfstate" - 2>/dev/null |
    python3 -c 'import json, sys; sys.exit(1 if json.load(sys.stdin).get("resources") else 0)' 2>/dev/null && return 0
  aws_ s3api head-object --bucket "$STATE_BUCKET" --key "$dir/app.tfstate" >/dev/null 2>&1 || return 0
  die "'$ENV' still has resources in its old state, s3://$STATE_BUCKET/$dir/app.tfstate (before D302). Destroy it with
the code from before the move (git switch --detach f4cad43 && ./serena aws destroy --env $ENV), then come back."
}

tf_init() {  # tf_init registry|personal|shared: point Terraform at this environment's state (the lock is a file beside it)
  [ "$1" != personal ] || check_no_old_state
  backend_config "$1"
  tf "$1" init -input=false -reconfigure "${BACKEND[@]}" >/dev/null ||
    die "terraform init failed for $1. Run it again without '>/dev/null' to see why: ./serena aws init"
}

cidr_list() {  # cidr_list "a/32,b/24" -> ["a/32","b/24"]; "" -> []
  local v; v="$(printf '%s' "$1" | sed 's/ //g')"
  [ -n "$v" ] && printf '["%s"]' "$(printf '%s' "$v" | sed 's/,/","/g')" || printf '[]'
}

# The app configuration's variables. app_vars IMAGE RUNNING [DEVTOOLS-IMAGE] fills the array TF_VARS.
app_vars() {
  TF_VARS=(
    -var "account_id=$ACCOUNT_ID" -var "region=$AWS_REGION" -var "env_name=$SERENA_ENV_NAME" -var "image_uri=$1" -var "running=$2"
    -var "etl_cidrs=$(cidr_list "$ETL_CIDRS")" -var "admin_cidrs=$(cidr_list "$ADMIN_CIDRS")" -var "waf=$WAF"
    -var "tenants=$(tenants_var)" -var "env_label=$ENV_LABEL" -var "protect_data=$PROTECT_DATA"
    -var "simulated_cspace=$SIMULATED_CSPACE" -var "devtools_image_uri=${3:-}" -var "web_count=$WEB_COUNT"
    -var "cdn_keys=$(cdn_keys_exist)" -var "alert_email=$ALERT_EMAIL"
  )
  if [ "$ROOT" = shared ]; then
    TF_VARS+=(
      -var "apache_cidrs=$(cidr_list "$APACHE_CIDRS")" -var "vpc_id=$VPC_ID"
      -var "app_subnet_ids=$(cidr_list "$APP_SUBNET_IDS")" -var "lb_subnet_ids=$(cidr_list "$LB_SUBNET_IDS")"
      -var "create_gateway_endpoints=$CREATE_GATEWAY_ENDPOINTS" -var "domain_name=$DOMAIN_NAME"
      -var "certificate_arn=$(certificate_arn)"
    )
  else
    TF_VARS+=(-var "allowed_cidrs=$(cidr_list "$ALLOWED_CIDRS")" -var "open_images=$OPEN_IMAGES")
  fi
}

# The shared root's certificate (D294) is made by ../registry; its ARN, or empty.
certificate_arn() {
  tf_init registry
  tf registry output -raw certificate_arn 2>/dev/null || true
}

# A shared environment's certificate is issued only once DevOps has added its validation record (D294, TQ4). Until
# then, say which record, and stop before the shared root.
need_certificate() {
  local arn status
  arn="$(tf registry output -raw certificate_arn 2>/dev/null || true)"
  [ -n "$arn" ] || die "No certificate for $DOMAIN_NAME in ../registry's state. Run ./serena aws deploy again."
  status="$(aws_ acm describe-certificate --certificate-arn "$arn" --query Certificate.Status --output text)"
  [ "$status" = ISSUED ] && return 0
  echo
  echo "The certificate for $DOMAIN_NAME is $status. DevOps adds this record in campus DNS, once (ACM renews it after):"
  aws_ acm describe-certificate --certificate-arn "$arn" \
    --query 'Certificate.DomainValidationOptions[0].ResourceRecord.[Type,Name,Value]' --output text
  die "Run ./serena aws deploy again once the record is in DNS and the certificate is ISSUED. Nothing else was changed."
}

# TQ8: ./serena aws deploys a shared environment only while it uses only the simulator (stage 2's first phase, D300).
# With a real CollectionSpace the pipeline deploys it (D268); by hand only as a break-glass deploy (D276).
need_break_glass() {
  [ "$ROOT" = shared ] && [ "$SIMULATED_CSPACE" != true ] || return 0
  local typed
  echo
  echo "'$ENV' is a shared environment with real data: the pipeline deploys it (D268)."
  echo "Deploy it from here only if the pipeline can't, as a break-glass deploy (D276), signed in with the break-glass"
  echo "permission set and following the recovery runbook; CloudTrail records it."
  read -r -p "Type 'break glass' to go ahead: " typed
  [ "$typed" = "break glass" ] || die "Stopped; nothing was deployed."
}

registry_vars() {
  REGISTRY_VARS=(-var "account_id=$ACCOUNT_ID" -var "region=$AWS_REGION" -var "env_name=$SERENA_ENV_NAME" -var "simulated_cspace=$SIMULATED_CSPACE")
  [ "$ROOT" != shared ] || REGISTRY_VARS+=(-var "domain_name=$DOMAIN_NAME")
}

approve() { [ "${SERENA_AWS_YES:-}" = 1 ] && echo "-auto-approve" || true; }

applied() {  # applied OUTPUT: a value the app was last applied with; empty if never applied or not an output then
  local v
  v="$(tf "$ROOT" output -raw "$1" 2>/dev/null || true)"
  case "$v" in *"No outputs"*|*Warning*|*"not found"*|*Error*) v="" ;; esac
  echo "$v"
}

need_deployed() {
  IMAGE="$(applied image_uri)"
  [ -n "$IMAGE" ] || die "'$ENV' isn't deployed (./serena aws deploy)."
}

# A museum's servability, recalls and cached files belong to the CollectionSpace server it was deployed for (the
# CSIDs are that server's), so a deployed museum's server never changes. A museum can be added. One can be removed
# only where data isn't protected, and when its name is typed: its bucket (its cached files) and secrets go with it.
check_museums() {  # check_museums ask|look: ask = this command applies (removing asks first); look = plan only
  local deployed museum url now removed="" ok
  deployed="$(applied museums)"
  [ -n "$deployed" ] || return 0   # never deployed: nothing to check
  for museum in $(museum_names "$deployed"); do
    url="$(server_of "$museum" "$deployed")"
    if now="$(server_of "$museum")"; then
      [ "$now" = "$url" ] && continue
      echo "'$ENV' was deployed with $museum on $url, but its settings now say $now." >&2
      echo "$museum's servability, recalls and cached files refer to records on the first." >&2
      die "Stopped; nothing was changed. Put the setting back; or run ./serena aws destroy first (it deletes Serena's data);
or deploy the new server as another environment: a different SERENA_ENV_NAME in $LOCAL."
    fi
    removed="$removed $museum"
  done
  for museum in $(museum_names); do
    server_of "$museum" "$deployed" >/dev/null || echo "Adding the museum $museum ($(server_of "$museum"))."
  done
  for museum in $removed; do
    [ "$PROTECT_DATA" != true ] ||
      die "Stopped; nothing was changed. '$ENV' protects its data (PROTECT_DATA=true), so $museum can't be removed."
    echo "$museum is no longer in the settings. Removing it deletes its bucket (every file Serena cached for it) and its"
    echo "secrets. Its rows stay in the tables, unused."
    [ "$1" = ask ] || { echo "(./serena aws deploy asks before removing it.)"; continue; }
    read -r -p "Type the museum's name ($museum) to remove it: " ok || ok=""
    [ "$ok" = "$museum" ] || die "Stopped; nothing was changed."
  done
}

# ---- secrets (secrets.tf; the formats are in backend/serena/config.py) -----------------------------------------------
secret_id() {  # secret_id cspace|etl-tokens|portal-signing-key MUSEUM
  echo "$NAME/$2/$1"
}

secret_versions() {  # secret_versions ID: how many versions it has ("" if it doesn't exist); never reads its value
  aws_ secretsmanager describe-secret --secret-id "$1" --query 'length(keys(VersionIdsToStages || `{}`))' --output text 2>/dev/null || true
}

secret_changed() {  # secret_changed ID: the day it last changed
  aws_ secretsmanager describe-secret --secret-id "$1" --query LastChangedDate --output text 2>/dev/null | cut -c1-10
}

put_secret() {  # put_secret ID: stores what comes on standard input (never an argument: not in the process list)
  aws_ secretsmanager put-secret-value --secret-id "$1" --secret-string file:///dev/stdin >/dev/null
}

need_secret() {  # need_secret ID
  [ -n "$(secret_versions "$1")" ] || die "No secret $1 yet. ./serena aws deploy creates it; then run this again."
}

# A rotation: the new value becomes "current" and the old current "previous", so both work until the next rotation
# (backend/serena/tokens.py, signed_links.py). The old value goes from the AWS CLI into python3 and back, never shown.
# rotate ID NEW-JSON-VALUE-ON-STDIN: prints nothing.
rotate() {
  local id="$1" old
  old="$(aws_ secretsmanager get-secret-value --secret-id "$id" --query SecretString --output text 2>/dev/null || echo '{}')"
  OLD="$old" python3 -c '
import json, os, sys
try:
    old = json.loads(os.environ["OLD"])
except ValueError:
    old = {}
new = json.load(sys.stdin)
print(json.dumps({"current": new, "previous": old.get("current") if isinstance(old, dict) else None}))' | put_secret "$id"
}

new_token() { python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }

etl_token() {  # etl_token MUSEUM [quiet]
  local id token
  id="$(secret_id etl-tokens "$1")"
  need_secret "$id"
  token="$(new_token)"
  printf '"%s"' "$token" | rotate "$id"
  [ "${2:-}" = quiet ] && return 0
  echo "$1's new ETL token, stored in $id. Copy it now into the ETL's token file for $1; it isn't shown again:"
  echo
  echo "  $token"
  echo
  echo "Its previous token keeps working until the next ./serena aws etl-token $1. Serena reads the new one within 5 minutes."
}

portal_key() {  # portal_key MUSEUM [quiet]
  local id key kid
  signed_museum "$1" || die "$1 doesn't allow signed access (backend/serena/museums/$1.yaml), so it has no portal key."
  id="$(secret_id portal-signing-key "$1")"
  need_secret "$id"
  key="$(new_token)" kid="$1-$(date -u +%Y%m%d%H%M%S)"
  printf '{"kid":"%s","key":"%s"}' "$kid" "$key" | rotate "$id"
  [ "${2:-}" = quiet ] && return 0
  echo "$1's new signing key for signed links, stored in $id. Give both to the portal now; they aren't shown again:"
  echo
  echo "  key ID: $kid"
  echo "  key:    $key"
  echo
  echo "Links signed with the previous key keep working until the next ./serena aws portal-key $1."
}

json_string() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }  # printf is a builtin: not in the process list

cspace_secret() {  # cspace_secret MUSEUM
  local museum="$1" id user="" password="" again=""
  [ "$SIMULATED_CSPACE" = false ] ||
    die "'$ENV' uses the simulated CollectionSpace: ./serena aws deploy has set its account to the simulator's own."
  id="$(secret_id cspace "$museum")"
  need_secret "$id"
  echo "$museum's read-only CollectionSpace service account on $(server_of "$museum"), for Serena's fetches and the light check."
  echo "What you type goes to AWS Secrets Manager ($id). It isn't shown, saved on this computer or logged."
  printf "Its user name: "; IFS= read -r user
  printf "Its password (not shown): "; IFS= read -rs password; echo
  printf "The password again: "; IFS= read -rs again; echo
  [ -n "$user" ] && [ -n "$password" ] || die "Nothing was changed: the user name and the password are both needed."
  [ "$password" = "$again" ] || die "Nothing was changed: the two passwords differ."
  printf '{"username":"%s","password":"%s"}' "$(json_string "$user")" "$(json_string "$password")" | put_secret "$id"
  password="" again=""
  echo "Saved. Serena uses it within 5 minutes; no deploy or restart is needed."
}

# With the simulator, deploy sets each museum's secrets once: the simulator's account (serena/serena, synthetic, in
# the fakecspace package), a random ETL token (the fake ETL reads it itself) and, for a museum with signed access,
# a random portal key. Nothing is shown.
sim_secrets() {
  local museum
  for museum in $(museum_names); do
    [ "$(secret_versions "$(secret_id cspace "$museum")")" != 0 ] ||
      printf '{"username":"serena","password":"serena"}' | put_secret "$(secret_id cspace "$museum")"
    [ "$(secret_versions "$(secret_id etl-tokens "$museum")")" != 0 ] || etl_token "$museum" quiet
    ! signed_museum "$museum" || [ "$(secret_versions "$(secret_id portal-signing-key "$museum")")" != 0 ] ||
      portal_key "$museum" quiet
  done
}

# ---- image delivery: the CloudFront signing key (D200; terraform/modules/files/delivery.tf, core/secrets.tf) ------
# The private key goes from openssl straight into the secret, first as its AWSPENDING version; the public keys (the
# current one and the one before it) go into an SSM parameter that Terraform reads, so CloudFront's key group trusts
# both. Once Terraform has applied, the pending key becomes the secret's current value with the key ID CloudFront gave
# it, and the app signs with it within 5 minutes. A rotation never breaks a URL already handed out: the previous key
# stays trusted until the next rotation (a URL lives 30 minutes at most, so don't rotate twice within 30 minutes).
cdn_secret() { echo "$NAME/cloudfront-signing-key"; }
cdn_param() { echo "/$NAME/cloudfront-public-keys"; }

cdn_keys_exist() {  # true once the first public key is in SSM (Terraform then reads it and delivers files)
  aws_ ssm get-parameter --name "$(cdn_param)" --query Parameter.Name --output text >/dev/null 2>&1 && echo true || echo false
}

cdn_key_names() {  # the trusted keys' names, oldest first, one per line
  aws_ ssm get-parameter --name "$(cdn_param)" --query Parameter.Value --output text 2>/dev/null |
    python3 -c 'import json, sys; [print(k["name"]) for k in json.load(sys.stdin)]' 2>/dev/null || true
}

# The secret's very first version also gets AWSCURRENT, whatever label it's given (Secrets Manager's rule), so a pending
# key is found by its AWSPENDING label alone.
pending_version() {  # the signing key secret's version labeled AWSPENDING; "" if none
  aws_ secretsmanager describe-secret --secret-id "$(cdn_secret)" --output json 2>/dev/null | python3 -c '
import json, sys
try:
    stages = json.load(sys.stdin).get("VersionIdsToStages") or {}
except ValueError:
    stages = {}
print(next((v for v, s in stages.items() if "AWSPENDING" in s), ""))'
}

apply_again() {  # apply with the running images and settings (no prompt for a change cdn-key or deploy started)
  app_vars "$(applied image_uri)" "$(was_running)" "$(applied devtools_image_uri)"
  # shellcheck disable=SC2046
  tf "$ROOT" apply -input=false $(approve) "${TF_VARS[@]}"
}

cdn_key() {  # a new signing key: made, trusted by CloudFront (Terraform), then used
  local id version name public keys
  id="$(cdn_secret)"
  need_secret "$id"
  command -v openssl >/dev/null || die "openssl isn't installed."
  if [ -n "$(pending_version)" ]; then
    echo "A new signing key is already waiting for CloudFront to trust it (an earlier cdn-key didn't finish): applying."
  else
    name="$NAME-$(date -u +%Y%m%d%H%M%S)"
    version="$(python3 -c 'import uuid; print(uuid.uuid4())')"
    echo "Making the CloudFront signing key $name. Its private key goes straight to AWS Secrets Manager ($id)."
    openssl genrsa 2048 2>/dev/null |
      KEY_NAME="$name" python3 -c 'import json, os, sys; print(json.dumps({"name": os.environ["KEY_NAME"], "private_key": sys.stdin.read()}))' |
      aws_ secretsmanager put-secret-value --secret-id "$id" --client-request-token "$version" --version-stages AWSPENDING \
        --secret-string file:///dev/stdin >/dev/null
    public="$(aws_ secretsmanager get-secret-value --secret-id "$id" --version-id "$version" --query SecretString --output text |
      python3 -c 'import json, sys; sys.stdout.write(json.load(sys.stdin)["private_key"])' | openssl rsa -pubout 2>/dev/null || true)"
    case "$public" in
      "-----BEGIN PUBLIC KEY-----"*) ;;
      *) aws_ secretsmanager update-secret-version-stage --secret-id "$id" --version-stage AWSPENDING --remove-from-version-id "$version" >/dev/null || true
         die "openssl couldn't make the key pair; nothing was changed." ;;
    esac
    keys="$(aws_ ssm get-parameter --name "$(cdn_param)" --query Parameter.Value --output text 2>/dev/null || echo '[]')"
    KEYS="$keys" KEY_NAME="$name" PUBLIC="$public" python3 -c '
import json, os
old = json.loads(os.environ["KEYS"])
print(json.dumps(old[-1:] + [{"name": os.environ["KEY_NAME"], "public_key": os.environ["PUBLIC"] + "\n"}]))' |
      aws_ ssm put-parameter --name "$(cdn_param)" --type String --overwrite --value file:///dev/stdin >/dev/null
    echo "Terraform now adds it to the key group CloudFront trusts (a few minutes)."
  fi
  apply_again
  finish_cdn_key
}

finish_cdn_key() {  # the pending key becomes the one the app signs with, once CloudFront trusts it
  local id version name key_id
  id="$(cdn_secret)"
  version="$(pending_version)"
  [ -n "$version" ] || return 0
  name="$(aws_ secretsmanager get-secret-value --secret-id "$id" --version-id "$version" --query SecretString --output text |
    python3 -c 'import json, sys; print(json.load(sys.stdin).get("name", ""))')"
  key_id="$(tf "$ROOT" output -json cdn_key_ids 2>/dev/null |
    KEY_NAME="$name" python3 -c 'import json, os, sys; print(json.load(sys.stdin).get(os.environ["KEY_NAME"], ""))' 2>/dev/null || true)"
  if [ -z "$key_id" ]; then
    echo "The new signing key $name isn't trusted by CloudFront yet: run ./serena aws deploy (or cdn-key) again to finish."
    return 0
  fi
  aws_ secretsmanager get-secret-value --secret-id "$id" --version-id "$version" --query SecretString --output text |
    KEY_ID="$key_id" python3 -c 'import json, os, sys; v = json.load(sys.stdin); print(json.dumps({"key_pair_id": os.environ["KEY_ID"], "private_key": v["private_key"]}))' |
    put_secret "$id"
  # Moving AWSCURRENT to the new version may already have taken AWSPENDING off the old one.
  [ -z "$(pending_version)" ] ||
    aws_ secretsmanager update-secret-version-stage --secret-id "$id" --version-stage AWSPENDING --remove-from-version-id "$version" >/dev/null
  echo "Serena signs the museums' files with $name within 5 minutes. The key before it stays trusted until the next ./serena aws cdn-key."
}

# ---- alert email (D201; deploy/terraform/modules/core/alerts.tf) -----------------------------------------------------
# AWS emails ALERT_EMAIL a link. Confirming it here, instead of by a click, makes unsubscribing need an AWS sign-in, so
# no one on a mailing list can unsubscribe everyone by accident.
confirm_alerts() {
  look; need_deployed
  local topic email link
  topic="$(applied alert_topic_arn)" email="$(applied alert_email)"
  [ -n "$topic" ] || die "'$ENV' has no alert topic yet: ./serena aws deploy."
  [ -n "$email" ] || die "No address is subscribed: set ALERT_EMAIL=\"<address>\" in $LOCAL, then ./serena aws deploy."
  if [ "$(alert_subscription)" = confirmed ]; then
    echo "Already confirmed: alerts and alarms go to $email. Nothing to do."; return 0
  fi
  echo "AWS emailed $email a link to confirm the subscription. Don't click it: copy the link and paste it here."
  printf "The link: "; IFS= read -r link
  # The request goes in a file only we can read, not on the command line (where ps would show the token). Not
  # file:///dev/stdin: the AWS CLI on macOS reads nothing from a pipe there ("Invalid JSON received").
  local request
  request="$(umask 077 && mktemp)" || die "Couldn't make a temporary file."
  LINK="$link" TOPIC="$topic" python3 -c '
import json, os, sys
from urllib.parse import parse_qs, urlparse
query = parse_qs(urlparse(os.environ["LINK"].strip()).query)
topic, token = query.get("TopicArn", [""])[0], query.get("Token", [""])[0]
if topic != os.environ["TOPIC"] or not token:
    sys.exit("That is not the confirmation link for this environment\x27s alert topic. Nothing was changed.")
print(json.dumps({"TopicArn": topic, "Token": token, "AuthenticateOnUnsubscribe": "true"}))' >"$request" ||
    { rm -f "$request"; exit 1; }
  if ! aws_ sns confirm-subscription --cli-input-json "file://$request" >/dev/null; then
    rm -f "$request"
    # Confirmed meanwhile (the same link pasted twice, or confirmed elsewhere): AWS refuses the link, but all is well.
    [ "$(alert_subscription)" != confirmed ] || { echo "Already confirmed: alerts and alarms go to $email."; return 0; }
    die "Not confirmed. AWS's link expires after 3 days: for a new one, remove ALERT_EMAIL, deploy, put it back and deploy again."
  fi
  rm -f "$request"
  echo "Confirmed: alerts and alarms now go to $email; unsubscribing needs an AWS sign-in."
}

# ---- commands -----------------------------------------------------------------------------------------------------
prepare() { load_env; check_account; need_terraform; ensure_state_bucket; }

# For commands that only look: no state bucket means nothing was ever deployed, and nothing is created.
look() {
  load_env; check_account; need_terraform
  aws_ s3api head-bucket --bucket "$STATE_BUCKET" >/dev/null 2>&1 || { echo "'$ENV' isn't deployed (./serena aws deploy)."; exit 0; }
  tf_init "$ROOT"
}

app_url() { applied url; }  # empty while a first deploy hasn't finished

# UC Berkeley's data stays in UC Berkeley's AWS accounts (decided October 29, 2026). An environment with a real
# CollectionSpace (production or QA: Lyrasis's QA tenants hold a copy of production's database) copies the museums'
# files into its account, so every deploy of one shows the rule and waits for the person deploying to type the
# account's number. With the simulator, nothing is asked.
acknowledge_real_data() {
  [ "$SIMULATED_CSPACE" != true ] || return 0
  local typed
  echo
  echo "WARNING: '$ENV' uses a real CollectionSpace: $(museum_names | tr '\n' ' ')"
  echo "Serena copies UC Berkeley museum data (images, documents and their identifiers) into AWS account $ACCOUNT_ID."
  echo "UC Berkeley data, from production or QA, is allowed only in a UC Berkeley AWS account, never in a personal one."
  read -r -p "If $ACCOUNT_ID is a UC Berkeley account, type its number to go ahead: " typed
  [ "$typed" = "$ACCOUNT_ID" ] || die "Stopped; nothing was deployed."
  echo
}

deploy() {
  load_env; check_account; need_break_glass; acknowledge_real_data
  [ "$ROOT" = shared ] || ensure_allowlist
  need_terraform
  command -v docker >/dev/null || die "Docker isn't installed or isn't on the PATH."
  docker info >/dev/null 2>&1 || die "Docker isn't running. Start Docker Desktop and try again."
  ensure_state_bucket
  tf_init "$ROOT"; check_museums ask   # before building anything
  local tag repo registry image devtools_image="" base url code museum _try
  tag="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
  [ -z "$(git status --porcelain 2>/dev/null)" ] || tag="$tag-dirty"
  tag="$tag-$(date -u +%Y%m%d%H%M%S)"

  echo "== 1/3 Image repositories"
  registry_vars
  tf_init registry
  tf registry apply -input=false -auto-approve "${REGISTRY_VARS[@]}"
  repo="$(tf registry output -raw repository_url)"
  [ "$ROOT" != shared ] || need_certificate
  registry="${repo%%/*}"
  image="$repo:$tag"

  echo "== 2/3 Image $image (linux/arm64)"
  docker build --pull --platform linux/arm64 -f deploy/Dockerfile -t "$image" .
  # The registry's short-lived token goes straight from the AWS CLI to Docker; it is never shown or saved here.
  aws_ ecr get-login-password | docker login --username AWS --password-stdin "$registry" >/dev/null
  docker push "$image"
  if [ "$SIMULATED_CSPACE" = true ]; then
    devtools_image="$(tf registry output -raw devtools_repository_url):$tag"
    echo "== 2/3 The simulator's and fake ETL's image $devtools_image (linux/arm64)"
    # The base image from ECR Public's copy of the Docker official image, as deploy/Dockerfile's (no Docker Hub limits
    # on a shared address). Here only: CI and the local stack build backend/Dockerfile from Docker Hub, since ECR
    # Public refuses GitHub's shared runners ("429 Data limit exceeded"). A named build context replaces the image
    # its FROM names, so the Dockerfile (and Dependabot's updates to it) stays as it is.
    base="$(awk 'toupper($1) == "FROM" { print $2; exit }' backend/Dockerfile)"
    case "$base" in
      */*|"") die "backend/Dockerfile's base image ($base) isn't a Docker official image; update deploy/aws.sh." ;;
    esac
    docker build --pull --platform linux/arm64 --build-context "$base=docker-image://public.ecr.aws/docker/library/$base" \
      -f backend/Dockerfile -t "$devtools_image" backend
    docker push "$devtools_image"
  fi

  echo "== 3/3 Serena. Terraform shows its plan and asks before changing anything."
  echo "   The first time takes about 15-25 minutes (CloudFront); it finishes when the app and the worker are running."
  echo "   If a task can't start, ./serena aws logs web (or worker) shows why."
  app_vars "$image" true "$devtools_image"
  # shellcheck disable=SC2046
  tf "$ROOT" apply -input=false $(approve) "${TF_VARS[@]}"
  [ "$SIMULATED_CSPACE" = false ] || sim_secrets
  finish_cdn_key   # a rotation an earlier cdn-key didn't finish
  if [ "$(cdn_keys_exist)" = false ]; then
    echo "== Image delivery: the first CloudFront signing key. Terraform shows a second, smaller plan."
    cdn_key
  fi

  url="$(app_url)"
  echo "$url" > "$URL_FILE"
  # A new CloudFront address can answer 403 or fail for a few minutes while it reaches every edge location.
  printf 'Checking %s/health ' "$url"
  for _try in $(seq 1 24); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$url/health" || true)"
    [ "$code" = 200 ] && break
    printf '.'; sleep 5
  done
  echo
  echo "$ENV_LABEL is up: $url   (the admin app: $url/admin/)"
  if [ "$code" != 200 ] && [ "$ROOT" = shared ]; then
    echo "Note: $url/health answers $code. DevOps's DNS record must point $DOMAIN_NAME at $(applied load_balancer_dns_name),"
    echo "and this computer's address must be in ADMIN_CIDRS (or another list the load balancer admits)."
  elif [ "$code" != 200 ]; then
    echo "Note: $url/health still answers $code after 2 minutes. If it's 403, your address may have changed: ./serena aws allow-my-ip"
  fi
  [ -z "$ALERT_EMAIL" ] || [ "$(alert_subscription)" != pending ] ||
    echo "Next: ./serena aws confirm-alerts   (AWS emailed $ALERT_EMAIL a link; paste it there, don't click it)"
  if [ "$SIMULATED_CSPACE" = true ]; then
    echo "It uses the simulated CollectionSpace (sign in to the admin app as admin/admin). A daily refresh:"
    for museum in $(museum_names); do echo "  ./serena aws etl $museum"; done
    echo "The simulator's records are lost whenever it restarts (a pause, a deploy); Serena keeps its tables and files."
  else
    for museum in $(museum_names); do
      [ "$(secret_versions "$(secret_id cspace "$museum")")" != 0 ] ||
        echo "Next: ./serena aws cspace-secret $museum   (its read-only CollectionSpace account isn't set yet)"
      [ "$(secret_versions "$(secret_id etl-tokens "$museum")")" != 0 ] ||
        echo "Next: ./serena aws etl-token $museum       (the ETL can't call Serena until it has one)"
    done
  fi
}

was_running() {  # true unless the environment is paused
  [ "$(applied running)" = false ] && echo false || echo true
}

plan() {
  look; need_deployed; check_museums look
  app_vars "$IMAGE" "$(was_running)" "$(applied devtools_image_uri)"
  tf "$ROOT" plan -input=false "${TF_VARS[@]}"
}

# Apply again with the running images: for a changed setting (pause, resume, the allowlist).
reapply() {  # reapply RUNNING
  prepare; tf_init "$ROOT"; need_deployed; check_museums ask
  app_vars "$IMAGE" "$1" "$(applied devtools_image_uri)"
  # shellcheck disable=SC2046
  tf "$ROOT" apply -input=false $(approve) "${TF_VARS[@]}"
}

secret_line() {  # secret_line LABEL ID FIX
  case "$(secret_versions "$2")" in
    "") echo "    $1: no secret yet (the next ./serena aws deploy creates it)" ;;
    0)  echo "    $1: NOT SET ($3)" ;;
    *)  echo "    $1: set, last changed $(secret_changed "$2")" ;;
  esac
}

alert_subscription() {  # confirmed, pending or none: the alert topic's email subscription
  local topic arn
  topic="$(applied alert_topic_arn)"
  [ -n "$topic" ] || { echo none; return 0; }
  arn="$(aws_ sns list-subscriptions-by-topic --topic-arn "$topic" --query 'Subscriptions[0].SubscriptionArn' --output text 2>/dev/null || true)"
  case "$arn" in arn:*) echo confirmed ;; PendingConfirmation) echo pending ;; *) echo none ;; esac
}

status() {
  look
  local url deployed museum services="web worker"
  echo "Environment: $ENV (account $ACCOUNT_ID, $AWS_REGION); Terraform state in s3://$STATE_BUCKET/serena/$SERENA_ENV_NAME/"
  IMAGE="$(applied image_uri)"
  [ -n "$IMAGE" ] || { echo "Not deployed (./serena aws deploy)."; return 0; }
  url="$(app_url)"
  case "$url" in https://*) echo "Address: $url" ;; *) echo "Address: none yet. The last deploy didn't finish; run ./serena aws deploy again." ;; esac
  echo "Image:   ${IMAGE##*:}"
  [ "$SIMULATED_CSPACE" = false ] || services="web worker fakecspace"
  # shellcheck disable=SC2086
  { aws_ ecs describe-services --cluster "$NAME" --services $services \
      --query "services[].[serviceName, join('', ['running ', to_string(runningCount), ' of ', to_string(desiredCount)])]" --output text 2>/dev/null || true; } |
  while IFS="$(printf '\t')" read -r name counts; do echo "  $name: $counts"; done
  if [ "$ROOT" = shared ]; then
    echo "Admitted addresses: Apache $APACHE_CIDRS; ETL $ETL_CIDRS; admin $ADMIN_CIDRS"
  else
    echo "Allowed addresses: $ALLOWED_CIDRS"
  fi
  if [ "$(applied delivery)" = true ]; then
    echo "Image delivery: on; signing keys trusted: $(cdn_key_names | tr '\n' ' ')(the newest signs)"
  else
    echo "Image delivery: off (no signing key yet: ./serena aws deploy or cdn-key)"
  fi
  [ -z "$(pending_version)" ] || echo "  A new signing key is waiting to be trusted: ./serena aws deploy"
  case "$(alert_subscription)" in
    confirmed) echo "Alert email: $(applied alert_email)" ;;
    pending) echo "Alert email: $(applied alert_email), NOT CONFIRMED (./serena aws confirm-alerts)" ;;
    *) echo "Alert email: none (set ALERT_EMAIL in $LOCAL and deploy)" ;;
  esac
  local firing
  firing="$(aws_ cloudwatch describe-alarms --alarm-name-prefix "$NAME-" --state-value ALARM --query 'MetricAlarms[].AlarmName' --output text 2>/dev/null || true)"
  [ "$(was_running)" = true ] && echo "Alarms: on${firing:+; firing: $firing}" || echo "Alarms: off while paused"
  deployed="$(applied museums)"   # what was deployed; the settings may have changed since
  echo "Museums:"
  for museum in $(museum_names "${deployed:-$MUSEUMS}"); do
    echo "  $museum: $(server_of "$museum" "${deployed:-$MUSEUMS}")"
    secret_line "CollectionSpace account" "$(secret_id cspace "$museum")" "./serena aws cspace-secret $museum"
    secret_line "ETL token" "$(secret_id etl-tokens "$museum")" "./serena aws etl-token $museum"
    ! signed_museum "$museum" ||
      secret_line "portal signing key" "$(secret_id portal-signing-key "$museum")" "./serena aws portal-key $museum"
  done
  [ -z "$deployed" ] || [ "$(printf '%s\n' $deployed | sort)" = "$(printf '%s\n' $MUSEUMS | sort)" ] ||
    echo "The settings list other museums or servers: ./serena aws plan shows the change."
}

# The fake ETL, once, inside the VPC (modules/simulator): it reaches the simulator and the internal load balancer
# directly, and reads the museum's ETL token itself. Its output is the task's log, printed when it ends.
etl() {  # etl MUSEUM [fake_etl options]
  local museum="${1:-}"; shift || true
  load_env
  [ "$SIMULATED_CSPACE" = true ] ||
    die "'$ENV' uses a real CollectionSpace: its servable lists come from the real ETL (Jira CSW-1027), not the fake one."
  need_museum "$museum" etl
  check_account; need_terraform; tf_init "$ROOT"; need_deployed
  local family subnets sg lb url task id overrides code log out quiet=false arg
  for arg in "$@"; do [ "$arg" != --json ] || quiet=true; done
  # With --json only the summary goes to standard output (./serena aws test reads it); the rest goes to errors.
  if [ "$quiet" = true ]; then exec 3>&2; else exec 3>&1; fi
  family="$(tf "$ROOT" output -json fake_etl | python3 -c 'import json,sys; print(json.load(sys.stdin)["task_definition"])')"
  subnets="$(tf "$ROOT" output -json fake_etl | python3 -c 'import json,sys; print(json.load(sys.stdin)["subnets"])')"
  sg="$(tf "$ROOT" output -json fake_etl | python3 -c 'import json,sys; print(json.load(sys.stdin)["security_group"])')"
  lb="$(applied load_balancer_url)" url="$(app_url)"
  overrides="$(python3 - "$museum" "$lb" "$(sim_url)" "$url" "$@" <<'PY'
import json, sys
museum, lb, sim, public, *extra = sys.argv[1:]
command = ["python", "-m", "devtools.fake_etl", "--museum", museum, "--serena", lb, "--cspace", sim, "--public", public,
           "--poll", "5", *extra]
print(json.dumps({"containerOverrides": [{"name": "fake-etl", "command": command}]}))
PY
)"
  echo "Running the fake ETL for $museum in '$ENV' (a minute or two) ..." >&3
  task="$(aws_ ecs run-task --cluster "$NAME" --task-definition "$family" --launch-type FARGATE --count 1 \
    --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$sg],assignPublicIp=ENABLED}" \
    --overrides "$overrides" --query 'tasks[0].taskArn' --output text)"
  case "$task" in arn:*) ;; *) die "The fake ETL's task didn't start: $task" ;; esac
  id="${task##*/}"
  echo "  task $id" >&3
  # The waits and reads below change nothing, so each is tried again on a dropped connection (a Wi-Fi or VPN blip):
  # the task runs on in AWS whatever happens to this computer's connection.
  until_stopped "$task" ||
    die "Couldn't tell whether the fake ETL finished (still running, or AWS unreachable from here). Its log: ./serena aws logs devtools (task $id)"
  log="/serena/$SERENA_ENV_NAME/devtools"
  out="$(retry aws_ logs get-log-events --log-group-name "$log" --log-stream-name "fake-etl/fake-etl/$id" --start-from-head \
    --query 'events[].message' --output text)" || die "The fake ETL's task ended, but its log couldn't be read: ./serena aws logs devtools (task $id)"
  if [ -n "$out" ] && [ "$out" != None ]; then printf '%s\n' "$out" | tr '\t' '\n'; else echo "(no output in $log)"; fi
  code="$(retry aws_ ecs describe-tasks --cluster "$NAME" --tasks "$task" --query 'tasks[0].containers[0].exitCode' --output text)" ||
    die "Couldn't read the fake ETL's exit code (task $id); its output is above."
  [ "$code" = 0 ] || die "The fake ETL ended with $code: $(retry aws_ ecs describe-tasks --cluster "$NAME" --tasks "$task" --query 'tasks[0].stoppedReason' --output text || true)"
}

# What Serena may serve for a museum: its rows in the servability table (the last servable list, D175), read with
# the profile's own access. Only reads. With the simulator, a deploy or pause empties the simulator but not this
# table: a listed file not cached yet can't be fetched until ./serena aws etl adds the records again.
list_servable() {  # list_servable MUSEUM [--limit N] [--kind KIND]
  local museum="${1:-}" limit=25 kind="" url max=()
  shift || true
  while [ $# -gt 0 ]; do
    case "$1" in
      --limit) [ $# -ge 2 ] || die "--limit needs a number"; limit="$2"; shift 2 ;;
      --kind) [ $# -ge 2 ] || die "--kind needs a kind (image, pdf, 3D, card ...)"; kind="$2"; shift 2 ;;
      *) die "Usage: ./serena aws list <museum> [--limit N] [--kind KIND]" ;;
    esac
  done
  case "$limit" in ''|*[!0-9]*) die "--limit needs a whole number (0 for all)" ;; esac
  load_env; need_museum "$museum" list; check_account; need_terraform; tf_init "$ROOT"; need_deployed
  url="$(app_url)"
  [ "$limit" = 0 ] || max=(--max-items "$limit")
  local filter=()
  [ -z "$kind" ] || filter=(--filter-expression "#k = :k" --expression-attribute-values "{\":t\":{\"S\":\"$museum\"},\":k\":{\"S\":\"$kind\"}}")
  [ -n "$kind" ] || filter=(--expression-attribute-values "{\":t\":{\"S\":\"$museum\"}}")
  retry aws_ dynamodb query --table-name "$NAME-servability" --index-name by_tenant \
      --key-condition-expression "tenant = :t" "${filter[@]}" ${max[@]+"${max[@]}"} \
      --projection-expression "blob_csid, media_csid, #k, #a" --expression-attribute-names '{"#k":"kind","#a":"access"}' \
      --output json |
    MUSEUM="$museum" URL="$url" LIMIT="$limit" python3 -c '
import json, os, sys
data = json.load(sys.stdin)
items = data.get("Items", [])
museum, url, limit = os.environ["MUSEUM"], os.environ["URL"], int(os.environ["LIMIT"])
if not items:
    print(f"Serena has nothing servable for {museum} yet (no updated refresh): ./serena aws etl {museum} with the simulator.")
    sys.exit()
rows = sorted((i.get("kind", {}).get("S", ""), i.get("media_csid", {}).get("S", ""), i["blob_csid"]["S"],
               i.get("access", {}).get("S", "")) for i in items)
print("%-8s %-10s %-36s  %s" % ("kind", "access", "Media CSID", "address"))
for kind, media, blob, access in rows:
    tail = "derivatives/Medium/content" if kind in ("image", "card") else "content"
    note = "  (needs a signed link)" if access != "public" else ""
    address = "%s/%s/imageserver/blobs/%s/%s" % (url, museum, blob, tail)
    print("%-8s %-10s %-36s  %s%s" % (kind, access, media or "(placeholder)", address, note))
more = " There are more: --limit N, or --limit 0 for all." if data.get("NextToken") else ""
print(f"{len(rows)} shown.{more}")'
}

# The AWS tests (serenade/aws/, D222-D231) against this environment once it's deployed and running: you run them,
# signed in, after ./serena aws deploy or resume; never in CI (D229). They make read-only AWS calls with this
# environment's profile, and change only what they undo (a fake ETL refresh, a recall they cancel).
run_tests() {  # run_tests [pytest options]
  load_env; check_account; need_terraform; tf_init "$ROOT"; need_deployed
  [ "$(was_running)" = true ] || die "'$ENV' is paused: ./serena aws resume first."
  local url saved deployed museum py files_url me
  url="$(app_url)"
  case "$url" in https://*) ;; *) die "'$ENV' has no address yet: run ./serena aws deploy again." ;; esac
  saved="$(cat "$URL_FILE" 2>/dev/null || true)"
  [ "$saved" = "$url" ] || die "$URL_FILE says '${saved:-nothing}', but '$ENV' is at $url: ./serena aws deploy saves it."
  deployed="$(applied museums)"
  museum="$(museum_names "${deployed:-$MUSEUMS}" | head -n 1)"
  # The admin account (D228): the simulator's synthetic admin/admin, or a museum admin's, asked for each run and
  # never saved or shown.
  if [ "$SIMULATED_CSPACE" = true ]; then
    : "${SERENADE_ADMIN_USER:=admin}" "${SERENADE_ADMIN_PASSWORD:=admin}"
  else
    [ -n "${SERENADE_ADMIN_USER:-}" ] ||
      die "'$ENV' uses a real CollectionSpace: set SERENADE_ADMIN_USER to a $museum admin's username for the run."
    if [ -z "${SERENADE_ADMIN_PASSWORD:-}" ]; then
      read -r -s -p "$SERENADE_ADMIN_USER's password (not shown or saved): " SERENADE_ADMIN_PASSWORD; echo
    fi
  fi
  serenade_venv test
  echo "The AWS tests against $ENV_LABEL: $url (image ${IMAGE##*:}, museum $museum)"
  [ "$SIMULATED_CSPACE" = true ] || echo "A real CollectionSpace: only the tests that look run."
  rm -rf serenade/.run/failures
  files_url="$(applied files_url)"; [ -n "$files_url" ] || files_url="$url"
  # The address-rule tests (T106 to T108, D299) need this computer's address and the lists the load balancer uses.
  me="$(my_ip)"
  SERENADE_AWS_ROOT="$ROOT" SERENADE_AWS_FILES_URL="$files_url" SERENADE_AWS_MY_ADDRESS="$me" \
    SERENADE_AWS_ETL_CIDRS="$ETL_CIDRS" SERENADE_AWS_ADMIN_CIDRS="$ADMIN_CIDRS" \
    SERENADE_AWS_ADMITTED_CIDRS="$APACHE_CIDRS,$ETL_CIDRS,$ADMIN_CIDRS" \
  SERENADE_AWS_ENV="$ENV" SERENADE_AWS_URL="$url" SERENADE_AWS_MUSEUM="$museum" SERENADE_AWS_LABEL="$ENV_LABEL" \
    SERENADE_AWS_IMAGE_TAG="${IMAGE##*:}" SERENADE_AWS_SIMULATED="$SIMULATED_CSPACE" \
    SERENADE_AWS_LOG_PREFIX="/serena/$SERENA_ENV_NAME" SERENADE_AWS_BUCKET="$NAME-$museum-$ACCOUNT_ID-$AWS_REGION" \
    SERENADE_ADMIN_USER="$SERENADE_ADMIN_USER" SERENADE_ADMIN_PASSWORD="$SERENADE_ADMIN_PASSWORD" \
    serenade/.venv/bin/python -m pytest serenade/aws -p no:cacheprovider "$@"
}

serenade_venv() {  # serenade_venv COMMAND: makes serenade/.venv once (the AWS tests and the replay use it)
  local py
  py="$(command -v python3.11 || true)"
  [ -n "$py" ] || die "./serena aws $1 needs python3.11 (the repository's Python)."
  if [ ! -x serenade/.venv/bin/python ]; then
    "$py" -m venv serenade/.venv
    serenade/.venv/bin/pip install -q --require-hashes -r serenade/requirements.txt
  fi
}

# The access-log replay (D278-D288): only against an environment with the simulator, whose misses fetch from it, never
# from a museum's CollectionSpace (D279); from this computer, through CloudFront, as visitors' requests come (D286).
replay_logs() {  # replay_logs [serenade/load/replay.py options]
  load_env
  [ "$SIMULATED_CSPACE" = true ] && [ "$OPEN_IMAGES" = false ] ||
    die "'$ENV' isn't an environment with the simulator and closed images: the replay runs only against one (D279)."
  local museum arg dry=false url summary metric svc
  museum="$(museum_names | head -n 1)"
  for arg in "$@"; do [ "$arg" != --dry-run ] || dry=true; done
  serenade_venv replay
  if [ "$dry" = true ]; then
    serenade/.venv/bin/python -m serenade.load.replay --museum "$museum" --env "$ENV" "$@"
    return
  fi
  check_account; need_terraform; tf_init "$ROOT"; need_deployed
  [ "$(was_running)" = true ] || die "'$ENV' is paused: ./serena aws resume first."
  url="$(app_url)"
  case "$url" in https://*) ;; *) die "'$ENV' has no address yet: run ./serena aws deploy again." ;; esac
  summary="$(mktemp)"
  SERENA_REPLAY_SIMULATED=true serenade/.venv/bin/python -m serenade.load.replay --url "$url" --museum "$museum" \
    --env "$ENV" --summary "$summary" "$@" || { rm -f "$summary"; die "The replay stopped; nothing was changed."; }
  local start end
  start="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["window"]["start"])' "$summary")"
  end="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["window"]["end"])' "$summary")"
  rm -f "$summary"
  echo "Waiting 3 minutes for CloudWatch's figures for the last minutes ..."
  sleep 180
  echo "CPU and memory, in percent of the task size, a minute at a time, $start to $end (D287):"
  for svc in web worker; do
    for metric in CPUUtilization MemoryUtilization; do
      retry aws_ cloudwatch get-metric-statistics --namespace AWS/ECS --metric-name "$metric" \
        --dimensions "Name=ClusterName,Value=$NAME" "Name=ServiceName,Value=$svc" --start-time "$start" \
        --end-time "$(python3 -c 'import datetime,sys; print((datetime.datetime.fromisoformat(sys.argv[1]) + datetime.timedelta(minutes=2)).isoformat())' "$end")" \
        --period 60 --statistics Average Maximum --output json |
        serenade/.venv/bin/python -m serenade.load.metrics "$svc ${metric%Utilization}"
    done
  done
}

retry() {  # retry COMMAND...: a read-only AWS call, tried up to 4 times, 5 seconds apart; its error shown on the last
  local _try
  for _try in 1 2 3; do "$@" 2>/dev/null && return 0; sleep 5; done
  "$@"
}

until_stopped() {  # until_stopped TASK: waits up to about 15 minutes for the task to stop
  local _poll state
  for _poll in $(seq 1 90); do
    state="$(retry aws_ ecs describe-tasks --cluster "$NAME" --tasks "$1" --query 'tasks[0].lastStatus' --output text)" || return 1
    [ "$state" = STOPPED ] && return 0
    sleep 10
  done
  return 1
}

logs() {
  load_env
  local svc="${1:-}"
  case "$svc" in web|worker) ;; devtools) [ "$SIMULATED_CSPACE" = true ] || die "'$ENV' doesn't run the simulator or the fake ETL." ;;
    *) die "Usage: ./serena aws logs web|worker|devtools" ;; esac
  aws_ logs tail "/serena/$SERENA_ENV_NAME/$svc" --follow --since 30m
}

destroy() {
  prepare
  local ok deployed devtools_image
  [ "$PROTECT_DATA" != true ] ||
    echo "'$ENV' protects its data (PROTECT_DATA=true): Terraform will refuse to delete its tables and non-empty buckets."
  echo "This deletes the '$ENV' Serena in AWS account $ACCOUNT_ID: its tables, cached files, secrets, logs and images."
  echo "Nothing in CollectionSpace changes. The KMS key is deleted after a waiting period."
  read -r -p "Type the environment's name ($ENV) to go ahead: " ok
  [ "$ok" = "$ENV" ] || die "Stopped; nothing was deleted."
  tf_init "$ROOT"
  IMAGE="$(applied image_uri)"; [ -n "$IMAGE" ] || IMAGE=none
  [ -n "$ALLOWED_CIDRS" ] || ALLOWED_CIDRS="127.0.0.1/32"   # the variable must be set, even to destroy
  devtools_image="$(applied devtools_image_uri)"; [ -n "$devtools_image" ] || devtools_image=none
  deployed="$(applied museums)"; [ -z "$deployed" ] || MUSEUMS="$deployed"   # the museums in the state
  app_vars "$IMAGE" false "$devtools_image"
  echo "Destroying Serena (about 15-20 minutes: CloudFront is disabled first) ..."
  # CloudFront removes its VPC origin's network interfaces in the background, which can briefly hold the VPC.
  tf "$ROOT" destroy -input=false -auto-approve "${TF_VARS[@]}" ||
    die "The destroy didn't finish. Wait a few minutes and run ./serena aws destroy again; Terraform continues where it stopped."
  aws_ ssm delete-parameter --name "$(cdn_param)" >/dev/null 2>&1 || true   # the public keys (made by cdn-key)
  tf_init registry
  registry_vars
  tf registry destroy -input=false -auto-approve "${REGISTRY_VARS[@]}"
  rm -f "$URL_FILE"
  echo "Done. '$ENV' is gone from AWS (./serena aws deploy creates it again)."
  echo "The Terraform state bucket s3://$STATE_BUCKET is kept; it holds the (now empty) state and its history."
}

case "$CMD" in
  deploy) deploy ;;
  plan) plan ;;
  status) status ;;
  url) load_env
       if [ -f "$URL_FILE" ]; then cat "$URL_FILE"; else
         look; u="$(app_url)"
         case "$u" in https://*) echo "$u" ;; *) echo "'$ENV' isn't deployed (./serena aws deploy)." ;; esac
       fi ;;
  logs) logs "${1:-}" ;;
  pause) reapply false; echo "Paused: no tasks run (./serena aws resume)." ;;
  resume) reapply true; echo "Running: $(app_url)" ;;
  allow-my-ip)
    load_env
    [ "$ROOT" = personal ] || die "'$ENV' is on the shared root: its addresses are ADMIN_CIDRS and the others in $LOCAL."
    ip="$(my_ip)/32"
    case ",$ALLOWED_CIDRS," in *",$ip,"*) echo "$ip is already allowed." ; exit 0 ;; esac
    new="${ALLOWED_CIDRS:+$ALLOWED_CIDRS,}$ip"
    save_local ALLOWED_CIDRS "$new"; ALLOWED_CIDRS="$new"
    echo "Allowed: $new"
    prepare; tf_init "$ROOT"
    if [ -z "$(applied image_uri)" ]; then echo "Saved; it applies at the first deploy."; else reapply "$(was_running)"; fi ;;
  etl) etl "$@" ;;
  list) list_servable "$@" ;;
  test) run_tests "$@" ;;
  replay) replay_logs "$@" ;;
  cspace-secret) load_env; need_museum "${1:-}" cspace-secret; check_account; cspace_secret "$1" ;;
  etl-token) load_env; need_museum "${1:-}" etl-token; check_account; etl_token "$1" ;;
  portal-key) load_env; need_museum "${1:-}" portal-key; check_account; portal_key "$1" ;;
  cdn-key) prepare; tf_init "$ROOT"; need_deployed; check_museums ask; cdn_key ;;
  confirm-alerts) confirm_alerts ;;
  init) prepare
        backend_config registry; tf registry init -reconfigure "${BACKEND[@]}"
        backend_config "$ROOT"; tf "$ROOT" init -reconfigure "${BACKEND[@]}" ;;
  destroy) destroy ;;
  help|-h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0" ;;
  *) die "Unknown command '$CMD'. ./serena aws help lists them." ;;
esac
