import json
import os
import sys
from execution.zapi_client import send_zapi_message
from execution.ai_client import call_ai_with_json_retry, load_directive
from execution.search_suppliers import search_suppliers_by_text
from execution.get_metadata import get_metadata
from execution.persistence import (
    get_or_create_profile, 
    get_group, 
    record_pedido, 
    record_recomendacao
)

# --- Configurações e Thresholds ---
CONFIDENCE_THRESHOLD = 0.80
SIMILARITY_THRESHOLD = 0.78

def validate_supplier_2_3_rule(supplier, pedido_subcategoria_id, pedido_texto, metadata_context):
    """
    Implementa a 'Regra dos 2/3' da supplier_match_directive:
    1. Similaridade >= 0.78
    2. Subcategoria igual (Nome ou ID)
    3. Palavra-chave correspondente
    """
    matches = 0
    
    # Critério 1: Similaridade
    if supplier.get("similarity", 0) >= SIMILARITY_THRESHOLD:
        matches += 1
        
    # Critério 2: Subcategoria
    metadata = supplier.get("metadata", {})
    # Busca o nome da subcategoria pedida no contexto para comparar por nome
    sub_pedida_nome = ""
    for s in metadata_context.get("subcategorias", []):
        if str(s.get("id")) == str(pedido_subcategoria_id):
            sub_pedida_nome = s.get("nome", "").upper()
            break
            
    meta_sub = str(metadata.get("subcategoria", "")).upper()
    meta_sub_id = str(metadata.get("subcategoria_id", ""))
    
    if (sub_pedida_nome and sub_pedida_nome == meta_sub) or (str(pedido_subcategoria_id) == meta_sub_id):
        matches += 1
        
    # Critério 3: Palavra-chave/Conteúdo
    content = supplier.get("content", "").lower()
    pedido_terms = [t for t in pedido_texto.lower().split() if len(t) > 3]
    if any(term in content for term in pedido_terms):
        matches += 1
        
    return matches >= 2

