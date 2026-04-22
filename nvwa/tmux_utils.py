import hashlib
import re


DEFAULT_TMUX_SESSION_NAME_MAX_LENGTH = 64
_SESSION_PREFIX = "nwtool"
_INVALID_CHARACTERS = re.compile(r"[^A-Za-z0-9_-]+")
_DASH_RUNS = re.compile(r"-{2,}")


def _short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


def build_tmux_session_name(project: str, tag: str, max_length: int = DEFAULT_TMUX_SESSION_NAME_MAX_LENGTH) -> str:
    raw_name = f"{_SESSION_PREFIX}-{project}-{tag}"
    sanitized = raw_name.replace(".", "-").replace(":", "-")
    sanitized = re.sub(r"\s+", "-", sanitized)
    sanitized = _INVALID_CHARACTERS.sub("-", sanitized)
    sanitized = _DASH_RUNS.sub("-", sanitized).strip("-")

    suffix_hash = _short_hash(raw_name)
    fallback_name = f"{_SESSION_PREFIX}-{suffix_hash}"
    if not sanitized or sanitized == _SESSION_PREFIX:
        return fallback_name

    if len(sanitized) <= max_length:
        return sanitized

    suffix = f"-{suffix_hash}"
    prefix_length = max_length - len(suffix)
    if prefix_length <= 0:
        return fallback_name[:max_length]

    truncated = sanitized[:prefix_length].rstrip("-")
    if not truncated:
        return fallback_name[:max_length]
    return f"{truncated}{suffix}"
