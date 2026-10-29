"""The AWS deployment (deploy/; D181-D194) stays in step with the code: the tables Terraform creates, and the settings
it gives the app."""
from __future__ import annotations

import re
from pathlib import Path

from serena import tables
from serena.config import Settings

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"

# Read from the environment by the fake ETL itself, not a setting (backend/devtools/fake_etl.py).
NOT_SETTINGS = {"SERENA_SIMULATED_CSPACE"}


def test_terraform_creates_the_tables_the_code_defines() -> None:
    """After changing a table: python -m serena.tables > ../deploy/terraform/modules/core/tables.json"""
    assert (DEPLOY / "terraform" / "modules" / "core" / "tables.json").read_text() == tables.as_json()


def test_every_setting_the_deployment_gives_is_one_serena_reads() -> None:
    """A misspelt SERENA_ name in the task definitions or the image would be ignored silently."""
    terraform = DEPLOY / "terraform"
    tf_files = sorted([*terraform.glob("personal/*.tf"), *terraform.glob("modules/*/*.tf")])
    sources = [*tf_files, DEPLOY / "Dockerfile"]
    names = {name for source in sources for name in re.findall(r"\bSERENA_[A-Z0-9_]+\b", source.read_text())}
    assert names, "no settings found: has the deployment moved?"
    fields = {f"SERENA_{field.upper()}" for field in Settings.model_fields}
    assert sorted(names - fields - NOT_SETTINGS) == []
