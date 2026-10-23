"""Small, dependency-light helpers for Django environment configuration.

Lists are comma-separated; malformed values fail fast with helpful errors.
"""
import os
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


_TRUE = {"1", "true", "yes", "on", "t"}
_FALSE = {"0", "false", "no", "off", "f"}


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean (true/false), got {raw!r}.")


def env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer.") from exc
    if value < minimum:
        raise ImproperlyConfigured(f"{name} must be >= {minimum}.")
    return value


def env_csv(name: str, default=()) -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        return list(default)
    return [part.strip() for part in raw.split(",") if part.strip()]


def env_origins(name: str, default=()) -> list[str]:
    """Read trusted HTTP(S) origins; tolerate pasted Markdown-escaped colons.

    CORS and CSRF origins must be scheme + hostname (+ optional port), not paths.
    """
    origins = []
    for entry in env_csv(name, default):
        origin = entry.replace(r"\:", ":").rstrip("\\").rstrip("/")
        try:
            parsed = urlsplit(origin)
            port = parsed.port  # Force invalid ports to raise ValueError.
            valid = (
                parsed.scheme in ("http", "https")
                and bool(parsed.hostname)
                and not parsed.username
                and not parsed.password
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
                and (port is None or 0 < port <= 65535)
                and not any(character.isspace() for character in origin)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ImproperlyConfigured(
                f"Invalid origin in {name}: {entry!r}. "
                "Use comma-separated URLs such as http://localhost:5175 without paths."
            )
        if origin not in origins:
            origins.append(origin)
    return origins
