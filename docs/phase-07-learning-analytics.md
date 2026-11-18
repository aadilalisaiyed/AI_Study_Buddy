# Phase 07 Learning Intelligence

Open **Analytics** in the authenticated workspace. The page reads persisted PostgreSQL records through the existing FastAPI service and renders them with Recharts. It makes no Gemini or Google Calendar requests and uses no new dependency, configuration variable, table, index, or migration.

## Metric definitions

| Metric | Definition |
| --- | --- |
| Graded attempts | Owned attempts in graded status, dated by submission |
| Quizzes completed | Distinct owned quiz IDs represented by those attempts |
| Questions answered | Graded answer rows with a nonempty submitted answer. False and choice zero count |
| Fully correct | Answered questions that earned all their marks, including fully correct short answers |
| Objective accuracy | Fully correct MCQ and true/false answers divided by answered MCQ and true/false questions |
| Answered marks score | Earned marks divided by available marks on answered questions. Short-answer partial marks contribute |
| Average attempt score | Equal-weight mean of individual earned over available marks percentages. Attempt totals include unanswered questions |
| Trends | Latest 120 graded attempts in the period, ordered by submission, with score and objective accuracy calculated independently |
| Measured quiz elapsed time | Sum of recorded submission minus start timestamps, clamped at zero. Elapsed time can include idle time |
| Topics | Answered count, full-credit count, earned and available marks, last submission, and original labels per saved Phase 05 topic key |
| Difficulty and question type | Answered count, full-credit count and earned/available marks grouped by the original question field |
| Weak topics | Phase 05 minimum answered sample and marks threshold, applied to the selected period. Ranked by ascending marks percentage. Upcoming revisions flag scheduled topics |
| Subject performance | Quiz results are Uncategorized because quizzes have no authoritative subject field. Planner distribution uses the stored revision subject |
| Active day | At least one graded quiz, persisted Tutor user message, or completed revision on the local day. Uploads and calendar sync never qualify |
| Current streak | Consecutive qualifying days ending today or yesterday, within the selected window |
| Longest streak | Longest consecutive run in the selected window |
| Revision scheduled | Non-cancelled sessions, including completed sessions, grouped by scheduled start |
| Revision completed / cancelled | Session state counts within the planned-start period |
| Past sessions pending | Scheduled sessions whose planned end has passed |
| Revision completion | Completed divided by completed plus past-pending. Future or currently scheduled sessions and cancelled sessions are excluded |
| Revision duration | Planned minutes on non-cancelled sessions, and the planned minutes on completed sessions as a separate value |
| Weekly revision activity | Non-cancelled plans and completed revisions grouped by the Monday of the scheduled start week |
| Upcoming revisions | Next five future scheduled local sessions across all dates |
| Tutor | New conversations, submitted user messages, and local days with Tutor activity |
| Library | Current READY count, and retained uploads, currently FAILED uploads, and processed timestamps in the selected range |
| Score-change insight | Mean of the latest three attempt scores minus mean of the previous three, in percentage points, if all six scores are present |

| Weak-topic improvement | Compares answered marks before and after the midpoint of the selected range, using the Phase 05 minimum sample in each half and requiring the earlier half to meet the weakness threshold |

Rates with zero denominators are null. Marks-based ratios are rounded half up to two decimal places, average scores and score changes to one. Revision elapsed durations are UTC timestamp differences and presented as planned minutes. No actual study timer is inferred. Subject labels do not establish mastery.

Topic keys reuse the existing Quiz Studio normalization and explicit CPU scheduling aliases. Original labels are preserved. Deletion follows the source tables: once an owned quiz or conversation is deleted, its cascaded attempt or message history stops contributing. Documents in deletion are excluded. Private text, storage keys, OAuth credentials, and model credentials are never returned.

## API

`GET /api/v1/analytics/overview` requires the existing bearer JWT. It returns a dashboard snapshot with `range`, `overview`, `trend`, `topics`, `weak_topics`, `types`, `difficulties`, `subjects`, `activity`, `consistency`, `revision`, `tutor`, `library`, and `insights`. All source queries are owner-scoped. Responses use `Cache-Control: private, no-store`.

Query parameters are `days` (default 30), or paired inclusive ISO dates `start_date` and `end_date`, plus optional IANA `timezone`. Dates span at most 366 days. The timezone defaults to the saved Planner preference, then Asia/Kolkata. PostgreSQL groups timestamps by the chosen local timezone and filters a half-open interval between local midnights, including daylight-saving transitions. `offset` and `limit` (default 30; maximum 100) paginate topic details. Trends are capped at 120. Weekly and daily data are bounded by the range. Upcoming revisions and the current READY count intentionally ignore the historical filter.

The service aggregates in PostgreSQL, uses no external analytics service, and does not cache private results. The Analytics page includes preset and custom date filters, quiz score and accuracy lines, dimension and subject bars, a keyboard-readable topic breakdown, an activity heatmap, revision charts and upcoming session links. Topic actions prefill Quiz Studio or the local Planner. The existing external calendar approval flow still applies.

## Local verification

From Git Bash, with the existing virtual environment and local PostgreSQL configured:

```bash
cd backend
source .venv/Scripts/activate
python -m alembic upgrade head
python -m alembic check
# Set DOCUMENT_TEST_DATABASE_URL to a separate disposable PostgreSQL database.
python -m pytest -q
cd ../frontend
npm run lint
npm run build
```

The database test submits a five-question fixture, checks marks vs objective accuracy, then checks the authenticated reports for owner isolation and the effect of deleting the quiz. The dedicated unit tests cover undefined rates, partial marks, empty streaks, duplicate days, and leap days.

## Limits and Phase 08 readiness

Elapsed quiz time can include idle periods. Actual study time, historical subject tagging, and historical processing failures are unavailable from current records. Weak-topic results are sample-limited; they are practice indicators. Before deployment, qualify larger-dataset query performance, exercise OAuth recovery and rate limits, rehearse PostgreSQL and object-store restore, verify encrypted token key recovery, and audit production log redaction and endpoint exposure.
