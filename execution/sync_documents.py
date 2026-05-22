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
import sys
import time

from execution.supabase_client import get_supabase_client
from execution.ai_client import get_embedding
from execution.get_metadata import build_taxonomy_lookup, normalize_text

# Console do Windows (cp1252) quebra ao imprimir ✓/✗ e acentos. Força UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _as_text(v, sep=", ") -> str:
    """Converte valores que podem vir como lista (JSON array) ou string em texto plano."""
    if v is None:
        return ""
    if isinstance(v, list):
        return sep.join(str(x).strip() for x in v if str(x).strip())
    return str(v).strip()


# Atributos booleanos de `parceiros` que descrevem diferenciais buscáveis.
# Mapeia coluna -> (texto p/ embedding, chave no metadata).
ATRIBUTOS_BOOL = [
    ("tem_espaco_kids", "Possui espaço kids (área de recreação infantil / playground)."),
    ("tem_menu_kids", "Possui menu kids (cardápio infantil)."),
    ("tem_trocador", "Possui trocador / fraldário."),
    ("tem_cadeira_alimentacao", "Possui cadeira de alimentação para bebês."),
    ("is_rota_gastronomica", "Faz parte da rota gastronômica."),
]


def build_content(p: dict) -> str:
    """Monta o texto rico que será vetorizado e usado na busca."""
    nome = _as_text(p.get("nome"))
    categoria = _as_text(p.get("categoria"))
    subcategoria = _as_text(p.get("subcategoria"))
    palavras_chave = _as_text(p.get("palavras_chave"))
    descricao = _as_text(p.get("descricao"))
    descricao_negocio = _as_text(p.get("descricao_negocio"))
    diferenciais = _as_text(p.get("diferenciais"), sep="; ")
    cidade = _as_text(p.get("cidade"))
    faixa_preco = _as_text(p.get("faixa_preco"))

    # Usa a primeira subcategoria se houver múltiplas (ex: "Lembrancinhas, Biscoitos")
    subcategoria_principal = subcategoria.split(",")[0].strip()

    lines = [
        f"ID: {p['id']}",
        f"NOME: {nome}",
        f"CATEGORIA: {categoria}",
        f"SUBCATEGORIA: {subcategoria_principal}",
    ]

    # Mantém a subcategoria completa (todas as variações) também buscável
    if subcategoria and subcategoria != subcategoria_principal:
        lines.append(f"SUBCATEGORIAS: {subcategoria}")

    if cidade:
        lines.append(f"CIDADE: {cidade}")

    if palavras_chave:
        lines.append(f"PALAVRAS-CHAVE: {palavras_chave}")

    # Atributos discriminantes que antes não entravam no texto buscável
    atributos = [texto for coluna, texto in ATRIBUTOS_BOOL if p.get(coluna)]
    if atributos:
        lines.append("ATRIBUTOS: " + " ".join(atributos))

    if faixa_preco:
        lines.append(f"FAIXA DE PREÇO: {faixa_preco}")

    if diferenciais:
        lines.append(f"DIFERENCIAIS: {diferenciais}")

    # Descrição: usa a melhor fonte disponível (descricao, depois descricao_negocio)
    desc_final = descricao or descricao_negocio
    if desc_final:
        lines.append(f"DESCRIÇÃO: {desc_final}")
    else:
        # Fallback mínimo se não houver descrição
        lines.append(f"DESCRIÇÃO: Fornecedor especializado em {subcategoria_principal} ({nome}).")

    return "\n".join(lines)