def process_whatsapp_message_e2e(message_text, is_from_me=False, chat_id=None, sender_name=None, target_phone=None, real_user_phone=None):
    """
    Orquestrador Oficial MAIA - Seguindo as 10 etapas da system_architecture_directive.
    """
    
    # 1. WEBHOOK / 2. TRIAGEM (Filtros Iniciais)
    if is_from_me:
        return None, "Mensagem própria ignorada pelo sistema."
    
    # 3. CLASSIFICAÇÃO
    try:
        class_instr = load_directive("classification_directive.md")
        class_res = call_ai_with_json_retry(class_instr, message_text)
        
        # 4. DECISÃO DE FLUXO (Python)
        is_valid = class_res.get("is_valid_request")
        confidence = class_res.get("confidence", 0)
        
        # Regra de Confiança: Abortar se < 0.80
        if not is_valid or confidence < CONFIDENCE_THRESHOLD:
            reason = class_res.get("reason", "Incerteza na classificação.")
            print(f"[TRIAGEM] Pedido recusado. Confidence: {confidence}. Motivo: {reason}")
            return None, reason
            
    except Exception as e:
        print(f"[ERRO] Falha técnica na classificação: {e}")
        return None, "Erro técnico na triagem."

    print(f"\n[DEBUG] Pedido Válido (Confiança: {confidence}). Categorizando...")

    # 5. CATEGORIZAÇÃO
    try:
        cat_instr = load_directive("categorization_directive.md")
        metadata_context = get_metadata()
        cat_prompt = f"Categorias reais disponíveis:\n{json.dumps(metadata_context)}\n\nPedido do Usuário: {message_text}"
        cat_res = call_ai_with_json_retry(cat_instr, cat_prompt)
        
        pedido_cat = cat_res.get("pedido_categoria")
        pedido_sub = cat_res.get("pedido_subcategoria")
        pedido_desc = cat_res.get("pedido_descricao")
    except Exception as e:
        print(f"[ERRO] Falha na categorização: {e}")
        return None, "Erro técnico na categorização."

    # 6. BUSCA VETORIAL (Com Threshold e Fallback embutidos em search_suppliers_by_text)
    try:
        candidates = search_suppliers_by_text(message_text)
        print(f"[BUSCA] Encontrados {len(candidates)} candidatos iniciais.")
    except Exception as e:
        print(f"[ERRO] Falha na busca: {e}")
        candidates = []

    # 7. VALIDAÇÃO DE FORNECEDORES (Regra dos 2/3)
    valid_suppliers = []
    for cand in candidates:
        if validate_supplier_2_3_rule(cand, pedido_sub, message_text, metadata_context):
            # Extrair ID do parceiro (a metadata do Supabase usa 'ID' em maiúsculo)
            f_id = cand.get("metadata", {}).get("ID") or cand.get("id")
            valid_suppliers.append({
                "fornecedor_id": f_id,
                "motivo_match": f"Validação técnica positiva (Match 2/3)."
            })
            if len(valid_suppliers) >= 3: # Limite Final de 3
                break

    # 8. PERSISTÊNCIA
    pedido_id = None
    try:
        profile_id = get_or_create_profile(real_user_phone, sender_name or "Usuária") if real_user_phone else None
        group_id = get_group(chat_id) if chat_id and "group" in str(chat_id) else None
        
        pedido_db_data = {
            "pedido_mensagem": message_text,
            "pedido_descricao": pedido_desc,
            "pedido_categoria": pedido_cat,
            "pedido_subcategoria": pedido_sub,
            "pedido_grupo": group_id, 
            "profile": profile_id
        }
        pedido_record = record_pedido(pedido_db_data)
        pedido_id = pedido_record["id"] if pedido_record else None
    except Exception as e:
        print(f"[AVISO] Falha ao persistir pedido no banco: {e}")

    # 9. GERAÇÃO DE RESPOSTA
    try:
        persona_instr = load_directive("persona_directive.md")
        resp_instr = load_directive("response_generation_directive.md")
        
        final_instr = f"{persona_instr}\n\n{resp_instr}"
        final_prompt = f"Lista de Fornecedores Selecionados:\n{json.dumps(valid_suppliers)}\n\nPedido original: {message_text}"
        
        final_res = call_ai_with_json_retry(final_instr, final_prompt)
        mensagem_final = final_res.get("mensagem_final")
        
        # Registrar Recomendações no Banco
        if pedido_id and valid_suppliers:
            for s in valid_suppliers:
                record_recomendacao({
                    "pedido_indicacao": pedido_id,
                    "fornecedor_recomendado": s.get("fornecedor_id"), # Corrigido para 'recomendado'
                    "motivo_recomendacao": s.get("motivo_match")
                })
    except Exception as e:
        print(f"[ERRO] Falha na geração da resposta: {e}")
        mensagem_final = "Oi! No momento tive um probleminha para gerar sua resposta, mas nossa equipe já foi avisada e vai te ajudar logo mais. 🙏"

    # 10. ENVIO WHATSAPP
    if target_phone and mensagem_final:
        send_zapi_message(target_phone, mensagem_final)
            
    return {"mensagem_final": mensagem_final}, None


if __name__ == "__main__":
    print("\n" + "="*40)
    print("      MAIA: AMBIENTE DE TESTE LOCAL")
    print("="*40)
    
    user_input = sys.argv[1] if len(sys.argv) > 1 else input("\n[WhatsApp Mock] Digite sua mensagem: ")
    
    # Simulação de parâmetros para teste
    result, error_reason = process_whatsapp_message_e2e(
        user_input, 
        real_user_phone="5511999999999", 
        target_phone="5511999999999"
    )
    
    if error_reason:
        print(f"\n[SISTEMA] Processamento encerrado: {error_reason}")
    elif result:
        print("\n" + "-"*30)
        print("RESPOSTA DA MAIA:")
        print("-" * 30)
        print(result.get("mensagem_final"))
        print("-" * 30)

