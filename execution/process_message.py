import json
import os
import sys
from ai_client import call_gemini, load_directive, get_embedding
from search_suppliers import search_suppliers_by_text
from get_metadata import get_metadata
from supabase_client import get_supabase_client

# --- Funções de Persistência (L3 Determinística) ---

def record_test_pedido(data):
    """
    Registra um pedido de indicação na tabela 'pedidos_indicacao'.
    Adiciona o prefixo [DATA TEST] na descrição.
    """
    supabase = get_supabase_client()
    
    # Prefixando a descrição para identificação fácil no Supabase
    if "pedido_descricao" in data and data["pedido_descricao"]:
        data["pedido_descricao"] = f"[DATA TEST] {data['pedido_descricao']}"
    else:
        data["pedido_descricao"] = "[DATA TEST] Pedido sem descrição gerada"
        
    try:
        # Nota: pedido_grupo e profile podem ser IDs reais ou virem de mocks de teste
        res = supabase.table("pedidos_indicacao").insert(data).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"Erro ao registrar pedido no Supabase: {e}")
        return None

def record_test_recomendacao(data):
    """
    Registra uma recomendação na tabela 'recomendacao_fornecedor'.
    Adiciona o prefixo [DATA TEST] no motivo.
    """
    supabase = get_supabase_client()
    
    if "motivo_recomendacao" in data and data["motivo_recomendacao"]:
        data["motivo_recomendacao"] = f"[DATA TEST] {data['motivo_recomendacao']}"
    else:
        data["motivo_recomendacao"] = "[DATA TEST] Recomendação sem motivo gerado"
        
    try:
        res = supabase.table("recomendacao_fornecedor").insert(data).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"Erro ao registrar recomendação no Supabase: {e}")
        return None

# --- Orquestração Principal (MAIA) ---

def process_whatsapp_message_e2e(message_text, is_from_me=False):
    """
    Fluxo completo: Classificação -> Categorização -> Busca Vetorial -> Match -> Resposta.
    """
    
    # 1. CLASSIFICATION
    try:
        class_instr = load_directive("classification_directive.md")
        if is_from_me:
            return None, "Mensagem própria ignorada pelo sistema."
            
        class_res_raw = call_gemini(class_instr, message_text)
        class_res = json.loads(class_res_raw)
        
        if not class_res.get("is_valid_request"):
            return None, class_res.get("reason", "Mensagem de entrada não era um pedido de indicação.")
    except Exception as e:
        print(f"Erro na etapa de Classificação: {e}")
        return None, "Falha na classificação técnica."

    print("\n[DEBUG] Mensagem válida identificada. Categorizando...")

    # 2. CATEGORIZATION
    try:
        cat_instr = load_directive("categorization_directive.md")
        metadata = get_metadata()
        cat_prompt = f"Categorias reais disponíveis:\n{json.dumps(metadata)}\n\nPedido do Usuário: {message_text}"
        
        cat_res_raw = call_gemini(cat_instr, cat_prompt)
        cat_res = json.loads(cat_res_raw)
        
        # Persistência do Pedido no Banco (com prefixo [DATA TEST])
        pedido_db_data = {
            "pedido_mensagem": message_text,
            "pedido_descricao": cat_res.get("pedido_descricao"),
            "pedido_categoria": cat_res.get("pedido_categoria"),
            "pedido_subcategoria": cat_res.get("pedido_subcategoria"),
            # IDs de teste padrão se não fornecidos
            "pedido_grupo": 1, 
            "profile": 1
        }
        pedido_record = record_test_pedido(pedido_db_data)
        pedido_id = pedido_record["id"] if pedido_record else None
    except Exception as e:
        print(f"Erro na etapa de Categorização/Persistência: {e}")
        pedido_id = None
        cat_res = {}

    # 3. SEARCH & MATCH (Busca Vetorial Gemini + Filtro AI)
    try:
        raw_results = search_suppliers_by_text(message_text)
        
        match_instr = load_directive("supplier_match_directive.md")
        match_prompt = f"Resultados brutos (Vector Store):\n{json.dumps(raw_results)}\n\nPedido: {message_text}"
        
        match_res_raw = call_gemini(match_instr, match_prompt)
        match_res = json.loads(match_res_raw)
        suppliers = match_res.get("fornecedores_validos", [])
    except Exception as e:
        print(f"Erro na etapa de Busca/Match: {e}")
        suppliers = []

    # 4. RESPONSE GENERATION
    try:
        persona_instr = load_directive("persona_directive.md")
        resp_instr = load_directive("response_generation_directive.md")
        
        final_instr = f"{persona_instr}\n\n{resp_instr}"
        final_prompt = f"Lista Final de Fornecedores Aprovados:\n{json.dumps(suppliers)}\n\nPedido original: {message_text}"
        
        final_res_raw = call_gemini(final_instr, final_prompt)
        final_res = json.loads(final_res_raw)
        
        # 5. Persistência das Recomendações
        if pedido_id and suppliers:
            for s in suppliers:
                rec_data = {
                    "pedido_indicacao": pedido_id,
                    "fornecedor_recomendado": s.get("fornecedor_id"),
                    "motivo_recomendacao": s.get("motivo_match")
                }
                record_test_recomendacao(rec_data)
                
        return final_res, None
    except Exception as e:
        print(f"Erro na etapa de Geração de Resposta: {e}")
        return {"mensagem_final": "Desculpe, tive um problema técnico para processar isso agora."}, None

# --- Script de Entrada de Console ---

if __name__ == "__main__":
    print("\n" + "="*40)
    print("      MAIA: AMBIENTE DE TESTE LOCAL")
    print("="*40)
    
    if len(sys.argv) > 1:
        user_input = " ".join(sys.argv[1:])
        print(f"\n[Argumento] Processando: {user_input}")
    else:
        user_input = input("\n[WhatsApp Mock] Digite sua mensagem: ")
    
    result, error_reason = process_whatsapp_message_e2e(user_input)
    
    if error_reason:
        print(f"\nMensagem de entrada não era um pedido de indicação. Nada foi feito!")
        # No futuro, se quiser ver o motivo técnico: print(f"Motivo: {error_reason}")
    elif result and "mensagem_final" in result:
        print("\n" + "-"*30)
        print("RESPOSTA DA MAIA (Final):")
        print("-"*30)
        print(result["mensagem_final"])
        print("-"*30)
        print("\n[SUCESSO] Dados registrados no Supabase com prefixo [DATA TEST].")
    
    print("\nTeste finalizado.\n")
