import json
import sys
from supabase_client import get_supabase_client

def get_metadata():
    """
    Busca categorias e subcategorias para fornecer contexto às diretivas de IA.
    """
    supabase = get_supabase_client()
    
    try:
        # Busca categorias
        categories_res = supabase.table("categorias").select("id, nome").execute()
        categories = categories_res.data
        
        # Busca subcategorias
        subcategories_res = supabase.table("subcategorias").select("id, categoria_id, nome").execute()
        subcategories = subcategories_res.data
        
        metadata = {
            "categorias": categories,
            "subcategorias": subcategories
        }
        
        return metadata
        
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    get_metadata()
