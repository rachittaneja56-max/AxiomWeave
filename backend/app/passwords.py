from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

password_hasher = PasswordHasher(
    time_cost=2, memory_cost=19_456, parallelism=1, hash_len=32, salt_len=16
)
_DUMMY_PASSWORD_HASH = password_hasher.hash("axiomweave dummy verifier value")
_BLOCKED_PASSWORDS = {
    "password",
    "password123",
    "123456789",
    "qwerty",
    "letmein",
    "axiomweave",
    "axiomweave123",
}


def normalize_username(username: str) -> str:
    normalized = username.strip().lower()
    if not 3 <= len(normalized) <= 64:
        raise ValueError("Username must be 3 to 64 characters.")
    if any(char not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for char in normalized):
        raise ValueError(
            "Username may contain only letters, numbers, dots, underscores, and hyphens."
        )
    return normalized


def validate_password(password: str) -> None:
    length = len(password)
    if not 15 <= length <= 128:
        raise ValueError("Password must be 15 to 128 characters.")
    if password.casefold() in _BLOCKED_PASSWORDS:
        raise ValueError("Choose a less common password.")


def hash_password(password: str) -> str:
    validate_password(password)
    return password_hasher.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        return password_hasher.verify(encoded_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def verify_dummy_password(password: str) -> None:
    verify_password(password, _DUMMY_PASSWORD_HASH)


def password_needs_rehash(encoded_hash: str) -> bool:
    try:
        return password_hasher.check_needs_rehash(encoded_hash)
    except (InvalidHashError, VerificationError):
        return False
