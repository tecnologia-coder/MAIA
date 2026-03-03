import json
import os
import sys
from execution.zapi_client import send_zapi_message
from execution.ai_client import call_gemini, load_directive, get_embedding
from execution.search_suppliers import search_suppliers_by_text
from execution.get_metadata import get_metadata
from execution.persistence import (
    get_or_create_profile, 
    get_or_create_group, 
    record_pedido, 
    record_recomendacao
)

# --- Orquestração Principal (MAIA) ---

def process_whatsapp_message_e2e(message_text, is_from_me=False, chat_id=None, sender_name=None, target_phone=None, real_user_phone=None):
    """
    Fluxo completo: Classificação -> Categorização -> Busca Vetorial -> Match -> Resposta.
    - chat_id: ID do grupo ou chat de origem.
    - target_phone: Número que RECEBERÁ a resposta da MAIA via Z-API.
    - real_user_phone: Número de quem ENVIOU (para o perfil).
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

    # 2. CATEGORIZATION & PERSISTENCE PREP
    try:
        # Gestão de Perfil e Grupo (Produção)
        profile_id = None
        group_id = None
        
        if real_user_phone:
            profile_id = get_or_create_profile(real_user_phone, sender_name or "Usuária")
        
        if chat_id and "group" in str(chat_id):
            group_id = get_or_create_group(chat_id)

        cat_instr = load_directive("categorization_directive.md")
        metadata = get_metadata()
        cat_prompt = f"Categorias reais disponíveis:\n{json.dumps(metadata)}\n\nPedido do Usuário: {message_text}"
        
        cat_res_raw = call_gemini(cat_instr, cat_prompt)
        cat_res = json.loads(cat_res_raw)
        
        # Registro do Pedido (Sem prefixos de teste)
        pedido_db_data = {
            "pedido_mensagem": message_text,
            "pedido_descricao": cat_res.get("pedido_descricao"),
            "pedido_categoria": cat_res.get("pedido_categoria"),
            "pedido_subcategoria": cat_res.get("pedido_subcategoria"),
            "pedido_grupo": group_id, 
            "profile": profile_id
        }
        pedido_record = record_pedido(pedido_db_data)
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
        
        # 5. Registro das Recomendações (Sem prefixos)
        if pedido_id and suppliers:
            for s in suppliers:
                rec_data = {
                    "pedido_indicacao": pedido_id,
                    "fornecedor_recomendado": s.get("fornecedor_id"),
                    "motivo_recomendacao": s.get("motivo_match")
                }
                record_recomendacao(rec_data)
        
        # 6. ENVIO DIRETO VIA Z-API
        if target_phone and final_res.get("mensagem_final"):
            send_zapi_message(target_phone, final_res["mensagem_final"])
                
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
