import json
import sys
from pathlib import Path

TARGETS = {
    "CONTENT_DNA_MAX_VIDEOS",
    "MEDIA_VIDEO_CONCURRENCY",
    "GLOBAL_VIDEO_GENERATION_CONCURRENCY",
}

def clean(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value

# Read every occurrence from local .env
local_occurrences = {key: [] for key in TARGETS}

for lineno, raw in enumerate(
    Path(".env").read_text(encoding="utf-8-sig").splitlines(),
    1
):
    line = raw.strip()

    if not line or line.startswith("#") or "=" not in line:
        continue

    key, value = line.split("=", 1)
    key = key.strip()

    if key in TARGETS:
        local_occurrences[key].append(
            (lineno, clean(value))
        )

# Read Cloud Run JSON from stdin
data = json.load(sys.stdin)

containers = (
    data.get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers", [])
)

if not containers:
    containers = data.get("template", {}).get("containers", [])

if not containers:
    print("ERROR: Cloud Run container configuration not found.")
    raise SystemExit(1)

cloud = {}

for item in containers[0].get("env", []):
    key = item.get("name")

    if key not in TARGETS:
        continue

    if item.get("valueFrom"):
        cloud[key] = None
    else:
        cloud[key] = clean(str(item.get("value", "")))

print()
print("Duplicate local values vs Cloud Run")
print("-----------------------------------")

for key in sorted(TARGETS):
    print()
    print(key)

    if key not in cloud:
        print("  Cloud Run: MISSING")
        continue

    if cloud[key] is None:
        print("  Cloud Run: SECRET REFERENCE")
        continue

    for lineno, value in local_occurrences[key]:
        result = "MATCH CLOUD" if value == cloud[key] else "NOT CLOUD"
        print(f"  local line {lineno}: {result}")

print()
print("No environment values were printed.")
