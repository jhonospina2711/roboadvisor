# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An AI-powered web scraping and Q&A system for Davivienda Corredores (Colombian investment broker). It combines RAG (Retrieval-Augmented Generation) with multi-fallback scraping and a pluggable LLM backend (Ollama local or Google Gemini cloud), exposed via CLI and FastAPI.

## Setup

```bash
py -3.14 -m venv venv
.\venv\Scripts\Activate.ps1        # Windows PowerShell
python -m pip install -r requirements.txt
python -m playwright install       # Download Chromium for browser automation
ollama pull gemma4:e4b             # Download local LLM (only needed for Ollama provider)
```

Copy `.env.example` to `.env` and fill in:
- `LLM_PROVIDER` — `ollama` (default, local) or `gemini` (cloud)
- `LOCAL_MODEL` — Ollama model name (default: `gemma4-financiero`; must match `ollama list`)
- `GEMINI_MODEL` — Gemini model name (default: `gemini-2.0-flash`)
- `GOOGLE_API_KEY` — required when `LLM_PROVIDER=gemini`
- `TARGET_URL` — target website (default: `https://daviviendacorredorescolab.dvvapps.io`)
- `QA_MAX_PAGES` / `QA_TOP_K` — indexing and retrieval defaults
- `LLM_TEMPERATURE` — model creativity (default: `0` for deterministic answers)

Ollama must be running on `http://localhost:11434` when `LLM_PROVIDER=ollama`.

**Windows pip error fix**: if `pip` shows "Fatal error in launcher", delete and recreate the venv, then always use `python -m pip` instead of bare `pip`.

## Running

```bash
# Interactive Q&A chat — provider selected via LLM_PROVIDER in .env
python davivienda_chat_qa.py --max-pages 20 --top-k 4

# Single question
python davivienda_chat_qa.py --question "¿Qué productos de inversión ofrecen?" --max-pages 20

# Override model at runtime (still uses the provider from LLM_PROVIDER)
python davivienda_chat_qa.py --model gemini-2.5-flash --max-pages 20

# REST API
uvicorn api:app --host 0.0.0.0 --port 8000

# Basic demo scraper (quotes.toscrape.com)
python scraper.py

# AI browser agent (Playwright + local LLM)
python agent_browser.py
```

API can be tested via `postman/DaviviendaCorredoresQA.postman_collection.json`.

No build step, no test suite, no linter configured.

## Architecture

### Folder structure

```
core/
├── document.py          # Document dataclass (url, title, text)
├── utils.py             # normalize_text / normalize_for_match (shared)
├── scraping/
│   ├── fetcher.py       # HTTP fetch with 3-layer anti-bot fallback
│   ├── parser.py        # HTML → clean text extraction pipeline
│   └── corpus.py        # build_corpus, sitemap + URL scope helpers
├── retrieval/
│   └── search.py        # Spanish tokenizer + BM25-like scorer
├── llm/
│   ├── base.py          # LLMClient Protocol (structural typing)
│   ├── factory.py       # get_llm_client() — reads LLM_PROVIDER from env
│   ├── ollama/
│   │   └── client.py    # OllamaClient wraps langchain_ollama.ChatOllama
│   └── gemini/
│       └── client.py    # GeminiClient wraps langchain_google_genai.ChatGoogleGenerativeAI
└── qa/
    ├── pipeline.py      # answer_question, build_prompt, dedup sources
    ├── guardrails.py    # Competitor detection → canned refusal
    └── fallback.py      # Extractive sentence fallback when LLM returns "not found"

api.py                   # FastAPI entry point (thin wrapper over core/)
davivienda_chat_qa.py    # CLI entry point (thin wrapper over core/)
scraper.py               # Educational static scraper (quotes.toscrape.com)
agent_browser.py         # LangChain + Playwright browser agent demo
```

### Switching LLM provider

The only change needed is in `.env`:

```env
# Use Ollama (local)
LLM_PROVIDER=ollama
LOCAL_MODEL=gemma4-financiero

# Use Gemini (cloud)
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-2.0-flash
GOOGLE_API_KEY=<your-key>
```

`core/llm/factory.py:get_llm_client()` reads `LLM_PROVIDER` and instantiates the right client. `api.py` and `davivienda_chat_qa.py` both call `get_llm_client()` — no other code needs to change.

### Data flow

```
TARGET_URL
  → [requests | cloudscraper | urllib] (3-layer anti-bot fallback)
  → Sitemap + internal link extraction + raw-HTML regex fallback
  → Per-page: remove layout noise → collect semantic chunks (h1/h2/h3/p/li)
               → content quality gate (min 220 chars, <40% boilerplate, <30% link-heavy)
               → deduplication by exact key + term signature
  → List[Document] (url, title, text)
  → Spanish BM25-like scorer → Top-K documents
  → Competitor guardrail check (short-circuits to canned refusal if triggered)
  → LLM prompt (OllamaClient or GeminiClient)
  → If LLM returns "not found" → extractive sentence fallback
```

### Search algorithm (`core/retrieval/search.py`)

Custom term-frequency scorer with Spanish-aware tokenization:
- Stopword removal (43 words), NFKD accent stripping, plural suffix stripping (`es`/`s`)
- Scoring: text hit = 1.0, title hit = 3.0, fuzzy prefix hit = 0.2, exact phrase = 6.0 bonus
- Falls back to top-ranked docs when all scores are 0

### Competitor guardrail (`core/qa/guardrails.py`)

`check_competitor_guardrail()` checks whether the question mentions a known competitor (Bancolombia, BBVA, Skandia, Itaú, etc.). If the competitor name is absent from the retrieved docs it returns a canned refusal instead of calling the LLM, preventing hallucinated competitor comparisons.

### API endpoints (`api.py`)

- `GET /health` — status, indexed page count, active provider + model
- `POST /ask` — `{question, top_k?, model?}` → answer + sources + provider
- `POST /reindex` — `{max_pages?}` → rebuild document index
- `GET /debug/index` — inspect indexed document titles/URLs (dev only)

Auto-indexes on startup; re-indexes within `/ask` if doc count drops below 3. Uses `threading.Lock` for index mutations.

### Anti-bot scraping strategy (`core/scraping/fetcher.py`)

1. `requests` with Chrome 124 User-Agent
2. `cloudscraper` (bypasses Cloudflare/WAF)
3. `urllib` bare-bones fallback
4. Detects anti-bot markers (`"pardon our interruption"`, `"noindex, nofollow"`) and skips those pages
5. 1-second delay between page fetches
6. Blocks PDFs, images, and `/download` URLs automatically
