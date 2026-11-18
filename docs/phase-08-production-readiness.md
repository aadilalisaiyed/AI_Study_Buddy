# Phase 08 production readiness

## Executive summary

Phase 08 adds revocable application sessions, API boundary controls, user-controlled subjects, and a verified PostgreSQL recovery workflow. Two additive migrations were applied to the local application database. The original frontend design and routes remain in use. Deployment is loopback-only. See the final verification results below for unfinished release checks.

## Security findings and treatment

| Severity | Finding | Treatment |
| --- | --- | --- |
| High | Logout previously discarded the browser JWT without server-side revocation | New session-bound JWTs are checked against a revocable PostgreSQL session. Logout revokes the active family |
| High | Login and registration could consume unbounded Argon2 concurrency | Per-process address and operation limits, bounded address table, and four concurrent password operations |
| Medium | Unknown users skipped Argon2 verification | One dummy Argon2 verification on that path; same error as a wrong password |
| Medium | Validation errors could include private input | Safe generic validation response. Avoid echoing database statement parameters and suppress default access logs in the run command |
| Medium | Non-file bodies lacked a server-side bound | 256 KiB streamed read limit before parsing. The existing PDF route retains its configured size and streaming reserve enforcement |
| Medium | Browser origins and API host acceptance were development-only | Explicit origin/host configuration, production validation, HTTPS cookie flags, and a same-origin reverse-proxy example |
| Medium | Missing quiz subject tags prevented meaningful grouping | Owned subjects, filtered document list, and immutable quiz subject snapshots |
| Medium | Recovery procedure was untested | Compressed logical PostgreSQL backup, restore to a new database, and isolated Chroma rebuild |
| Residual | Quota and abuse throttles vary by process and provider | Run one API process for the demo. Use an edge limiter and shared throttling before multiple workers or public exposure |

Registration retains a minimum 12-character password, normalized email and unique email handling. Duplicate registration still indicates that the email already has an account. Public password recovery is unavailable because no verified email service is configured.

## Sessions and API behavior

Login remains form-encoded and returns an access JWT with additive `expires_in`. Access is HS256 only, with expiry, issued-at, subject, type and session checks. Inactive users are rejected. The frontend keeps the short-lived access JWT and account profile in tab-scoped sessionStorage so page reloads preserve sign-in. Logout clears the cache. The refresh credential remains in an HttpOnly cookie. Access JWTs in sessionStorage are readable by scripts running on the app origin, so deploy with the tested CSP and keep third-party scripts out of the authenticated workspace. A seven-day absolute server-side session uses an opaque HttpOnly, SameSite=Lax cookie scoped to the authentication API. Its secret and the previous rotation are stored as digests. Refresh and logout require an exact configured browser Origin. Replay of the immediately previous refresh value revokes that session family. The browser serializes rotation across cooperating tabs when Web Locks is available. Production uses Secure cookies and rejects legacy JWTs without a session claim. The loopback development API accepts previously issued bearer JWTs until they expire.

`POST /api/v1/auth/refresh` rotates the refresh cookie and returns a new access token. `POST /api/v1/auth/logout` revokes the active cookie session and expires that cookie. Requests to other private routes continue using bearer JWTs. Deploy the API and frontend on the same site, preferably behind one origin. Passwords, session cookies, request bodies and query strings are omitted from request logs. Request logs use route templates, request IDs, status and elapsed milliseconds. Unexpected errors log their exception class only. API documentation routes are disabled in production. Complete distributed rate limiting, alerting, and production log retention before public operation.

## Authorization, data, and external calls

Existing owner filters and regression fixtures cover documents, citations, quiz questions and attempts, Tutor history, Planner proposals, MCP context and analytics. MCP runs in-process and can consume an existing Planner approval. It cannot authorize a Calendar write. RAG treats retrieved text as data and verifies that citation labels refer to retrieved passages. Citation provenance does not establish factual correctness. Short-answer results explain the rubric matcher can miss paraphrases. Calendar and Gemini regression tests use test doubles; routine regression makes no billable calls.

Subject names use Unicode normalization, collapsed spacing and case-folding for per-user uniqueness. The Library creates subjects, assigns them to PDFs, and filters by subject. Quiz Studio can select a subject independently of filenames. Analytics groups graded attempts by the quiz's saved subject snapshot. Older quizzes remain Uncategorized. Deleting a subject through the API clears document assignments without changing quiz snapshots. Revision Planner continues to record explicit subject text.

## Backup, restore, and recovery

Use PostgreSQL client tools at least as new as the source server. Restore to the same or a newer major version and rehearse any major-version upgrade separately. Keep dumps outside the repository in a private ACL-controlled directory. Bash umask alone does not establish an NTFS ACL. Encrypt copies stored outside the trusted machine. Supply connection settings via a private libpq service/passfile. Avoid putting secrets in command arguments or shell history.

```bash
# Git Bash. Set PGHOST, PGPORT, PGUSER, PGDATABASE using private local settings.
bash scripts/backup-postgres.sh "$HOME/private-db-backups"
bash scripts/restore-postgres.sh /path/to/archive.dump studybuddy_restore_rehearsal
```

Restore creates a new database and refuses an existing target. A failed restore may leave the new empty database for investigation. Never point a rehearsal at the active application database. The local rehearsal matched 127 users, 12 quiz attempts, 21 revisions, 41 auth sessions and 29 validated foreign keys. There were zero orphan quiz attempts. Both source and restoration were in an isolated instance.

