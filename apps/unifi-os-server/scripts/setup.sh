#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -f "${REPO_ROOT}/.venv/bin/python3" ]; then
  if command -v uv &>/dev/null; then
    uv venv "${REPO_ROOT}/.venv"
    uv pip install --python "${REPO_ROOT}/.venv/bin/python3" pyyaml pytest ruff
  fi
fi

if [ -f "${REPO_ROOT}/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.venv/bin/activate"
fi

echo "================================================================="
echo "   SCAFFOLDING & QUALITY VERIFICATION: ha-addon-unifi-os-server  "
echo "================================================================="

echo -e "\n1. [Manifest Validation] Checking config.yaml(.disabled), build.yaml, and translations..."
python3 "${REPO_ROOT}/scripts/test_config.py"

echo -e "\n2. [OKF v0.2 Validation] Checking Open Knowledge Format bundle..."
bash "${REPO_ROOT}/scripts/validate_okf.sh"

echo -e "\n3. [Security Audit] Running pre-commit secret & credential scanner..."
bash "${REPO_ROOT}/scripts/security_audit.sh"

echo -e "\n4. [Shell Syntax] Validating bash scripts with 'bash -n'..."
for sh_file in "${REPO_ROOT}/scripts"/*.sh; do
  bash -n "$sh_file"
done
echo "✓ All bash scripts passed syntax checks!"

echo -e "\n5. [Pytest Suite] Running automated unit & regression tests..."
cd "${REPO_ROOT}" && pytest tests/ -v

echo -e "\n================================================================="
echo "✓ ALL QUALITY GATES PASSED! Pre-implementation scaffolding ready."
echo "================================================================="
