#!/usr/bin/env bash
# Regenerates the backend's pinned requirements files (exact versions with hashes) from pyproject.toml and
# requirements-tools.in, as in the BMU. Never edit requirements*.txt by hand: change pyproject.toml (or
# requirements-tools.in) and run this.
#
# Needs Python 3.11 (.python-version: the Python that CI and the images run) with the tools installed:
#   pip install --require-hashes -r backend/requirements-tools.txt
#
#   backend/pin-requirements.sh                          keep every pin; add or drop what pyproject.toml changed
#   backend/pin-requirements.sh --upgrade                move every package to its newest allowed version
#   backend/pin-requirements.sh --upgrade-package boto3  move one package (repeat the option for more)
#
# CI runs it with no options and fails if any file changes.
set -euo pipefail
cd "$(dirname "$0")"

version=$(python -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if [ "$version" != "$(cat ../.python-version)" ]; then
  echo "This is Python $version. Use Python $(cat ../.python-version), the version CI and the images run." >&2
  exit 1
fi

options=(--quiet --generate-hashes --allow-unsafe --strip-extras)
# The app: its dependencies, and setuptools to build it (--all-build-deps), so nothing unpinned is installed.
pip-compile "${options[@]}" --all-build-deps "$@" -o requirements.txt pyproject.toml
# The tests and checks: the app's pins plus the dev extra (pytest, moto, ruff, mypy).
pip-compile "${options[@]}" --all-build-deps --extra dev -c requirements.txt "$@" -o requirements-dev.txt pyproject.toml
# pip-tools and pip-audit, in their own file so they never change the app's or the tests' versions.
pip-compile "${options[@]}" "$@" -o requirements-tools.txt requirements-tools.in
