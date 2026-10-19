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
#   ./serena aws etl MUSEUM [--rows N] [--failed]   with the simulator: a whole daily refresh by the fake ETL, run
#                              once inside the environment; prints the refresh's result and sample image addresses
#   ./serena aws cspace-secret MUSEUM   set a museum's read-only CollectionSpace account (asks; nothing is shown or saved)
#   ./serena aws etl-token MUSEUM       make a museum's new ETL token (the old one keeps working until the next);
#                              shows it once, for the ETL's token file
#   ./serena aws portal-key MUSEUM      make a new signing key for a museum's signed links (the old one keeps working
#                              until the next); shows it once, for the portal
#   ./serena aws destroy       delete everything in AWS for this environment, data included (asks first)
#   ./serena aws init          point Terraform at this environment's state, to run terraform commands yourself
#
# Which environment: --env NAME or SERENA_AWS_ENV (default personal-dev). Its settings are in
# deploy/environments/NAME.conf; NAME.local.conf (not committed) holds the account number and allowed addresses.
# CSPACE_TENANTS lists the museums the environment serves, each with its CollectionSpace server
# ("pahma=https://... cinefiles=https://..."). With SIMULATED_CSPACE=true the environment runs the simulated
# CollectionSpace instead, for the museums in SIMULATED_MUSEUMS, and ./serena aws etl runs the fake ETL; deploy then
# sets every secret itself (the simulator's account, random ETL tokens and portal keys). Never with data that matters.
# Sign in first with: aws sso login --profile <the environment's AWS_PROFILE>. Nothing here handles a password, token
# or key except cspace-secret, etl-token and portal-key, which pass them straight to AWS Secrets Manager.
# Terraform (deploy/terraform) creates everything; its state is in an S3 bucket in the same account, which the first
# deploy creates. SERENA_AWS_YES=1 skips Terraform's "yes" prompt. Works with the macOS bash (3.2) and needs python3.
# A deployed museum's CollectionSpace server never changes (check_museums). Modeled on the BMU's deploy/aws.sh.
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
  CSPACE_TENANTS="" OPEN_IMAGES="" WAF="" PROTECT_DATA="" WEB_COUNT=""
  # shellcheck disable=SC1090
  . "$CONF"
  # shellcheck disable=SC1090
  [ -f "$LOCAL" ] && . "$LOCAL"
  : "${AWS_PROFILE:?set AWS_PROFILE in $CONF}" "${AWS_REGION:?set AWS_REGION in $CONF}" "${SERENA_ENV_NAME:?set SERENA_ENV_NAME in $CONF}"
  NAME="serena-$SERENA_ENV_NAME"   # the cluster's name and the prefix of every resource
  local flag
  for flag in SIMULATED_CSPACE OPEN_IMAGES WAF PROTECT_DATA; do
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

# The simulator's address in the VPC (Cloud Map): local.simulator_url in deploy/terraform/app/devtools.tf.
sim_url() { echo "http://fakecspace.$NAME.internal:8180"; }

signed_museum() {  # signed_museum MUSEUM: whether its configuration allows signed access (it then has a portal key;
  # local.signed_museums in deploy/terraform/app/versions.tf)
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
  for key in app registry; do
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

tf() {  # tf registry|app <terraform arguments>
  local part="$1"; shift
  terraform -chdir="$TF_DIR/$part" "$@"
}

backend_config() {  # backend_config registry|app
  BACKEND=(-backend-config="bucket=$STATE_BUCKET" -backend-config="key=serena/$SERENA_ENV_NAME/$1.tfstate"
           -backend-config="region=$AWS_REGION" -backend-config="use_lockfile=true")
}

tf_init() {  # tf_init registry|app: point Terraform at this environment's state (the lock is a file beside it)
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
    -var "allowed_cidrs=$(cidr_list "$ALLOWED_CIDRS")" -var "etl_cidrs=$(cidr_list "$ETL_CIDRS")"
    -var "admin_cidrs=$(cidr_list "$ADMIN_CIDRS")" -var "open_images=$OPEN_IMAGES" -var "waf=$WAF"
    -var "tenants=$(tenants_var)" -var "env_label=$ENV_LABEL" -var "protect_data=$PROTECT_DATA"
    -var "simulated_cspace=$SIMULATED_CSPACE" -var "devtools_image_uri=${3:-}" -var "web_count=$WEB_COUNT"
  )
}

