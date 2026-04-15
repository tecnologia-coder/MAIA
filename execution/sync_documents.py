"""
sync_documents.py
-----------------
Sincroniza a tabela `documents` com os dados atuais da tabela `parceiros`.

Para cada parceiro ativo (status_aprovacao = 'aprovado'), este script:
1. Monta um conteúdo rico combinando nome, categoria, subcategoria, palavras-chave e descrição
2. Gera um novo embedding via OpenAI
3. Atualiza (ou insere) o registro na tabela `documents`

Uso:
    python -m execution.sync_documents
    python -m execution.sync_documents --dry-run   # apenas imprime, não salva
"""

import argparse
import json
import time

from execution.supabase_client import get_supabase_client
from execution.ai_client import get_embedding


def build_content(p: dict) -> str:
    """Monta o texto rico que será vetorizado e usado na busca."""
    nome = (p.get("nome") or "").strip()
    categoria = (p.get("categoria") or "").strip()
    subcategoria = (p.get("subcategoria") or "").strip()
    palavras_chave = (p.get("palavras_chave") or "").strip()
    descricao = (p.get("descricao") or "").strip()

    # Usa a primeira subcategoria se houver múltiplas (ex: "Lembrancinhas, Biscoitos")
    subcategoria_principal = subcategoria.split(",")[0].strip()

    lines = [
        f"ID: {p['id']}",
        f"NOME: {nome}",
        f"CATEGORIA: {categoria}",
        f"SUBCATEGORIA: {subcategoria_principal}",
    ]

    if palavras_chave:
        lines.append(f"PALAVRAS-CHAVE: {palavras_chave}")

    if descricao:
        lines.append(f"DESCRIÇÃO: {descricao}")
    else:
        # Fallback mínimo se não houver descrição
        lines.append(f"DESCRIÇÃO: Fornecedor especializado em {subcategoria_principal} ({nome}).")

    return "\n".join(lines)


def build_metadata(p: dict) -> dict:
    subcategoria_principal = (p.get("subcategoria") or "").split(",")[0].strip()
    return {
        "ID": int(p["id"]),
        "nome": p.get("nome", "").strip(),
        "categoria": p.get("categoria", "").strip(),
        "subcategoria": subcategoria_principal,
        "source": "blob",
        "blobType": "text/plain",
        "loc": {"lines": {"from": 1, "to": 5}},
    }


def sync(dry_run: bool = False):
    sb = get_supabase_client()

    # Busca parceiros aprovados
    res = sb.table("parceiros").select(
        "id, nome, categoria, subcategoria, palavras_chave, descricao, status_aprovacao"
    ).eq("status_aprovacao", "aprovado").execute()

    parceiros = res.data
    print(f"Parceiros aprovados encontrados: {len(parceiros)}")

    # Busca documentos existentes (para saber se é insert ou update)
    docs_res = sb.table("documents").select("id, metadata").execute()
    doc_by_parceiro_id = {}
    for doc in docs_res.data:
        try:
            meta = doc["metadata"] if isinstance(doc["metadata"], dict) else json.loads(doc["metadata"])
            pid = meta.get("ID") or meta.get("id")
            if pid:
                doc_by_parceiro_id[int(pid)] = doc["id"]
        except Exception:
            pass

    print(f"Documentos existentes no vector store: {len(doc_by_parceiro_id)}")
    print()

    updated = 0
    inserted = 0
    errors = 0

    for p in parceiros:
        pid = int(p["id"])
        nome = p.get("nome", "").strip()

        try:
            content = build_content(p)
            metadata = build_metadata(p)

            if dry_run:
                print(f"[DRY-RUN] {nome}")
                print(content)
                print()
                continue

            # Gera embedding
            embedding = get_embedding(content)
            time.sleep(0.3)  # respeita rate limit da OpenAI

            if pid in doc_by_parceiro_id:
                # UPDATE
                doc_id = doc_by_parceiro_id[pid]
                sb.table("documents").update({
                    "content": content,
                    "metadata": metadata,
                    "embedding": embedding,
                }).eq("id", doc_id).execute()
                print(f"  ✓ Atualizado: {nome}")
                updated += 1
            else:
                # INSERT
                sb.table("documents").insert({
                    "content": content,
                    "metadata": metadata,
                    "embedding": embedding,
                }).execute()
                print(f"  + Inserido:   {nome}")
                inserted += 1

        except Exception as e:
            print(f"  ✗ Erro em {nome}: {e}")
            errors += 1

    if not dry_run:
        print()
        print(f"Concluído — Atualizados: {updated} | Inseridos: {inserted} | Erros: {errors}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Apenas imprime o conteúdo, não salva")
    args = parser.parse_args()
    sync(dry_run=args.dry_run)
