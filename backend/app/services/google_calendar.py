from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from time import sleep
from urllib.parse import quote, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, text

from app.ai.llm import TutorError
from app.core.config import get_settings
from app.models.planner import CalendarConnection, CalendarRate
from app.schemas.planner import zone
from app.services.conversation_service import now

EVENT_SCOPE = "https://www.googleapis.com/auth/calendar.events"
LIST_SCOPE = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
REQUIRED = {EVENT_SCOPE, LIST_SCOPE, "openid", "email"}
EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
ROOT = "https://www.googleapis.com/calendar/v3"
TOKEN = "https://oauth2.googleapis.com/token"
USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


def lock_owner(db, owner):
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"), {"scope": f"revision:{owner}"})


def rate(db, owner):
    current = now().replace(second=0, microsecond=0)
    entry = db.get(CalendarRate, owner)
    if entry is None:
        db.add(CalendarRate(user_id=owner, bucket=current, count=1))
    elif entry.bucket != current:
        entry.bucket, entry.count = current, 1
    else:
        if entry.count >= get_settings().calendar_requests_per_minute:
            raise TutorError("calendar_rate", "Calendar request limit reached. Try again in a minute.", 429)
        entry.count += 1
    db.flush()


def connection(db, owner):
    return db.scalar(select(CalendarConnection).where(CalendarConnection.user_id == owner))


def encryption():
    settings = get_settings()
    try:
        return Fernet(settings.calendar_token_encryption_key.get_secret_value().encode())
    except (AttributeError, ValueError, TypeError) as error:
        raise TutorError("calendar_config", "Configure the Calendar encryption key on the backend.", 503) from error


def configuration():
    settings = get_settings()
    encryption()
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise TutorError("calendar_config", "Configure the Google OAuth client on the backend.", 503)
    if set(settings.google_calendar_scopes.split()) != REQUIRED:
        raise TutorError("calendar_config", "Configure the four documented Google Calendar and account scopes.", 503)
    redirect = urlsplit(settings.google_oauth_redirect_uri)
    frontend = urlsplit(settings.planner_frontend_url)
    for target in (redirect, frontend):
        if (not target.hostname or target.username or target.password or target.query or target.fragment
                or (target.scheme != "https" and not (target.scheme == "http" and target.hostname in {"127.0.0.1", "localhost", "::1"}))):
            raise TutorError("calendar_config", "Check the Calendar application URLs.", 503)
    if redirect.path != "/api/v1/integrations/google/callback" or frontend.path not in ("", "/"):
        raise TutorError("calendar_config", "Use the documented Calendar callback and frontend origin.", 503)
    return settings


def encode_secret(value):
    return encryption().encrypt(value.encode()).decode()


def decode_secret(value):
    try:
        return encryption().decrypt(value.encode()).decode()
    except (InvalidToken, AttributeError) as error:
        raise TutorError("calendar_reconnect", "Reconnect Google Calendar to restore authorization.", 409) from error


class GoogleError(TutorError):
    def __init__(self, remote_status, message="Google Calendar could not complete the request.", *, code="calendar_provider"):
        status = remote_status if remote_status in {404, 409, 412, 429} else 503
        super().__init__(code, message, status)
        self.remote_status = remote_status


