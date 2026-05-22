from execution.ai_client import get_embedding
from execution.supabase_client import get_supabase_client
from execution.get_metadata import build_taxonomy_lookup, normalize_text

# Threshold de similaridade mínima para a busca vetorial.
# Mantido em 0.60 (recall maior); a validação rigorosa final é feita pelo Agente LLM.
THRESHOLD = 0.60

# Colunas de `parceiros` necessárias para o pré-filtro estruturado determinístico.
PARCEIRO_COLS = (
    "id, nome, categoria, subcategoria, palavras_chave, descricao, cidade, "
    "tem_espaco_kids, tem_menu_kids, tem_trocador, tem_cadeira_alimentacao, "
    "is_rota_gastronomica, status_aprovacao"
)

# Atributos booleanos que podem ser exigidos pelo pedido (flag -> coluna).
ATRIBUTO_FLAG_COLUNA = {
    "requer_espaco_kids": "tem_espaco_kids",
    "requer_menu_kids": "tem_menu_kids",
    "requer_trocador": "tem_trocador",
}


def _parceiro_id(candidate):
    """Extrai o ID do parceiro de um candidato (vetorial ou estruturado)."""
    meta = candidate.get("metadata", {}) or {}
    pid = meta.get("ID") or meta.get("id") or candidate.get("id")
    try:
        return int(pid)
    except (TypeError, ValueError):
        return None


def _docs_by_parceiro():
    """Indexa os documentos do vector store por ID do parceiro: {pid: {content, metadata}}."""
    supabase = get_supabase_client()
    out = {}
    try:
        res = supabase.table("documents").select("content, metadata").execute()
        for d in res.data or []:
            meta = d.get("metadata") or {}
            pid = meta.get("ID") or meta.get("id")
            if pid is not None:
                out[int(pid)] = {"content": d.get("content", ""), "metadata": meta}
    except Exception as e:
        print(f"[SEARCH] Falha ao indexar documents: {e}")
    return out


# ---------------------------------------------------------------------------
# 1. Busca semântica (vetorial) + fallback lexical — mantém o contrato antigo
# ---------------------------------------------------------------------------

def search_suppliers_by_text(query_text):
    """
    Busca semântica via RPC `match_documents` (cosseno, top 10), filtrando por
    THRESHOLD. Se a vetorial não retornar nada (ou falhar), cai no fallback lexical.
    """
    supabase = get_supabase_client()

    try:
        # Gera embedding dentro do try: se a OpenAI falhar (ex.: 429 sem quota),
        # cai no fallback lexical em vez de propagar a exceção.
        embedding = get_embedding(query_text)

        rpc_params = {
            "query_embedding": embedding,
            "filter": {},
            "match_count": 10,
        }
        res = supabase.rpc("match_documents", rpc_params).execute()
        candidates = res.data if res.data else []

        valid_candidates = []
        for c in candidates:
            if c.get("similarity", 0) >= THRESHOLD:
                valid_candidates.append(_normalize_candidate(c))

        if not valid_candidates:
            print(f"[SEARCH] Nenhum resultado vetorial acima de {THRESHOLD}. Iniciando fallback lexical...")
            valid_candidates = search_suppliers_lexical(query_text)

        return valid_candidates

    except Exception as e:
        print(f"Erro na busca vetorial: {e}")
        return search_suppliers_lexical(query_text)


def _normalize_candidate(c):
    """Normaliza metadados: garante 'id' minúsculo e enriquece descrição vazia."""
    meta = c.get("metadata", {}) or {}
    if "ID" in meta and "id" not in meta:
        meta["id"] = meta["ID"]

    content = c.get("content", "")
    if "DESCRIÇÃO:" in content and content.strip().endswith("DESCRIÇÃO:"):
        nome = meta.get("nome", "este fornecedor")
        subcat = meta.get("subcategoria", "")
        c["content"] = f"{content} Fornecedor especializado em {subcat} ({nome})."

    c["metadata"] = meta
    return c


def search_suppliers_lexical(query_text):
    """Fallback por palavras-chave (ILike) na tabela documents, combinando termos via OR."""
    supabase = get_supabase_client()
    try:
        # Sanitiza termos: remove pontuação das bordas. Vírgula/%/parênteses quebram o
        # parser de lógica do PostgREST no .or_() (erro PGRST100), então são removidos.
        import re
        seen = set()
        terms = []
        for raw in query_text.split():
            t = re.sub(r"[^0-9A-Za-zÀ-ÿ]+", "", raw)
            if len(t) > 3 and t.lower() not in seen:
                seen.add(t.lower())
                terms.append(t)
        # Limita a quantidade de termos para manter a query enxuta
        terms = terms[:12]
        if not terms:
            return []

        or_filter = ",".join([f"content.ilike.%{t}%" for t in terms])
        res = supabase.table("documents").select("id, content, metadata").or_(or_filter).limit(10).execute()

        lexical_results = []
        for item in res.data:
            c = _normalize_candidate({
                "id": item["id"],
                "content": item.get("content", ""),
                "similarity": THRESHOLD,
                "metadata": item.get("metadata", {}) or {},
            })
            lexical_results.append(c)
        return lexical_results
    except Exception as e:
        print(f"Erro na busca lexical: {e}")
        return []


# ---------------------------------------------------------------------------
# 2. Pré-filtro estruturado determinístico (consulta direta em `parceiros`)
# ---------------------------------------------------------------------------

