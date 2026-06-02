from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from whitenoise.storage import CompressedManifestStaticFilesStorage

from config.storage import SkipSourceMapsStorage


class SkipSourceMapsStorageTests(SimpleTestCase):
    @override_settings(STATIC_URL="/static/")
    def test_vendor_bootswatch_directory_falls_back_to_plain_static_url(self):
        storage = SkipSourceMapsStorage()

        with patch.object(
            CompressedManifestStaticFilesStorage,
            "url",
            side_effect=ValueError("Missing staticfiles manifest entry for 'vendor/bootswatch'"),
        ):
            self.assertEqual(storage.url("vendor/bootswatch"), "/static/vendor/bootswatch")

    @override_settings(STATIC_URL="/static/")
    def test_other_missing_assets_still_raise(self):
        storage = SkipSourceMapsStorage()

        with patch.object(
            CompressedManifestStaticFilesStorage,
            "url",
            side_effect=ValueError("Missing staticfiles manifest entry for 'vendor/adminlte/css/adminlte.min.css'"),
        ):
            with self.assertRaises(ValueError):
                storage.url("vendor/adminlte/css/adminlte.min.css")