registry_vars() {
  REGISTRY_VARS=(-var "account_id=$ACCOUNT_ID" -var "region=$AWS_REGION" -var "env_name=$SERENA_ENV_NAME" -var "simulated_cspace=$SIMULATED_CSPACE")
}

approve() { [ "${SERENA_AWS_YES:-}" = 1 ] && echo "-auto-approve" || true; }

applied() {  # applied OUTPUT: a value the app was last applied with; empty if never applied or not an output then
  local v
  v="$(tf app output -raw "$1" 2>/dev/null || true)"
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
# backend/fakecspace/app.py), a random ETL token (the fake ETL reads it itself) and, for a museum with signed access,
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

# ---- commands -----------------------------------------------------------------------------------------------------
prepare() { load_env; check_account; need_terraform; ensure_state_bucket; }

# For commands that only look: no state bucket means nothing was ever deployed, and nothing is created.
look() {
  load_env; check_account; need_terraform
  aws_ s3api head-bucket --bucket "$STATE_BUCKET" >/dev/null 2>&1 || { echo "'$ENV' isn't deployed (./serena aws deploy)."; exit 0; }
  tf_init app
}

app_url() { applied url; }  # empty while a first deploy hasn't finished

deploy() {
  load_env; check_account; ensure_allowlist; need_terraform
  command -v docker >/dev/null || die "Docker isn't installed or isn't on the PATH."
  docker info >/dev/null 2>&1 || die "Docker isn't running. Start Docker Desktop and try again."
  ensure_state_bucket
  tf_init app; check_museums ask   # before building anything
  local tag repo registry image devtools_image="" url code museum
  tag="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
  [ -z "$(git status --porcelain 2>/dev/null)" ] || tag="$tag-dirty"
  tag="$tag-$(date -u +%Y%m%d%H%M%S)"

  echo "== 1/3 Image repositories"
  registry_vars
  tf_init registry
  tf registry apply -input=false -auto-approve "${REGISTRY_VARS[@]}"
  repo="$(tf registry output -raw repository_url)"
  registry="${repo%%/*}"
  image="$repo:$tag"

  echo "== 2/3 Image $image (linux/arm64)"
  docker build --platform linux/arm64 -f deploy/Dockerfile -t "$image" .
  # The registry's short-lived token goes straight from the AWS CLI to Docker; it is never shown or saved here.
  aws_ ecr get-login-password | docker login --username AWS --password-stdin "$registry" >/dev/null
  docker push "$image"
  if [ "$SIMULATED_CSPACE" = true ]; then
    devtools_image="$(tf registry output -raw devtools_repository_url):$tag"
    echo "== 2/3 The simulator's and fake ETL's image $devtools_image (linux/arm64)"
    docker build --platform linux/arm64 -f backend/Dockerfile -t "$devtools_image" backend
    docker push "$devtools_image"
  fi

  echo "== 3/3 Serena. Terraform shows its plan and asks before changing anything."
  echo "   The first time takes about 15-25 minutes (CloudFront); it finishes when the app and the worker are running."
  echo "   If a task can't start, ./serena aws logs web (or worker) shows why."
  app_vars "$image" true "$devtools_image"
  # shellcheck disable=SC2046
  tf app apply -input=false $(approve) "${TF_VARS[@]}"
  [ "$SIMULATED_CSPACE" = false ] || sim_secrets

  url="$(app_url)"
  echo "$url" > "$URL_FILE"
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$url/health" || true)"
  echo
  echo "$ENV_LABEL is up: $url   (the admin app: $url/admin/)"
  [ "$code" = 200 ] || echo "Note: $url/health answered $code. A new CloudFront address can take a few minutes to work everywhere."
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
  tf app plan -input=false "${TF_VARS[@]}"
}

# Apply again with the running images: for a changed setting (pause, resume, the allowlist).
reapply() {  # reapply RUNNING
  prepare; tf_init app; need_deployed; check_museums ask
  app_vars "$IMAGE" "$1" "$(applied devtools_image_uri)"
  # shellcheck disable=SC2046
  tf app apply -input=false $(approve) "${TF_VARS[@]}"
}

secret_line() {  # secret_line LABEL ID FIX
  case "$(secret_versions "$2")" in
    "") echo "    $1: no secret yet (the next ./serena aws deploy creates it)" ;;
    0)  echo "    $1: NOT SET ($3)" ;;
    *)  echo "    $1: set, last changed $(secret_changed "$2")" ;;
  esac
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
  echo "Allowed addresses: $ALLOWED_CIDRS"
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

