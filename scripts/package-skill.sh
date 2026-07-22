#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(CDPATH= cd -- "$script_dir/.." && pwd -P)"

command -v python3 >/dev/null 2>&1 || {
  echo "Model Boss: python3 is required" >&2
  exit 127
}

mkdir -p "$repo_root/dist"
exec python3 -m runtime.model_boss.package \
  --repo-root "$repo_root" \
  --output "$repo_root/dist/model-boss.skill"
