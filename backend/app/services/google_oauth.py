from base64 import urlsafe_b64encode
from datetime import timedelta
from hashlib import sha256
from secrets import compare_digest, token_urlsafe
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import delete, select

from app.ai.llm import TutorError
from app.models.planner import CalendarConnection, OAuthState
from app.services.conversation_service import now
from app.services.google_calendar import check_scopes, configuration, connection, decode_secret, encode_secret, lock_owner, provider, rate

COOKIE = "study_calendar_oauth"


def digest(value):
    return sha256(value.encode()).hexdigest()


def begin(db, owner):
    settings = configuration()
    lock_owner(db, owner)
    rate(db, owner)
    db.execute(delete(OAuthState).where(OAuthState.user_id == owner))
    db.execute(delete(OAuthState).where(OAuthState.expires_at < now() - timedelta(hours=1)))
    ticket = token_urlsafe(32)
    db.add(OAuthState(user_id=owner, ticket_digest=digest(ticket), expires_at=now() + timedelta(minutes=10)))
    db.commit()
    start = settings.google_oauth_redirect_uri.rsplit("/", 1)[0] + "/launch"
    return start + "?" + urlencode({"ticket": ticket})


def launch(db, ticket):
    settings = configuration()
    row = db.scalar(select(OAuthState).where(OAuthState.ticket_digest == digest(ticket)).with_for_update())
    if not row or row.expires_at <= now() or row.used_at:
        raise TutorError("oauth_state", "This Calendar connection link expired. Start again.", 400)
    state, browser, verifier = (token_urlsafe(48) for _ in range(3))
    row.ticket_digest = None
    row.state_digest = digest(state)
    row.browser_digest = digest(browser)
    row.encrypted_verifier = encode_secret(verifier)
    db.commit()
    params = dict(client_id=settings.google_oauth_client_id, redirect_uri=settings.google_oauth_redirect_uri,
                  response_type="code", scope=settings.google_calendar_scopes, access_type="offline", prompt="consent",
                  state=state, code_challenge=urlsafe_b64encode(sha256(verifier.encode()).digest()).rstrip(b"=").decode(),
                  code_challenge_method="S256")
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params), browser


def finish(db, *, state, browser, code, denied):
    settings = configuration()
    if not state or not browser:
        raise TutorError("oauth_state", "Invalid Calendar authorization state.", 400)
    row = db.scalar(select(OAuthState).where(OAuthState.state_digest == digest(state)).with_for_update())
    if not row or not compare_digest(row.browser_digest or "", digest(browser)) or row.used_at or row.expires_at <= now():
        raise TutorError("oauth_state", "Invalid or expired Calendar authorization state.", 400)
    owner, state_id = row.user_id, row.id
    verifier = decode_secret(row.encrypted_verifier)
    row.used_at = now()
    row.encrypted_verifier = None
    db.commit()
    if denied:
        return "denied"
    if not code:
        raise TutorError("oauth_code", "Google did not return an authorization code.", 400)
    result = provider().tokens(grant_type="authorization_code", code=code, code_verifier=verifier,
                              redirect_uri=settings.google_oauth_redirect_uri)
    scopes = check_scopes(result.get("scope"))
    refresh = result.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        raise TutorError("oauth_refresh", "Google did not grant offline access. Reconnect and grant consent.", 409)
    identity = provider().userinfo(result["access_token"])
    account, email = identity.get("sub"), identity.get("email")
    if not isinstance(account, str) or not 1 <= len(account) <= 180:
        raise TutorError("oauth_identity", "Google did not return a valid account identifier.", 409)
    lock_owner(db, owner)
    if db.get(OAuthState, state_id, populate_existing=True) is None:
        raise TutorError("oauth_state", "The Calendar authorization was superseded.", 400)
    row = connection(db, owner)
    if row is None:
        row = CalendarConnection(user_id=owner, status="connected")
        db.add(row)
    if row.google_account_id != account:
        row.selected_calendar = None
        row.last_synced_at = None
    row.google_account_id = account
    row.google_email = email[:320] if identity.get("email_verified") is True and isinstance(email, str) else None
    row.encrypted_refresh_token = encode_secret(refresh)
    row.encrypted_access_token = encode_secret(result["access_token"])
    row.access_expires_at = now() + timedelta(seconds=result["expires_in"])
    row.scopes = scopes
    row.status = "connected"
    row.connected_at = now()
    row.last_refreshed_at = None
    db.commit()
    return "connected"


def disconnect(db, owner):
    lock_owner(db, owner)
    db.execute(delete(OAuthState).where(OAuthState.user_id == owner))
    row = connection(db, owner)
    if not row:
        db.commit()
        return True
    revoked = True
    if row.encrypted_refresh_token:
        try:
            provider().revoke(decode_secret(row.encrypted_refresh_token))
        except TutorError:
            revoked = False
    row.encrypted_refresh_token = row.encrypted_access_token = None
    row.access_expires_at = None
    row.google_email = None
    row.selected_calendar = None
    row.scopes = []
    row.status = "disconnected"
    db.commit()
    return revoked
