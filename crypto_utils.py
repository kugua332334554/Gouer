import hashlib
import base64
import logging

logger = logging.getLogger(__name__)

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet

    from cryptography.fernet import Fernet

    import config
    key = config.ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY (env KEY) is not set — cannot encrypt/decrypt bot tokens. "
            "Set KEY=<your-secret> in .env."
        )
    # Derive a 32-byte key from the raw KEY string, then base64-encode for Fernet.
    derived = hashlib.sha256(key.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(derived)
    _fernet = Fernet(fernet_key)
    return _fernet

#ecp
def encrypt_token(token: str) -> str:
    if not token:
        return ""
    try:
        f = _get_fernet()
        return f.encrypt(token.encode("utf-8")).decode("ascii")
    except Exception as e:
        logger.warning(f"encrypt_token failed, storing as plaintext: {e}")
        return token  # 回退：明文存储

#dcp
def decrypt_token(encrypted: str) -> str:
    if not encrypted:
        return ""
    try:
        f = _get_fernet()
        return f.decrypt(encrypted.encode("ascii")).decode("utf-8")
    except Exception as e:
        # 旧数据可能未加密，直接返回原始值作为明文
        logger.warning(f"decrypt_token failed (likely plaintext legacy data): {e}")
        return encrypted

#hashtoken
def hash_token(token: str) -> str:
    if not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
