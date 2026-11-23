"""The AWS deployment (deploy/; D181-D194) stays in step with the code: the tables Terraform creates, and the settings
it gives the app. The committed settings files keep the default environment on the simulator and hold nothing that
belongs only in an uncommitted <env>.local.conf."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from serena import tables
from serena.config import Settings

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"

# Names in the deployment that aren't Serena's settings (none now: SERENA_SIMULATED_CSPACE became one).
NOT_SETTINGS: set[str] = set()


def test_terraform_creates_the_tables_the_code_defines() -> None:
    """After changing a table: python -m serena.tables > ../deploy/terraform/modules/core/tables.json"""
    assert (DEPLOY / "terraform" / "modules" / "core" / "tables.json").read_text() == tables.as_json()


def test_every_setting_the_deployment_gives_is_one_serena_reads() -> None:
    """A misspelt SERENA_ name in the task definitions or the image would be ignored silently."""
    terraform = DEPLOY / "terraform"
    roots_and_modules = ("personal/*.tf", "shared/*.tf", "modules/*/*.tf")
    tf_files = sorted(f for pattern in roots_and_modules for f in terraform.glob(pattern))
    sources = [*tf_files, DEPLOY / "Dockerfile"]
    names = {name for source in sources for name in re.findall(r"\bSERENA_[A-Z0-9_]+\b", source.read_text())}
    assert names, "no settings found: has the deployment moved?"
    fields = {f"SERENA_{field.upper()}" for field in Settings.model_fields}
    assert sorted(names - fields - NOT_SETTINGS) == []


ENVIRONMENTS = DEPLOY / "environments"


def committed_settings_files() -> list[Path]:
    """deploy/environments/*.conf, but not a developer's uncommitted <env>.local.conf (git ignores those)."""
    return sorted(f for f in ENVIRONMENTS.glob("*.conf") if not f.name.endswith(".local.conf"))


def test_the_default_environment_is_personal_dev_with_the_simulator() -> None:
    """./serena aws with no --env and no SERENA_AWS_ENV deploys personal-dev, which runs only the simulator."""
    aws_sh = (DEPLOY / "aws.sh").read_text()
    assert re.search(r'^ENV="\$\{SERENA_AWS_ENV:-personal-dev\}"$', aws_sh, re.MULTILINE)
    settings = (ENVIRONMENTS / "personal-dev.conf").read_text()
    assert re.search(r"^SIMULATED_CSPACE=true\b", settings, re.MULTILINE)
    assert re.search(r"^PROTECT_DATA=false\b", settings, re.MULTILINE)


# What belongs only in the uncommitted <env>.local.conf (the repository is public). Placeholders such as "vpc-..." pass.
NOT_IN_COMMITTED_SETTINGS = {
    "an account number": re.compile(r"(?<!\d)\d{12}(?!\d)"),
    "an IPv4 address or range": re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?(?![\d.])"),
    "an email address": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "a VPC or subnet ID": re.compile(r"\b(?:vpc|subnet)-[0-9a-f]{8,17}\b"),
}


def test_no_committed_settings_file_holds_what_belongs_in_its_local_conf() -> None:
    files = committed_settings_files()
    assert {f.name for f in files} >= {"personal-dev.conf", "ucb-stage1.conf", "ucb-stage2.conf"}
    found = [
        f"{f.name}:{number}: {what}"
        for f in files
        for number, line in enumerate(f.read_text().splitlines(), start=1)
        for what, pattern in NOT_IN_COMMITTED_SETTINGS.items()
        if pattern.search(line)
    ]
    assert found == []


def test_the_settings_check_finds_what_it_looks_for() -> None:
    """The patterns above match real values and leave the placeholders alone. The values here are made up: the
    addresses from the documentation ranges (RFC 5737) and a reserved domain."""
    caught = [
        f'ACCOUNT_ID="{"0" * 12}"',
        'ALLOWED_CIDRS="192.0.2.0/24"',
        "ETL_CIDRS=198.51.100.7",
        "ALERT_EMAIL=someone@example.edu",
        "VPC_ID=vpc-0abc1234",
        'APP_SUBNET_IDS="subnet-0123456789abcdef0"',
    ]
    passed = ["#   VPC_ID=vpc-...", 'APP_SUBNET_IDS="subnet-...,subnet-..."', "AWS_REGION=us-west-2", "WEB_COUNT=2"]
    for line in caught:
        assert any(p.search(line) for p in NOT_IN_COMMITTED_SETTINGS.values()), line
    for line in passed:
        assert not any(p.search(line) for p in NOT_IN_COMMITTED_SETTINGS.values()), line


def shell_words(aws_sh: str, variable: str) -> set[str]:
    """The words of a "VARIABLE=..." list in deploy/aws.sh, which may continue over several lines."""
    match = re.search(rf'^{variable}="([^"]*)"', aws_sh, re.MULTILINE)
    assert match, f"{variable} isn't in deploy/aws.sh"
    return set(match.group(1).split())


def test_every_setting_is_either_in_ssm_or_in_the_files() -> None:
    """With SETTINGS=ssm (D273), load_env reads every setting from SSM but the few that say how to reach the account:
    a new setting must be listed in SSM_SETTINGS or FILE_SETTINGS, or a pipeline environment would never get it.
    PIPELINE_SETTINGS are in SSM only, written by ./serena aws pipeline, never by settings push (DP11)."""
    aws_sh = (DEPLOY / "aws.sh").read_text()
    in_ssm, in_files = shell_words(aws_sh, "SSM_SETTINGS"), shell_words(aws_sh, "FILE_SETTINGS")
    in_pipeline = shell_words(aws_sh, "PIPELINE_SETTINGS")
    assert in_ssm & in_files == in_ssm & in_pipeline == in_files & in_pipeline == set()
    load_env = aws_sh[aws_sh.index("load_env() {") :]
    resets = load_env[: load_env.index('. "$CONF"')]  # what load_env empties before reading the files
    started_empty = set(re.findall(r'\b([A-Z][A-Z0-9_]+)=""', resets))
    assert started_empty == (in_ssm | in_files | in_pipeline) - {"AWS_PROFILE", "AWS_REGION", "SERENA_ENV_NAME"}
    set_in_committed_files = {
        name
        for f in committed_settings_files()
        for name in re.findall(r"^([A-Z][A-Z0-9_]+)=", f.read_text(), re.MULTILINE)
    }
    assert sorted(set_in_committed_files - in_ssm - in_files) == []


def test_the_pipeline_installs_the_terraform_ci_uses() -> None:
    """DP17: the buildspecs install Terraform at CI's version (Dependabot reads neither), and both the same one."""
    ci = (DEPLOY.parent / ".github" / "workflows" / "ci.yml").read_text()
    ci_version = re.search(r'terraform_version: "([0-9.]+)"', ci)
    assert ci_version
    pins = set()
    for mode in ("plan", "apply"):
        buildspec = (DEPLOY / "pipeline" / f"buildspec-{mode}.yml").read_text()
        version = re.search(r'TERRAFORM_VERSION: "([0-9.]+)"', buildspec)
        sha = re.search(r'TERRAFORM_SHA256: "([0-9a-f]{64})"', buildspec)
        assert version and sha, f"buildspec-{mode}.yml pins Terraform's version and SHA256"
        assert version.group(1) == ci_version.group(1), f"buildspec-{mode}.yml installs CI's Terraform"
        pins.add((version.group(1), sha.group(1)))
    assert len(pins) == 1


def test_aws_sh_never_pipes_a_command_into_grep_q() -> None:
    """deploy/aws.sh runs with pipefail. "cmd | grep -q" then fails at random when grep stops at its first match while
    cmd is still writing (SIGPIPE): ./serena aws pipeline once took the pipeline's own OIDC provider for the account's
    and planned to destroy it (November 5, 2026). Read the output into a variable and search that. An echo of one
    value is the exception: it has written everything before grep reads."""
    aws_sh = (DEPLOY / "aws.sh").read_text()
    assert re.search(r"^set -euo pipefail$", aws_sh, re.MULTILINE)
    code = re.sub(r"^\s*#.*$", "", aws_sh, flags=re.MULTILINE)  # comments may name the pattern
    pipes = re.finditer(r"([^\n|]*)\|\s*(?:\\\n)?\s*grep -[A-Za-z]*q", code)
    offenders = [m.group(0).strip() for m in pipes if not m.group(1).strip().startswith("echo ")]
    assert offenders == []


GITHUB_PROVIDER = "arn:aws:iam::111111111111:oidc-provider/token.actions.githubusercontent.com"
# A fake terraform state list and aws iam list-open-id-connect-providers for oidc_provider_create. STATE: none, as for
# a root never applied; broken, as for a state that can't be read; otherwise the state's resources. PROVIDERS: the
# account's OIDC providers, or "fail".
OIDC_FAKES = """set -euo pipefail
ENV=ucb-prod
die() { echo "$*" >&2; exit 1; }
tf() {
  case "$STATE" in
    none) echo "No state file was found!" >&2; return 1 ;;
    broken) echo "Error: Failed to load state: AccessDenied" >&2; return 1 ;;
    *) echo "$STATE" ;;
  esac
}
aws_() { echo called > "$CALLED"; [ "$PROVIDERS" != fail ] || return 255; echo "$PROVIDERS"; }
"""


def oidc_provider_create(tmp_path: Path, state: str, providers: str = "") -> subprocess.CompletedProcess[str]:
    """Runs deploy/aws.sh's oidc_provider_create as pipeline_root does, with a fake terraform and AWS CLI."""
    function = shell_function((DEPLOY / "aws.sh").read_text(), "oidc_provider_create")
    script = f'{OIDC_FAKES}{function}\ncreate="$(oidc_provider_create)" || exit 1\necho "create=$create"\n'
    env = {**os.environ, "STATE": state, "PROVIDERS": providers, "CALLED": str(tmp_path / "aws-called")}
    # The function is this repository's own deploy/aws.sh, not outside input.
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)  # noqa: S603, S607


@pytest.mark.parametrize(("providers", "create"), [("", "true"), (GITHUB_PROVIDER, "false")])
def test_a_root_never_applied_has_no_state_yet_and_holds_no_provider(
        tmp_path: Path, providers: str, create: str) -> None:
    """terraform state list fails with "No state file was found!" before a root's first apply (the BMU's checklist,
    November 14, 2026): the pipeline's root holds nothing, so it makes the provider only where the account has none."""
    result = oidc_provider_create(tmp_path, "none", providers)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"create={create}\n"


def test_a_provider_the_pipelines_state_holds_stays_its_own(tmp_path: Path) -> None:
    result = oidc_provider_create(tmp_path, "aws_iam_openid_connect_provider.github[0]\naws_iam_role.plan",
                                  GITHUB_PROVIDER)
    assert result.stdout == "create=true\n"


def test_a_state_that_cant_be_read_stops_before_anything_is_planned(tmp_path: Path) -> None:
    result = oidc_provider_create(tmp_path, "broken")
    assert result.returncode == 1
    assert result.stderr == ("Couldn't read the pipeline's Terraform state (terraform state list) for 'ucb-prod'. "
                             "Nothing was changed.\n")
    assert not (tmp_path / "aws-called").exists()
    pipeline_root = shell_function((DEPLOY / "aws.sh").read_text(), "pipeline_root")
    assert 'create="$(oidc_provider_create)" || exit 1' in pipeline_root  # before it plans anything


def test_oidc_providers_that_cant_be_listed_stop(tmp_path: Path) -> None:
    """Called in $(…) || exit 1, where set -e doesn't apply: a failed list would otherwise read as "the account has
    none", and Terraform would plan a second provider, which IAM refuses."""
    result = oidc_provider_create(tmp_path, "none", "fail")
    assert result.returncode == 1
    assert result.stderr == "Couldn't list the account's OIDC providers. Nothing was changed.\n"


def github_environment_check() -> str:
    """The Python that ./serena aws pipeline runs on a GitHub environment's rules (check_github_environments)."""
    aws_sh = (DEPLOY / "aws.sh").read_text()
    body = aws_sh[aws_sh.index("check_github_environments() {") :]
    return body[body.index("python3 -c '") + len("python3 -c '") : body.index("' <<<\"$json\"")]


@pytest.mark.parametrize(
    ("real", "allow", "prevent", "refused"),
    [
        ("true", "false", False, True),  # real data: self-review only with ALLOW_SELF_REVIEW (D308)
        ("true", "true", False, False),
        ("true", "false", True, False),
        ("false", "false", False, False),  # the simulator only (DP13)
    ],
)
def test_self_review_needs_allow_self_review_where_there_is_real_data(
    real: str, allow: str, prevent: bool, refused: bool
) -> None:
    rules = {"protection_rules": [{"type": "required_reviewers", "prevent_self_review": prevent,
                                   "reviewers": [{"type": "User"}]}],
             "deployment_branch_policy": {"custom_branch_policies": True}}
    env = {**os.environ, "NAME": "ucb-stage2", "ENVIRONMENT": "ucb-stage2", "REAL": real, "ALLOW": allow,
           "CONF": "ucb-stage2.conf", "BRANCHES": json.dumps({"branch_policies": [{"name": "main", "type": "branch"}]})}
    # The program is this repository's own deploy/aws.sh, not outside input.
    result = subprocess.run([sys.executable, "-c", github_environment_check()],  # noqa: S603
                            input=json.dumps(rules), env=env, capture_output=True, text=True, check=True)
    assert ("Prevent self-review" in result.stdout) is refused


def test_only_qa_and_dev_settings_files_allow_self_review() -> None:
    """D308: ALLOW_SELF_REVIEW=true never in a production environment's committed settings."""
    allowed = {f.name for f in committed_settings_files() if re.search(r"^ALLOW_SELF_REVIEW=true", f.read_text(), re.M)}
    assert not {name for name in allowed if "prod" in name.lower()}


def committed_setting(conf: Path, name: str) -> str | None:
    values = re.findall(rf"^{name}=\"?([^\"\s#]*)", conf.read_text(), re.MULTILINE)
    return values[-1] if values else None


def test_production_is_protected_from_its_first_deploy() -> None:
    """ucb-prod holds real data from its first deploy: the pipeline deploys it (settings in SSM), its data is protected,
    and it takes only a commit already deployed to its pre-production environment, which exists."""
    conf = ENVIRONMENTS / "ucb-prod.conf"
    expected = {"SETTINGS": "ssm", "TERRAFORM_ROOT": "shared", "SIMULATED_CSPACE": "false", "PROTECT_DATA": "true",
                "WAF": "true", "WEB_COUNT": "2", "ALLOW_SELF_REVIEW": None}
    assert {name: committed_setting(conf, name) for name in expected} == expected
    pre = committed_setting(conf, "PREPRODUCTION")
    assert pre and pre != "ucb-prod" and (ENVIRONMENTS / f"{pre}.conf").is_file()


def test_every_environment_the_deploy_workflow_offers_has_a_settings_file() -> None:
    workflow = (DEPLOY.parent / ".github" / "workflows" / "deploy.yml").read_text()
    options = re.search(r"^\s+options: \[([^\]]*)\]", workflow, re.MULTILINE)
    assert options
    offered = {name.strip() for name in options.group(1).split(",")}
    assert "ucb-prod" in offered
    assert offered <= {f.stem for f in committed_settings_files()}


def test_the_deploy_workflow_checks_pre_production_before_anything_else() -> None:
    """The check runs in a job with no GitHub environment and no AWS sign-in, and the plan job waits for it."""
    workflow = (DEPLOY.parent / ".github" / "workflows" / "deploy.yml").read_text()
    job = workflow[workflow.index("  preproduction:") : workflow.index("  plan:")]
    assert "deploy/pipeline/check-preproduction.sh" in job
    assert "environment:" not in job and "id-token" not in job and "configure-aws-credentials" not in job
    plan = workflow[workflow.index("  plan:") : workflow.index("  apply:")]
    assert re.search(r"^    needs: preproduction$", plan, re.MULTILINE)


# A fake gh for check-preproduction.sh: the deployments' latest states in STATES (comma-separated, "-" for a
# deployment with no status yet), its calls appended to CALLED.
FAKE_GH = """#!/usr/bin/env bash
echo "$*" >>"$CALLED"
case "$2" in
  repos/*/deployments\\?*) i=0; IFS=, read -ra states <<<"$STATES"
    for s in "${states[@]}"; do [ -n "$s" ] && echo "https://api.example.test/statuses/$i/$s"; i=$((i + 1)); done ;;
  https://api.example.test/statuses/*) s="${2%%\\?*}"; s="${s##*/}"; [ "$s" = - ] && echo "" || echo "$s" ;;
  *) exit 1 ;;
