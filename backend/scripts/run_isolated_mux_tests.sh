#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Fail closed if test helper is altered to import app modules, which initialize clients.
python - <<'PY'
import ast
from pathlib import Path
for p in (Path('tests/test_isolated_audio_mux_recovery.py'), Path('tests/test_isolated_artifact_restoration.py')):
 tree=ast.parse(p.read_text(encoding='utf-8'))
 for node in ast.walk(tree):
  if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('app'):
   raise SystemExit('REFUSING: test suite imports live backend modules')
  if isinstance(node, ast.Import) and any(alias.name.startswith('app') for alias in node.names):
   raise SystemExit('REFUSING: test suite imports live backend modules')
print('Isolation check: no live application module imports')
PY
python - <<'PYTEST_PREREQ'
import shutil
missing = [name for name in ('ffmpeg', 'ffprobe') if not shutil.which(name)]
if missing:
    raise SystemExit('OFFLINE TEST PREREQUISITE MISSING: ' + ', '.join(missing) + '\nInstall FFmpeg plus FFprobe and ensure both are visible to Python PATH.')
PYTEST_PREREQ
python -m pytest -q tests/test_isolated_audio_mux_recovery.py tests/test_isolated_artifact_restoration.py
