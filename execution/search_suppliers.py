from execution.ai_client import get_embedding
from execution.supabase_client import get_supabase_client

THRESHOLD = 0.78

def search_suppliers_by_text(query_text):
    """
    Realiza a busca de fornecedores seguindo a vector_search_directive:
    1. Busca Vetorial (Top 10)
    2. Threshold de 0.78
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
        valid_candidates = [c for c in candidates if c.get("similarity", 0) >= THRESHOLD]
        
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
    """
    supabase = get_supabase_client()
    try:
        # Busca básica por ILike no conteúdo dos documentos
        # Nota: Ajustar campos conforme o schema real de parcerias/documentos
        res = supabase.table("documents").select("id, content, metadata")\
            .ilike("content", f"%{query_text}%")\
            .limit(10).execute()
            
        lexical_results = []
        for item in res.data:
            # Transforma em formato compatível com o retorno vetorial
            # Atribuímos uma 'similaridade' simbólica de 0.78 para passar no match
            lexical_results.append({
                "id": item["id"],
                "content": item["content"],
                "similarity": 0.78, 
                "metadata": item["metadata"]
            })
            
        return lexical_results
    except Exception as e:
        print(f"Erro na busca lexical: {e}")
        return []

