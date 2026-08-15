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

# In-tree .venv, kept out of sync services in place (see the xattr step
# below). A venv is machine-specific and never syncs correctly anyway;
# ignoring it where it sits matches what a clone outside a synced folder
# already has, so there is one layout for every machine.
VENV="${QLENS_VENV:-.venv}"
PYTHON="$VENV/bin/python"

# The first interpreter that is Python 3.11 or newer. Bare python3 can be
# an older pyenv or system build, so named versions and the common
# framework/Homebrew locations are tried before falling back to it.
find_python() {
  local candidate version
  for candidate in \
    python3.13 python3.12 python3.11 \
    /Library/Frameworks/Python.framework/Versions/3.1[1-9]/bin/python3 \
    /opt/homebrew/bin/python3.1[1-9] \
    /usr/local/bin/python3.1[1-9] \
    python3; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    version="$("$candidate" -c 'import sys; print(1 if sys.version_info[:2] >= (3, 11) else 0)' 2>/dev/null || echo 0)"
    [ "$version" = "1" ] && { echo "$candidate"; return 0; }
  done
  return 1
}

# An existing directory proves nothing: a venv left by an interrupted
# install, or one with a stale interpreter, fails the version probe.
if [ ! -x "$PYTHON" ] || ! "$PYTHON" --version >/dev/null 2>&1; then
  if ! base_python="$(find_python)"; then
    echo "launch: need Python 3.11 or newer. Install it from https://www.python.org/downloads/" >&2
    exit 1
  fi
  echo "launch: creating environment in $VENV (using $base_python)"
  rm -rf "$VENV"
  "$base_python" -m venv "$VENV"
  # Keep sync services (Dropbox, iCloud, OneDrive) off the venv in place:
  # sync churn invalidates the code signatures of compiled numpy/scipy
  # extensions, and macOS then refuses to load them. Harmless off macOS or
  # outside a synced folder, so it runs unconditionally and can't be
  # forgotten. Set before any compiled dependency is installed.
  xattr -w com.dropbox.ignored 1 "$VENV" 2>/dev/null || true
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
