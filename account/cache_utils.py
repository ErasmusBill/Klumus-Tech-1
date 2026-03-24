from django.core.cache import cache


def _cache_version_key(school_id, section: str) -> str:
    return f"cache_version:{section}:{school_id}"


def get_cache_version(school_id, section: str) -> int:
    return cache.get(_cache_version_key(school_id, section), 1)


def bump_cache_version(school_id, section: str) -> None:
    key = _cache_version_key(school_id, section)
    try:
        cache.incr(key)
    except Exception:
        current = cache.get(key, 1)
        cache.set(key, current + 1, None)


def make_cache_key(section: str, school_id, suffix: str = "") -> str:
    version = get_cache_version(school_id, section)
    return f"{section}:{school_id}:v{version}:{suffix}"


def make_user_cache_key(section: str, user_id, suffix: str = "") -> str:
    # User-scoped keys reuse the same versioning format with `user` as namespace.
    version = get_cache_version(user_id, f"user:{section}")
    return f"user:{section}:{user_id}:v{version}:{suffix}"


def bump_user_cache_version(user_id, section: str) -> None:
    bump_cache_version(user_id, f"user:{section}")


def should_cache(request) -> bool:
    return request.method == "GET" and not request.session.get("_messages")
