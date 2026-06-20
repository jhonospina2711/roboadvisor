# Davivienda Corredores Q&A

Asistente de preguntas y respuestas sobre el sitio público de Davivienda Corredores. Combina scraping con múltiples capas anti-bot, indexación RAG personalizada en español, y soporte para dos proveedores LLM: **Ollama** (local) y **Google Gemini** (nube), seleccionables mediante una variable de entorno.

## Componentes

| Archivo | Rol |
|---|---|
| `davivienda_chat_qa.py` | CLI interactivo o pregunta única |
| `api.py` | API REST (FastAPI) |
| `scraper.py` | Scraper educativo estático (quotes.toscrape.com) |
| `agent_browser.py` | Agente IA con navegador Playwright |
| `core/` | Toda la lógica de negocio (scraping, retrieval, LLM, QA) |

## Requisitos previos

- Python 3.10+
- [Ollama](https://ollama.com/) — solo si usas `LLM_PROVIDER=ollama`
- Clave de [Google AI Studio](https://aistudio.google.com/) — solo si usas `LLM_PROVIDER=gemini`

## Inicio rápido (Windows PowerShell)

### 1. Entorno virtual

```powershell
py -3.14 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install
```

> Si aparece *"Fatal error in launcher"*, elimina el venv y vuelve a crearlo usando siempre `python -m pip` en lugar de `pip` directamente.

### 2. Configurar `.env`

Copia el archivo de ejemplo y edítalo:

```powershell
copy .env.example .env
```

**Solo cambia `LLM_PROVIDER`** para elegir el backend:

```env
# Para usar Ollama (modelo local, no requiere internet)
LLM_PROVIDER=ollama
LOCAL_MODEL=gemma4-financiero   # debe coincidir con: ollama list

# Para usar Gemini (nube, requiere GOOGLE_API_KEY)
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-2.0-flash
GOOGLE_API_KEY=tu-clave-aqui
```

Puedes tener todas las variables en el `.env` al mismo tiempo; solo se usa la sección del proveedor activo.

### 3. Descargar modelo (solo Ollama)

```powershell
ollama pull gemma4:e4b
```

Asegúrate de que el nombre coincida con `LOCAL_MODEL` en tu `.env`.

### 4. Ejecutar

```powershell
# Chat interactivo
python davivienda_chat_qa.py --max-pages 20 --top-k 4

# Pregunta única
python davivienda_chat_qa.py --question "¿Qué productos de inversión ofrecen?" --max-pages 20

# API REST
python -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

## API REST

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/health` | Estado del servicio, proveedor activo y páginas indexadas |
| `POST` | `/ask` | Responde una pregunta (`question`, `top_k?`, `model?`) |
| `POST` | `/reindex` | Reconstruye el índice de documentos (`max_pages?`) |
| `GET` | `/debug/index` | Lista los documentos indexados (desarrollo) |

Colección Postman lista para importar: `postman/DaviviendaCorredoresQA.postman_collection.json`

### Ejemplos curl

```bash
# Health check
curl http://localhost:8000/health

# Preguntar
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "¿Qué productos de inversión ofrecen para personas?", "top_k": 4}'

# Reindexar
curl -X POST http://localhost:8000/reindex \
  -H "Content-Type: application/json" \
  -d '{"max_pages": 20}'
```

## Arquitectura `core/`

```
core/
├── document.py          # Dataclass Document (url, title, text)
├── utils.py             # Normalización de texto compartida
├── scraping/
│   ├── fetcher.py       # HTTP con fallback anti-bot (requests → cloudscraper → urllib)
│   ├── parser.py        # Extracción y limpieza de HTML
│   └── corpus.py        # build_corpus, sitemap, filtros de URL
├── retrieval/
│   └── search.py        # Tokenizador español + scorer BM25-like
├── llm/
│   ├── base.py          # Protocol LLMClient
│   ├── factory.py       # get_llm_client() — lee LLM_PROVIDER del .env
│   ├── ollama/
│   │   └── client.py    # OllamaClient
│   └── gemini/
│       └── client.py    # GeminiClient
└── qa/
    ├── pipeline.py      # answer_question, build_prompt
    ├── guardrails.py    # Detección de competidores → respuesta bloqueada
    └── fallback.py      # Fallback extractivo cuando el LLM no encuentra info
```

## Flujo de datos

```
TARGET_URL
  → Scraping anti-bot (3 capas)
  → Extracción de texto limpio por página
  → List[Document]
  → Scorer BM25 español → Top-K documentos
  → Guardrail de competidores (corto-circuita si aplica)
  → LLM (Ollama o Gemini según LLM_PROVIDER)
  → Si responde "no encontré" → fallback extractivo por oraciones
```
