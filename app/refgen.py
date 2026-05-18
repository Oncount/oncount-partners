import secrets
import string

ALPHABET = string.ascii_lowercase + string.digits


def generate_ref_slug(length: int = 6) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))
