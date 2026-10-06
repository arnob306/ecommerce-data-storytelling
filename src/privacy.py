"""
Customer privacy helpers.

Customer names never leave the adapter. They are replaced with a keyed hash
(HMAC-SHA256) so repeat customers can still be counted without storing who
they are. A plain unsalted hash of a short name is trivially reversible, so
the key (salt) lives in the environment and the code fails closed without it.
"""

import hashlib
import hmac
import os
import re
from typing import Optional

MIN_SALT_LENGTH = 16
HASH_LENGTH = 16
SALT_ENV_VAR = 'CUSTOMER_HASH_SALT'

_WHITESPACE_RE = re.compile(r'\s+')


class PrivacyError(RuntimeError):
    """Raised when privacy settings are missing or unsafe."""


def get_salt() -> str:
    """Return the hashing key from the environment, failing closed."""
    salt = os.environ.get(SALT_ENV_VAR, '')
    if len(salt) < MIN_SALT_LENGTH:
        raise PrivacyError(
            f'{SALT_ENV_VAR} must be set to a secret of at least '
            f'{MIN_SALT_LENGTH} characters (put it in .env, never in git).'
        )
    return salt


def _normalise(value: object) -> str:
    if not isinstance(value, str):
        return ''
    return _WHITESPACE_RE.sub(' ', value).strip().casefold()


def hash_customer(
    name: object, suburb: object, salt: str
) -> Optional[str]:
    """
    Return a stable pseudonymous ID for a customer, or None if unnamed.

    Name plus suburb is used because "Jane D." alone is not unique.
    """
    if len(salt) < MIN_SALT_LENGTH:
        raise PrivacyError('Salt is too short to be safe.')
    clean_name = _normalise(name)
    if not clean_name:
        return None
    message = f'{clean_name}|{_normalise(suburb)}'.encode('utf-8')
    digest = hmac.new(salt.encode('utf-8'), message, hashlib.sha256)
    return digest.hexdigest()[:HASH_LENGTH]
