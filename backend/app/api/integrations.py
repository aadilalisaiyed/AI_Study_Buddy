from logging import Filter, getLogger
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from app.ai.llm import TutorError
from app.api.documents import DB, Owner
from app.core.config import get_settings
from app.schemas.planner import CalendarChoice
from app.services import google_oauth
from app.services.google_calendar import access, configuration, connection, lock_owner, provider, rate

router = APIRouter(prefix="/api/v1/integrations/google", tags=["Google Calendar"])


class OAuthAccessFilter(Filter):
    def filter(self, record):
        # Uvicorn's access record includes the complete request target.
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            path = str(args[2])
            return not ("/integrations/google/callback" in path or "/integrations/google/launch" in path)
        return True


getLogger("uvicorn.access").addFilter(OAuthAccessFilter())


@router.post("/authorize")
def authorize(owner: Owner, db: DB):
    return {"url": google_oauth.begin(db, owner.id)}


@router.get("/launch", include_in_schema=False)
def launch(db: DB, ticket: str = Query(max_length=128)):
    url, browser = google_oauth.launch(db, ticket)
    redirect = RedirectResponse(url, status_code=303, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    redirect.set_cookie(google_oauth.COOKIE, browser, httponly=True, samesite="lax",
                        secure=get_settings().google_oauth_redirect_uri.startswith("https:"),
                        path="/api/v1/integrations/google/callback", max_age=600)
    return redirect


@router.get("/callback")
def callback(request: Request, db: DB):
    try:
        state = google_oauth.finish(db, state=request.query_params.get("state"),
            browser=request.cookies.get(google_oauth.COOKIE), code=request.query_params.get("code"),
            denied=bool(request.query_params.get("error")))
    except TutorError as error:
        db.rollback()
        state = error.code if error.code in {"oauth_state", "oauth_refresh", "calendar_scope", "calendar_config"} else "failed"
    base = get_settings().planner_frontend_url.rstrip("/")
    response = RedirectResponse(f"{base}/calendar?" + urlencode({"google": state}), status_code=303,
                                headers={"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})
    response.delete_cookie(google_oauth.COOKIE, path="/api/v1/integrations/google/callback")
    return response


def connection_view(db, owner):
    row = connection(db, owner)
    configured = True
    try:
        configuration()
    except TutorError:
        configured = False
    return {
        "configured": configured, "status": row.status if row else "disconnected",
        "email": row.google_email if row and row.status != "disconnected" else None,
        "selected_calendar": row.selected_calendar if row else None, "last_synced_at": row.last_synced_at if row else None,
    }


@router.get("/status")
def status(owner: Owner, db: DB):
    return connection_view(db, owner.id)


def calendar_list(db, owner):
    lock_owner(db, owner)
    row = connection(db, owner)
    rate(db, owner)
    try:
        return row, provider().calendars(access(db, row))
    except TutorError as error:
        if row and error.code == "calendar_reconnect":
            row.status = "reconnect_required"
        db.commit()
        raise


@router.get("/calendars")
def calendars(owner: Owner, db: DB):
    _, items = calendar_list(db, owner.id)
    db.commit()
    return {"items": items}


@router.put("/calendar")
def select_calendar(data: CalendarChoice, owner: Owner, db: DB):
    identifier = owner.id
    row, items = calendar_list(db, identifier)
    chosen = next((item for item in items if item["id"] == data.calendar_id), None)
    if not chosen:
        db.commit()
        raise TutorError("calendar_not_found", "Writable calendar not found.", 404)
    row.selected_calendar = chosen
    db.commit()
    return connection_view(db, identifier)


@router.post("/disconnect")
def disconnect(owner: Owner, db: DB):
    return {"status": "disconnected", "revoked": google_oauth.disconnect(db, owner.id)}
