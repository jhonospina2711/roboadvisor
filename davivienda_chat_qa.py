"""CLI entry point for the Davivienda Corredores Q&A assistant.

Provider and model are controlled via environment variables:
  LLM_PROVIDER=ollama  (default) or gemini
  LOCAL_MODEL=<ollama model name>
  GEMINI_MODEL=<gemini model name>
"""

import argparse
import os

import requests
from dotenv import load_dotenv

from core.llm.factory import get_default_model, get_llm_client
from core.qa.pipeline import answer_question
from core.scraping.corpus import build_corpus
from core.scraping.fetcher import USER_AGENT

load_dotenv()


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def run_single_question(question: str, max_pages: int, top_k: int, model: str) -> None:
    docs = build_corpus(session=_build_session(), max_pages=max_pages)
    if not docs:
        print("No se pudo construir corpus de paginas publicas.")
        return

    llm = get_llm_client(model=model)
    print(f"\nPaginas indexadas: {len(docs)}")
    print("\n=== RESPUESTA ===")
    print(answer_question(question=question, docs=docs, llm=llm, top_k=top_k))


def run_chat(max_pages: int, top_k: int, model: str) -> None:
    docs = build_corpus(session=_build_session(), max_pages=max_pages)
    if not docs:
        print("No se pudo construir corpus de paginas publicas.")
        return

    llm = get_llm_client(model=model)
    provider = os.getenv("LLM_PROVIDER", "ollama")
    print(f"\nIndice listo con {len(docs)} paginas. Modelo: {model} ({provider})")
    print("Escribe tu pregunta (o 'salir').\n")

    while True:
        question = input("Cliente> ").strip()
        if not question:
            continue
        if question.lower() in {"salir", "exit", "quit"}:
            break
        print("\nAsistente>")
        print(answer_question(question=question, docs=docs, llm=llm, top_k=top_k))
        print()


def main() -> None:
    default_model = get_default_model()

    parser = argparse.ArgumentParser(
        description="Q&A con scraping para Davivienda Corredores (Ollama o Gemini)"
    )
    parser.add_argument("--question", type=str, default="", help="Pregunta unica")
    parser.add_argument("--max-pages", type=int, default=20, help="Maximo de paginas a indexar")
    parser.add_argument("--top-k", type=int, default=4, help="Cantidad de paginas relevantes por respuesta")
    parser.add_argument("--model", type=str, default=default_model, help="Nombre del modelo LLM")

    args = parser.parse_args()

    if args.question:
        run_single_question(
            question=args.question,
            max_pages=args.max_pages,
            top_k=args.top_k,
            model=args.model,
        )
    else:
        run_chat(max_pages=args.max_pages, top_k=args.top_k, model=args.model)


if __name__ == "__main__":
    main()
