# yourproject/storage.py  (same folder as settings.py)
from whitenoise.storage import CompressedManifestStaticFilesStorage

class SkipSourceMapsStorage(CompressedManifestStaticFilesStorage):
    """
    Subclass that silently skips missing source map (.map) file errors
    instead of raising MissingFileError during collectstatic.
    """
    def post_process(self, paths, dry_run=False, **options):
        for result in super().post_process(paths, dry_run, **options):
            if isinstance(result, Exception):
                # Swallow MissingFileError for source map files only
                if hasattr(result, 'args') and '.map' in str(result.args):
                    continue
            yield result