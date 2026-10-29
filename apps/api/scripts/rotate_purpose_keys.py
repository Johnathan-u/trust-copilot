#!/usr/bin/env python3
"""Re-encrypt MFA and connector rows under the current purpose key. Counts only.

Refuses APP_ENV=production. Do not point it at a live database.

From apps/api:
  python scripts/rotate_purpose_keys.py --dry-run
  python scripts/rotate_purpose_keys.py --limit 100 --after-id 0
"""

import sys
from pathlib import Path

_api_root = Path(__file__).resolve().parent.parent
if str(_api_root) not in sys.path:
    sys.path.insert(0, str(_api_root))

from app.core.key_rotation import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