esac
"""
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def check_preproduction(tmp_path: Path, environment: str, states: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FAKE_GH)
    (bin_dir / "gh").chmod(0o755)
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "ENVIRONMENT": environment, "COMMIT": COMMIT,
           "REPOSITORY": "owner/repo", "STATES": states, "CALLED": str(tmp_path / "called"),
           "GITHUB_STEP_SUMMARY": str(tmp_path / "summary")}
    # The program is this repository's own script, not outside input.
    return subprocess.run([str(DEPLOY / "pipeline" / "check-preproduction.sh")],  # noqa: S603
                          cwd=DEPLOY.parent, env=env, capture_output=True, text=True, check=False)


@pytest.mark.parametrize(
    ("states", "allowed"),
    [
        ("success", True),
        ("failure,success", True),  # a later run at the same commit failed: it was still deployed once
        ("", False),  # never deployed there
        ("failure", False),
        ("waiting,queued,-", False),  # waiting for its reviewer, or not started
        ("in_progress", False),
    ],
)
def test_production_takes_only_a_commit_deployed_to_pre_production(
        tmp_path: Path, states: str, allowed: bool) -> None:
    result = check_preproduction(tmp_path, "ucb-prod", states)
    assert (result.returncode == 0) is allowed, result.stderr
    pre = committed_setting(ENVIRONMENTS / "ucb-prod.conf", "PREPRODUCTION")
    first_call = (tmp_path / "called").read_text().splitlines()[0]
    assert f"sha={COMMIT}&environment={pre}&" in first_call
    assert ("Refused" in (tmp_path / "summary").read_text()) is not allowed


def test_an_environment_without_pre_production_takes_any_commit(tmp_path: Path) -> None:
    result = check_preproduction(tmp_path, "ucb-stage2", "")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "called").exists()


@pytest.mark.parametrize(
    ("committed", "local", "refusal"),
    [
        ("PREPRODUCTION=qa", "", None),
        ("PREPRODUCTION=prod", "", "must name another environment"),  # itself
        ("PREPRODUCTION=nowhere", "", "must name another environment"),
        ("", "PREPRODUCTION=qa", "goes only in"),  # the workflow reads only the committed file
    ],
)
def test_preproduction_is_another_environment_named_in_the_committed_file(
        tmp_path: Path, committed: str, local: str, refusal: str | None) -> None:
    (tmp_path / "qa.conf").write_text("AWS_PROFILE=p\nAWS_REGION=us-west-2\nSERENA_ENV_NAME=qa\n")
    (tmp_path / "prod.conf").write_text(f"AWS_PROFILE=p\nAWS_REGION=us-west-2\nSERENA_ENV_NAME=prod\n{committed}\n")
    if local:
        (tmp_path / "prod.local.conf").write_text(local + "\n")
    load_env = shell_function((DEPLOY / "aws.sh").read_text(), "load_env")
    # Stops just after the PREPRODUCTION checks: the rest of load_env needs the account.
    script = (f'die() {{ echo "die: $*"; exit 1; }}\nENV_DIR="{tmp_path}"; ENV=prod; CMD=settings\n'
              + load_env.replace('  : "${AWS_PROFILE:?', '  echo checked; return 0\n  : "${AWS_PROFILE:?', 1)
              + "\nload_env\n")
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)  # noqa: S603, S607
    if refusal:
        assert result.returncode == 1 and refusal in result.stdout
    else:
        assert result.returncode == 0 and "checked" in result.stdout, result.stdout + result.stderr


@pytest.mark.parametrize("environment", ["../ucb-prod", "UCB-PROD", "no-such-environment"])
def test_the_pre_production_check_refuses_a_name_that_isnt_an_environment(tmp_path: Path, environment: str) -> None:
    assert check_preproduction(tmp_path, environment, "success").returncode != 0


def shell_function(aws_sh: str, name: str) -> str:
    """One function of deploy/aws.sh, from its "name() {" line to the closing brace at the start of a line."""
    match = re.search(rf"^{name}\(\) {{.*?^}}$|^{name}\(\) {{[^\n]*}}$", aws_sh, re.MULTILINE | re.DOTALL)
    assert match, f"{name} isn't in deploy/aws.sh"
    return match.group(0)


SIMULATOR = "pahma=http://fakecspace.serena-stage2.internal:8180/pahma"
QA, PRODUCTION = "pahma=https://pahma.qa.collectionspace.org", "pahma=https://pahma.collectionspace.org"


@pytest.mark.parametrize(
    ("deployed", "now", "stops"),
    [
        (SIMULATOR, QA, False),  # the simulator's records are synthetic
        (QA, PRODUCTION, True),  # one real server to another: Serena's data refers to the first
        (QA, QA, False),
        (QA, SIMULATOR, True),
    ],
)
def test_a_museum_may_move_only_from_the_simulator(deployed: str, now: str, stops: bool) -> None:
    aws_sh = (DEPLOY / "aws.sh").read_text()
    functions = "\n".join(shell_function(aws_sh, f) for f in ("museum_names", "server_of", "sim_url", "check_museums"))
    script = f"""set -euo pipefail
