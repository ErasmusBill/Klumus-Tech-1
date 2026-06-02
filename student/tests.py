from django.contrib.staticfiles import finders
from django.test import SimpleTestCase


class StudentStaticAssetTests(SimpleTestCase):
    def test_empty_assignments_illustration_exists(self):
        self.assertIsNotNone(
            finders.find("assets/img/no-tasks.svg"),
            "Expected student empty-state illustration to exist at static/assets/img/no-tasks.svg.",
        )

    def test_billing_empty_state_illustration_exists(self):
        self.assertIsNotNone(
            finders.find("assets/img/no-billing.svg"),
            "Expected billing empty-state illustration to exist at static/assets/img/no-billing.svg.",
        )
