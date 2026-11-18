# Phase 06 Revision Planner and Google Calendar

The authenticated Planner saves revisions and preferences in the existing PostgreSQL database. Calendar access is optional. Suggestions use the same graded-quiz topic aggregates as Quiz Studio. The proposal and slot calculations run locally. Phase 06 adds no Gemini requests or hosted MCP infrastructure.

## Google setup

1. In your existing Google project, enable Google Calendar API and create a **Web application** OAuth client. Configure OAuth consent. For an external app in Testing, add the Google account you intend to use as a test user.
2. Register this exact authorized redirect URI: `http://127.0.0.1:8000/api/v1/integrations/google/callback`. Open the frontend at `http://127.0.0.1:5173` for the default callback target.
3. In the ignored repository-root `.env`, fill `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, `GOOGLE_CALENDAR_SCOPES`, `GOOGLE_CALENDAR_TIMEZONE`, `PLANNER_FRONTEND_URL`, and `CALENDAR_TOKEN_ENCRYPTION_KEY`. Copy the four scopes exactly from the template. The existing `calendar.events` scope supports event listing and writing. The additional `calendar.calendarlist.readonly` scope supports selection of writable calendars. `openid email` identifies the connected account. The Planner discloses and requests this access at consent. Availability uses events.list on the selected calendar and requires no separate FreeBusy scope.
4. If generating the encryption key yourself, run `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` in a private terminal and put the result in the root `.env`. Preserve it across restarts and keep a secure backup. Future key rotation should decrypt existing ciphertext with the prior key, re-encrypt it with a new key, and then switch the active configuration during a maintenance window. Connecting again is the recovery path when an old key is unavailable.

Google documents that external OAuth apps in Testing can receive refresh tokens that expire after seven days when Calendar scopes are included. Reconnect when the Planner shows an expired connection. [Google Web OAuth](https://developers.google.com/identity/protocols/oauth2/web-server) · [Calendar scopes](https://developers.google.com/workspace/calendar/api/auth)

From Windows Git Bash, run `docker compose up -d postgres chroma`. In `backend`, activate your current environment with `source .venv/Scripts/activate`, then run `python -m pip install -r requirements.txt`, `python -m alembic upgrade head`, and `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`. In `frontend`, run `npm install` and `npm run dev`. The existing document worker is only needed for document ingestion. The Planner requires no background worker.

## OAuth and data protection

The authenticated authorization route issues a one-use launch ticket. The launch route sets an HttpOnly SameSite=Lax cookie and sends Google a fresh state and PKCE challenge. Stored ticket and state values are hashed. The short-lived PKCE verifier, Google refresh token, and cached Google access token use Fernet authenticated encryption. State validation binds the callback to the initiating user and browser. It rejects stale, replayed, and mismatched requests. OAuth query strings are suppressed in the Uvicorn access logger. Deployments should also exclude these paths from reverse-proxy URI logging. The callback returns only a safe status to the configured frontend. The app's in-memory JWT session requires sign-in again after a full-page Google redirect.

Disconnect clears the locally stored Google credentials and attempts revocation. If revocation cannot be confirmed, use Google's account permissions screen to remove the grant. Local sessions and existing Google events are retained.

## Scheduling and synchronization

Recommendations prioritize weak-topic marks, the answered sample size, and recency. Each recommendation includes its evidence, suggested duration, source quiz, and surviving owned PDFs. A topic with a future scheduled revision is suppressed. Recommendation priority is a planning heuristic.

Preferences store study days, a same-day time window, duration, IANA timezone, breaks, a daily study limit, and optional reminders. The slot search examines at most 14 days and returns up to eight options on 15-minute boundaries. It checks local sessions, breaks and daily limits. If selected, it also checks the one authorized Google calendar using bounded pages of events. All-day Google events are handled in the calendar's timezone. Local-only slots explicitly exclude external commitments from the check. Ambiguous DST times require a first/second occurrence for manual entries. Nonexistent times are rejected. Manual sessions can cross midnight and consume time on both days.

Every external write has an owned, expiring approval record with an idempotency key, action, exact session data, version, and destination Google account and calendar. Only the authenticated REST confirmation route can mark a proposal approved. The MCP write tools consume that approval. The local operation commits first. Remote writes then use a deterministic event ID and a private operation marker. Update and delete use ETag preconditions. A response lost after creation or update is reconciled using the approved marker and matching event details. A lost deletion response is reconciled against absence of the app-managed event. Direct Google edits cause a sync conflict. The app preserves the local session and avoids overwriting the external edit. The original approval can be retried for up to 24 hours with the same details. Selecting the original calendar is required to propose changes to an existing linked event. Completing a local session does not write to Google.

Calendar calls are user-triggered, time-bounded, and limited by `CALENDAR_REQUESTS_PER_MINUTE`. A read request may retry once after a short transient failure. A longer Retry-After or an exhausted quota surfaces an error. Writes are retried only by the user against an existing approved operation. There is no continuous polling or automatic billing setup.

## Database and API

Migration `ac63781ec225` adds `calendar_connections`, `calendar_oauth_states`, `calendar_rate`, `revision_preferences`, `revision_sessions`, `revision_session_documents`, `calendar_event_links`, and `revision_proposals`. Foreign keys link user, session, document, quiz, connection and approval data. Source deletion removes an association or clears the source quiz reference while preserving revision history. The schema enforces session duration/status, unique provider event and connection ownership, and user-scoped proposal idempotency.

| Prefix | Endpoints |
| --- | --- |
| `/api/v1/integrations/google` | `POST /authorize`, `GET /launch` with a one-use ticket, `GET /callback` with browser-bound state, `GET /status`, `GET /calendars`, `PUT /calendar`, `POST /disconnect` |
| `/api/v1/planner` | `GET/PUT /preferences`, `GET/POST /sessions`, `GET/PATCH/DELETE /sessions/{id}`, `POST /sessions/{id}/complete`, `POST /sessions/{id}/sync`, `GET /recommendations`, `GET /availability`, `POST /proposals`, `GET /proposals/{id}`, `POST /proposals/{id}/confirm` |

The local-only create, update and cancel REST shortcuts require a UUID query parameter `request_id`; the Planner uses proposals for both local and remote review. All private endpoints derive identity from the existing JWT. Foreign resource IDs return 404.

## MCP tools

Official Python MCP SDK 2.3.0 runs a real client/server exchange on in-process memory transport. FastAPI creates the server with the verified user ID in a closure. Tool inputs never accept a user ID or arbitrary Google event ID. Tools produce typed results with either `value` or a structured `error`.

| Tool | Input |
| --- | --- |
| `get_revision_recommendations` | No arguments |
| `list_revision_sessions` | Optional timezone-aware range and pagination offset |
| `get_calendar_availability` | First and last dates, optional duration and Google check |
| `propose_revision_session` | Typed proposal input, including operation UUID |
| `create_revision_session`, `sync_revision_session`, `reschedule_revision_session`, `cancel_revision_session` | One matching approved proposal UUID |

## Verification and live opt-in

Run `python -m pytest -q` in `backend`. Set `DOCUMENT_TEST_DATABASE_URL` to a disposable PostgreSQL database for OAuth, approval, isolation, and MCP protocol integration tests. Routine tests simulate provider responses. From `frontend`, run `npm run lint` and `npm run build`.

For the live test, start the API against a disposable PostgreSQL database, sign into that app and complete actual Google OAuth consent. Create a **secondary** Google calendar named `AI Study Buddy Test`, select it in the Planner, and note its exact ID. Keep it dedicated to test events. From the test terminal set `DOCUMENT_TEST_DATABASE_URL` to that same database, `GOOGLE_CALENDAR_TEST_ID` to the dedicated calendar ID, and `RUN_LIVE_CALENDAR_TEST=1`. Supply the same JWT signing environment used by that API. Enter a fresh JWT locally with `read -rs PLANNER_LIVE_JWT; export PLANNER_LIVE_JWT`, then run `python -m pytest -q tests/test_calendar_live.py`. Unset the JWT afterward. The opt-in test checks the selected calendar, uses unique fixture titles and confirmed create, edit and cancellation proposals, and verifies removal. Keep the test calendar free of personal events.
