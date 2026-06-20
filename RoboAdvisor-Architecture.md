# Arquitectura RoboAdvisor — Davivienda Corredores

## Visión General

Sistema RAG (Retrieval-Augmented Generation) compuesto por dos servicios independientes y una base de datos vectorial compartida.

```mermaid
graph TB
    subgraph PYTHON ["🐍 Python Service — robo-advisor-ingestion"]
        P1[Scraper<br/>Playwright/BeautifulSoup]
        P2[Text Cleaner<br/>HTML → texto limpio]
        P3[Chunker<br/>LangChain RecursiveCharacterTextSplitter]
        P4[Embedder<br/>LangChain Embeddings]
        P5[PGVector Writer<br/>LangChain PGVector store]
        P1 --> P2 --> P3 --> P4 --> P5
    end

    subgraph PG ["🐘 PostgreSQL + pgvector"]
        DB[(document_chunks<br/>content + embedding + metadata)]
    end

    subgraph NEST ["🟥 NestJS — nest-gpt"]
        N1[VectorModule<br/>TypeORM + pgvector]
        N2[mefia-chat.use-case<br/>Orquestador RAG]
        N3[AiProviderService<br/>getEmbedding + generateChat]
        N4[AsesorFinanciero.md<br/>System Prompt RAG]
        N1 -->|top-K chunks| N2
        N3 -->|vector de consulta| N1
        N2 --> N3
        N4 -->|inyecta CONTEXTO_VECTORIAL| N2
    end

    subgraph ANGULAR ["🔷 Angular — bpiapp"]
        UI[Chat RoboAdvisor]
    end

    P5 --> DB
    DB --> N1
    UI -->|POST /gpt/mefia-chat| N2
    N2 -->|respuesta estructurada| UI

    CRON[⏰ Cron / Task Scheduler] -->|dispara ingestion| P1
```

---

## Base de Datos Vectorial: pgvector (PostgreSQL)

### ¿Por qué pgvector?

| Criterio | pgvector |
|---|---|
| Motor base | PostgreSQL — el mismo que ya usa NestJS con TypeORM |
| Instalación | Extensión sobre Postgres, misma imagen Docker |
| Operación | Una sola BD para datos relacionales Y vectores |
| Búsqueda | `cosine`, `L2`, `inner product` |
| Integración NestJS | TypeORM con columna tipo `vector` |
| Escalabilidad | Suficiente para decenas de millones de chunks |

### Configuración Docker

Reemplazar la imagen estándar en `docker-compose.yml`:

```yaml
services:
  db:
    container_name: bpai-db
    image: pgvector/pgvector:pg16   # imagen con la extensión incluida
    environment:
      POSTGRES_DB: bpai-db
      POSTGRES_USER: bpai-user
      POSTGRES_PASSWORD: bpai-password
    ports:
      - "5432:5432"
    volumes:
      - bpai-postgres-data:/var/lib/postgresql/data
    restart: always

volumes:
  bpai-postgres-data:
```

Activar la extensión una sola vez (vía migración o subscriber de inicialización):

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### Diseño de la tabla `document_chunks`

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | UUID | PK |
| `content` | TEXT | Chunk de texto scrapeado |
| `embedding` | VECTOR(768) | Vector generado (dims según modelo) |
| `source_url` | TEXT | URL de origen en Davivienda Corredores |
| `product_name` | TEXT | Nombre del producto financiero |
| `scraped_at` | TIMESTAMP | Fecha del scraping |
| `chunk_index` | INT | Posición del chunk dentro del documento |

> **Nota sobre dimensiones del vector:**
> - Ollama `nomic-embed-text` → `768` dims
> - Gemini `text-embedding-004` → `768` dims
> - OpenAI `text-embedding-3-small` → `1536` dims
>
> El modelo de embedding usado en Python (ingesta) **debe ser el mismo** que usa NestJS en runtime.

---

## Servicio Python — `robo-advisor-ingestion`

**Responsabilidad única:** mantener la base de datos vectorial actualizada con la información más reciente de Davivienda Corredores.

### Estructura de módulos

```mermaid
graph LR
    A[scraper.py] --> B[cleaner.py]
    B --> C[chunker.py]
    C --> D[embedder.py]
    D --> E[vector_store.py]
    F[scheduler.py] -->|orquesta| A
    G[config.py] -.->|env vars| A & D & E
```

