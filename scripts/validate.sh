#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(CDPATH= cd -- "$script_dir/.." && pwd -P)"
cd "$repo_root"

command -v python3 >/dev/null 2>&1 || {
  echo "token-saver: python3 is required" >&2
  exit 127
}

python3 -m unittest discover -s tests -v

for json_file in \
  config/token-saver.schema.json \
  config/token-saver.example.json \
  references/profiles/anthropic.json \
  references/profiles/openai.json \
  references/profiles/kimi.json \
  evals/evals.json \
  evals/routing-evals.json \
  benchmarks/trigger-eval.json \
  benchmarks/benchmark.json; do
  python3 -m json.tool "$json_file" >/dev/null
done

bash -n scripts/package-skill.sh scripts/validate.sh scripts/setup-model-providers.sh
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" .
python3 -m unittest tests.test_skill_content tests.test_docs -q

validation_tmp="$(mktemp -d)"
trap 'rm -rf -- "$validation_tmp"' EXIT HUP INT TERM
python3 -m runtime.token_saver.package \
  --repo-root "$repo_root" \
  --output "$validation_tmp/token-saver.skill" >/dev/null
cmp dist/token-saver.skill "$validation_tmp/token-saver.skill"
python3 -m runtime.token_saver.package \
  --repo-root "$repo_root" \
  --validate "$validation_tmp/token-saver.skill" >/dev/null
unzip -t "$validation_tmp/token-saver.skill" >/dev/null
git diff --check
