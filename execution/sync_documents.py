"""
sync_documents.py
-----------------
Sincroniza a tabela `documents` com os dados atuais da tabela `parceiros`.

Para cada parceiro ativo (status_aprovacao = 'aprovado'), este script:
1. Monta um conteúdo rico combinando nome, categoria, subcategoria, palavras-chave e descrição
2. Gera um novo embedding via o provedor configurado (EMBEDDING_PROVIDER: google|openai)
3. Atualiza (ou insere) o registro na tabela `documents`

Uso:
    python -m execution.sync_documents
    python -m execution.sync_documents --dry-run   # apenas imprime, não salva
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone

from execution.supabase_client import get_supabase_client
from execution.ai_client import get_embedding, get_embedding_provider_info
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

PARCEIRO_SYNC_COLS = (
    "id, nome, categoria, subcategoria, palavras_chave, descricao, descricao_negocio, "
    "diferenciais, cidade, faixa_preco, latitude, longitude, "
    "tem_espaco_kids, tem_menu_kids, tem_trocador, tem_cadeira_alimentacao, "
    "is_rota_gastronomica, status_aprovacao"
)

GENERATED_CANCELLED_COLS = {"whatsapp_link"}
CANCELLED_COPY_COLS = {
    "id",
    "nome",
    "categoria",
    "subcategoria",
    "palavras_chave",
    "cidade",
    "instagram_url",
    "email",
    "endereco_fisico",
    "site_url",
    "is_vip",
    "logo_url",
    "created_at",
    "status_aprovacao",
    "termos_aceitos",
    "vantagem_exclusiva",
    "telefone_whatsapp",
    "is_rota_gastronomica",
    "tem_espaco_kids",
    "tem_menu_kids",
    "tem_trocador",
    "tem_cadeira_alimentacao",
    "diagnostico_babyfriendly",
    "user_id",
    "data_fim_trial",
    "plano_escolhido",
    "recorrencia",
    "status_pagamento",
    "diferenciais",
    "descricao_negocio",
    "descricao",
    "latitude",
    "longitude",
    "horario_funcionamento",
    "faixa_preco",
    "id_assinatura_cyclopay",
    "ultima_sincronizacao_cyclopay",
    "data_termos",
    "ultimo_email_enviado",
    "ultima_alteracao_senha",
    "contato_gerente_interno",
    "texto_adesao",
    "data_cancelamento_registro",
    "plano",
    "assinatura_cyclopay",
    "cancelado_em",
}


def _metadata_to_dict(metadata):
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str):
        return json.loads(metadata)
    return {}


def _metadata_partner_id(metadata):
    try:
        meta = _metadata_to_dict(metadata)
        pid = meta.get("ID") or meta.get("id")
        return int(pid) if pid is not None else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _docs_by_partner(sb=None):
    """Return {partner_id: [document, ...]} for all vector-store documents."""
    sb = sb or get_supabase_client()
    docs_res = sb.table("documents").select("id, content, metadata").execute()
    out = {}
    for doc in docs_res.data or []:
        pid = _metadata_partner_id(doc.get("metadata"))
        if pid is not None:
            out.setdefault(pid, []).append(doc)
    return out


def _delete_document_ids(sb, document_ids, dry_run=False):
    deleted = 0
    for doc_id in document_ids:
        if dry_run:
            print(f"[DRY-RUN] Removeria document_id={doc_id}")
        else:
            sb.table("documents").delete().eq("id", doc_id).execute()
        deleted += 1
    return deleted


def _upsert_partner_document(sb, p, sub_por_nome=None, cat_por_nome=None, force=False, dry_run=False):
    pid = int(p["id"])
    nome = (p.get("nome") or "").strip()
    docs = _docs_by_partner(sb).get(pid, [])
    primary_doc = docs[0] if docs else None
    extra_doc_ids = [d["id"] for d in docs[1:]]

    content = build_content(p)
    metadata = build_metadata(p, sub_por_nome=sub_por_nome, cat_por_nome=cat_por_nome)
    provider_atual = get_embedding_provider_info()["embedding_provider"]

    if primary_doc:
        primary_meta = _metadata_to_dict(primary_doc.get("metadata"))
        same_content = primary_doc.get("content") == content
        same_provider = primary_meta.get("embedding_provider") == provider_atual
        if dry_run:
            action = "skip" if (not force) and same_content and same_provider else "update"
            print(f"[DRY-RUN] {action} document para parceiro {pid} ({nome})")
            if extra_doc_ids:
                print(f"[DRY-RUN] Removeria documentos duplicados: {extra_doc_ids}")
            return {
                "inserted": 0,
                "updated": int(action == "update"),
                "skipped": int(action == "skip"),
                "deleted": len(extra_doc_ids),
            }
        if (not force) and same_content and same_provider:
            sb.table("documents").update({"metadata": metadata}).eq("id", primary_doc["id"]).execute()
            deleted = _delete_document_ids(sb, extra_doc_ids)
            return {"inserted": 0, "updated": 0, "skipped": 1, "deleted": deleted}

    if dry_run:
        print(f"[DRY-RUN] insert document para parceiro {pid} ({nome})")
        return {"inserted": 1, "updated": 0, "skipped": 0, "deleted": 0}

    embedding = get_embedding(content, task_type="RETRIEVAL_DOCUMENT")
    time.sleep(0.3)

    if primary_doc:
        sb.table("documents").update({
            "content": content,
            "metadata": metadata,
            "embedding": embedding,
        }).eq("id", primary_doc["id"]).execute()
        deleted = _delete_document_ids(sb, extra_doc_ids)
        return {"inserted": 0, "updated": 1, "skipped": 0, "deleted": deleted}

    sb.table("documents").insert({
        "content": content,
        "metadata": metadata,
        "embedding": embedding,
    }).execute()
    return {"inserted": 1, "updated": 0, "skipped": 0, "deleted": 0}


def remove_partner_documents(partner_id, dry_run: bool = False, sb=None):
    """Remove all vector-store documents for a partner."""
    sb = sb or get_supabase_client()
    pid = int(partner_id)
    docs = _docs_by_partner(sb).get(pid, [])
    deleted = _delete_document_ids(sb, [d["id"] for d in docs], dry_run=dry_run)
    print(f"[VECTOR SYNC] Parceiro {pid}: documentos removidos={deleted}")
    return {"deleted": deleted}


def sync_partner(partner_id, dry_run: bool = False, force: bool = False, sb=None):
    """
    Sync one partner into the vector store. Only approved partners are indexed;
    every other status is removed from documents.
    """
    sb = sb or get_supabase_client()
    pid = int(partner_id)
    res = sb.table("parceiros").select(PARCEIRO_SYNC_COLS).eq("id", pid).execute()
    partner = (res.data or [None])[0]

    if not partner:
        print(f"[VECTOR SYNC] Parceiro {pid} nao existe em parceiros; removendo documents.")
        return remove_partner_documents(pid, dry_run=dry_run, sb=sb)

    if partner.get("status_aprovacao") != "aprovado":
        print(f"[VECTOR SYNC] Parceiro {pid} status={partner.get('status_aprovacao')}; removendo documents.")
        return remove_partner_documents(pid, dry_run=dry_run, sb=sb)

    cat_por_nome, sub_por_nome, _ = build_taxonomy_lookup()
    result = _upsert_partner_document(
        sb,
        partner,
        sub_por_nome=sub_por_nome,
        cat_por_nome=cat_por_nome,
        force=force,
        dry_run=dry_run,
    )
    print(f"[VECTOR SYNC] Parceiro {pid} sincronizado: {result}")
    return result


def move_cancelled_partner(partner_id, dry_run: bool = False, sb=None):
    """
    Move a cancelled partner to parceiros_cancelados and remove it from the vector store.
    """
    sb = sb or get_supabase_client()
    pid = int(partner_id)
    res = sb.table("parceiros").select("*").eq("id", pid).execute()
    partner = (res.data or [None])[0]

    removed = remove_partner_documents(pid, dry_run=dry_run, sb=sb)
    if not partner:
        print(f"[VECTOR SYNC] Parceiro {pid} ja nao existe em parceiros.")
        return {"moved": 0, **removed}

    cancelled = {
        k: v
        for k, v in partner.items()
        if k in CANCELLED_COPY_COLS and k not in GENERATED_CANCELLED_COLS
    }
    now = datetime.now(timezone.utc).isoformat()
    cancelled.update({
        "status_aprovacao": "cancelado",
        "status_pagamento": "cancelado",
        "is_vip": False,
        "data_cancelamento_registro": now,
        "cancelado_em": cancelled.get("cancelado_em") or now,
    })

    if dry_run:
        print(f"[DRY-RUN] Moveria parceiro {pid} para parceiros_cancelados e removeria de parceiros.")
        return {"moved": 1, **removed}

    sb.table("parceiros_cancelados").upsert(cancelled, on_conflict="id").execute()
    sb.table("parceiros").delete().eq("id", pid).execute()
    print(f"[VECTOR SYNC] Parceiro {pid} movido para parceiros_cancelados.")
    return {"moved": 1, **removed}


def reconcile(dry_run: bool = False, force: bool = False, sb=None):
    """
    Repair global consistency:
    - remove documents for missing/non-approved/cancelled partners
    - ensure approved partners have one current vector-store document
    """
    sb = sb or get_supabase_client()
    partner_res = sb.table("parceiros").select(PARCEIRO_SYNC_COLS).execute()
    partners = partner_res.data or []
    partners_by_id = {int(p["id"]): p for p in partners}
    approved = [p for p in partners if p.get("status_aprovacao") == "aprovado"]

    docs_by_partner = _docs_by_partner(sb)
    deleted = 0
    for pid, docs in docs_by_partner.items():
        partner = partners_by_id.get(pid)
        if not partner or partner.get("status_aprovacao") != "aprovado":
            deleted += _delete_document_ids(sb, [d["id"] for d in docs], dry_run=dry_run)

    cat_por_nome, sub_por_nome, _ = build_taxonomy_lookup()
    summary = {"inserted": 0, "updated": 0, "skipped": 0, "deleted": deleted, "errors": 0}
    for partner in approved:
        try:
            result = _upsert_partner_document(
                sb,
                partner,
                sub_por_nome=sub_por_nome,
                cat_por_nome=cat_por_nome,
                force=force,
                dry_run=dry_run,
            )
            for key in ("inserted", "updated", "skipped", "deleted"):
                summary[key] += result.get(key, 0)
        except Exception as e:
            print(f"[VECTOR SYNC] Erro ao reconciliar parceiro {partner.get('id')}: {e}")
            summary["errors"] += 1

    print(f"[VECTOR SYNC] Reconcile concluido: {summary}")
    return summary


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

    # Provedor/dimensão do embedding gravados no doc — permitem detectar store misto
    # (vetores de provedores diferentes não são comparáveis).
    meta.update(get_embedding_provider_info())

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
    res = sb.table("parceiros").select(PARCEIRO_SYNC_COLS).eq("status_aprovacao", "aprovado").execute()

    parceiros = res.data
    print(f"Parceiros aprovados encontrados: {len(parceiros)}")

    # Provedor/dimensão ativos — usados para detectar store misto no sync incremental.
    provider_info = get_embedding_provider_info()
    provider_atual = provider_info["embedding_provider"]
    print(f"Provedor de embedding ativo: {provider_atual} ({provider_info['embedding_dim']} dims)")

    # Busca documentos existentes (para saber se é insert ou update e p/ sync incremental)
    docs_res = sb.table("documents").select("id, content, metadata").execute()
    doc_by_parceiro_id = {}
    content_by_parceiro_id = {}
    provider_by_parceiro_id = {}
    for doc in docs_res.data:
        try:
            meta = doc["metadata"] if isinstance(doc["metadata"], dict) else json.loads(doc["metadata"])
            pid = meta.get("ID") or meta.get("id")
            if pid:
                doc_by_parceiro_id[int(pid)] = doc["id"]
                content_by_parceiro_id[int(pid)] = doc.get("content")
                provider_by_parceiro_id[int(pid)] = meta.get("embedding_provider")
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

            # Sync incremental: pula o re-embed só se o conteúdo NÃO mudou E o doc já foi
            # embeddado com o MESMO provedor atual. Se o provedor mudou, re-embeda mesmo com
            # conteúdo igual (vetores de provedores diferentes não são comparáveis).
            # `force=True` ignora este atalho e reprocessa tudo.
            mesmo_provedor = provider_by_parceiro_id.get(pid) == provider_atual
            if (not force) and pid in doc_by_parceiro_id and content_by_parceiro_id.get(pid) == content and mesmo_provedor:
                # Mesmo assim atualiza o metadata (barato, sem custo de embedding)
                sb.table("documents").update({"metadata": metadata}).eq("id", doc_by_parceiro_id[pid]).execute()
                print(f"  · Inalterado (só metadata): {nome}")
                skipped += 1
                continue

            # Gera embedding (RETRIEVAL_DOCUMENT: embedding assimétrico de documento no Google)
            embedding = get_embedding(content, task_type="RETRIEVAL_DOCUMENT")
            time.sleep(0.3)  # respeita rate limit do provedor

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
    parser.add_argument("--partner-id", type=int, help="Sincroniza um parceiro especifico")
    parser.add_argument("--remove-partner-id", type=int, help="Remove os documentos de um parceiro do vector store")
    parser.add_argument("--move-cancelled-id", type=int, help="Move um parceiro cancelado para parceiros_cancelados")
    parser.add_argument("--reconcile", action="store_true", help="Corrige divergencias entre parceiros e documents")
    args = parser.parse_args()
    if args.partner_id:
        sync_partner(args.partner_id, dry_run=args.dry_run, force=args.force)
    elif args.remove_partner_id:
        remove_partner_documents(args.remove_partner_id, dry_run=args.dry_run)
    elif args.move_cancelled_id:
        move_cancelled_partner(args.move_cancelled_id, dry_run=args.dry_run)
    elif args.reconcile:
        reconcile(dry_run=args.dry_run, force=args.force)
    else:
        sync(dry_run=args.dry_run, force=args.force)
