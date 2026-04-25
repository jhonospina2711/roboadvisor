# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An AI-powered web scraping and Q&A system for Davivienda Corredores (Colombian investment broker). It combines RAG (Retrieval-Augmented Generation) with multi-fallback scraping and a local Ollama LLM, exposed via CLI and FastAPI.

## Setup

```bash
py -3.14 -m venv venv
.\venv\Scripts\Activate.ps1        # Windows PowerShell
python -m pip install -r requirements.txt
python -m playwright install       # Download Chromium for browser automation
ollama pull gemma4:e4b             # Download local LLM
```

Copy `.env` and fill in:
- `LOCAL_MODEL` — Ollama model name (default: `gemma4:e4b`)
- `TARGET_URL` — target website (default: `https://daviviendacorredorescolab.dvvapps.io`)
- `QA_MAX_PAGES` / `QA_TOP_K` — indexing and retrieval defaults
- `GOOGLE_API_KEY`, `OPENAI_API_KEY` — optional cloud LLM keys

Ollama must be running locally on `http://localhost:11434` before starting any QA or API component.

## Running

```bash
# Interactive Q&A chat (scrapes + indexes on start)
python davivienda_chat_qa.py --max-pages 20 --top-k 4

# Single question
python davivienda_chat_qa.py --question "¿Qué productos de inversión ofrecen?" --max-pages 20

# REST API
uvicorn api:app --host 0.0.0.0 --port 8000

# Basic demo scraper (quotes.toscrape.com)
python scraper.py

# AI browser agent (Playwright + local LLM)
python agent_browser.py
```

No build step, no test suite, no linter configured.

## Architecture

### Components

| File | Role |
|---|---|
| `scraper.py` | Educational static scraper (Requests + BeautifulSoup, quotes.toscrape.com) |
| `agent_browser.py` | LangChain + Playwright async agent with local Gemma LLM |
| `davivienda_chat_qa.py` | Core RAG system — scraping, indexing, retrieval, LLM Q&A |
| `api.py` | FastAPI wrapper around davivienda_chat_qa |

### Data flow

```
Target URL
  → [requests | cloudscraper | urllib] (3-layer anti-bot fallback)
  → Sitemap + link extraction → per-page text cleaning
  → List[Document] (url, title, text)
  → Custom BM25-like scoring (Spanish NLP: stopwords, accent-insensitive, suffix stripping)
  → Top-K documents → LLM prompt
  → Ollama Gemma response (+ extractive fallback if LLM output unparseable)
```

### Search algorithm (`davivienda_chat_qa.py`)

Custom term-frequency scorer with Spanish-aware tokenization:
- Stopword removal (43 Spanish words), NFKD accent stripping, plural suffix stripping (`es`/`s`)
- Scoring: text hit = 1.0, title hit = 3.0, fuzzy prefix hit = 0.2, exact phrase in text = 6.0 bonus
- Min-threshold filter before returning Top-K

### API endpoints (`api.py`)

- `GET /health` — status + index doc count
- `POST /ask` — `{question, top_k?}` → answer + sources
- `POST /reindex` — rebuild document index
- `GET /debug/index` — inspect indexed documents (dev only)

Auto-indexes on startup; re-indexes if doc count drops below threshold. Uses `threading.Lock` for index mutations.

### Anti-bot scraping strategy

1. `requests` with Chrome 124 User-Agent
2. `cloudscraper` (bypasses Cloudflare/WAF)
3. `urllib` bare-bones fallback
4. Detects anti-bot markers (`"pardon our interruption"`) and skips those pages
5. 1-second delay between page fetches
6. Blocks PDFs, images, and download URLs automatically
