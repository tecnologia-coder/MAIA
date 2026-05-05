"""
Backfill: classifica pedidos antigos que estão sem tags_semanticas.
Usa Gemini (gemini-2.0-flash-lite) em batches de 20 pedidos por vez.
"""

import json
import os
import sys
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# Suporta tanto GEMINI_API_KEY quanto GOOGLE_API_KEY (legado)
_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not _api_key:
    print("[ERRO] Configure GEMINI_API_KEY ou GOOGLE_API_KEY no ambiente.")
    sys.exit(1)

# Adiciona raiz do projeto ao path para importar execution/
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from execution.supabase_client import get_supabase_client

MODEL = "gemini-2.0-flash-lite"
BATCH_SIZE = 20
LIMIT = 100  # máximo de pedidos por execução

CATEGORIES = [
    "BEBÊS E CRIANÇAS",
    "GESTANTES",
    "MÃES",
    "UTILIDADES",
    "FESTAS",
    "SAÚDE",
    "GASTRONOMIA",
]

SYSTEM_PROMPT = (
    "Você é um classificador de pedidos de indicação recebidos em grupos de WhatsApp de mães.\n"
    f"Categorias disponíveis: {', '.join(CATEGORIES)}.\n"
    "Para cada pedido, atribua de 1 a 3 tags da lista acima que melhor descrevem o assunto.\n"
    "Retorne APENAS um JSON array, sem texto adicional: "
    '[{"id": N, "tags": ["TAG1", "TAG2"]}]'
)


def classify_batch(client: genai.Client, batch: list[dict]) -> list[dict]:
    user_prompt = "\n".join(
        f"ID: {p['id']} | {p.get('pedido_mensagem') or p.get('pedido_descricao') or 'sem texto'}"
        for p in batch
    )

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
    )

    response = client.models.generate_content(
        model=MODEL,
        contents=user_prompt,
        config=config,
    )

    raw = response.text.strip()
    if raw.startswith("```json"):
        raw = raw.replace("```json", "", 1).replace("```", "", 1).strip()

    return json.loads(raw)


def main():
    supabase = get_supabase_client()
    client = genai.Client(api_key=_api_key)

    print(f"[classify_pedidos] Buscando até {LIMIT} pedidos sem tags_semanticas...")

    res = (
        supabase.table("pedidos_indicacao")
        .select("id, pedido_mensagem, pedido_descricao")
        .is_("tags_semanticas", "null")
        .limit(LIMIT)
        .execute()
    )

    pedidos = res.data or []
    if not pedidos:
        print("[classify_pedidos] Nenhum pedido pendente. Nada a fazer.")
        return

    print(f"[classify_pedidos] {len(pedidos)} pedidos encontrados. Classificando em batches de {BATCH_SIZE}...")

    processed = 0
    errors = 0

    for i in range(0, len(pedidos), BATCH_SIZE):
        batch = pedidos[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"[classify_pedidos] Batch {batch_num}: {len(batch)} pedidos...")

        try:
            classifications = classify_batch(client, batch)
        except Exception as e:
            print(f"[classify_pedidos] Erro no batch {batch_num}: {e}")
            errors += len(batch)
            time.sleep(5)
            continue

        for cls in classifications:
            valid_tags = [t for t in cls.get("tags", []) if t in CATEGORIES]
            if not valid_tags:
                continue

            try:
                supabase.table("pedidos_indicacao").update(
                    {"tags_semanticas": valid_tags}
                ).eq("id", cls["id"]).execute()
                processed += 1
            except Exception as e:
                print(f"[classify_pedidos] Erro ao atualizar pedido {cls['id']}: {e}")
                errors += 1

        # Pequena pausa entre batches para evitar rate limit
        if i + BATCH_SIZE < len(pedidos):
            time.sleep(1)

    print(f"\n[classify_pedidos] Concluído. Processados: {processed} | Erros: {errors} | Total: {len(pedidos)}")


if __name__ == "__main__":
    main()
