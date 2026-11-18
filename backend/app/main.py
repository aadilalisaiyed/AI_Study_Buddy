
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import get_settings
from app.core.http_boundary import HttpBoundary
from fastapi.middleware.cors import CORSMiddleware
from app.ai.llm import TutorError
from app.api.chat import router as chat_router, tutor_error
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.quizzes import router as quizzes_router
from app.api.integrations import router as integrations_router
from app.api.planner import router as planner_router
from app.api.health import router as health_router
from app.api.analytics import router as analytics_router
from app.api.subjects import router as subjects_router


settings = get_settings()

app = FastAPI(
    title="AI Study Buddy API",
    description="AI-powered learning platform with RAG and MCP",
    version="0.1.0",
    docs_url=None if settings.production else "/docs",
    redoc_url=None if settings.production else "/redoc",
    openapi_url=None if settings.production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(HttpBoundary, production=settings.production)


@app.exception_handler(RequestValidationError)
def validation_error(_request, _error):
    return JSONResponse({"detail": "Request validation failed. Check the submitted fields."}, 422)


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(chat_router)
app.include_router(quizzes_router)
app.include_router(integrations_router)
app.include_router(planner_router)
app.include_router(analytics_router)
app.include_router(subjects_router)
app.add_exception_handler(TutorError, tutor_error)

@app.get("/")
def root():
    return {
        "message": "Welcome to AI Study Buddy API",
        "version": "0.1.0",
    }
