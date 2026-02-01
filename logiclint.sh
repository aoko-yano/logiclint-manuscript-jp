#!/usr/bin/env bash
set -euo pipefail

TOOL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_ROOT="$(pwd)"

echo "Building logiclint Docker image..."
docker build -t logiclint-tool -f "${TOOL_ROOT}/Dockerfile" "${TOOL_ROOT}"

echo "Running logiclint (workdir: ${WORK_ROOT})..."
docker run --rm -v "${WORK_ROOT}:/work" -w /work logiclint-tool "$@"