### Módulos y responsabilidades

| Módulo | Función | Librería |
|---|---|---|
| `scraper.py` | Navega Davivienda Corredores, extrae HTML por sección de producto | `Playwright` + `BeautifulSoup4` |
| `cleaner.py` | Elimina menús, footers, avisos legales repetitivos, normaliza texto | Python nativo |
| `chunker.py` | Divide en chunks de ~500 tokens con overlap de 50 | `LangChain RecursiveCharacterTextSplitter` |
| `embedder.py` | Convierte cada chunk a vector float[] | `LangChain OllamaEmbeddings` o `GoogleGenerativeAIEmbeddings` |
| `vector_store.py` | Conecta a pgvector y hace UPSERT de chunks | `LangChain PGVector` |
| `scheduler.py` | Ejecuta el pipeline completo en horario (ej. diario 2am) | `APScheduler` |
| `config.py` | Variables de entorno: URL de PG, modelo de embedding, URL Davivienda | `pydantic-settings` |

### Flujo detallado de ingesta

```
1. scheduler.py dispara pipeline
2. scraper.py → lista de URLs de productos Davivienda Corredores
3. Por cada URL:
   a. scraper.py     → HTML crudo
   b. cleaner.py     → texto limpio + metadata { url, product_name, scraped_at }
   c. chunker.py     → lista de chunks con metadata heredada
   d. embedder.py    → chunk + vector[]
   e. vector_store.py → UPSERT en tabla document_chunks (clave: source_url)
4. Log de ejecución: cantidad chunks insertados / actualizados / eliminados
```

### Estrategia de chunking recomendada

- Tamaño de chunk: **~500 tokens** con overlap de **50 tokens**
- Separadores: secciones de producto, encabezados H2/H3
- Metadata obligatoria por chunk: URL, nombre del producto, fecha de scraping

### Variables de entorno Python

```env
PGVECTOR_CONNECTION_STRING=postgresql+psycopg2://user:pass@localhost:5432/bpai-db
EMBEDDING_MODEL=nomic-embed-text
DAVIVIENDA_BASE_URL=https://www.daviviendacorredores.com
CHUNK_SIZE=500
CHUNK_OVERLAP=50
SCHEDULE_CRON=0 2 * * *
```

---

## Backend NestJS — `nest-gpt`

**Responsabilidad única:** recibir la pregunta del usuario, ejecutar el pipeline RAG en tiempo real y retornar una respuesta estructurada.

### Flujo RAG completo

```mermaid
graph TD
    GC[GptController<br/>POST /gpt/mefia-chat] --> GS[GptService.qaChat]
    GS --> UC[mefia-chat.use-case<br/>⭐ Orquestador RAG]
    UC -->|1. embed pregunta| AI[AiProviderService<br/>getEmbedding]
    AI -->|vector_q| VS[VectorService<br/>similaritySearch]
    VS -->|SQL cosine search| PG[(pgvector<br/>document_chunks)]
    PG -->|top-K chunks| UC
    UC -->|2. construir prompt| SP[AsesorFinanciero.md<br/>system prompt + CONTEXTO_VECTORIAL]
    SP -->|3. prompt enriquecido| AI2[AiProviderService<br/>generateChatCompletion]
    AI2 -->|respuesta estructurada| GC
```

### Responsabilidades por capa

| Capa | Archivo | Estado | Función |
|---|---|---|---|
| **Controller** | `gpt/gpt.controller.ts` | Sin cambios | Recibe `POST /gpt/mefia-chat` |
| **Service** | `gpt/gpt.service.ts` | Sin cambios | Delega a `qaChatUseCase` |
| **Use Case** | `gpt/use-cases/mefia-chat.use-case.ts` | **Se amplía** | Orquesta embed → búsqueda → inyección → LLM |
| **VectorModule** | `vector/vector.module.ts` | **Nuevo** | Expone `VectorService` a `GptModule` |
| **VectorService** | `vector/vector.service.ts` | **Nuevo** | Ejecuta query cosine en pgvector vía TypeORM |
| **DocumentChunk entity** | `vector/entities/document-chunk.entity.ts` | **Nueva** | Entidad TypeORM mapeada a `document_chunks` |
| **AiProviderService** | `ai/ai-provider.interface.ts` | Ya existe ✅ | `getEmbedding()` listo para usar |
| **AsesorFinanciero.md** | `AsesorFinanciero.md` | Ya existe ✅ | System prompt con etiqueta `[CONTEXTO_VECTORIAL]` |

