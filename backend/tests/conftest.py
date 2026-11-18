import os
from secrets import token_urlsafe


TEST_DATABASE = os.getenv("DOCUMENT_TEST_DATABASE_URL")
os.environ["DATABASE_URL"] = TEST_DATABASE or "postgresql+psycopg://testing@127.0.0.1:1/testing"
if os.getenv("RUN_LIVE_CALENDAR_TEST") != "1":
    os.environ.setdefault("JWT_SECRET_KEY", token_urlsafe(48))
