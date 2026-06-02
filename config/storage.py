from django.conf import settings
from whitenoise.storage import CompressedManifestStaticFilesStorage


class SkipSourceMapsStorage(CompressedManifestStaticFilesStorage):
    def url(self, name, force=False):
        try:
            return super().url(name, force=force)
        except ValueError:
            # Jazzmin uses vendor/bootswatch as a directory base for its theme switcher.
            # Manifest storage only knows about files, so fall back to the plain static URL.
            if name.rstrip("/") == "vendor/bootswatch":
                return f"{settings.STATIC_URL.rstrip('/')}/vendor/bootswatch"
            raise

    def post_process(self, paths, dry_run=False, **options):
        for name, hashed_name, processed in super().post_process(paths, dry_run, **options):
            if isinstance(processed, Exception) and '.map' in str(processed):
                # Skip missing source map errors instead of crashing
                processed = True
            yield name, hashed_name, processed