die() {{ echo "STOPPED: $*"; exit 3; }}
applied() {{ echo "$DEPLOYED"; }}
ENV=ucb-stage2 NAME=serena-stage2 LOCAL=ucb-stage2.local.conf PROTECT_DATA=true IN_BUILD=true MUSEUMS="$NOW"
{functions}
check_museums look
echo CHECKED
"""
    env = {**os.environ, "DEPLOYED": deployed, "NOW": now}
    # The script is this repository's own deploy/aws.sh, not outside input.
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)  # noqa: S603, S607
    assert ("STOPPED" in result.stdout) is stops
    assert ("CHECKED" in result.stdout) is not stops


def policy_statements(document: str) -> list[tuple[list[str], str]]:
    """The statements of one aws_iam_policy_document in modules/core/iam.tf: each one's actions and resources."""
    iam = (DEPLOY / "terraform" / "modules" / "core" / "iam.tf").read_text()
    match = re.search(rf'^data "aws_iam_policy_document" "{document}" {{.*?^}}$', iam, re.MULTILINE | re.DOTALL)
    assert match, f"the {document} policy isn't in modules/core/iam.tf"
    statements = []
    for body in re.findall(r"^  statement {(.*?)^  }$", match.group(0), re.MULTILINE | re.DOTALL):
        actions = re.search(r"actions\s*=\s*\[(.*?)\]", body, re.DOTALL)
        resources = re.search(r"resources\s*=\s*(.+)", body)
        statements.append((re.findall(r'"([^"]+)"', actions.group(1)) if actions else [],
                           resources.group(1).strip() if resources else ""))
    return statements