def search_suppliers_structured(categoria_id=None, subcategoria_id=None, flags=None, limit=10):
    """
    Recupera candidatos de forma DETERMINÍSTICA direto da tabela `parceiros`
    (apenas aprovados), ancorando por categoria/subcategoria da taxonomia e por
    atributos booleanos (espaço kids, menu kids, trocador) quando o pedido exigir.

    Não filtra por cidade: "Cerro Azul" é um bairro/avenida (cidade = "Maringá"),
    então a região é tratada como sinal textual/semântico, não como filtro rígido.

    O `similarity` aqui é um *score de confiança do pré-filtro* (não cosseno):
      0.85 = match de subcategoria | 0.70 = match de categoria | 0.65 = match por atributo
    """
    flags = flags or {}
    supabase = get_supabase_client()
    _, sub_por_nome, _ = build_taxonomy_lookup()

    # Constrói o lookup de categoria por nome também (fallback quando a subcat não resolve)
    from execution.get_metadata import get_metadata
    cat_por_nome = {normalize_text(c.get("nome")): c.get("id") for c in get_metadata().get("categorias", [])}

    # Atributos exigidos pelo pedido
    requeridos = [col for flag, col in ATRIBUTO_FLAG_COLUNA.items() if flags.get(flag)]

    try:
        q = supabase.table("parceiros").select(PARCEIRO_COLS).eq("status_aprovacao", "aprovado")
        for col in requeridos:
            q = q.eq(col, True)  # filtro determinístico no banco
        rows = q.execute().data or []
    except Exception as e:
        print(f"[SEARCH] Falha no pré-filtro estruturado: {e}")
        return []

    docs = _docs_by_parceiro()
    results = []
    for p in rows:
        sub_principal = normalize_text((p.get("subcategoria") or "").split(",")[0])
        sm = sub_por_nome.get(sub_principal)
        p_sub_id = sm["id"] if sm else None
        p_cat_id = (sm["categoria_id"] if sm else None) or cat_por_nome.get(normalize_text(p.get("categoria")))

        # Score base por aderência à taxonomia do pedido
        if subcategoria_id and str(p_sub_id) == str(subcategoria_id):
            score = 0.85
        elif categoria_id and str(p_cat_id) == str(categoria_id):
            score = 0.70
        elif requeridos:
            # Sem match de taxonomia, mas passou no filtro de atributo (sinal forte)
            score = 0.65
        else:
            continue  # sem relação com o pedido

        pid = int(p["id"])
        doc = docs.get(pid)
        content = doc["content"] if doc else _content_minimo(p)
        meta = dict(doc["metadata"]) if doc else {}
        meta.update({
            "ID": pid,
            "id": pid,
            "nome": p.get("nome"),
            "categoria_id": p_cat_id,
            "subcategoria_id": p_sub_id,
            "cidade": p.get("cidade"),
        })
        for flag, col in ATRIBUTO_FLAG_COLUNA.items():
            if p.get(col):
                meta[col] = True
        # demais atributos informativos
        for col in ("tem_cadeira_alimentacao", "is_rota_gastronomica"):
            if p.get(col):
                meta[col] = True

        results.append({
            "id": pid,
            "content": content,
            "similarity": score,
            "metadata": meta,
            "fonte": "estruturado",
        })

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:limit]


def _content_minimo(p):
    """Conteúdo mínimo p/ parceiro ainda não sincronizado no vector store."""
    nome = p.get("nome") or ""
    cat = p.get("categoria") or ""
    sub = (p.get("subcategoria") or "").split(",")[0].strip()
    cidade = p.get("cidade") or ""
    return f"ID: {p['id']}\nNOME: {nome}\nCATEGORIA: {cat}\nSUBCATEGORIA: {sub}\nCIDADE: {cidade}"


# ---------------------------------------------------------------------------
# 3. Orquestração: estruturado (determinístico) + vetorial (ranqueamento)
# ---------------------------------------------------------------------------

def search_suppliers(query_text, categoria_id=None, subcategoria_id=None, flags=None, limit=10):
    """
    Combina o pré-filtro estruturado (determinístico) com a busca vetorial
    (semântica), deduplicando por ID de parceiro e mantendo o maior score.
    O determinismo entra primeiro; a vetorial amplia o recall e ranqueia.
    """
    structured = search_suppliers_structured(categoria_id, subcategoria_id, flags=flags, limit=limit)
    try:
        vector = search_suppliers_by_text(query_text)
    except Exception as e:
        print(f"[SEARCH] Busca vetorial indisponível: {e}")
        vector = []

    by_pid = {}
    for cand in structured + vector:  # estruturado primeiro (preserva *_id/atributos)
        pid = _parceiro_id(cand)
        if pid is None:
            continue
        existing = by_pid.get(pid)
        if existing is None:
            by_pid[pid] = cand
            continue
        # Combina metadados das duas fontes e mantém o candidato de maior score como base.
        combined_meta = {**(existing.get("metadata") or {}), **(cand.get("metadata") or {})}
        winner = cand if cand.get("similarity", 0) > existing.get("similarity", 0) else existing
        winner["metadata"] = combined_meta
        by_pid[pid] = winner

    merged = sorted(by_pid.values(), key=lambda x: x.get("similarity", 0), reverse=True)

    if not merged:
        merged = search_suppliers_lexical(query_text)

    return merged[:limit]
