"""
training_store.py
乙：上傳訓練資料的『累積儲存』與『合併供重訓』。

設計重點：
- 上傳『進訓練』的資料必須含真實標籤 Late_delivery_risk（否則無法學習）。
- 入庫前先過 C 驗證閘門（重複欄/像不像訂單資料），並去除 PII（at-rest 安全）；
  Order Id 不在此雜湊，留待重訓時由 DataPipeline 統一去識別化，避免欄位衝突。
- 採『append 累積』而非覆蓋，讓訓練資料隨真實案例增長。
"""
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from security_utils import DeIdentifier
from preprocessor import validate_upload_columns  # 重用 C 驗證閘門

TARGET_COLUMN = "Late_delivery_risk"


class TrainingDataError(ValueError):
    """上傳訓練資料未通過驗證（缺標籤等）。由 API 轉成 400。"""


def _read_csv(buf_or_path) -> pd.DataFrame:
    try:
        return pd.read_csv(buf_or_path, encoding="latin-1")
    except UnicodeDecodeError:
        return pd.read_csv(buf_or_path, encoding="utf-8")


def append_training_csv(file_buffer, store_path: Path, hash_salt: str = "EDIS_2026") -> dict:
    """
    驗證並把一批上傳的訓練資料『累積』到 store_path。

    Returns: {"added": 本次筆數, "total": 累積總筆數}
    Raises: UploadValidationError / TrainingDataError（皆應轉成 HTTP 400）
    """
    df = _read_csv(file_buffer)

    # 1) C 驗證閘門（重複欄 / 是否像訂單資料）
    validate_upload_columns(list(df.columns))

    # 2) 進訓練必須有真實標籤
    label = next((c for c in df.columns if c.lower() == TARGET_COLUMN.lower()), None)
    if label is None:
        raise TrainingDataError(
            f"訓練資料必須含標籤欄位 '{TARGET_COLUMN}'（真實是否延遲），否則無法用於訓練。"
        )

    # 3) 去除 PII（at-rest 安全）；Order Id 留待重訓時統一雜湊
    df = DeIdentifier(hash_salt=hash_salt).drop_sensitive_columns(df)

    # 4) append 累積（讀舊 + concat + 寫，容忍欄位差異）
    store_path = Path(store_path)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    if store_path.exists() and store_path.stat().st_size > 0:
        existing = _read_csv(store_path)
        combined = pd.concat([existing, df], ignore_index=True)
    else:
        combined = df
    combined.to_csv(store_path, index=False, encoding="latin-1", errors="replace")
    return {"added": int(len(df)), "total": int(len(combined))}


def build_combined_training_file(raw_path: Path, store_path: Path, out_path: Path) -> dict:
    """
    把『原始檔 + 累積訓練資料』合併成一個檔，供 DataPipeline 重訓使用。

    Returns: {"raw": n, "accumulated": n, "total": n}
    """
    raw_path, store_path, out_path = Path(raw_path), Path(store_path), Path(out_path)
    raw = _read_csv(raw_path)
    if store_path.exists() and store_path.stat().st_size > 0:
        store = _read_csv(store_path)
        combined = pd.concat([raw, store], ignore_index=True)
        n_acc = int(len(store))
    else:
        combined = raw
        n_acc = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_path, index=False, encoding="latin-1", errors="replace")
    return {"raw": int(len(raw)), "accumulated": n_acc, "total": int(len(combined))}