def build_metadata(p: dict, sub_por_nome=None, cat_por_nome=None) -> dict:
    """
    Monta o metadata do documento, agora incluindo os IDs da taxonomia
    (`subcategoria_id`/`categoria_id`), a cidade e os atributos booleanos —
    o que torna o filtro determinístico (Regra 2/3 e `match_documents`) possível.
    """
    sub_por_nome = sub_por_nome or {}
    cat_por_nome = cat_por_nome or {}

    subcategoria_principal = _as_text(p.get("subcategoria")).split(",")[0].strip()
    categoria_txt = _as_text(p.get("categoria"))

    # Resolve IDs da taxonomia a partir do texto livre (normalizado)
    sub_match = sub_por_nome.get(normalize_text(subcategoria_principal))
    subcategoria_id = sub_match.get("id") if sub_match else None
    # categoria_id: prefere o da subcategoria resolvida; senão tenta pelo nome da categoria
    categoria_id = sub_match.get("categoria_id") if sub_match else cat_por_nome.get(normalize_text(categoria_txt))

    meta = {
        "ID": int(p["id"]),
        "nome": _as_text(p.get("nome")),
        "categoria": categoria_txt,
        "subcategoria": subcategoria_principal,
        "categoria_id": categoria_id,
        "subcategoria_id": subcategoria_id,
        "cidade": _as_text(p.get("cidade")),
        "source": "blob",
        "blobType": "text/plain",
        "loc": {"lines": {"from": 1, "to": 5}},
    }

    # Atributos booleanos no metadata (habilitam filtro via `filter` no match_documents)
    for coluna, _ in ATRIBUTOS_BOOL:
        if p.get(coluna):
            meta[coluna] = True

    return meta


def sync(dry_run: bool = False, force: bool = False):
    sb = get_supabase_client()

    # Mapas de taxonomia (nome -> id) para resolver o texto livre dos parceiros
    cat_por_nome, sub_por_nome, _ = build_taxonomy_lookup()

    # Busca parceiros aprovados (agora com colunas ricas: cidade, geo, atributos, descrições)
    res = sb.table("parceiros").select(
        "id, nome, categoria, subcategoria, palavras_chave, descricao, descricao_negocio, "
        "diferenciais, cidade, faixa_preco, latitude, longitude, "
        "tem_espaco_kids, tem_menu_kids, tem_trocador, tem_cadeira_alimentacao, "
        "is_rota_gastronomica, status_aprovacao"
    ).eq("status_aprovacao", "aprovado").execute()

    parceiros = res.data
    print(f"Parceiros aprovados encontrados: {len(parceiros)}")

    # Busca documentos existentes (para saber se é insert ou update e p/ sync incremental)
    docs_res = sb.table("documents").select("id, content, metadata").execute()
    doc_by_parceiro_id = {}
    content_by_parceiro_id = {}
    for doc in docs_res.data:
        try:
            meta = doc["metadata"] if isinstance(doc["metadata"], dict) else json.loads(doc["metadata"])
            pid = meta.get("ID") or meta.get("id")
            if pid:
                doc_by_parceiro_id[int(pid)] = doc["id"]
                content_by_parceiro_id[int(pid)] = doc.get("content")
        except Exception:
            pass

    print(f"Documentos existentes no vector store: {len(doc_by_parceiro_id)}")
    print()

    updated = 0
    inserted = 0
    skipped = 0
    errors = 0

    for p in parceiros:
        pid = int(p["id"])
        nome = (p.get("nome") or "").strip()

        try:
            content = build_content(p)
            metadata = build_metadata(p, sub_por_nome=sub_por_nome, cat_por_nome=cat_por_nome)

            if dry_run:
                print(f"[DRY-RUN] {nome} | subcat_id={metadata.get('subcategoria_id')} cat_id={metadata.get('categoria_id')}")
                print(content)
                print()
                continue

            # Sync incremental: se o conteúdo não mudou, não re-embeda (economiza OpenAI).
            # `force=True` ignora este atalho e reprocessa tudo.
            if (not force) and pid in doc_by_parceiro_id and content_by_parceiro_id.get(pid) == content:
                # Mesmo assim atualiza o metadata (barato, sem custo de embedding)
                sb.table("documents").update({"metadata": metadata}).eq("id", doc_by_parceiro_id[pid]).execute()
                print(f"  · Inalterado (só metadata): {nome}")
                skipped += 1
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
        print(f"Concluído — Atualizados: {updated} | Inseridos: {inserted} | Inalterados: {skipped} | Erros: {errors}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Apenas imprime o conteúdo, não salva")
    parser.add_argument("--force", action="store_true", help="Reprocessa (re-embeda) todos, ignorando o cache de conteúdo")
    args = parser.parse_args()
    sync(dry_run=args.dry_run, force=args.force)
