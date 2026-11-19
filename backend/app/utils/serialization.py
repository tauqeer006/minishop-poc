import uuid
from datetime import datetime, timezone

SENSITIVE_KEYS = {
    "password", "password_hash", "token", "access_token", "authorization", "jwt",
    "secret", "api_key", "cookie", "set-cookie",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def public(obj):
    """Recursively convert a Mongo document to JSON-safe data: `_id`->`id`, datetimes->ISO strings.
    Internal fields (password hashes, TTL markers, request fingerprints) are never exposed."""
    hidden = {"password_hash", "expire_at", "request_fingerprint", "processed", "window_id"}
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in hidden:
                continue
            out["id" if k == "_id" else k] = public(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [public(v) for v in obj]
    if isinstance(obj, datetime):
        return iso(obj)
    return obj


def sanitize(obj, depth: int = 0):
    """Strip secrets from anything headed to an observability collection."""
    if depth > 6:
        return "<truncated>"
    if isinstance(obj, dict):
        return {
            str(k): ("<redacted>" if str(k).lower() in SENSITIVE_KEYS else sanitize(v, depth + 1))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [sanitize(v, depth + 1) for v in obj[:50]]
    if isinstance(obj, str) and len(obj) > 500:
        return obj[:500] + "..."
    return obj
