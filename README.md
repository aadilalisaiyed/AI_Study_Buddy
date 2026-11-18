<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&amp;color=0:0F3F49,65:164B56,100:7F0508&amp;height=220&amp;section=header&amp;text=AI%20Study%20Buddy&amp;fontSize=54&amp;fontColor=ECE6DF&amp;fontAlignY=38&amp;desc=Learn%20Deeper.%20Remember%20Longer.&amp;descSize=19&amp;descAlignY=60" alt="AI Study Buddy — Learn Deeper. Remember Longer." width="100%" />

[![React](https://img.shields.io/badge/React-0F3F49?style=for-the-badge&logo=react&logoColor=ECE6DF)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0F3F49?style=for-the-badge&logo=fastapi&logoColor=ECE6DF)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-0F3F49?style=for-the-badge&logo=postgresql&logoColor=ECE6DF)](https://www.postgresql.org/)
[![Gemini](https://img.shields.io/badge/Gemini-7F0508?style=for-the-badge&logo=googlegemini&logoColor=ECE6DF)](https://ai.google.dev/)

</div>

---

## 🧠 About

**AI Study Buddy** is a study workspace that turns course PDFs into answers with page citations, practice quizzes, and revision plans.

**Upload notes → Ask questions → Take a quiz → Review weak topics → Plan revision**

## ✨ Features

| Feature | What you can do |
| --- | --- |
| 📚 **Document Library** | Upload private PDFs, preview them, and organize them by subject. |
| 💬 **AI Tutor** | Ask questions about selected PDFs and check answers against page citations. |
| 📝 **Quiz Studio** | Generate quizzes, review graded attempts, and practice weak topics. |
| 📊 **Learning Analytics** | Explore quiz performance, study activity, and revision completion. |
| 🗓️ **Revision Planner** | Schedule study sessions locally or sync them to Google Calendar after approving each event change. |

## 🛠️ Tech Stack

| Layer | Stack |
| --- | --- |
| Frontend | React, Vite, Tailwind CSS, Recharts |
| Backend | Python, FastAPI, SQLAlchemy, Alembic |
| Data | PostgreSQL, private Supabase Storage, ChromaDB |
| AI & integrations | Gemini, PyMuPDF, Model Context Protocol, Google Calendar OAuth |

## 🏗️ Architecture

```mermaid
flowchart TD
    Browser["Frontend · React, Vite, Tailwind CSS, Recharts"]
    API["Backend REST API · Python, FastAPI"]
    DB[("PostgreSQL · accounts, documents, quizzes, revision sessions")]
    Storage[("Supabase Storage · private PDFs")]
    Vectors[("ChromaDB · PDF chunk embeddings")]
    Worker["Document worker · Python, PyMuPDF"]
    Gemini["Google Gemini · embeddings and generation"]
    MCP["Planner tools · Python MCP SDK"]
    Calendar["Google Calendar API · OAuth 2.0"]

    Browser -->|"HTTPS or local HTTP · JWT"| API
    API -->|"SQLAlchemy · Alembic migrations"| DB
    API -->|"Store and retrieve PDFs"| Storage
    DB -->|"Queued PDF jobs"| Worker
    Worker -->|"Read and verify PDFs"| Storage
    Worker -->|"Embed PDF chunks"| Gemini
    Worker -->|"Index chunks with page references"| Vectors
    API -->|"Retrieve relevant PDF chunks"| Vectors
    API -->|"Generate Tutor answers and quizzes"| Gemini
    API -->|"Invoke Planner tools"| MCP
    MCP -->|"Sync approved event changes"| Calendar
```

## 🚀 Run Locally

You'll need Python, Node.js with npm, and Docker Compose.

**1. Create a local `.env` in the repository root.** Set `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DATABASE_URL`, and `JWT_SECRET_KEY`. Point `DATABASE_URL` at your PostgreSQL database using `postgresql+psycopg://`. Compose exposes PostgreSQL on port `5433` by default.

For PDF and AI features, configure a private Supabase bucket using `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, and `SUPABASE_STORAGE_BUCKET`. Set `GEMINI_API_KEY` and set `GEMINI_FREE_TIER_CONFIRMED=true` only after confirming your Gemini project is on the Free tier. Google Calendar is optional.

**2. Start the databases and API.** These commands use Git Bash on Windows.

```bash
docker compose up -d postgres chroma
cd backend
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

In a second terminal, activate the same virtual environment from `backend` and run `python -m app.document_worker` to index uploaded PDFs.

**3. Start the frontend** from the repository root in a separate terminal.

```bash
cd frontend
npm ci
npm run dev
```

Open [AI Study Buddy](http://127.0.0.1:5173).

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&amp;color=0:7F0508,45:164B56,100:0F3F49&amp;height=100&amp;section=footer" alt="" width="100%" />

</div>
