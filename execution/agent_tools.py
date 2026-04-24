

import json
from execution.supabase_client import get_supabase_client
from execution.search_suppliers import search_suppliers_by_text
from execution.get_metadata import get_metadata

def supabase_vector_store(query: str) -> str:
    """
    Busca fornecedores candidatos no banco de dados baseados na intenção do usuário.
    Usa busca semântica (cosseno) na tabela documents e retorna até 10 resultados brutos para validação.
    
    Args:
        query: Uma frase ou conjunto de palavras-chave ricas e descritivas elaborada com base no contexto, categoria e subcategoria.
        
    Returns:
        JSON string contendo a lista de candidatos com seus metadados completos e score de similaridade.
    """
    print(f"[TOOL] Chamando supabase_vector_store com query: '{query}'")
    try:
        candidates = search_suppliers_by_text(query)
        print(f"[TOOL] Retornando {len(candidates)} candidatos para o Agente.")
        res_json = json.dumps({"candidatos": candidates}, ensure_ascii=False)
        # print(f"[TOOL DEBUG] Resposta JSON: {res_json[:200]}...")
        return res_json
    except Exception as e:
        print(f"[TOOL ERRO] supabase_vector_store: {e}")
        return json.dumps({"candidatos": []})

def get_categoria(categoria_id: int) -> str:
    """
    Obtém o nome textual da categoria a partir do seu ID numérico.
    
    Args:
        categoria_id: O ID numérico da categoria retornado na etapa de categorização.
        
    Returns:
        O nome descritivo da categoria ou mensagem de erro se não encontrada.
    """
    print(f"[TOOL] Chamando get_categoria para ID: {categoria_id}")
    try:
        metadata = get_metadata()
        for cat in metadata.get("categorias", []):
            if str(cat.get("id")) == str(categoria_id):
                return cat.get("nome")
        return f"Categoria ID {categoria_id} não encontrada."
    except Exception as e:
        return f"Erro ao buscar categoria: {e}"

def get_subcategoria(subcategoria_id: int) -> str:
    """
    Obtém o nome textual da subcategoria a partir do seu ID numérico.
    
    Args:
        subcategoria_id: O ID numérico da subcategoria retornado na etapa de categorização.
        
    Returns:
        O nome descritivo da subcategoria ou mensagem de erro se não encontrada.
    """
    print(f"[TOOL] Chamando get_subcategoria para ID: {subcategoria_id}")
    try:
        metadata = get_metadata()
        for sub in metadata.get("subcategorias", []):
            if str(sub.get("id")) == str(subcategoria_id):
                return sub.get("nome")
        return f"Subcategoria ID {subcategoria_id} não encontrada."
    except Exception as e:
        return f"Erro ao buscar subcategoria: {e}"

def link_fornecedor(fornecedor_id: int) -> str:
    """
    Resgata os dados completos de contato de um parceiro validado para montar a recomendação final.
    DEVE ser chamado para CADA fornecedor que você decidir recomendar.
    
    Args:
        fornecedor_id: O ID numérico do fornecedor (encontrado na chave 'metadata.id' dos candidatos).
        
    Returns:
        JSON string contendo os dados de contato do parceiro, especificamente o whatsapp_link.
    """
    print(f"[TOOL] Chamando link_fornecedor para ID: {fornecedor_id}")
    supabase = get_supabase_client()
    try:
        res = supabase.table("parceiros").select("id, whatsapp_link, status").eq("id", fornecedor_id).execute()
        if res.data:
            return json.dumps(res.data[0], ensure_ascii=False)
        return json.dumps({"erro": f"Fornecedor ID {fornecedor_id} não encontrado na tabela parceiros."})
    except Exception as e:
        print(f"[TOOL ERRO] link_fornecedor: {e}")
        return json.dumps({"erro": "Erro técnico ao buscar dados de contato."})

# Exporta a lista de ferramentas que será injetada na chamada do Gemini
agentic_tools = [
    supabase_vector_store,
    get_categoria,
    get_subcategoria,
    link_fornecedor
]
