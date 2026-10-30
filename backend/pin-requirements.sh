#!/usr/bin/env bash
# Regenerates the backend's pinned requirements files (exact versions with hashes) from requirements.in,
# requirements-dev.in and requirements-tools.in, as in the BMU. Never edit requirements*.txt by hand: change the .in
# file and run this. Dependabot reruns pip-compile with the options in each .txt file's header.
#
# Needs Python 3.11 (.python-version: the Python that CI and the images run) with the tools installed:
#   pip install --require-hashes -r backend/requirements-tools.txt
#
#   backend/pin-requirements.sh                          keep every pin; add or drop what the .in files changed
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
# The app and the worker, with setuptools to build Serena itself (so nothing unpinned is installed).
pip-compile "${options[@]}" "$@" -o requirements.txt requirements.in
# The simulator (fakecspace) for the local stack's image and the tests: constrained to the app's pins.
pip-compile "${options[@]}" "$@" -o requirements-sim.txt requirements-sim.in
# The tests and checks: the app's pins (requirements-dev.in constrains to requirements.txt) plus pytest, moto, ruff, mypy.
pip-compile "${options[@]}" "$@" -o requirements-dev.txt requirements-dev.in
# pip-tools and pip-audit, in their own file so they never change the app's or the tests' versions.
pip-compile "${options[@]}" "$@" -o requirements-tools.txt requirements-tools.in
