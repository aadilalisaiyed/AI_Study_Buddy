from datetime import datetime, timezone

import httpx
import pytest

from app.services.google_calendar import GoogleCalendar, GoogleError


def test_provider_paginates_busy_and_preserves_conditional_write():
    calls = []
    calendar = {"id": "calendar@example.com", "timezone": "Asia/Kolkata"}
    end = datetime(2027, 1, 6, tzinfo=timezone.utc)
    start = datetime(2027, 1, 4, tzinfo=timezone.utc)

    def handle(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer fixture-token"
        if request.method == "PATCH":
            assert request.headers["If-Match"] == '"baseline"'
            return httpx.Response(412, json={"error": {}})
        assert request.url.params["singleEvents"] == "true"
        if request.url.params.get("pageToken") == "second":
            return httpx.Response(200, json={"items": [
                {"id": "declined", "attendees": [{"self": True, "responseStatus": "declined"}]},
                {"id": "clear", "transparency": "transparent"},
                {"id": "same-owned-event"},
            ]})
        return httpx.Response(200, json={"items": [
            {"id": "holiday", "start": {"date": "2027-01-05"}, "end": {"date": "2027-01-06"}},
        ], "nextPageToken": "second"})

    client = GoogleCalendar(httpx.Client(transport=httpx.MockTransport(handle)))
    intervals = client.busy("fixture-token", calendar, start, end, excluding="same-owned-event")
    assert len(intervals) == 1
    assert intervals[0][0].isoformat() == "2027-01-04T18:30:00+00:00"
    with pytest.raises(GoogleError) as failure:
        client.update("fixture-token", calendar["id"], "owned-id", '"baseline"', {"summary": "Practice"})
    assert failure.value.remote_status == 412 and len(calls) == 3


def test_retry_after_avoids_immediate_rate_retry():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    google = GoogleCalendar(httpx.Client(transport=httpx.MockTransport(handle)))
    with pytest.raises(GoogleError) as failure:
        google.calendars("fixture-token")
    assert failure.value.status == 429 and len(seen) == 1
