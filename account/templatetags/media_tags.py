from django import template
from django.templatetags.static import static

register = template.Library()


@register.filter
def safe_media_url(value, fallback=""):
    """
    Return a safe URL for FileField/ImageField values.
    Falls back to a static asset if provided, otherwise empty string.
    """
    if not value:
        return static(fallback) if fallback else ""
    try:
        return value.url
    except Exception:
        return static(fallback) if fallback else ""
