"""TC-01-003 evidence: static licence scan of the shipped stack (no network, no installs).

Run from the repository root: python artifacts/acceptance/TC-01-003/scan_licences.py
Prints the production Compose services and images, the web lock licence counts (runtime and
dev), every runtime web entry that is not plainly permissive, and the API runtime pins. The
per-package Python licences are read from installed metadata by
apps/api/tests/release/test_license_resolution.py in CI.
"""

import json
import re
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path.cwd()
PERMISSIVE = {"MIT", "Apache-2.0", "ISC", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "BlueOak-1.0.0"}

compose = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text())
print("## docker-compose.prod.yml")
for name, svc in compose["services"].items():
    built = f"(built from {svc['build']['dockerfile']})" if "build" in svc else "?"
    print(f"{name}: {svc.get('image', built)}")
print("volumes:", ", ".join(compose.get("volumes") or {}))

packages = json.loads((ROOT / "apps/web/package-lock.json").read_text())["packages"]
runtime, dev, odd = Counter(), Counter(), []
for path, info in packages.items():
    if not path:
        continue
    lic = info.get("license")
    lic = lic.get("type") if isinstance(lic, dict) else str(lic)
    (dev if info.get("dev") else runtime)[lic] += 1
    if not info.get("dev") and lic not in PERMISSIVE:
        odd.append(f"{path.rsplit('node_modules/', 1)[-1]}@{info.get('version')}: {lic}")
print(f"\n## apps/web/package-lock.json runtime ({sum(runtime.values())} entries)")
for lic, n in runtime.most_common():
    print(f"{n:4d} {lic}")
print(f"\n## apps/web/package-lock.json dev only ({sum(dev.values())} entries)")
for lic, n in dev.most_common():
    print(f"{n:4d} {lic}")
print("\n## runtime web entries that are not plainly permissive")
print("\n".join(odd))

lock = (ROOT / "apps/api/requirements.lock").read_text()
pins = re.findall(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)", lock, re.MULTILINE)
print(f"\n## apps/api/requirements.lock ({len(pins)} runtime pins)")
print(" ".join(f"{n}=={v}" for n, v in pins))
