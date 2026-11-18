# Phase 04 document-grounded AI Tutor

## Flow and persistence

Select one or more READY PDFs in the Tutor. The existing sign-in flow preserves a draft entered on the homepage. The Tutor saves conversations, supports rename and delete, and restores messages and source selection when reopened. The application uses the JWT already issued by its FastAPI authentication routes.

The API checks conversation and document ownership, reserves a user request and saves the question and a pending assistant turn in PostgreSQL. The query includes the current question and bounded context from earlier turns on the current document scope. The Phase 03 retriever embeds that query and sends owner and document filters to Chroma. The tutor deduplicates passages, packs them under a conservative UTF-8 budget, and submits only those passages and bounded history to Gemini. It rejects generated source labels outside that set. A valid reference is tied to a real chunk, file, and PDF page. The browser renders Markdown without active HTML, images, or model-defined links.

Chat currently uses one authenticated completion response. The browser shows a pending state and can stop waiting. The server can finish that operation after the browser disconnects, and reopening the conversation retrieves its final state. Duplicate request IDs replay the stored turn. Failed or interrupted answers remain failed or pending until their deadline. Reopening the conversation labels expired pending turns as failed.

When a source is deleted, its historical citation retains its filename and page number as an unavailable reference. Its excerpt and preview are withheld. The saved answer text stays in conversation history until the conversation is deleted. Subsequent retrieval and conversation context exclude deleted sources. Citation validation establishes that a model used a real source label. Factual support is evaluated separately using known-fact fixtures; the service does not perform a second model-based fact-check on every response.

## API

All routes require an existing bearer token. The base path is `/api/v1/chat/conversations`.

| Method | Route | Purpose |
| --- | --- | --- |
| POST | Base path | Create a conversation |
| GET | Base path | List owned conversations with limit and offset |
| GET | `/{id}` | Read conversation metadata and selected documents |
| PATCH | `/{id}` | Rename or change the default document selection |
| DELETE | `/{id}` | Remove a conversation and its messages |
| GET | `/{id}/messages` | Read deterministic, cursor-paginated message history |
| POST | `/{id}/messages` | Submit a question, selected document UUIDs, and idempotency UUID |

Migration `786d1e428cd2` adds `conversations`, `conversation_documents`, `messages`, and `chat_usage`. Foreign keys model ownership, selected documents, and history. The message identity, role/status checks and request-role uniqueness support deterministic history and idempotency. The usage ledger survives conversation deletion, so deleting a chat does not reset the request limit.

## ₹0 controls

The backend uses the configured Gemini Developer API Free project with billing disabled. Set `GEMINI_FREE_TIER_CONFIRMED=true` only after checking its tier. The vendor API key cannot itself attest the billing tier. A server allowlist limits generation to `gemini-3.5-flash-lite`. Gemini 2.5 Flash is deprecated by Google. The embedding space stays at `gemini-embedding-2` with 768 dimensions. The synchronous embed call sends a bounded list of independent inputs through the SDK and does not create asynchronous Batch API jobs. [Gemini pricing and availability](https://ai.google.dev/gemini-api/docs/pricing)

Defaults include three questions per user per minute, 20 per rolling day, one concurrent question, five selected PDFs, six retrieved chunks, 5,000 bytes for the serialized context plus prompt, 1,024 maximum output tokens, and at most two attempts for transient generation or embedding errors. Gemini quota errors surface without repeated generation requests. The provider's actual project quota can be lower and applies across users. Check active limits in AI Studio and keep Cloud Billing disabled. [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)

See the root `.env.example` for every limit and the [document guide](phase-03-documents.md) for Supabase, Chroma, migrations, worker, API, and frontend startup. Unit and PostgreSQL-backed tests use deterministic cloud adapters. Run `python -m pytest -q` from `backend`. The document guide describes the opt-in live operating-systems test. A 429 with `rate_limit` means the local quota was reached. `provider_quota` means Gemini rejected the request due to provider limits. Check server configuration on `provider_configuration` and the local Chroma service on `retrieval_unavailable`.