# The fake ETL, once, inside the VPC (devtools.tf): it reaches the simulator and the internal load balancer directly,
# and reads the museum's ETL token itself. Its output is the task's log, printed when it ends.
etl() {  # etl MUSEUM [fake_etl options]
  local museum="${1:-}"; shift || true
  load_env
  [ "$SIMULATED_CSPACE" = true ] ||
    die "'$ENV' uses a real CollectionSpace: its servable lists come from the real ETL (Jira CSW-1027), not the fake one."
  need_museum "$museum" etl
  check_account; need_terraform; tf_init app; need_deployed
  local family subnets sg lb url task id overrides code log out
  family="$(tf app output -json fake_etl | python3 -c 'import json,sys; print(json.load(sys.stdin)["task_definition"])')"
  subnets="$(tf app output -json fake_etl | python3 -c 'import json,sys; print(json.load(sys.stdin)["subnets"])')"
  sg="$(tf app output -json fake_etl | python3 -c 'import json,sys; print(json.load(sys.stdin)["security_group"])')"
  lb="$(applied load_balancer_url)" url="$(app_url)"
  overrides="$(python3 - "$museum" "$lb" "$(sim_url)" "$url" "$@" <<'PY'
import json, sys
museum, lb, sim, public, *extra = sys.argv[1:]
command = ["python", "-m", "devtools.fake_etl", "--museum", museum, "--serena", lb, "--cspace", sim, "--public", public,
           "--poll", "5", *extra]
print(json.dumps({"containerOverrides": [{"name": "fake-etl", "command": command}]}))
PY
)"
  echo "Running the fake ETL for $museum in '$ENV' (a minute or two) ..."
  task="$(aws_ ecs run-task --cluster "$NAME" --task-definition "$family" --launch-type FARGATE --count 1 \
    --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$sg],assignPublicIp=ENABLED}" \
    --overrides "$overrides" --query 'tasks[0].taskArn' --output text)"
  case "$task" in arn:*) ;; *) die "The fake ETL's task didn't start: $task" ;; esac
  id="${task##*/}"
  echo "  task $id"
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
  tf_init app
  IMAGE="$(applied image_uri)"; [ -n "$IMAGE" ] || IMAGE=none
  [ -n "$ALLOWED_CIDRS" ] || ALLOWED_CIDRS="127.0.0.1/32"   # the variable must be set, even to destroy
  devtools_image="$(applied devtools_image_uri)"; [ -n "$devtools_image" ] || devtools_image=none
  deployed="$(applied museums)"; [ -z "$deployed" ] || MUSEUMS="$deployed"   # the museums in the state
  app_vars "$IMAGE" false "$devtools_image"
  echo "Destroying Serena (about 15-20 minutes: CloudFront is disabled first) ..."
  # CloudFront removes its VPC origin's network interfaces in the background, which can briefly hold the VPC.
  tf app destroy -input=false -auto-approve "${TF_VARS[@]}" ||
    die "The destroy didn't finish. Wait a few minutes and run ./serena aws destroy again; Terraform continues where it stopped."
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
    ip="$(my_ip)/32"
    case ",$ALLOWED_CIDRS," in *",$ip,"*) echo "$ip is already allowed." ; exit 0 ;; esac
    new="${ALLOWED_CIDRS:+$ALLOWED_CIDRS,}$ip"
    save_local ALLOWED_CIDRS "$new"; ALLOWED_CIDRS="$new"
    echo "Allowed: $new"
    prepare; tf_init app
    if [ -z "$(applied image_uri)" ]; then echo "Saved; it applies at the first deploy."; else reapply "$(was_running)"; fi ;;
  etl) etl "$@" ;;
  cspace-secret) load_env; need_museum "${1:-}" cspace-secret; check_account; cspace_secret "$1" ;;
  etl-token) load_env; need_museum "${1:-}" etl-token; check_account; etl_token "$1" ;;
  portal-key) load_env; need_museum "${1:-}" portal-key; check_account; portal_key "$1" ;;
  init) prepare
        backend_config registry; tf registry init -reconfigure "${BACKEND[@]}"
        backend_config app; tf app init -reconfigure "${BACKEND[@]}" ;;
  destroy) destroy ;;
  help|-h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0" ;;
  *) die "Unknown command '$CMD'. ./serena aws help lists them." ;;
esac