@pytest.mark.parametrize("role", ["web", "worker"])
def test_web_and_worker_can_read_stored_etl_lists(role: str) -> None:
    """The worker checks and applies each stored ETL list; the web task's Manual refresh dry run reads the last updated
    refresh's list to compare with. Moto doesn't enforce IAM, so only this catches a missing grant before AWS does."""
    assert any("s3:GetObject" in actions and resources == "local.servable_list_arn"
               for actions, resources in policy_statements(role))


SAMPLE_AWS_CONFIG = """\
[profile admin-sso]
sso_session = campus
sso_account_id = 111111111111
sso_role_name = Developer

[sso-session campus]
sso_start_url = https://example.awsapps.com/start
sso_region = us-west-2

[profile deployer]
role_arn = arn:aws:iam::111111111111:role/deployer
source_profile = admin-sso

[profile old-style]
sso_start_url = https://example.awsapps.com/start
sso_region = us-west-2
sso_account_id = 111111111111
sso_role_name = Developer

[profile old-style-deployer]
role_arn = arn:aws:iam::111111111111:role/deployer
source_profile = old-style
"""


@pytest.mark.skipif(not shutil.which("aws"), reason="needs the AWS CLI, which reads the sample configuration")
@pytest.mark.parametrize(("profile", "hint"), [
    ("deployer", "aws sso login --sso-session campus"),  # a role through a profile on an SSO session (UC Berkeley's)
    ("admin-sso", "aws sso login --sso-session campus"),
    ("old-style-deployer", "aws sso login --profile old-style"),  # a role through a profile with its own SSO settings
    ("old-style", "aws sso login --profile old-style"),
    ("missing", "aws sso login --profile missing"),
    ("", "aws sso login --profile <profile>"),  # no profile: the pipeline's builds
])
def test_the_sign_in_hint_names_what_signs_in(tmp_path: Path, profile: str, hint: str) -> None:
    """aws.sh's "Not signed in" message: aws sso login --profile fails for a profile that takes a role from another."""
    script = (DEPLOY / "aws.sh").read_text()
    functions = ""
    for name in ("sso_profile", "sign_in_hint"):
        found = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", script, re.S | re.M)
        assert found, f"deploy/aws.sh has no {name} function"
        functions += found.group(0)
    (tmp_path / "config").write_text(SAMPLE_AWS_CONFIG)
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "AWS_PROFILE": profile,
           "AWS_CONFIG_FILE": str(tmp_path / "config"), "AWS_SHARED_CREDENTIALS_FILE": str(tmp_path / "credentials")}
    # The function is this repository's own deploy/aws.sh, not outside input.
    out = subprocess.run(["bash", "-c", f"{functions}\nsign_in_hint"],  # noqa: S603, S607
                         env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == hint


def _sso_cache(home: Path, key: str, expires: str) -> None:
    """A made-up SSO token file, named as the SDKs' SSO token provider names it."""
    cache = home / ".aws" / "sso" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(key.encode()).hexdigest()  # noqa: S324 (the SDKs' file name, not a security use)
    (cache / f"{name}.json").write_text(json.dumps({"accessToken": "made-up", "expiresAt": expires}))


@pytest.mark.skipif(not shutil.which("aws"), reason="needs the AWS CLI, which reads the sample configuration")
@pytest.mark.parametrize(("profile", "token", "signed_in"), [
    ("deployer", None, False),  # the role's credentials still cached by the CLI, the SSO token gone (aws sso logout)
    ("deployer", ("campus", "2000-01-01T00:00:00Z"), False),  # expired
    ("deployer", ("campus", "2999-01-01T00:00:00Z"), True),
    ("admin-sso", ("campus", "2999-01-01T00:00:00UTC"), True),
    ("old-style-deployer", None, False),
    ("old-style-deployer", ("https://example.awsapps.com/start", "2999-01-01T00:00:00Z"), True),
    ("", None, True),  # no profile: the pipeline's builds have no SSO token
])
def test_signing_in_needs_the_sso_token_terraform_reads(
        tmp_path: Path, profile: str, token: tuple[str, str] | None, signed_in: bool) -> None:
    """sts get-caller-identity passes on the CLI's cached role credentials after aws sso logout; Terraform doesn't."""
    script = (DEPLOY / "aws.sh").read_text()
    functions = ""
    for name in ("die", "aws_", "sso_profile", "sign_in_hint", "sso_token_valid", "signed_in_account"):
        found = re.search(rf"^{name}\(\) \{{(?: .*?\}}\n|\n.*?^\}}\n)", script, re.S | re.M)
        assert found, f"deploy/aws.sh has no {name} function"
        functions += found.group(0)
    (tmp_path / "config").write_text(SAMPLE_AWS_CONFIG)
    real_aws = shutil.which("aws")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # A fake aws: sts answers as if the CLI still held the role's credentials; everything else is the real CLI.
    (bin_dir / "aws").write_text(f'#!/bin/bash\ncase " $* " in *" sts get-caller-identity "*) echo 111111111111 ;;'
                                 f' *) exec "{real_aws}" "$@" ;; esac\n')
    (bin_dir / "aws").chmod(0o755)
    if token:
        _sso_cache(tmp_path, *token)
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path), "AWS_PROFILE": profile,
           "AWS_REGION": "us-west-2", "AWS_CONFIG_FILE": str(tmp_path / "config"),
           "AWS_SHARED_CREDENTIALS_FILE": str(tmp_path / "credentials")}
    # The functions are this repository's own deploy/aws.sh, not outside input.
    out = subprocess.run(["bash", "-c", f"ENV=test\n{functions}\nsigned_in_account"],  # noqa: S603, S607
                         env=env, capture_output=True, text=True, check=False)
    if signed_in:
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == "111111111111"
    else:
        assert out.returncode == 1
        assert out.stderr.startswith("Not signed in to AWS for 'test'. Run: aws sso login --")
        assert "made-up" not in out.stdout + out.stderr


