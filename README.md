# Scraping Codelab

## Descripción

Este proyecto contiene dos scripts de web scraping que extraen citas de [Quotes to Scrape](https://quotes.toscrape.com/):

### `scraper.py` — Web Scraper tradicional
Utiliza **Requests** y **BeautifulSoup** para hacer scraping estático de la página. Recorre múltiples páginas extrayendo citas, autores y tags.

### `agent_browser.py` — Agente de IA con navegador
Utiliza **LangChain** con **Gemma en local (vía Ollama)** y **Playwright** para crear un agente de IA que controla un navegador real. El agente navega a la página, extrae la primera cita y la traduce a español, japonés y swahili.

### `davivienda_chat_qa.py` — Chat Q&A con scraping de Davivienda Corredores
Hace scraping de páginas públicas de Davivienda Corredores, indexa contenido y responde preguntas de clientes usando **Gemma local (Ollama)** con fuentes citadas.

### `api.py` — API para integrar el chat en una app
Expone endpoints HTTP para consultar preguntas de clientes, refrescar índice y revisar estado del servicio.

## Requisitos previos

- Python 3.10+
- [Ollama](https://ollama.com/) instalado
- Un modelo Gemma descargado en Ollama (por ejemplo, `gemma4:e4b`)

## Inicio rapido (Windows PowerShell)

1. Ir a la carpeta del proyecto:
   ```powershell
   cd C:\Users\tamac\Documents\5.GENIA\roboAdvisor\scraping-codelab
   ```

2. Crear y activar entorno virtual:
   ```powershell
   py -3.14 -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. Instalar dependencias usando el Python activo (recomendado):
   ```powershell
   python -m pip install --upgrade pip
   python -m pip install -r .\requirements.txt
   ```

4. Instalar navegadores de Playwright:
   ```powershell
   python -m playwright install
   ```

5. Asegurar modelo local en Ollama:
   ```powershell
   ollama pull gemma4:e4b
   ```

6. Crear archivo `.env` en la raiz:
   ```env
   LOCAL_MODEL=gemma4:e4b
   LLM_TEMPERATURE=0
   ```

7. Levantar la API:
   ```powershell
   python -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload
   ```

8. Verificar servicio:
   ```powershell
   curl http://localhost:8000/health
   ```

## Solucion de error: "Fatal error in launcher"

Si aparece un error como este al instalar dependencias:

`Fatal error in launcher: Unable to create process ...`

normalmente significa que `pip.exe` quedo enlazado a una ruta vieja del entorno virtual.

Solucion recomendada:

```powershell
deactivate
Remove-Item -Recurse -Force .\venv
py -3.14 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r .\requirements.txt
```

Nota: usa `python -m pip` en lugar de `pip` para evitar conflictos de PATH en Windows.

## Instalación

1. Clonar el repositorio:
   ```bash
   git clone <url-del-repositorio>
   cd scraping-codelab
   ```

2. Crear y activar un entorno virtual:
   ```bash
   python -m venv venv

   # Windows (PowerShell)
   .\venv\Scripts\Activate.ps1

   # Linux/Mac
   source venv/bin/activate
   ```

3. Instalar dependencias:
   ```bash
   python -m pip install -r requirements.txt
   ```

4. Instalar los navegadores de Playwright:
   ```bash
   playwright install
   ```

5. Descargar un modelo Gemma local con Ollama:
   ```bash
   ollama pull gemma4:e4b
   ```

6. Configurar las variables de entorno. Crear un archivo `.env` en la raíz del proyecto:
   ```
   LOCAL_MODEL=gemma4:e4b
   LLM_TEMPERATURE=0
   ```

Si no defines `LOCAL_MODEL`, el script usa `gemma4:e4b` por defecto.
Si no defines `LLM_TEMPERATURE`, se usa `0` por defecto.

## Ejecución

### Scraper tradicional
```bash
python scraper.py
```
Extrae citas de las primeras 3 páginas y las muestra en consola.

### Agente de IA con navegador
```bash
python agent_browser.py
```
Abre un navegador Chromium, navega a la página de citas y usa IA para extraer y traducir la primera cita.

### Chat Q&A con scraping de Davivienda Corredores

Modo chat interactivo:
```bash
python davivienda_chat_qa.py --max-pages 20 --top-k 4
```

Pregunta única por línea de comando:
```bash
python davivienda_chat_qa.py --question "¿Qué productos de inversión ofrecen para personas?" --max-pages 20 --top-k 4
```

Opcionalmente puedes cambiar el modelo:
```bash
python davivienda_chat_qa.py --model gemma4:e4b
```

### API HTTP (FastAPI)

Levantar servidor:
```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

Health check:
```bash
curl http://localhost:8000/health
```

Reindexar contenido:
```bash
curl -X POST http://localhost:8000/reindex -H "Content-Type: application/json" -d "{\"max_pages\":20}"
```

Preguntar al asistente:
```bash
curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d "{\"question\":\"¿Qué productos de inversión ofrecen para personas?\",\"top_k\":4,\"model\":\"gemma4:e4b\"}"
```

Colección de Postman lista para importar:
- `postman/DaviviendaCorredoresQA.postman_collection.json`
