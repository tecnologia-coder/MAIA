from execution.ai_client import get_embedding
from execution.supabase_client import get_supabase_client

THRESHOLD = 0.60

def search_suppliers_by_text(query_text):
    """
    Realiza a busca de fornecedores seguindo a vector_search_directive:
    1. Busca Vetorial (Top 10)
    2. Threshold de 0.70 (Ajustado para maior recall)
    3. Fallback Lexical se necessário
    """
    supabase = get_supabase_client()
    embedding = get_embedding(query_text)
    
    # 1. Busca Vetorial
    try:
        rpc_params = {
            "query_embedding": embedding,
            "filter": {},
            "match_count": 10
        }
        
        res = supabase.rpc("match_documents", rpc_params).execute()
        candidates = res.data if res.data else []
        
        # 2. Filtrar por Threshold
        valid_candidates = []
        for c in candidates:
            if c.get("similarity", 0) >= THRESHOLD:
                # Normaliza metadados: garante 'id' minúsculo e 'description'
                meta = c.get("metadata", {})
                if "ID" in meta and "id" not in meta:
                    meta["id"] = meta["ID"]
                
                content = c.get("content", "")
                if "DESCRIÇÃO:" in content and content.strip().endswith("DESCRIÇÃO:"):
                    # Descrição vazia no content, tenta inferir algo útil
                    nome = meta.get("nome", "este fornecedor")
                    subcat = meta.get("subcategoria", "")
                    c["content"] = f"{content} Fornecedor especializado em {subcat} ({nome})."
                
                c["metadata"] = meta
                valid_candidates.append(c)
        
        # 3. Fallback Lexical se nenhum superar o threshold
        if not valid_candidates:
            print(f"[SEARCH] Nenhum resultado vetorial acima de {THRESHOLD}. Iniciando fallback lexical...")
            valid_candidates = search_suppliers_lexical(query_text)
            
        return valid_candidates
        
    except Exception as e:
        print(f"Erro na busca vetorial: {e}")
        # Tenta fallback em caso de erro na busca vetorial
        return search_suppliers_lexical(query_text)

def search_suppliers_lexical(query_text):
    """
    Busca fallback por palavras-chave (ILike) nas tabelas de documentos/parceiros.
    Agora busca por termos individuais para maior abrangência.
    """
    supabase = get_supabase_client()
    try:
        # Extrai palavras significativas (maiores que 3 letras)
        terms = [t for t in query_text.split() if len(t) > 3]
        if not terms:
            return []

        # Constrói a query ILike combinando termos (OR)
        # Nota: O Supabase Python client não tem um .or_ especificado para filtros dinâmicos dessa forma 
        # sem usar strings cruas, então usaremos uma abordagem simplificada de buscar pelo primeiro termo principal
        # ou todos se possível via .or_ string.
        
        or_filter = ",".join([f"content.ilike.%{t}%" for t in terms])
        
        res = supabase.table("documents").select("id, content, metadata")\
            .or_(or_filter)\
            .limit(10).execute()
            
        lexical_results = []
        for item in res.data:
            meta = item.get("metadata", {})
            if "ID" in meta and "id" not in meta:
                meta["id"] = meta["ID"]
            
            content = item.get("content", "")
            if "DESCRIÇÃO:" in content and content.strip().endswith("DESCRIÇÃO:"):
                nome = meta.get("nome", "este fornecedor")
                subcat = meta.get("subcategoria", "")
                content = f"{content} Fornecedor especializado em {subcat} ({nome})."

            lexical_results.append({
                "id": item["id"],
                "content": content,
                "similarity": THRESHOLD,
                "metadata": meta
            })
            
        return lexical_results
    except Exception as e:
        print(f"Erro na busca lexical: {e}")
        return []