# ---- settings set, pull and push (SSM is the settings' one copy, decided November 20, 2026), in one document
# (decided November 22, 2026). The settings functions of deploy/aws.sh, run against a stand-in SSM: one file per
# parameter under $SSM_DIR (its name is the path), versions under $SSM_DIR.version, writes logged in $SSM_DIR.log.
# FAKE_SSM_FAIL=describe or value makes that read fail, as a refused or throttled one does.
FAKE_SSM = r"""
arg() {  # arg OPTION ARGS...: the value after OPTION
  local want="$1"; shift
  while [ $# -gt 0 ]; do [ "$1" != "$want" ] || { printf '%s' "$2"; return 0; }; shift; done
}
aws_() {
  local a take=false first name
  case "$*" in
    "ssm describe-parameters"*) [ "${FAKE_SSM_FAIL:-}" != describe ] || { echo "ThrottlingException" >&2; return 254; }
      local path; path="$(arg --parameter-filters "$@")"; path="${path##*Values=}"
      ls "$SSM_DIR$path" 2>/dev/null | sed "s|^|$path/|" | paste -s -d '\t' - ;;
    "ssm get-parameters"*) first="$(arg --names "$@")"
      case "$(arg --query "$@")" in
        'Parameters[0].Value') [ "${FAKE_SSM_FAIL:-}" != value ] || { echo "ThrottlingException" >&2; return 254; }
          if [ -f "$SSM_DIR$first" ]; then cat "$SSM_DIR$first"; echo; else echo None; fi ;;
        'Parameters[0].Version') cat "$SSM_DIR.version$first" 2>/dev/null || echo None ;;
        *) for a in "$@"; do case "$a" in --names) take=true ;; --*) take=false ;;
             *) [ "$take" = false ] || [ ! -f "$SSM_DIR$a" ] || printf '%s\t%s\n' "$a" "$(cat "$SSM_DIR$a")" ;;
           esac; done ;;
      esac ;;
    "ssm put-parameter"*) name="$(arg --name "$@")"
      mkdir -p "$(dirname "$SSM_DIR$name")" "$(dirname "$SSM_DIR.version$name")"
      printf '%s' "$(arg --value "$@")" > "$SSM_DIR$name"
      echo $(( $(cat "$SSM_DIR.version$name" 2>/dev/null || echo 0) + 1 )) > "$SSM_DIR.version$name"
      echo "put $name" >> "$SSM_DIR.log" ;;
    "ssm delete-parameter"*) name="$(arg --name "$@")"; rm -f "$SSM_DIR$name"; echo "delete $name" >> "$SSM_DIR.log" ;;
    "ssm add-tags-to-resource"*) echo "tag $(arg --resource-id "$@") $(arg --tags "$@")" >> "$SSM_DIR.log" ;;
    *) echo "unexpected: aws $*" >&2; return 1 ;;
  esac
}
die() { echo "$*" >&2; exit 1; }
signed_in_account() { echo 111122223333; }
signed_in_as() { echo "Profile p"; }
"""
SETTINGS_FUNCTIONS = ("is_ssm_setting", "is_pipeline_setting", "settings_path", "settings_doc", "settings_home",
                      "ssm_param_names", "not_pipeline_params", "settings_store", "settings_where", "read_settings_doc",
                      "settings_doc_version", "settings_doc_lines", "read_param", "pipeline_settings_lines",
                      "ssm_settings", "setting_in", "has_line", "write_settings_doc", "settings_doc_header",
                      "set_in_settings_doc", "not_migrated", "put_setting", "save_local", "from_ssm",
                      "settings_in_files_only", "settings_set", "settings_pull", "settings_push", "settings_migrate",
                      "settings_show")
DOC = "/serena-t/settings/all"


def run_settings(tmp_path: Path, body: str, answers: str = "y\n", files: dict[str, str] | None = None,
                 ssm_values: dict[str, str] | None = None, doc: str | None = None, fail: str = "",
                 cmd: str = "settings") -> subprocess.CompletedProcess[str]:
    """body runs after the settings are loaded from the files (as load_env leaves them for ./serena aws settings).
    ssm_values are parameters of their own (one per setting, from before the document, or REAL_DATA_ACCOUNT); doc is
    the settings document's text."""
    aws_sh = (DEPLOY / "aws.sh").read_text()
    lists = "".join(re.search(rf'^{v}="[^"]*"$', aws_sh, re.MULTILINE | re.DOTALL).group(0) + "\n"  # type: ignore[union-attr]
                    for v in ("SSM_SETTINGS", "FILE_SETTINGS", "PIPELINE_SETTINGS"))
    lists += re.search(r"^SETTINGS_DOC_MAX=\d+", aws_sh, re.MULTILINE).group(0) + "\n"  # type: ignore[union-attr]
    functions = "\n".join(shell_function(aws_sh, name) for name in SETTINGS_FUNCTIONS)
    tmp_path.mkdir(parents=True, exist_ok=True)
    conf, local = tmp_path / "t.conf", tmp_path / "t.local.conf"
    conf.write_text("AWS_PROFILE=p\nAWS_REGION=us-west-2\nSERENA_ENV_NAME=t\nSETTINGS=ssm\nWEB_COUNT=2\n")
    local.write_text("".join(f'{k}="{v}"\n' for k, v in (files or {}).items()))
    ssm_dir = tmp_path / "ssm"
    for key, value in (ssm_values or {}).items():
        (ssm_dir / "serena-t" / "settings").mkdir(parents=True, exist_ok=True)
        (ssm_dir / "serena-t" / "settings" / key).write_text(value)
    if doc is not None:
        set_doc(tmp_path, doc)
    script = (FAKE_SSM + lists + functions + f'\nCONF="{conf}"; LOCAL="{local}"; ENV=t; NAME=serena-t; CMD={cmd}\n'
              f'SETTINGS=ssm; ACCOUNT_ID=""; . "$CONF"; . "$LOCAL"\n' + body + "\n")
    env = {**os.environ, "SSM_DIR": str(ssm_dir), "FAKE_SSM_FAIL": fail}
    return subprocess.run(["bash", "-c", script], input=answers, env=env,  # noqa: S603, S607
                          capture_output=True, text=True, check=False)


