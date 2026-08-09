#!/usr/bin/env bash
# Start the Qlens viewer.
#
#   ./launch.sh                     open on sample runs
#   ./launch.sh data/traces.jsonl   open on a trace source
#
# Creates or reuses a virtual environment, installs qlens into it, and
# serves the viewer. Pass --state-dir, --port, or any other qlens view
# option straight through.

set -euo pipefail
cd "$(dirname "$0")" || exit 1

# Outside the project tree on purpose. A venv holding compiled numpy and
# scipy extensions inside a synced folder (Dropbox, iCloud, OneDrive) has
# its code signatures invalidated by sync churn, and macOS then refuses
# to load the libraries.
VENV="${QLENS_VENV:-$HOME/.venvs/qlens}"
PYTHON="$VENV/bin/python"

if ! command -v python3 >/dev/null 2>&1; then
  echo "launch: python3 is not on PATH. Install Python 3.11 or newer." >&2
  exit 1
fi

# An existing directory proves nothing: a venv synced from another
# machine or left by an interrupted install has a stale interpreter.
if [ ! -x "$PYTHON" ] || ! "$PYTHON" --version >/dev/null 2>&1; then
  echo "launch: creating environment in $VENV"
  rm -rf "$VENV"
  python3 -m venv "$VENV"
  "$PYTHON" -m ensurepip --upgrade >/dev/null
fi

if ! "$PYTHON" -c "import qlens" >/dev/null 2>&1; then
  echo "launch: installing qlens"
  "$PYTHON" -m pip install --quiet --upgrade pip
  "$PYTHON" -m pip install --quiet -e ".[qiskit]"
fi

if [ "$#" -eq 0 ]; then
  echo "launch: no trace source given, opening sample runs"
  exec "$PYTHON" -m qlens.viewer.cli view --demo
fi

exec "$PYTHON" -m qlens.viewer.cli view "$@"
