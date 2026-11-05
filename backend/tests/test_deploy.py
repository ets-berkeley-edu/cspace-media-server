"""The AWS deployment (deploy/; D181-D194) stays in step with the code: the tables Terraform creates, and the settings
it gives the app. The committed settings files keep the default environment on the simulator and hold nothing that
belongs only in an uncommitted <env>.local.conf."""
from __future__ import annotations

import re
from pathlib import Path

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
