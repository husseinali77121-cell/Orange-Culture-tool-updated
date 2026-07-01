#!/usr/bin/env python3
"""
Generate a password hash for the Streamlit `subscribers` secret.

Usage:
    python make_password_hash.py

Then paste the result into .streamlit/secrets.toml, e.g.:

    subscribers_json = '''
    {
      "doctor@hospital.com": {
        "expiry": "2026-12-31",
        "password": "pbkdf2_sha256$200000$....$...."
      },
      "legacy@old.com": "2026-06-30"   # still works, no password required
    }
    '''
"""

import getpass
from auth_utils import hash_password

if __name__ == "__main__":
    pw1 = getpass.getpass("New password: ")
    pw2 = getpass.getpass("Confirm password: ")
    if pw1 != pw2:
        raise SystemExit("❌ Passwords do not match.")
    if len(pw1) < 8:
        print("⚠️  Warning: password is shorter than 8 characters.")
    print("\nCopy this into the user's record as \"password\":\n")
    print(hash_password(pw1))
