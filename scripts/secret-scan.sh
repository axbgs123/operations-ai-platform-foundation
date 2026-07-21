#!/usr/bin/env bash
set -euo pipefail

patterns='BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{30,}'

if git grep -nIE "$patterns" -- ':!pnpm-lock.yaml' ':!apps/api/uv.lock'; then
  echo "Potential secret detected in tracked files."
  exit 1
fi

echo "secret_scan=clean"
