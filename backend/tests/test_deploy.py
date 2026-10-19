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
    """After changing a table: python -m serena.tables > ../deploy/terraform/app/tables.json"""
    assert (DEPLOY / "terraform" / "app" / "tables.json").read_text() == tables.as_json()


def test_every_setting_the_deployment_gives_is_one_serena_reads() -> None:
    """A misspelt SERENA_ name in the task definitions or the image would be ignored silently."""
    sources = [*sorted((DEPLOY / "terraform" / "app").glob("*.tf")), DEPLOY / "Dockerfile"]
    names = {name for source in sources for name in re.findall(r"\bSERENA_[A-Z0-9_]+\b", source.read_text())}
    assert names, "no settings found: has the deployment moved?"
    fields = {f"SERENA_{field.upper()}" for field in Settings.model_fields}
    assert sorted(names - fields - NOT_SETTINGS) == []
