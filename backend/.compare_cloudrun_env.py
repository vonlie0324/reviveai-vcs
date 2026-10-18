import json
import sys
from pathlib import Path

IGNORE = {
    "PORT",
    "K_SERVICE",
    "K_REVISION",
    "K_CONFIGURATION",
}

def clean(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value

# Local .env
local = {}
duplicates = []

for raw in Path(".env").read_text(encoding="utf-8-sig").splitlines():
    line = raw.strip()

    if not line or line.startswith("#") or "=" not in line:
        continue

    if line.startswith("export "):
        line = line[7:].strip()

    key, value = line.split("=", 1)
    key = key.strip()

    if not key or key in IGNORE:
        continue

    if key in local:
        duplicates.append(key)

    local[key] = clean(value)

# Cloud Run JSON from stdin
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

    if not key or key in IGNORE:
        continue

    if item.get("valueFrom"):
        cloud[key] = {
            "type": "secret",
            "value": None,
        }
    else:
        cloud[key] = {
            "type": "plain",
            "value": clean(str(item.get("value", ""))),
        }

print()
print("==============================================================")
print(" ReviveAI Environment Check")
print("==============================================================")

if duplicates:
    print()
    print("DUPLICATES IN LOCAL .env:")
    for key in sorted(set(duplicates)):
        print(f"  WARN  {key}")
else:
    print()
    print("DUPLICATES IN LOCAL .env: none")

print()
print("LOCAL vs CLOUD RUN")
print("------------------")

matches = 0
different = 0
local_only = 0
cloud_only = 0
secrets = 0

for key in sorted(set(local) | set(cloud)):

    if key not in cloud:
        print(f"LOCAL ONLY    {key}")
        local_only += 1
        continue

    if key not in local:
        print(f"CLOUD ONLY    {key}")
        cloud_only += 1
        continue

    if cloud[key]["type"] == "secret":
        print(f"SECRET REF    {key}")
        secrets += 1
        continue

    if local[key] == cloud[key]["value"]:
        print(f"MATCH         {key}")
        matches += 1
    else:
        print(f"DIFFERENT     {key}")
        different += 1

print()
print("------------------")
print(f"MATCH        : {matches}")
print(f"DIFFERENT    : {different}")
print(f"LOCAL ONLY   : {local_only}")
print(f"CLOUD ONLY   : {cloud_only}")
print(f"SECRET REF   : {secrets}")
print()
print("All environment values remain redacted.")
