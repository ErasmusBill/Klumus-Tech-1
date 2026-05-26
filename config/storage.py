
from whitenoise.storage import CompressedManifestStaticFilesStorage

class SkipSourceMapsStorage(CompressedManifestStaticFilesStorage):
    def post_process(self, paths, dry_run=False, **options):
        for name, hashed_name, processed in super().post_process(paths, dry_run, **options):
            if isinstance(processed, Exception) and '.map' in str(processed):
                # Skip missing source map errors instead of crashing
                processed = True
            yield name, hashed_name, processed