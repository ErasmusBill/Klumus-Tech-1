from django import template
from django.templatetags.static import static

register = template.Library()


@register.filter
def safe_media_url(value, fallback=""):
    """
    Return a safe URL for FileField/ImageField values.
    Falls back to a static asset if provided, otherwise empty string.
    """
    fallback_url = static(fallback) if fallback else ""

    if not value:
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
