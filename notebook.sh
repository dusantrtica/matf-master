#!/usr/bin/env bash
# Launch JupyterLab in a local virtualenv for interactive work on the CP solver.
#
# Requires a local Python (3.11 recommended) already installed on your machine.
# Override the interpreter with: PYTHON=python3.x ./notebook.sh
#
# On first run this creates ./.venv and installs requirements-notebook.txt.
# The repo root is put on PYTHONPATH so notebooks can `import src.algo...`.
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3.11}"
VENV_DIR=".venv"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Error: '$PYTHON' not found. Install it or set PYTHON=python3.x" >&2
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtualenv in $VENV_DIR using $PYTHON ..."
  "$PYTHON" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements-notebook.txt

export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

exec jupyter lab "$@"
