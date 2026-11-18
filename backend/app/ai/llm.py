from dataclasses import dataclass
from functools import lru_cache
from time import sleep

import httpx
from google.genai import errors, types
from pydantic import BaseModel, Field, ValidationError

from app.ai.gemini import FREE_CHAT_MODELS, client_for
from app.ai.prompts import TUTOR_PROMPT
from app.core.config import Settings, get_settings


class TutorError(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code = code
        self.status = status


class AnswerSection(BaseModel):
    text: str = Field(min_length=1, max_length=3500)
    sources: list[str] = Field(min_length=1, max_length=12)


class ModelAnswer(BaseModel):
    insufficient: bool
    sections: list[AnswerSection] = Field(max_length=12)


@dataclass(frozen=True)
class Generation:
    answer: ModelAnswer
    model: str
    usage: dict[str, int]


class GeminiTutor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = client_for(
            settings, model=settings.gemini_chat_model, allowed=FREE_CHAT_MODELS,
            timeout=settings.gemini_chat_timeout_seconds,
        )

    def generate(self, payload: str) -> Generation:
        answer, usage = self.generate_structured(payload, TUTOR_PROMPT, ModelAnswer, self.settings.gemini_chat_max_output_tokens)
        return Generation(answer, self.settings.gemini_chat_model, usage)

    def generate_structured(self, payload, prompt, schema, max_tokens, *, provider_schema=None):
        settings = self.settings
        for attempt in range(settings.gemini_retry_attempts):
            try:
                response = self.client.models.generate_content(
                    model=settings.gemini_chat_model, contents=payload,
                    config=types.GenerateContentConfig(
                        system_instruction=prompt,
                        temperature=settings.gemini_chat_temperature,
                        max_output_tokens=max_tokens,
                        response_mime_type="application/json",
                        response_schema=provider_schema or schema,
                        thinking_config=types.ThinkingConfig(thinking_level="minimal"),
                    ),
                )
                candidate = (response.candidates or [None])[0]
                if candidate is None or candidate.finish_reason != types.FinishReason.STOP or not response.text:
                    raise TutorError("incomplete_response", "Gemini could not complete a supported answer. Try a shorter question.", 502)
                answer = schema.model_validate_json(response.text)
                usage = response.usage_metadata
                counts = {key: value for key, value in {
                    "input": getattr(usage, "prompt_token_count", None),
                    "output": getattr(usage, "candidates_token_count", None),
                    "total": getattr(usage, "total_token_count", None),
                }.items() if value is not None}
                return answer, counts
            except ValidationError as error:
                raise TutorError("invalid_response", "Gemini returned an invalid answer. Try again.", 502) from error
            except errors.APIError as error:
                if error.code == 429:
                    raise TutorError("provider_quota", "Gemini's Free-tier quota is temporarily exhausted. Try again later.", 429) from error
                if error.code in (400, 401, 403, 404):
                    raise TutorError("provider_configuration", "Gemini rejected the server credentials or model configuration.") from error
                if error.code not in (500, 502, 503, 504) or attempt + 1 == settings.gemini_retry_attempts:
                    raise TutorError("generation_unavailable", "Gemini is temporarily unavailable. Try again.") from error
            except httpx.TimeoutException as error:
                raise TutorError("generation_timeout", "Gemini timed out. Try again.", 504) from error
            except httpx.TransportError as error:
                if attempt + 1 == settings.gemini_retry_attempts:
                    raise TutorError("generation_unavailable", "Gemini is temporarily unavailable. Try again.") from error
            sleep(2 ** attempt)
        raise AssertionError("Invalid Gemini retry limit")


@lru_cache
def get_tutor() -> GeminiTutor:
    return GeminiTutor(get_settings())
