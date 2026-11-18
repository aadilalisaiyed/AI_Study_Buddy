# AI Study Buddy

AI Study Buddy is a study workspace for private course PDFs, document-grounded Tutor answers, practice quizzes, learning analytics, and revision planning.

## Run locally

1. Copy .env.example to .env and configure the local database and any optional providers. Keep real credentials in .env.
2. Run docker compose up -d postgres chroma.
3. In backend, install requirements.txt in a virtual environment, run python -m alembic upgrade head, and start python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log.
4. For PDF indexing, start python -m app.document_worker in a separate backend terminal with the same environment.
5. In frontend, run npm ci and npm run dev. Open http://127.0.0.1:5173.

See [operations and testing](docs/phase-08-production-readiness.md) and [learning analytics](docs/phase-07-learning-analytics.md).