def set_doc(tmp_path: Path, text: str) -> None:
    """Ops saves the settings document in the console: its text, and the version goes up."""
    path = tmp_path / "ssm" / "serena-t" / "settings" / "all"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    version = tmp_path / "ssm.version" / "serena-t" / "settings" / "all"
    version.parent.mkdir(parents=True, exist_ok=True)
    version.write_text(str(int(version.read_text()) + 1 if version.exists() else 1) + "\n")


def doc_text(tmp_path: Path) -> str:
    return (tmp_path / "ssm" / "serena-t" / "settings" / "all").read_text()


def doc_of(values: dict[str, str]) -> str:
    return "# Serena's settings, written by a test\n" + "".join(f'{k}="{v}"\n' for k, v in values.items())


def ssm_now(tmp_path: Path) -> dict[str, str]:
    """The settings in the stand-in SSM: the document's lines, and the parameters beside it."""
    root = tmp_path / "ssm" / "serena-t" / "settings"
    if not root.exists():
        return {}
    settings = {p.name: p.read_text() for p in root.iterdir() if p.name != "all"}
    if (root / "all").exists():
        for line in doc_text(tmp_path).splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                settings[key.strip()] = value.strip().strip('"')
    return settings


def ssm_log(tmp_path: Path) -> list[str]:
    log = tmp_path / "ssm.log"
    return log.read_text().splitlines() if log.exists() else []


IN_SSM = {"ACCOUNT_ID": "111122223333", "ALLOWED_CIDRS": "203.0.113.7/32", "ENV_LABEL": "Set by Ops", "WEB_COUNT": "2"}
HERE = {"ACCOUNT_ID": "111122223333", "ALLOWED_CIDRS": "203.0.113.7/32", "ENV_LABEL": "Old label"}


def test_settings_push_writes_a_new_environments_settings_as_one_document(tmp_path: Path) -> None:
    result = run_settings(tmp_path, "settings_push", files=HERE, ssm_values={"REAL_DATA_ACCOUNT": "111122223333"})
    assert result.returncode == 0, result.stderr
    assert f"From {tmp_path}/t.conf and {tmp_path}/t.local.conf to {DOC}" in result.stdout
    root = tmp_path / "ssm" / "serena-t" / "settings"
    assert sorted(p.name for p in root.iterdir()) == ["REAL_DATA_ACCOUNT", "all"]
    text = doc_text(tmp_path)
    assert text.startswith("# Serena's settings for 't' (account 111122223333).")
    assert 'ENV_LABEL="Old label"' in text.splitlines() and 'WEB_COUNT="2"' in text.splitlines()
    assert ssm_log(tmp_path) == [f"put {DOC}", f"tag {DOC} Key=project,Value=serena"]


def test_settings_push_only_adds(tmp_path: Path) -> None:
    """SSM is the settings' one copy (Ops may change one in the console): a push from files that may be out of date
    adds what SSM doesn't have, and leaves what it has as it is, naming set and pull."""
    result = run_settings(tmp_path, "settings_push", files={**HERE, "VPC_ID": "vpc-0abc"}, doc=doc_of(IN_SSM))
    assert result.returncode == 0, result.stderr
    assert "  ENV_LABEL=Set by Ops   (the files here: Old label)" in result.stdout
    assert "settings set --env t" in result.stdout and "settings pull --env t" in result.stdout
    assert "  + VPC_ID=vpc-0abc" in result.stdout and "ENV_LABEL=Old" not in result.stdout.split("+", 1)[1]
    assert ssm_now(tmp_path) == {**IN_SSM, "VPC_ID": "vpc-0abc"}
    again = run_settings(tmp_path, "settings_push", files={**HERE, "VPC_ID": "vpc-0abc"})
    assert again.returncode == 0 and "Nothing to add" in again.stdout


def test_settings_push_leaves_a_setting_set_to_nothing_on_purpose(tmp_path: Path) -> None:
    """A line Ops set to "" is a value: push doesn't fill it in from the files here."""
    result = run_settings(tmp_path, "settings_push", files=HERE, doc=doc_of({**IN_SSM, "ENV_LABEL": ""}))
    assert result.returncode == 0, result.stderr
    assert "  + ENV_LABEL" not in result.stdout and 'ENV_LABEL=""' in doc_text(tmp_path)


def test_set_changes_one_line_and_keeps_the_comments(tmp_path: Path) -> None:
    """Ops changed ENV_LABEL and added a comment; a developer whose files still have the old label sets
    ALLOWED_CIDRS. Only that line changes, in SSM and in the files here, after asking."""
    doc = doc_of(IN_SSM) + "# Ops: the VPN range is the second one\n"
    result = run_settings(tmp_path, "settings_set ALLOWED_CIDRS 198.51.100.0/24", answers="n\n", files=HERE, doc=doc)
    assert result.returncode == 1 and doc_text(tmp_path) == doc
    assert f"In SSM, account 111122223333, the document {DOC}:" in result.stdout
    assert "  ~ ALLOWED_CIDRS=198.51.100.0/24 (was 203.0.113.7/32)" in result.stdout
    result = run_settings(tmp_path, "settings_set ALLOWED_CIDRS 198.51.100.0/24", files=HERE)
    assert result.returncode == 0, result.stderr
    assert ssm_now(tmp_path) == {**IN_SSM, "ALLOWED_CIDRS": "198.51.100.0/24"}
    assert "# Ops: the VPN range is the second one" in doc_text(tmp_path)
    assert 'ALLOWED_CIDRS="198.51.100.0/24"' in (tmp_path / "t.local.conf").read_text()
    assert ssm_log(tmp_path) == [f"put {DOC}", f"tag {DOC} Key=project,Value=serena"]


def test_settings_set_with_no_value_removes_the_setting(tmp_path: Path) -> None:
    result = run_settings(tmp_path, 'settings_set ENV_LABEL ""', files=HERE, doc=doc_of(IN_SSM))
    assert result.returncode == 0, result.stderr
    assert "  - ENV_LABEL (was Set by Ops)" in result.stdout
    assert "ENV_LABEL" not in ssm_now(tmp_path) and 'ENV_LABEL=""' in (tmp_path / "t.local.conf").read_text()


