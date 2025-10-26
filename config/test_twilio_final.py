# test_twilio_final.py
import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN") 
phone_number = os.getenv("TWILIO_PHONE_NUMBER")

print("Testing Twilio with CORRECT credentials...")
print(f"Account SID: {account_sid}")

try:
    client = Client(account_sid, auth_token)
    
    # Test authentication
    account = client.api.accounts(account_sid).fetch()
    print(f"✅ SUCCESS: Authenticated as {account.friendly_name}")
    
    # Test sending capability
    print("✅ Twilio credentials are VALID!")
    
except Exception as e:
    print(f"❌ FAILED: {e}")