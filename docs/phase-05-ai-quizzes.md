# Phase 05 AI Quiz Studio

Quiz Studio uses the existing JWT session, private Supabase bucket, local PostgreSQL and Chroma. Start the app using the [document setup guide](phase-03-documents.md). From Windows Git Bash in `backend`, activate the existing virtual environment with `source .venv/Scripts/activate`, run `python -m alembic upgrade head`, and start the API and ingestion worker. Start the frontend with `npm run dev` from `frontend`.

## Generation

Select one or more owned READY PDFs and choose 5, 10, 15, or 20 questions, subject to the server limit. Mixed quizzes distribute questions across multiple choice, true/false, and short answer in that order, assigning any remaining questions to the earlier types. Mixed difficulty requires at least two difficulty levels. A generation request is persisted with an idempotency UUID and a three-minute lease. Interrupted requests are shown as failed once the lease expires. A generation that returns insufficient, duplicate, or invalid questions fails as a whole.

For a broad quiz, the API selects up to eight evenly spaced indexed chunks per PDF and rotates through the PDFs under a byte budget. Topic-focused quizzes prioritize owner-scoped semantic hits from the existing retriever, then supplement them with page samples. This is sampled coverage. It does not assess every section of a long PDF. The Free Gemini model used by the Tutor generates a structured batch. The backend validates question count, type and difficulty, options and answer keys, rubrics, duplicate prompts, and citation labels and verbatim evidence against the supplied passages. Evidence validation verifies provenance. The factual accuracy of an explanation still depends on the generated content.

Quizzes remain fixed once ready. Multiple-choice options are shuffled before saving the snapshot, so retakes preserve ordering and answer keys. The question-taking response has a separate schema with ID, position, prompt, type, options, and maximum marks. Answer keys, rubrics, explanations, and citations stay server-side during a quiz. Results are available to the owner after the attempt is graded.

## Attempts and analytics

Autosaved answers are held in PostgreSQL. Refreshing restores server-confirmed answers after signing in again. Each quiz may have multiple attempts. Server time controls timed attempts and the next attempt read or mutation finalizes an expired attempt using its saved answers. Duplicate submit requests replay the same grade. Unanswered items score zero. MCQ and true/false use exact typed keys.

Short answers use a literal concept rubric. Each independent concept earns one point when a stored phrase matches a whole normalized phrase in a clause. Clauses that negate a listed concept normally receive no credit. A concept can earn no more than one point. This is deliberately conservative and can miss valid paraphrases or nuances. It does not measure writing quality or call Gemini to score an answer. Scores use integer marks and round the percentage to two decimal places, half-up.

Quiz Studio shows totals, partial credit, explanations, topic and difficulty charts, and verified document/page previews. The application keeps historical scores and explanations when a document is deleted. Such citations become unavailable and no source excerpt is stored in the quiz. The immutable quiz references a document snapshot, so document deletion does not cascade to historical attempts.

The summary reports graded attempts, completed distinct quizzes, answered/correct/incorrect/partial/unanswered counts, correctness among answered items, average score, marks by question type, difficulty and normalized topic, and the latest 20 scores and durations. Weak topics require at least three answered items by default and fewer than 65% of available marks. Practice Weak Topics uses surviving READY sources for weak topics, passes recent prompts for exclusion, and checks normalized exact repeats against answered history. It requires a user action and counts against the generation quota.

Migration `18d7af31c905` adds `quizzes`, `quiz_questions`, `quiz_attempts`, `quiz_answers`, and `quiz_generation_usage`. Ownership, position and attempt-answer uniqueness, mark bounds, and idempotency are enforced by database constraints and transactional routes. Deleting a quiz removes its attempts and answers. Its separate quota entry remains.

## API inventory

All endpoints require a bearer token and filter resources by authenticated owner. The prefix is `/api/v1/quizzes`.

| Method | Path | Contract |
| --- | --- | --- |
| GET | `/config` | Configured quiz limits |
| GET | `/performance/summary` | Persisted performance and weak topics |
| POST | `/generate` | Idempotent generation or weak-topic practice, with a ready, generating, or failed status |
| GET | Prefix | Paginated quiz history |
| GET | `/{quiz_id}` | Quiz metadata |
| GET | `/{quiz_id}/questions` | Safe question payload |
| DELETE | `/{quiz_id}` | Delete quiz and its attempts |
| POST | `/{quiz_id}/attempts` | Start an attempt using a request UUID |
| GET | `/{quiz_id}/attempts` | Paginated attempt history |
| POST | `/{quiz_id}/retake` | Start a separate attempt on the same quiz |
| GET | `/attempts/{id}` | Resume saved answers and question positions |
| PATCH | `/attempts/{id}/answers` | Save a map of question IDs to typed answers |
| POST | `/attempts/{id}/submit` | Grade once and return results |
| GET | `/attempts/{id}/results` | Return review after grading |

## Free service limits and verification

The existing verified Free-tier environment and allowlisted `gemini-3.5-flash-lite` model are reused. Quiz and Tutor generation share one active-request slot. Each user can start three quiz generations per rolling day by default. Transient failures use the Gemini client's bounded retry limit. Provider quota errors finish the generation with an actionable failed status. A provider's account-wide quotas also include PDF indexing and any other tools using the project. See every tuning limit in the root `.env.example`. Short-answer grading and analytics use local computation. There are no new Python or npm dependencies.

Run `python -m pytest -q` from `backend`. Set `DOCUMENT_TEST_DATABASE_URL` to a disposable migrated PostgreSQL database to enable authenticated integration tests. The opt-in live quiz test uses `RUN_LIVE_QUIZ_TEST=1` and `DOCUMENT_CLOUD_TEST_BUCKET=study-documents` with the existing confirmed Free provider credentials and Chroma configuration. Run `python -m pytest -q tests/test_quiz_live.py` on the isolated test database with its document worker paused. From `frontend`, run `npm run lint` and `npm run build`.

For browser acceptance, upload a disposable text PDF on deadlock, generate five medium MCQs, answer some correctly and incorrectly, refresh and sign in, submit, inspect a cited page, retake, and reopen history. Confirm another account receives a 404 for the quiz, its results, and source download. Delete the disposable PDF and confirm the historical score remains while the citation becomes unavailable.