@pytest.mark.parametrize(("args", "message"), [
    ("REAL_DATA_ACCOUNT 111122223333", "set by ./serena aws pipeline"),
    ("ACCOUNT_ID 999988887777", "ACCOUNT_ID is the account the settings are in"),
    ("AWS_PROFILE x", "isn't a setting ./serena aws keeps in SSM"),
    ("PROTECT_DATA yes", "PROTECT_DATA must be true or false"),
    ("TERRAFORM_ROOT other", "TERRAFORM_ROOT must be personal or shared"),
    ("WEB_COUNT two", "WEB_COUNT must be a number"),
    ("ENV_LABEL '$(whoami)'", "can't have"),
])
def test_settings_set_refuses_what_it_cant_set(tmp_path: Path, args: str, message: str) -> None:
    result = run_settings(tmp_path, f"settings_set {args}", files=HERE, doc=doc_of(IN_SSM))
    assert result.returncode == 1 and message in result.stderr, result.stderr
    assert ssm_now(tmp_path) == IN_SSM and "Write this" not in result.stdout


def test_settings_set_needs_settings_pushed_first(tmp_path: Path) -> None:
    result = run_settings(tmp_path, "settings_set ALLOWED_CIDRS 198.51.100.0/24", files=HERE)
    assert result.returncode == 1 and "settings push --env t" in result.stderr and ssm_now(tmp_path) == {}


def test_set_stops_if_someone_saved_the_document_meanwhile(tmp_path: Path) -> None:
    """set reads the document, then writes it back: if its version changed in between, it stops rather than undo
    that change. Here the version goes up on every read of it, as if someone kept saving."""
    body = ("eval \"$(declare -f aws_ | sed '1s/aws_/real_aws_/')\"\n"
            "aws_() { case \"$*\" in *Version*) v=\"$SSM_DIR.version/serena-t/settings/all\"; "
            "echo $(( $(cat \"$v\") + 1 )) > \"$v\" ;; esac; real_aws_ \"$@\"; }\n"
            "settings_set ENV_LABEL x")
    result = run_settings(tmp_path, body, files=HERE, doc=doc_of(IN_SSM))
    assert result.returncode == 1 and f"Someone saved {DOC} just now" in result.stderr, result.stderr
    assert doc_text(tmp_path) == doc_of(IN_SSM)


def test_settings_pull_brings_the_files_here_up_to_date(tmp_path: Path) -> None:
    """Ops changed ENV_LABEL and removed ALLOWED_CIDRS: pull writes both into the .local.conf and changes nothing in
    SSM. WEB_COUNT, set in the committed file, matches; a setting in neither SSM nor the files isn't written."""
    in_ssm = {k: v for k, v in IN_SSM.items() if k != "ALLOWED_CIDRS"}
    result = run_settings(tmp_path, "settings_pull", files=HERE, doc=doc_of(in_ssm))
    assert result.returncode == 0, result.stderr
    assert "  ENV_LABEL=Set by Ops   (was Old label)" in result.stdout
    assert f"Updated 2 setting(s) in {tmp_path}/t.local.conf from SSM ({DOC})." in result.stdout
    local = (tmp_path / "t.local.conf").read_text()
    assert 'ENV_LABEL="Set by Ops"' in local and 'ALLOWED_CIDRS=""' in local and "WAF" not in local
    assert ssm_now(tmp_path) == in_ssm and ssm_log(tmp_path) == []
    files_now = {line.split("=", 1)[0]: line.split("=", 1)[1].strip('"') for line in local.splitlines() if "=" in line}
    again = run_settings(tmp_path, "settings_pull", files=files_now)
    assert f"already match SSM ({DOC})." in again.stdout, again.stdout + again.stderr


def test_settings_show_names_pull_where_the_files_differ(tmp_path: Path) -> None:
    result = run_settings(tmp_path, "settings_show", files=HERE, doc=doc_of(IN_SSM),
                          ssm_values={"REAL_DATA_ACCOUNT": "111122223333"})
    assert result.returncode == 0, result.stderr
    assert f"the document {DOC} (version 1)" in result.stdout
    assert "  ENV_LABEL=Set by Ops   (the files here: Old label)" in result.stdout
    assert "  REAL_DATA_ACCOUNT=111122223333   (set by ./serena aws pipeline)" in result.stdout
    assert "To bring the files here up to date: ./serena aws settings pull --env t" in result.stdout


@pytest.mark.parametrize(("line", "message"), [
    ('ALLOWED_CIDRS="203.0.113.7/32', "must be in double quotes"),
    ("ALLOWED_CIDRS=203.0.113.7/32 198.51.100.0/24", "must be in double quotes"),
    ('ENV_LABEL="$(touch PWNED)"', "must be in double quotes"),
    ('ENV_LABEL="a`b`"', "must be in double quotes"),
    ('OLD_SETTING="x"', "OLD_SETTING isn't a setting ./serena aws reads"),
    ('REAL_DATA_ACCOUNT="111122223333"', "REAL_DATA_ACCOUNT isn't kept in the document"),
    ('ALLOWED_CIDRS="198.51.100.0/24"', "ALLOWED_CIDRS is set twice"),
    ("allowed_cidrs=x", "isn't NAME=\"value\""),
    ("VPC_ID='vpc-1'", "must be in double quotes"),
    ("ENV_LABEL=a#b", "must be in double quotes"),
    ("VPC_ID=“vpc-1”", "has a curly quote in it"),
])
def test_a_mistake_in_the_document_stops_every_command_and_names_its_line(tmp_path: Path, line: str,
                                                                          message: str) -> None:
    """The document is data, never run, so a value can't run a command; a line that isn't NAME="value" for a setting
    ./serena aws reads stops every command (from_ssm: the pipeline's build too), naming the line."""
    values = dict(IN_SSM)
    key = line.split("=", 1)[0]
    if "twice" not in message:
        values.pop(key, None)  # the line replaces the setting's own
    doc = doc_of(values)
    number = len(doc.splitlines()) + 1
    result = run_settings(tmp_path, 'from_ssm; echo "read: $ENV_LABEL"', cmd="plan", files=HERE, doc=doc + line + "\n")
    assert result.returncode == 1, result.stdout
    assert f"Line {number} of {DOC} in SSM" in result.stderr and message in result.stderr, result.stderr
    assert "read:" not in result.stdout and not (tmp_path / "PWNED").exists()


def test_a_value_set_quoted_or_bare_with_a_comment_reads_the_same(tmp_path: Path) -> None:
    others = {k: v for k, v in IN_SSM.items() if k != "ALLOWED_CIDRS"}
    doc = doc_of(others) + "  ALLOWED_CIDRS=198.51.100.0/24   # the VPN\n"
    result = run_settings(tmp_path, 'from_ssm; echo "read: $ALLOWED_CIDRS"', cmd="plan", files=HERE, doc=doc)
    assert result.returncode == 0, result.stderr
    assert "read: 198.51.100.0/24\n" in result.stdout


