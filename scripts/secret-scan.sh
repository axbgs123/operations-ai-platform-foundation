#!/usr/bin/env bash
set -euo pipefail

patterns='BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|sk-[A-Za-z0-9]{20,}|sk-(proj|ant)-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|glpat-[A-Za-z0-9_-]{20,}|xox[baprs]-[0-9A-Za-z-]{20,}|npm_[A-Za-z0-9]{36,}|pypi-[A-Za-z0-9_-]{20,}|([Cc][Oo][Oo][Kk][Ii][Ee]|[Aa][Uu][Tt][Hh][Oo][Rr][Ii][Zz][Aa][Tt][Ii][Oo][Nn])[[:space:]]*[:=][[:space:]]*([^[:space:]]{16,}|[Bb][Ee][Aa][Rr][Ee][Rr][[:space:]]+[^[:space:]]{16,})'
repo='.'
scan_history=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    --history) scan_history=true; shift ;;
    *) echo "usage: $0 [--repo PATH] [--history]" >&2; exit 2 ;;
  esac
done

is_synthetic_fixture_match() {
  case "$1:$2" in
    apps/api/app/core/rate_limit.py:327:6b4dec44c198ef00618fdbc70f28ab8c6ff0f83c49fe5c953660e7de304878e1|apps/api/app/modules/risk_rag/evaluation.py:30:0c231ea81472b877e89fb27bc53b9c74e3e62e389334559efa6eeb1bb2fec072|apps/api/tests/core/test_log_redaction.py:25:0a5ffaa8a0c5bb3d72a9fc4f5f7fc81fa55d6a7e5e491cf2712caf75f9d38b9d|apps/api/tests/workspace/test_workspace_api.py:72:20329df5496549a2208616a9c760d578328fdd6f886d942c27c1c7abf261926a)
      return 0 ;;
    *)
      return 1 ;;
  esac
}

has_disallowed_git_matches() {
  local revision="${1:-}"
  local location
  local fingerprint
  while IFS=$'\t' read -r location fingerprint; do
    if ! is_synthetic_fixture_match "$location" "$fingerprint"; then
      return 0
    fi
  done < <(
    {
      if [[ -n "$revision" ]]; then
        git -C "$repo" grep -nIE "$patterns" "$revision" -- 2>/dev/null || true
      else
        git -C "$repo" grep -nIE "$patterns" -- 2>/dev/null || true
      fi
    } | while IFS= read -r record; do
      if [[ -n "$revision" ]]; then record="${record#*:}"; fi
      match_path="${record%%:*}"
      remainder="${record#*:}"
      match_line="${remainder%%:*}"
      content="${remainder#*:}"
      content_fingerprint="$(printf '%s' "$content" | shasum -a 256 | awk '{print $1}')"
      printf '%s:%s\t%s\n' "$match_path" "$match_line" "$content_fingerprint"
    done
  )
  return 1
}

if has_disallowed_git_matches; then
  echo 'secret_scan=failed'
  exit 1
fi

if {
  git -C "$repo" ls-files --others --exclude-standard -z
  find "$repo" -type f \( -name '.env' -o -name '.env.*' \) -not -path "$repo/.env.example" -print0
} | while IFS= read -r -d '' path; do
  candidate="$path"
  if [[ "$candidate" != "$repo/"* ]]; then
    candidate="$repo/$candidate"
  fi
  if grep -I -E "$patterns" -- "$candidate" >/dev/null 2>&1; then
    exit 1
  fi
done; then
  :
else
  echo 'secret_scan=failed'
  exit 1
fi

if [[ "$scan_history" == true ]]; then
  if git -C "$repo" rev-list --all | (
    while read -r revision; do
      if has_disallowed_git_matches "$revision"; then
        exit 1
      fi
    done
    exit 0
  ); then :; else
    echo 'secret_scan=failed'
    exit 1
  fi
fi

echo "secret_scan=clean"
