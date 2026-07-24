"""
Xtremio Crypto Service
======================
Functions for cryptography and hash encoding/decoding.
"""
from __future__ import annotations

from base64 import b64decode, b64encode
from json import dumps, loads
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from config import FERNET_KEY, InvalidHashError, logger

fernet = Fernet(FERNET_KEY)


def decode_hash(hash_str: str) -> dict[str, Any]:
    """
    Decodes the hash, auto-detecting base64 or Fernet encryption.

    Args:
        hash_str: Encoded string.

    Returns:
        Decoded dictionary.

    Raises:
        InvalidHashError: If hash is invalid or corrupted.
    """
    try:
        decoded = fernet.decrypt(hash_str.encode())
        return loads(decoded.decode("utf-8"))
    except (InvalidToken, ValueError):
        pass

    try:
        decoded_bytes = b64decode(hash_str)
        try:
            return loads(decoded_bytes.decode("utf-8"))
        except UnicodeDecodeError:
            return loads(decoded_bytes.decode("latin1"))
    except Exception as exc:
        raise InvalidHashError("Invalid or corrupted hash") from exc


def encode_hash(data: dict[str, Any], use_fernet: bool = False) -> str:
    """
    Encodes dictionary to Base64 or Fernet hash.

    Args:
        data: Dictionary to encode.
        use_fernet: If True, uses Fernet encryption.

    Returns:
        Encoded string.
    """
    raw = dumps(data).encode("utf-8")
    if use_fernet:
        return fernet.encrypt(raw).decode()
    return b64encode(raw).decode()
