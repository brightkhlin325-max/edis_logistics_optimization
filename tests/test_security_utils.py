"""
tests/test_security_utils.py
DeIdentifier（去識別化 / 第一層資料安全防護）單元測試。

涵蓋：
  - 敏感欄位刪除
  - Order Id → SHA-256 雜湊（決定性、salt 影響、欄位改名）
  - 人名遮蔽 mask_name 各邊界情況
  - apply_all 綜合管線
"""

import pandas as pd

from security_utils import (
    DeIdentifier,
    get_leakage_columns,
    get_sensitive_columns,
)


def _raw():
    return pd.DataFrame({
        "Order Id": [12345, 67890],
        "Customer Fname": ["John", "Mary"],
        "Customer Lname": ["Doe", "Chen"],
        "Customer Street": ["123 Main St", "456 Oak Ave"],
        "Customer Zipcode": ["10001", "20002"],
        "Days for shipment (scheduled)": [3, 5],
    })


def test_drop_sensitive_columns_removes_pii():
    safe = DeIdentifier().drop_sensitive_columns(_raw())
    for col in ("Customer Fname", "Customer Lname",
                "Customer Street", "Customer Zipcode"):
        assert col not in safe.columns
    # 非敏感欄位保留
    assert "Days for shipment (scheduled)" in safe.columns


def test_hash_id_columns_renames_and_hashes():
    out = DeIdentifier().hash_id_columns(_raw())
    assert "Order Id" not in out.columns
    assert "Order Id_hash" in out.columns
    # SHA-256 十六進位為 64 字元
    assert out["Order Id_hash"].str.len().eq(64).all()
    # 原始明文不應殘留
    assert not out["Order Id_hash"].astype(str).str.contains("12345").any()


def test_hash_is_deterministic_and_salt_sensitive():
    a = DeIdentifier(hash_salt="A")._sha256("12345")
    a2 = DeIdentifier(hash_salt="A")._sha256("12345")
    b = DeIdentifier(hash_salt="B")._sha256("12345")
    assert a == a2          # 相同 salt + 輸入 → 相同雜湊（決定性）
    assert a != b           # 不同 salt → 不同雜湊（防彩虹表）
    assert len(a) == 64


def test_mask_name_variants():
    d = DeIdentifier()
    assert d.mask_name("John") == "J**n"
    assert d.mask_name("Doe") == "D*e"
    assert d.mask_name("Al") == "A*"
    assert d.mask_name("X") == "X"
    assert d.mask_name("") == "***"
    assert d.mask_name(None) == "***"


def test_apply_all_pipeline():
    safe = DeIdentifier().apply_all(_raw())
    # 敏感欄位全消、ID 已雜湊改名
    assert "Customer Fname" not in safe.columns
    assert "Order Id_hash" in safe.columns
    assert "Order Id" not in safe.columns


def test_column_helpers_return_copies():
    leak = get_leakage_columns()
    leak.append("MUTATED")
    assert "MUTATED" not in get_leakage_columns()  # 回傳的是複本，不可污染原清單
    assert "Customer Email" in get_sensitive_columns()
