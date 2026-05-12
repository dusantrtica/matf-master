#!/bin/bash
# Build the thesis PDF using Bazel.
# The latexrun wrapper has a known bug with lualatex sandbox paths,
# so bazel build reports failure even though the PDF is produced.
# This script works around that by using --sandbox_debug to retain
# the sandbox files and extracting the PDF.

WORKSPACE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$WORKSPACE_DIR"

echo "Building thesis PDF..."
bazel build //docs:master --sandbox_debug 2>&1 || true

PDF_PATH=$(find /private/var/tmp/_bazel_*/*/sandbox/darwin-sandbox/*/execroot/_main/ \
    -name "master.pdf" 2>/dev/null | sort | tail -1)

if [ -z "$PDF_PATH" ]; then
    echo "ERROR: master.pdf not found. Check bazel build output for LaTeX errors."
    exit 1
fi

cp "$PDF_PATH" docs/master.pdf
echo "PDF generated: docs/master.pdf ($(wc -c < docs/master.pdf) bytes)"

open docs/master.pdf 2>/dev/null || true
