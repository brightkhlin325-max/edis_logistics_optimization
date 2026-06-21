"""
security_utils.py
EDIS — DataCo 物流延遲預測與最佳化調度系統

負責人：Lisa
功能：資料去識別化工具模組（第一層安全防護）
  - SHA-256 雜湊 Order ID
  - 客戶姓名遮蔽（Masking）
  - 敏感欄位刪除
  - 統一去識別化入口
"""

import hashlib
import re
import pandas as pd
from typing import Optional


# ── 敏感欄位定義 ────────────────────────────────────────────────────────────

SENSITIVE_COLUMNS = [
    "Customer Fname",
    "Customer Lname",
    "Customer Street",
    "Customer Zipcode",
    "Customer Email",
    "Customer Password",
]

# 模型訓練時也必須排除（資料洩漏欄位）
LEAKAGE_COLUMNS = [
    "Delivery Status",
    "Days for shipping (real)",
    "Order Status",
    "Late_delivery_risk",   # 標籤欄位，由 pipeline 單獨處理
]

# 保留但需雜湊的 ID 欄位
ID_COLUMNS_TO_HASH = [
    "Order Id",
]


# ── 去識別化主類別 ───────────────────────────────────────────────────────────

class DeIdentifier:
    """
    負責將原始 DataCo DataFrame 轉換為去識別化版本。

    使用範例：
        de_id = DeIdentifier()
        safe_df = de_id.apply_all(raw_df)
    """

    def __init__(self, hash_salt: str = "EDIS_2026"):
        """
        Parameters
        ----------
        hash_salt : str
            加入 SHA-256 雜湊的 salt，避免彩虹表攻擊。
            可從環境變數或設定檔傳入，預設為固定值供開發使用。
        """
        self.hash_salt = hash_salt

    # ── 公開方法 ──────────────────────────────────────────────────────────

    def apply_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        一次套用所有去識別化操作，回傳安全版 DataFrame。
        這是唯一對外的主要入口，data_pipeline.py 應只呼叫此方法。

        操作順序：
        1. 刪除敏感欄位
        2. 雜湊 ID 欄位
        """
        df = df.copy()
        df = self.drop_sensitive_columns(df)
        df = self.hash_id_columns(df)
        return df

    def drop_sensitive_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        刪除所有敏感欄位（客戶姓名、地址、郵遞區號等）。
        只刪除實際存在於 df 的欄位，避免 KeyError。
        """
        cols_to_drop = [c for c in SENSITIVE_COLUMNS if c in df.columns]
        if cols_to_drop:
            print(f"[DeIdentifier] 刪除敏感欄位：{cols_to_drop}")
        return df.drop(columns=cols_to_drop)

    def hash_id_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        對 ID_COLUMNS_TO_HASH 中定義的欄位進行 SHA-256 雜湊。
        原始欄位名稱保留，值替換為 64 位元十六進位雜湊字串。
        """
        for col in ID_COLUMNS_TO_HASH:
            if col in df.columns:
                df[col] = df[col].astype(str).apply(self._sha256)
                # 重新命名為 hash 欄位，讓下游清楚知道已雜湊
                df = df.rename(columns={col: f"{col}_hash"})
                print(f"[DeIdentifier] 已對 '{col}' 進行 SHA-256 雜湊 → '{col}_hash'")
        return df

    def mask_name(self, name: Optional[str]) -> str:
        """
        遮蔽人名（保留首尾字母，中間替換為 *）。
        例如：'John' → 'J**n'，'Doe' → 'D*e'

        Parameters
        ----------
        name : str | None
            原始姓名字串

        Returns
        -------
        str
            遮蔽後的字串
        """
        if not name or not isinstance(name, str):
            return "***"
        name = name.strip()
        if len(name) <= 2:
            return name[0] + "*" * (len(name) - 1)
        return name[0] + "*" * (len(name) - 2) + name[-1]

    # ── 私有方法 ──────────────────────────────────────────────────────────

    def _sha256(self, value: str) -> str:
        """
        回傳 value 加上 salt 後的 SHA-256 十六進位字串。
        """
        payload = f"{self.hash_salt}:{value}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── 便利函數（模組層級）─────────────────────────────────────────────────────

def get_leakage_columns() -> list:
    """回傳資料洩漏欄位清單（供 data_pipeline.py 使用）。"""
    return LEAKAGE_COLUMNS.copy()


def get_sensitive_columns() -> list:
    """回傳敏感欄位清單（供文件或稽核使用）。"""
    return SENSITIVE_COLUMNS.copy()


# ── 快速測試（直接執行此檔案時）────────────────────────────────────────────

if __name__ == "__main__":
    import pandas as pd

    print("=== security_utils.py 快速測試 ===\n")

    # 建立假資料
    sample = pd.DataFrame({
        "Order Id": [12345, 67890],
        "Customer Fname": ["John", "Mary"],
        "Customer Lname": ["Doe", "Chen"],
        "Customer Street": ["123 Main St", "456 Oak Ave"],
        "Customer Zipcode": ["10001", "20002"],
        "Days for shipment (scheduled)": [3, 5],
        "Late_delivery_risk": [1, 0],
    })

    print("原始資料：")
    print(sample.to_string())
    print()

    de_id = DeIdentifier()
    safe = de_id.apply_all(sample)

    print("\n去識別化後：")
    print(safe.to_string())

    print("\n[SUCCESS] 測試完成。敏感欄位已移除，Order Id 已雜湊。")
