# AI Study Buddy frontend

## Run locally

```sh
npm install
npm run dev
npm run lint
npm run build
```

The frontend uses `VITE_API_BASE_URL` and defaults to `http://127.0.0.1:8000`. Run Vite on port 5173 for the current backend CORS configuration. For a production static host, configure a fallback to `index.html` for client-side routes.

## Routes

| Audience | Routes |
| --- | --- |
| Public | `/`, `/features`, `/workspace`, `/pricing`, `/resources`, `/resources/:slug` |
| Account | `/login`, `/signup` |
| Signed in | `/dashboard`, `/chat`, `/library`, `/quizzes`, `/analytics`, `/calendar`, `/settings` |

Registration, form-encoded login, and bearer-authenticated profile lookup use the FastAPI authentication endpoints. The access token and profile stay in React memory for the current session. The document library uses the token for protected requests. A refresh requires another login. The home composer carries a draft to the AI Tutor through the sign-in flow.

Generated quizzes and saved attempts, personal analytics, profile editing, and billing are pending backend services. The quiz sample and calendar navigation work locally. Public chart data and example prices are illustrative.

The Document Library and AI Tutor use the Phase 03 and Phase 04 APIs. See [the AI Tutor guide](../docs/phase-04-rag-ai-tutor.md) for conversation history, citations, and Free-tier limits. See [the document storage and ingestion guide](../docs/phase-03-documents.md) for local setup.

Quiz Studio uses the real Phase 05 assessment API. See the [quiz guide](../docs/phase-05-ai-quizzes.md) for timed attempts, generation and grading limits, and verification.

Revision Planner supports local scheduling and consent-gated Google Calendar sync. See the [Phase 06 guide](../docs/phase-06-mcp-calendar.md).

## Fonts and artwork

Instrument Serif is the bundled display fallback until a licensed copy of [Grown](https://din-studio.com/product/grown/) is available. Great Vibes and Prata are bundled through Fontsource.

The built-in image generation tool created the WebP assets in `src/assets` from these prompts.

- `dusk.webp` used the supplied dusk mockup as a composition reference. Prompt: “Reconstruct a realistic wide 16:9 panoramic photograph of a snowy downtown at pink dusk, from an elevated rooftop, close high rises with warm illuminated windows on far left, low snow-covered roofs and warm traffic below, distant dense skyline in lower third, dark deep aquamarine overcast sky across upper two thirds and rose clouds towards outer horizon. Cinematic photography with sharp natural architecture. Remove every interface element, words, bar, buttons, and marks. Full bleed edge to edge background texture.”
- `textbook.webp`, `desk.webp`, and `revision.webp` are crops from a generated editorial photo sheet. Prompt: “Create one wide editorial photography contact sheet separated into exact horizontal thirds of equal height, no borders or gaps. Top third: close-up of an open textbook with reading glasses and warm sunlight on a dark wooden study desk. Middle third: a laptop open on a walnut desk with a small plant and a ceramic coffee mug, quiet library backdrop, editorial product photography. Bottom third: overhead monthly paper calendar with a pencil and a green plant at the corner, warm afternoon light. Realistic subdued tones, tan and deep green. No overlays, no labels, no logos. Landscape 3:2.”

## Learning Intelligence

See [Phase 07 Learning Analytics](../docs/phase-07-learning-analytics.md) for metrics, the Analytics API, and local verification.

## Operations

See [Phase 08 production readiness](../docs/phase-08-production-readiness.md) for session settings, Docker, backup, recovery, and deployment guidance.
