"""
auth.py
EDIS 登入驗證模組
使用 SQLite 儲存使用者帳號；密碼以 bcrypt 雜湊（含 per-user salt、刻意慢速）。
Session token 使用 HMAC-SHA256 簽章，簽章金鑰改由環境變數讀取。
"""
import sqlite3
import hashlib  # token 簽章 (HMAC-SHA256) 使用
import os
from pathlib import Path

import bcrypt

DB_PATH = Path(__file__).parent.parent / "data" / "edis_users.db"


def hash_password(password: str) -> str:
    """以 bcrypt 雜湊密碼（含隨機 salt），回傳可儲存的字串。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _is_bcrypt_hash(value) -> bool:
    """判斷字串是否為 bcrypt 雜湊（$2a$/$2b$/$2y$ 開頭）。"""
    return isinstance(value, str) and value.startswith(("$2a$", "$2b$", "$2y$"))

def init_db():
    """初始化資料庫，建立 users 表格"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'Viewer',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()

    # 建立/維護測試帳號（密碼以 bcrypt 雜湊）
    # 遷移策略（直接重建）：偵測到既有帳號仍是舊 SHA-256 格式 → 直接重寫為 bcrypt
    test_accounts = [
        ("admin", "edis1234", "Logistics_Manager"),
        ("viewer", "view1234", "Viewer"),
    ]
    for username, password, role in test_accounts:
        c.execute("SELECT password_hash FROM users WHERE username=?", (username,))
        row = c.fetchone()
        if row is None:
            c.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, hash_password(password), role)
            )
        elif not _is_bcrypt_hash(row[0]):
            c.execute(
                "UPDATE users SET password_hash=?, role=? WHERE username=?",
                (hash_password(password), role, username)
            )

    conn.commit()
    conn.close()
    print(f"[Auth] 資料庫初始化完成（bcrypt）：{DB_PATH}")

def verify_user(username: str, password: str):
    """
    驗證使用者帳號密碼。
    先依 username 取出 bcrypt 雜湊，再用 bcrypt.checkpw 比對
    （bcrypt 含隨機 salt，無法用 SQL 的 = 直接比對）。
    回傳 {"success": True, "role": "Logistics_Manager"} 或 {"success": False, "role": None}
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT password_hash, role FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if not row:
        return {"success": False, "role": None}
    stored_hash, role = row
    try:
        ok = bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # 雜湊格式異常（理論上 init_db 已升級），一律視為驗證失敗
        ok = False
    if ok:
        return {"success": True, "role": role}
    return {"success": False, "role": None}

# ── Cryptographic Stateless Session Tokens (JWT-like) ───────────────────
import hmac
import base64
import json
import time

# 簽章金鑰改由環境變數讀取，避免將祕密寫死在原始碼/版本控制中。
# 未設定環境變數時退回開發用 fallback，讓本地 demo 仍可運作（正式環境請設定 EDIS_SECRET_KEY）。
SECRET_KEY = os.environ.get("EDIS_SECRET_KEY", "edis_super_secret_key_2026_rf").encode()

def generate_token(username: str, role: str) -> str:
    """Generate a cryptographic signature token containing user role and expiration."""
    payload = {
        "username": username,
        "role": role,
        "exp": time.time() + 86400  # 24 hours validity
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    signature = hmac.new(SECRET_KEY, payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"

def verify_token(token: str) -> dict:
    """Verify the signature and expiration of the token, returning payload info if valid."""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return {"success": False, "message": "Invalid token format"}
        payload_b64, signature = parts
        expected_sig = hmac.new(SECRET_KEY, payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, signature):
            return {"success": False, "message": "Signature mismatch"}
        payload_str = base64.urlsafe_b64decode(payload_b64.encode()).decode()
        payload = json.loads(payload_str)
        if time.time() > payload.get("exp", 0):
            return {"success": False, "message": "Token expired"}
        return {"success": True, "username": payload["username"], "role": payload["role"]}
    except Exception as e:
        return {"success": False, "message": f"Token verification error: {str(e)}"}

if __name__ == "__main__":
    init_db()
    print("測試帳號：")
    print("  Manager → username: admin    password: edis1234")
    print("  Viewer  → username: viewer   password: view1234")

