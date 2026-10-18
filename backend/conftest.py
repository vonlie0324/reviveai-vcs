import os

# Existing service/unit tests exercise the media pipeline directly. Authentication
# has its own tests and is disabled for the legacy suite so those tests remain
# deterministic and do not require live Firebase credentials.
os.environ.setdefault("FIREBASE_AUTH_REQUIRED", "false")
