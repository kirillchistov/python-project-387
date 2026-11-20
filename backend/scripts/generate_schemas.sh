#!/usr/bin/env bash
# Перегенерирует app/api/schemas/generated.py из docs/api/openapi.yaml.
# Файл не редактируется руками — источник истины контракта в spec/*.tsp
# (см. AGENTS.md, port-to-python-plan.md §4.2). CI прогоняет этот скрипт
# и проверяет `git diff --exit-code` — так же, как для openapi.yaml и
# frontend/src/api/schema.d.ts.
set -euo pipefail
cd "$(dirname "$0")/.."

uv run datamodel-codegen \
  --input ../docs/api/openapi.yaml \
  --input-file-type openapi \
  --output app/api/schemas/generated.py \
  --output-model-type pydantic_v2.BaseModel \
  --target-python-version 3.12 \
  --use-schema-description \
  --field-constraints \
  --collapse-root-models \
  --use-standard-collections \
  --disable-timestamp \
  --custom-file-header "# СГЕНЕРИРОВАНО из docs/api/openapi.yaml командой scripts/generate_schemas.sh — не редактировать руками."
