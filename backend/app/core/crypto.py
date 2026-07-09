"""AES 加解密工具 — 用于 API Key 等敏感信息的安全存储"""

import base64
import hashlib
import os

from cryptography.fernet import Fernet
from loguru import logger

from app.core.config import settings


def _get_fernet_key() -> bytes:
    """从 .env 的 ENCRYPT_KEY 派生 Fernet 密钥，不存在则自动生成并写回"""
    encrypt_key = getattr(settings, "ENCRYPT_KEY", "") or ""
    if not encrypt_key:
        # 首次启动：生成随机密钥，写入 .env
        encrypt_key = Fernet.generate_key().decode()
        _write_encrypt_key_to_env(encrypt_key)
        logger.info("已自动生成 ENCRYPT_KEY 并写入 .env")
    return encrypt_key.encode()


def _write_encrypt_key_to_env(key: str):
    """将 ENCRYPT_KEY 写入 .env 文件"""
    env_path = _get_env_path()
    lines = []
    found = False
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("ENCRYPT_KEY="):
                    lines.append(f"ENCRYPT_KEY={key}\n")
                    found = True
                else:
                    lines.append(line)
    except FileNotFoundError:
        pass
    if not found:
        lines.append(f"ENCRYPT_KEY={key}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    # 同步到运行时 settings
    settings.ENCRYPT_KEY = key


def _get_env_path() -> str:
    """获取 .env 文件路径"""
    import os
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))), ".env")
    if os.path.exists(env_path):
        return env_path
    return ".env"


_fernet: Fernet = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_get_fernet_key())
    return _fernet


def encrypt(plaintext: str) -> str:
    """加密明文，返回 base64 字符串"""
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """解密 base64 字符串，返回明文"""
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except Exception as e:
        logger.warning(f"解密失败: {e}")
        return ""
