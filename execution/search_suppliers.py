from execution.ai_client import get_embedding
from execution.supabase_client import get_supabase_client

def search_suppliers_by_text(query_text):
    """
    Gera o embedding do texto e realiza a busca vetorial no Supabase.
    """
    supabase = get_supabase_client()
    embedding = get_embedding(query_text)
    
    try:
        rpc_params = {
            "query_embedding": embedding,
            "filter": {},
            "match_count": 10
        }
        
        # Busca na tabela de documentos (vetores)
        res = supabase.rpc("match_documents", rpc_params).execute()
        
        return res.data
        
    except Exception as e:
        print(f"Erro na busca vetorial: {e}")
        return []
