import json
import sys
import unicodedata
from execution.supabase_client import get_supabase_client


def normalize_text(s):
    """Normaliza texto para comparação: minúsculas, sem acentos, sem espaços extras."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip().lower()


def build_taxonomy_lookup(metadata=None):
    """
    Constrói mapas de nome normalizado -> id para categorias e subcategorias,
    permitindo resolver o texto livre de `parceiros` para os IDs da taxonomia.
    Retorna (categoria_por_nome, subcategoria_por_nome, subcategoria_por_id).
    """
    metadata = metadata or get_metadata()
    cat_por_nome = {}
    for c in metadata.get("categorias", []):
        cat_por_nome[normalize_text(c.get("nome"))] = c.get("id")

    sub_por_nome = {}
    sub_por_id = {}
    for s in metadata.get("subcategorias", []):
        sub_por_nome[normalize_text(s.get("nome"))] = {
            "id": s.get("id"),
            "categoria_id": s.get("categoria_id"),
        }
        sub_por_id[str(s.get("id"))] = s
    return cat_por_nome, sub_por_nome, sub_por_id


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
