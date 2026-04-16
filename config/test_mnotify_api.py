import os
import unittest

import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("MNOTIFY_API_KEY")
sender_id = os.getenv("MNOTIFY_SENDER_ID")
base_url = os.getenv("MNOTIFY_BASE_URL", "https://api.mnotify.com/api").rstrip("/")
run_mnotify_tests = os.getenv("RUN_MNOTIFY_TESTS") == "1"

if not run_mnotify_tests:
    print("Skipping MNotify tests. Set RUN_MNOTIFY_TESTS=1 to enable.")
    raise unittest.SkipTest("MNotify tests disabled")


class TestMNotifyAPI(unittest.TestCase):
    def test_balance_endpoint(self):
        self.assertTrue(api_key, "MNOTIFY_API_KEY is required")
        response = requests.get(f"{base_url}/balance/sms?key={api_key}", timeout=15)
        response.raise_for_status()
        payload = response.json()
        self.assertEqual(str(payload.get("status", "")).lower(), "success")

    def test_sender_status_endpoint(self):
        self.assertTrue(api_key, "MNOTIFY_API_KEY is required")
        self.assertTrue(sender_id, "MNOTIFY_SENDER_ID is required")
        response = requests.post(
            f"{base_url}/senderid/status/?key={api_key}",
            json={"sender_name": sender_id},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        self.assertEqual(str(payload.get("status", "")).lower(), "success")
