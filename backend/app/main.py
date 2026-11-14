
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router


app = FastAPI(
    title="AI Study Buddy API",
    description="AI-powered learning platform with RAG and MCP",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health_router)


@app.get("/")
def root():
    return {
        "message": "Welcome to AI Study Buddy API",
        "version": "0.1.0",
    }