LEGACY = {**IN_SSM, "REAL_DATA_ACCOUNT": "111122223333", "OLD_SETTING": "x"}


def test_before_migrate_the_parameters_are_read_and_set_and_push_refuse(tmp_path: Path) -> None:
    result = run_settings(tmp_path, 'from_ssm; echo "read: $ENV_LABEL"', cmd="plan", files=HERE, ssm_values=LEGACY)
    assert result.returncode == 0, result.stderr
    assert "read: Set by Ops" in result.stdout
    result = run_settings(tmp_path, "settings_show", files=HERE)
    assert "one parameter per setting" in result.stdout and "settings migrate --env t" in result.stdout
    for body in ("settings_set ENV_LABEL x", "settings_push"):
        result = run_settings(tmp_path, body, files=HERE)
        assert result.returncode == 1 and "settings migrate --env t" in result.stderr, result.stderr
        assert "Write th" not in result.stdout  # refused before it asks
    assert ssm_now(tmp_path) == LEGACY and ssm_log(tmp_path) == []


def test_migrate_moves_the_parameters_into_the_document_from_ssms_values(tmp_path: Path) -> None:
    """From SSM's values, never the files'; REAL_DATA_ACCOUNT stays a parameter of its own; a parameter ./serena aws
    doesn't read is left alone; the old parameters go only once the document reads back."""
    files = {**HERE, "ALLOWED_CIDRS": "192.0.2.0/24"}  # SSM's 203.0.113.7/32 wins
    result = run_settings(tmp_path, "settings_migrate", answers="n\n", files=files, ssm_values=LEGACY)
    assert result.returncode == 1 and ssm_log(tmp_path) == []
    assert 'ALLOWED_CIDRS="203.0.113.7/32"' in result.stdout
    assert "Left alone, as ./serena aws doesn't read them: OLD_SETTING" in result.stdout
    result = run_settings(tmp_path, "settings_migrate", files=files)
    assert result.returncode == 0, result.stderr
    root = tmp_path / "ssm" / "serena-t" / "settings"
    assert sorted(p.name for p in root.iterdir()) == ["OLD_SETTING", "REAL_DATA_ACCOUNT", "all"]
    assert ssm_now(tmp_path) == LEGACY
    assert ssm_log(tmp_path)[:2] == [f"put {DOC}", f"tag {DOC} Key=project,Value=serena"]
    assert sorted(ssm_log(tmp_path)[2:]) == [f"delete /serena-t/settings/{k}" for k in sorted(IN_SSM)]
    again = run_settings(tmp_path, "settings_migrate", files=files)
    assert "already keeps its settings in one document" in again.stdout


@pytest.mark.parametrize("value", ['x"; touch PWNED; #', "first line\nENV_LABEL\tsecond"])
def test_before_migrate_a_value_that_could_run_never_reaches_the_files_here(tmp_path: Path, value: str) -> None:
    result = run_settings(tmp_path, "settings_pull", files=HERE, ssm_values={**LEGACY, "ENV_LABEL": value})
    files = (tmp_path / "t.local.conf").read_text()
    assert result.returncode == 1 and ("fix it in SSM first" in result.stderr or "line break" in result.stderr)
    assert not (tmp_path / "PWNED").exists()
    result = run_settings(tmp_path, "settings_migrate", files=HERE)
    assert result.returncode == 1 and not (tmp_path / "ssm" / "serena-t" / "settings" / "all").exists()
    assert (tmp_path / "t.local.conf").read_text() == files


def test_a_line_break_in_real_data_account_cant_add_a_setting(tmp_path: Path) -> None:
    """REAL_DATA_ACCOUNT is read on its own and checked, so a line break in it can't pass for a setting's line, which
    pull would write into the sourced .local.conf."""
    bad = {"REAL_DATA_ACCOUNT": '111122223333\nENV_LABEL\tx"; touch PWNED; #'}
    for body in ("settings_pull", "from_ssm"):
        result = run_settings(tmp_path, body, files=HERE, doc=doc_of(IN_SSM), ssm_values=bad)
        assert result.returncode == 1, result.stdout
        assert "/serena-t/settings/REAL_DATA_ACCOUNT in SSM isn't an account number" in result.stderr
    assert 'ENV_LABEL="Old label"' in (tmp_path / "t.local.conf").read_text() and not (tmp_path / "PWNED").exists()


@pytest.mark.parametrize("fail", ["describe", "value"])
@pytest.mark.parametrize("body", ["settings_push", "settings_set ENV_LABEL x", "settings_pull", "settings_show",
                                  "settings_migrate", "from_ssm"])
def test_a_failed_ssm_read_stops_every_command_before_it_changes_anything(tmp_path: Path, fail: str,
                                                                          body: str) -> None:
    """A read refused or throttled by AWS must never pass for "no settings": push would then rewrite the document
    from the files here, undoing Ops' changes."""
    files = {**HERE, "VPC_ID": "vpc-0abc"}
    result = run_settings(tmp_path, body, files=files, doc=doc_of(IN_SSM), fail=fail)
    if body == "settings_migrate" and fail == "value":  # it needn't read the document to see it's there
        assert "already keeps its settings in one document" in result.stdout
    else:
        assert result.returncode != 0, result.stdout
        assert "Couldn't" in result.stderr, result.stderr
    assert doc_text(tmp_path) == doc_of(IN_SSM) and ssm_log(tmp_path) == []
    assert (tmp_path / "t.local.conf").read_text() == "".join(f'{k}="{v}"\n' for k, v in files.items())


def test_save_local_refuses_a_value_that_would_run_in_the_files_here(tmp_path: Path) -> None:
    result = run_settings(tmp_path, 'save_local ENV_LABEL "\\$(whoami)"', files=HERE)
    assert result.returncode == 1 and "can't have" in result.stderr
    assert 'ENV_LABEL="Old label"' in (tmp_path / "t.local.conf").read_text()


@pytest.mark.parametrize(("sub", "admin"), [("pull", False), ("show", False), ("set", True), ("push", True)])
def test_settings_pull_and_show_run_as_the_deployer(sub: str, admin: bool) -> None:
    """They only read, which the deployer may; push and set write, as ADMIN_PROFILE where the environment has one."""
    load_env = shell_function((DEPLOY / "aws.sh").read_text(), "load_env")
    choice = re.search(r'  case "\$CMD:\$\{SETTINGS_SUB:-\}" in.*?esac', load_env, re.DOTALL)
    assert choice
    script = (f"CMD=settings; SETTINGS_SUB={sub}; ADMIN_PROFILE=admin; AWS_PROFILE=deployer\n{choice.group(0)}\n"
              'echo "$AWS_PROFILE"')
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)  # noqa: S603, S607
    assert result.stdout.strip() == ("admin" if admin else "deployer")
