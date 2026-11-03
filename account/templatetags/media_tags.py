from django import template
from django.core.files.storage import default_storage
from django.templatetags.static import static

register = template.Library()


@register.filter
def safe_media_url(value, fallback=""):
    """
    Return a safe URL for FileField/ImageField values.
    Falls back to a static asset if provided, otherwise empty string.
    Removes any fallback avatar images for users in the system.
    """
    # Remove any user avatar fallback images
    if fallback and ("avatar" in fallback or "profile" in fallback):
        fallback = ""

    fallback_url = static(fallback) if fallback else ""

    if not value:
        return fallback_url

    # Accept plain string paths/URLs in templates as a safe fallback path.
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return fallback_url
        if candidate.startswith(("http://", "https://", "/")):
            return candidate
        try:
            if default_storage.exists(candidate):
                return default_storage.url(candidate)
        except Exception:
            pass
        return fallback_url

    # If this is a FieldFile and the backing file is missing, use fallback.
    name = getattr(value, "name", None)
    storage = getattr(value, "storage", None)
    if name and storage:
        try:
            if not storage.exists(name):
                return fallback_url
        except Exception:
            # Ignore storage lookup failures and try URL resolution below.
            pass

    try:
        url = value.url
        return url or fallback_url
    except Exception:
        return fallback_url


@register.filter
def user_initials(value):
    """
    Return 1-2 uppercase initials for a User, Teacher, Student, Parent, or name string.
    Used when a user has not provided a profile picture.
    """
    if not value:
        return "U"
    if hasattr(value, "initials") and value.initials:
        return value.initials
    if hasattr(value, "user") and hasattr(value.user, "initials") and value.user.initials:
        return value.user.initials
    if hasattr(value, "get_full_name"):
        name = value.get_full_name() or getattr(value, "username", "")
    elif isinstance(value, str):
        name = value
    else:
        name = str(value)
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1][0]}".upper()
    elif len(parts) == 1 and parts[0]:
        return parts[0][:2].upper()
    return "U"
