# Phase 03 private document storage

## Local setup

From the repository root, merge the document settings in the root `.env.example` into your existing `.env`. Preserve your PostgreSQL credentials, configured host port, and JWT secret. The example uses port 5433. The API and worker resolve the root environment file relative to their source, so the launch directory does not affect environment loading.

Use the Supabase **Free** plan. Create a **private** bucket named `study-documents`, set a maximum file size of 25 MiB, and allow `application/pdf` only. Leave anonymous object policies disabled. In the root `.env` set `STORAGE_PROVIDER=supabase`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, and `SUPABASE_STORAGE_BUCKET=study-documents`. Use the Supabase project HTTPS URL. The server secret bypasses Supabase RLS, so keep it in backend environment only. The application retains its own JWT and PostgreSQL.

Use a Gemini Developer API project on the Free tier with Cloud Billing disabled. Set `GEMINI_API_KEY` and set `GEMINI_FREE_TIER_CONFIRMED=true` after checking that project. The default text embedding model is `gemini-embedding-2` at 768 dimensions. Text from PDFs is sent to Gemini for embeddings. On the Gemini Free tier, Google says application inputs and responses may be used to improve its products. Use permitted study material and avoid sensitive PDFs. [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)

From Windows Git Bash:

```bash
docker compose up -d postgres chroma
cd backend
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another backend terminal:

```bash
source .venv/Scripts/activate
python -m app.document_worker
```

In a frontend terminal:

```bash
cd frontend
npm install
npm run dev
```

Chroma persists in a separate Docker volume and binds to localhost on port 8001 by default. Keep it on a private network. Supervise the ingestion worker so it restarts after a job timeout.

## Document endpoints

All operations derive ownership from the JWT. Foreign resource IDs return 404. The base path is `/api/v1/documents`.

| Method | Route | Result |
| --- | --- | --- |
| POST | `/uploads/init` | Reserve quota and create upload metadata |
| PUT | `/{id}/uploads/content` | Accept bounded PDF bytes and write a private immutable object |
| POST | `/{id}/uploads/complete` | Verify the remote SHA-256 and size, then queue ingestion |
| GET | Base path | List owned metadata with search, filters, pagination, and sort |
| GET | `/{id}` | Read owned metadata and worker status |
| GET | `/{id}/download` | Return the integrity-checked PDF for download or preview |
| POST | `/{id}/retry` | Requeue eligible failed ingestion |
| DELETE | `/{id}` | Queue object and vector removal |

The server commits a checksum reservation before it uses Supabase's create-without-upsert request. A duplicate key is accepted only when the remote bytes match the original checksum. Completion verifies the stored bytes and is safe to retry after a client interruption. The worker separately verifies integrity, extracts text, and uses stable chunk IDs. Retries process the same document row and verify the complete Chroma index before reporting `READY`.

Quotas default to 25 MiB per file, 20 documents per user, and a 750 MiB application-wide storage reservation. Reservations include pending uploads and incomplete deletions and are serialized in PostgreSQL. They account for this application's records in one database. Supabase governs actual shared project storage and egress, including objects from other apps. Use a single app database for the bucket and check project usage in Supabase. [Supabase Free limits](https://supabase.com/pricing)

The worker expires unfinished uploads after 24 hours. If storage or vector deletion fails, the record remains `DELETING`; retry it from the library once automatic attempts stop. A missing object after an interrupted upload can be resumed with the original PDF. Scanned, encrypted, or damaged PDFs report actionable failures. OCR is outside this implementation.

Migration `786d1e428cd2` preserves older GCS records and tags them as legacy. Legacy rows and vectors are retained. The Supabase adapter is used only for new uploads and never interprets a legacy object key as a Supabase object. A legacy original must be obtained from its previous storage and re-uploaded before it can be previewed or downloaded here. Changing the embedding model or chunk settings requires re-ingestion into the new collection.

## Verification

Run `python -m pytest -q` from `backend`. Set `DOCUMENT_TEST_DATABASE_URL` to a dedicated PostgreSQL test database to enable integration tests. For the live synthetic check, apply migrations to that test database, start an isolated Chroma instance, and set `RUN_LIVE_DOCUMENT_TEST=1` and `DOCUMENT_CLOUD_TEST_BUCKET=study-documents`. Then run `python -m pytest -q tests/test_document_cloud.py`. Start this test with the regular worker paused for the test database because the test claims its own worker jobs. The fixture creates and deletes its own uniquely scoped PDF and uses the configured Free-tier provider project.
