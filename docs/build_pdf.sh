#!/bin/bash
# Build the thesis PDF using Bazel and copy it to docs/master.pdf.

set -e

WORKSPACE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$WORKSPACE_DIR"

echo "Building thesis PDF..."
bazel build //docs:master

cp bazel-bin/docs/master.pdf docs/master.pdf
chmod u+w docs/master.pdf
echo "PDF generated: docs/master.pdf ($(wc -c < docs/master.pdf) bytes)"

open docs/master.pdf 2>/dev/null || true
