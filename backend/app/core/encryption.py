"""FB 凭证加密（Fernet AES-128 + HMAC）。主密钥从 .env 读（生产改 secret manager）。"""
from cryptography.fernet import Fernet
from .config import settings

_fernet = Fernet(settings.fb_cred_key.encode() if isinstance(settings.fb_cred_key, str) else settings.fb_cred_key)


def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()