class GoogleCalendar:
    def __init__(self, client):
        self.client = client

    def send(self, method, url, *, token=None, retry=False, **kwargs):
        for attempt in range(2 if retry else 1):
            headers = kwargs.get("headers", {}).copy()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            options = {key: value for key, value in kwargs.items() if key != "headers"}
            try:
                response = self.client.request(method, url, headers=headers, **options)
            except httpx.TransportError as error:
                if retry and attempt == 0:
                    sleep(.4)
                    continue
                raise GoogleError(503, "Google Calendar did not respond. Try again.") from error
            if response.is_success:
                try:
                    return response.json() if response.content else {}
                except ValueError as error:
                    if url.endswith("/revoke"):
                        return {}
                    raise GoogleError(503, "Google returned an unreadable response.") from error
            code = response.status_code
            if retry and attempt == 0 and code in {429, 500, 502, 503, 504}:
                delay = response.headers.get("Retry-After", "")
                if delay and (not delay.isdecimal() or int(delay) > 2):
                    raise GoogleError(code, "Google asked the app to retry later.")
                sleep(float(delay) if delay else .5)
                continue
            try:
                invalid_grant = response.json().get("error") == "invalid_grant"
            except (ValueError, AttributeError):
                invalid_grant = False
            if invalid_grant or code == 401:
                raise GoogleError(code, "Google authorization has expired. Reconnect Calendar.", code="calendar_reconnect")
            if code == 429:
                raise GoogleError(code, "Google Calendar quota is temporarily exhausted. Try again later.")
            if code == 403:
                raise GoogleError(code, "Google denied this calendar operation. Check consent and calendar access.")
            raise GoogleError(code)
        raise AssertionError("Unreachable Google request retry state")

    def tokens(self, **data):
        settings = configuration()
        result = self.send("POST", TOKEN, data={
            "client_id": settings.google_oauth_client_id, "client_secret": settings.google_oauth_client_secret.get_secret_value(), **data,
        })
        if (not isinstance(result, dict) or not isinstance(result.get("access_token"), str)
                or not result["access_token"] or result.get("token_type", "").lower() != "bearer"
                or type(result.get("expires_in")) is not int or not 1 <= result["expires_in"] <= 86400):
            raise GoogleError(503, "Google returned unusable calendar credentials.")
        return result

    def userinfo(self, token):
        return self.send("GET", USERINFO, token=token)

    def revoke(self, token):
        return self.send("POST", "https://oauth2.googleapis.com/revoke", data={"token": token})

    def calendars(self, token):
        items = self.paginate(token, ROOT + "/users/me/calendarList", {
            "minAccessRole": "writer", "maxResults": 100,
            "fields": "nextPageToken,items(id,summary,summaryOverride,timeZone,primary,accessRole)",
        })
        return [dict(id=item["id"], name=item.get("summaryOverride") or item.get("summary") or "Google Calendar",
                     timezone=item.get("timeZone", "UTC"), primary=item.get("primary", False))
                for item in items if item.get("accessRole") in ("writer", "owner")]

    def paginate(self, token, url, params):
        items = []
        for _ in range(5):
            data = self.send("GET", url, token=token, params=params, retry=True)
            items.extend(data.get("items", []))
            cursor = data.get("nextPageToken")
            if not cursor:
                return items
            params = {**params, "pageToken": cursor}
        raise GoogleError(503, "Google returned too many results. Try a shorter range.")

    def busy(self, token, calendar, start, end, excluding=None):
        url = self.events_url(calendar["id"])
        events = self.paginate(token, url, {
            "timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true",
            "maxResults": 100, "timeZone": calendar["timezone"],
            "fields": "nextPageToken,items(id,status,transparency,start,end,attendees(self,responseStatus))",
        })
        timezone_value = zone(calendar["timezone"])
        intervals = []
        for item in events:
            if (item.get("id") == excluding or item.get("status") == "cancelled" or item.get("transparency") == "transparent"
                    or any(a.get("self") and a.get("responseStatus") == "declined" for a in item.get("attendees", []))):
                continue
            try:
                def instant(value):
                    if "dateTime" in value:
                        parsed = datetime.fromisoformat(value["dateTime"])
                        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone_value)
                    return datetime.combine(date.fromisoformat(value["date"]), time.min, timezone_value)
                intervals.append((instant(item["start"]).astimezone(timezone.utc), instant(item["end"]).astimezone(timezone.utc)))
            except (KeyError, ValueError, TypeError) as error:
                raise GoogleError(503, "Google returned an event whose date could not be checked.") from error
        return intervals

    @staticmethod
    def events_url(calendar, event=None):
        url = f"{ROOT}/calendars/{quote(calendar, safe='')}/events"
        return url + f"/{quote(event, safe='')}" if event else url

    def event(self, token, calendar, identifier):
        try:
            event = self.send("GET", self.events_url(calendar, identifier), token=token, retry=True)
            return None if event.get("status") == "cancelled" else event
        except GoogleError as error:
            if error.remote_status in (404, 410):
                return None
            raise

    def create(self, token, calendar, body):
        return self.send("POST", self.events_url(calendar), token=token, json=body, params={"sendUpdates": "none"})

    def update(self, token, calendar, identifier, etag, body):
        return self.send("PATCH", self.events_url(calendar, identifier), token=token, json=body,
                         headers={"If-Match": etag}, params={"sendUpdates": "none"})

    def remove(self, token, calendar, identifier, etag):
        return self.send("DELETE", self.events_url(calendar, identifier), token=token,
                         headers={"If-Match": etag}, params={"sendUpdates": "none"})


@lru_cache
def provider():
    return GoogleCalendar(httpx.Client(timeout=httpx.Timeout(4, connect=2.5), follow_redirects=False))


def access(db, row):
    if not row or row.status != "connected" or not row.encrypted_refresh_token:
        raise TutorError("calendar_reconnect", "Connect Google Calendar to continue.", 409)
    try:
        if row.encrypted_access_token and row.access_expires_at and row.access_expires_at > now() + timedelta(seconds=45):
            return decode_secret(row.encrypted_access_token)
        refreshed = provider().tokens(grant_type="refresh_token", refresh_token=decode_secret(row.encrypted_refresh_token))
        granted = refreshed.get("scope")
        if granted:
            check_scopes(granted)
        row.encrypted_access_token = encode_secret(refreshed["access_token"])
        if refreshed.get("refresh_token"):
            row.encrypted_refresh_token = encode_secret(refreshed["refresh_token"])
        row.access_expires_at = now() + timedelta(seconds=refreshed["expires_in"])
        row.last_refreshed_at = now()
        return refreshed["access_token"]
    except TutorError as error:
        if error.code in {"calendar_reconnect", "calendar_scope"}:
            row.status = "reconnect_required"
            row.encrypted_access_token = None
        raise


def check_scopes(value):
    provided = set(value.split()) if isinstance(value, str) else set()
    if EMAIL_SCOPE in provided:
        provided.add("email")
    if not REQUIRED.issubset(provided):
        raise TutorError("calendar_scope", "Grant the requested Calendar and account scopes, then reconnect.", 409)
    return sorted(provided)
