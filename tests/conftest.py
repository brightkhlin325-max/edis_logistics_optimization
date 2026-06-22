"""
tests/conftest.py
共用測試設定：把專案根目錄與 core/ 加入 sys.path，
讓各測試檔可直接 `from app import app`、`from optimizer import ...`、
`from security_utils import ...`，不必各自重複設定。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "core"

for p in (ROOT, CORE):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)