### Lógica conceptual de `mefia-chat.use-case.ts` (pipeline RAG)

```
Recibe: { question: string }

Paso 1 — Embedding de la consulta:
  vector_q = aiProvider.getEmbedding(EMBED_MODEL, question)

Paso 2 — Búsqueda vectorial (top-K por similitud coseno):
  chunks[] = vectorService.similaritySearch(vector_q, topK=5)
  → Query pgvector: ORDER BY embedding <=> $1 LIMIT 5

Paso 3 — Construcción del contexto inyectado:
  contextBlock = chunks.map(c => c.content).join('\n---\n')
  userPrompt = "[CONTEXTO_VECTORIAL]\n" + contextBlock + "\n\nPREGUNTA: " + question

Paso 4 — Generación con LLM:
  result = aiProvider.generateChatCompletion(
    model     = OLLAMA_QA_MODEL,
    system    = AsesorFinanciero.md,   ← ya tiene la etiqueta [CONTEXTO_VECTORIAL]
    user      = userPrompt,
    options   = { temperature: 0.07 } ← disciplina para respuesta estructurada
  )

Retorna: { answer: result.content, model: result.model }
```

### Variables de entorno a agregar en `.env`

```env
# pgvector (puede reusar las mismas credenciales de POSTGRES_*)
PGVECTOR_HOST=localhost
PGVECTOR_PORT=5432
PGVECTOR_USER=bpai-user
PGVECTOR_PASSWORD=bpai-password
PGVECTOR_DB=bpai-db

# Parámetros RAG
VECTOR_TOP_K=5
EMBED_MODEL=nomic-embed-text
```

---

## Separación de Responsabilidades (Resumen)

| Responsabilidad | Python | NestJS |
|---|---|---|
| Scraping de Davivienda Corredores | ✅ | ❌ |
| Limpieza y chunking de texto | ✅ | ❌ |
| Generación de embeddings (ingesta) | ✅ | ❌ |
| Escritura en pgvector | ✅ | ❌ |
| Programación de re-indexado | ✅ | ❌ |
| Recibir pregunta del usuario | ❌ | ✅ |
| Embedding de la consulta (runtime) | ❌ | ✅ |
| Búsqueda por similitud coseno (runtime) | ❌ | ✅ |
| Inyección de contexto en prompt | ❌ | ✅ |
| Llamada al LLM para respuesta | ❌ | ✅ |
| Autenticación JWT del usuario | ❌ | ✅ |
| Exposición de API REST al frontend Angular | ❌ | ✅ |

---

## Estado del Proyecto (Lo que ya está listo)

| Componente | Estado | Notas |
|---|---|---|
| `AiProviderService.getEmbedding()` | ✅ Listo | Soporta Gemini y Ollama |
| `AiProviderService.generateChatCompletion()` | ✅ Listo | Con retry en Gemini |
| `AsesorFinanciero.md` (system prompt RAG) | ✅ Listo | Ya incluye etiqueta `[CONTEXTO_VECTORIAL]` |
| `mefia-chat.use-case.ts` (base) | ✅ Listo | Solo falta agregar pasos 1-3 del pipeline RAG |
| `docker-compose.yml` | ⚠️ Requiere cambio de imagen | `postgres:16-alpine` → `pgvector/pgvector:pg16` |
| `VectorModule` + `VectorService` | ❌ Pendiente | Módulo nuevo en NestJS |
| `DocumentChunk` entity | ❌ Pendiente | Entidad TypeORM nueva |
| Proyecto Python de ingesta | ❌ Pendiente | Nuevo repositorio/servicio |

---

## Orden de Implementación Recomendado

1. **`docker-compose.yml`** — Cambiar imagen a `pgvector/pgvector:pg16`
2. **`DocumentChunk` entity** — Entidad TypeORM con columna `vector`
3. **`VectorModule` + `VectorService`** — Módulo de búsqueda por similitud
4. **`mefia-chat.use-case.ts`** — Ampliar con los 4 pasos del pipeline RAG
5. **Proyecto Python** — Scraper + Chunker + Embedder + Writer con LangChain
