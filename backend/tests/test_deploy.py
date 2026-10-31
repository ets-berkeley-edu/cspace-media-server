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