Supabase object bytes need their own protected backup. Restore missing metadata to an isolated PostgreSQL instance first. Confirm PDF ownership, key, size and SHA-256 against the object manifest. For a missing object, restore verified bytes to the correct private bucket/key during maintenance, or have the owner re-upload through the Library. An unavailable original cannot be reconstructed from embeddings. Resume interrupted uploads through the Library, retry failed processing, and let deletion retries finish before repeating deletion. Monitor storage and egress in the provider dashboard before raising application limits. Supabase database backups exclude Storage API objects. [Supabase backup documentation](https://supabase.com/docs/guides/platform/backups)

Chroma is derived. Rehearse on a separate Chroma volume or collection with a copy of PostgreSQL and the original PDF bytes. Preserve the pipeline version, embedding model, dimension, chunk configuration, owner and document IDs. The ingestion path verifies the checksum, extracts pages, upserts stable chunk IDs and verifies the new set. Compare the owner-scoped chunk set and page references before switching endpoints in maintenance. Pause when the provider quota is exhausted and resume after its reset. The isolated rebuild test reingests a two-page PDF twice and verifies identical page/chunk IDs and foreign-owner exclusion. Existing worker tests cover abandoned lease recovery and stale workers.

Keep the Calendar encryption key outside the database backup and maintain a separate protected copy. Rotation requires decrypting with the old key and re-encrypting with the new key during maintenance. There is no automatic rotation utility. Loss of the key requires account reconnection to replace the old ciphertext.

## Performance and frontend

A sequential local benchmark used 4,000 synthetic graded attempts and 20,000 answered questions in a 90-day range, in one rolled-back PostgreSQL transaction. Over 15 analytics-service runs the median was 367.6 ms and nearest-rank p95 was 655.2 ms. This measures a local service path and includes the first run. It does not represent concurrent production traffic or a mixed workload. No index changes were justified by this sample. Large mixed workloads and vector latency/memory benchmarking remain unverified.

Existing focus indicators and reduced-motion styling remain. Quiz results describe rubric limits. Analytics charts now offer a text list of exact trend values. Chromium checked analytics, document-subject creation, refresh after a reload, logout, two-account data isolation, quiz results, topic actions and local revision completion. Width checks cover 320, 375, 430, 768, 1024, 1440 and 1920 px after chart layout settled. Full WCAG conformance, assistive-technology testing and Lighthouse scores remain unverified.

## Deployment feasibility

| Option | Fit at ₹0 |
| --- | --- |
| Local demonstration | Recommended. Run the loopback API, worker, persistent PostgreSQL and Chroma volumes on the existing machine |
| Render free web service | Preview only. Free web instances sleep, lack persistent disks, and free PostgreSQL expires after 30 days. No verified durable worker/vector configuration under the constraint |
| Cloudflare Pages hybrid | Static frontend can fit Pages limits. Python API, worker, PostgreSQL and Chroma need another durable host. A temporary Quick Tunnel is a testing URL and cannot provide a stable production OAuth callback |

[Render free service limits](https://render.com/docs/free) · [Cloudflare Pages limits](https://developers.cloudflare.com/pages/platform/limits/) · [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)

There is no verified no-card public architecture for this full workload. Keep Compose services bound to loopback, with the existing host PostgreSQL default 5433. Configure separate development, isolated test and production environments. The environment template describes explicit origins and hosts. `scripts/Caddyfile.example` illustrates the TLS proxy, same-origin API and a CSP. Build the frontend with `VITE_API_BASE_URL=/` for that configuration. Review production proxy trust, test the actual HTTPS/CSP profile with PDF.js and OAuth, and register the exact HTTPS callback before approving any deployment. No public endpoint, tunnel or paid service was created.

## Verification and operations

From Git Bash:

```bash
docker compose config --quiet
docker compose up -d postgres chroma
cd backend
source .venv/Scripts/activate
python -m alembic upgrade head
python -m alembic check
# Run against a separate test database:
python -m pytest -q -p no:cacheprovider
# Separate terminals for the application and ingestion worker:
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
python -m app.document_worker
cd ../frontend
npm run lint
npm run build
npm audit --omit=dev --audit-level=high
```

Final backend result was 40 passed and 3 opt-in live provider tests skipped. Alembic reported no drift in both the isolated and running development databases. Frontend lint and build, Compose validation, Chromium acceptance, and the npm production dependency audit passed.

Check database health and worker logs after upgrades. Protect backups and limit local process access. Use provider dashboards to check model availability and remaining quota before enabling external smoke tests. Limits are subject to provider changes. No billing configuration was changed. An npm registry production audit returned zero advisories. A comprehensive Python advisory scan was not run.

Phase 06 reconnect remains blocked on user sign-in and consent. A read-only database check confirmed the connection still disconnected and the cancelled test session and deleted-event link retained. Prior live event operations and revocation were already verified. No Calendar write or revocation was attempted in Phase 08.

## Readiness

- **Local development:** ready after migration.
- **Academic demonstration:** suitable with local services and the tested workflow. Show Calendar reconnect as pending until consent is verified.
- **Limited private beta:** conditional on checked HTTPS/proxy behavior, abuse controls, backup operations, and a complete accessibility and mixed-load rehearsal.
- **Public production:** unverified. Resolve the private beta conditions and durable hosting, provider limits, operational monitoring, and dependency/security review before approval.
