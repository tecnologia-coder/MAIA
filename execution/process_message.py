import json
import os
import sys
from datetime import datetime, timezone
from execution.zapi_client import send_zapi_message, send_zapi_button_actions
from execution.ai_client import call_ai_with_json_retry, load_directive
from execution.search_suppliers import search_suppliers_by_text
from execution.get_metadata import get_metadata
from execution.persistence import (
    get_or_create_profile, 
    get_group, 
    record_pedido, 
    update_pedido,
    record_recomendacao,
    record_mensagem,
    record_pedido_sem_fornecedor,
    get_chat_history,
    save_to_chat_history
)

# --- Configurações e Thresholds ---
CONFIDENCE_THRESHOLD = 0.80
SIMILARITY_THRESHOLD = 0.60

def validate_supplier_2_3_rule(supplier, pedido_subcategoria_id, pedido_texto, metadata_context):
    """
    Implementa a 'Regra dos 2/3' da supplier_match_directive:
    1. Similaridade >= 0.60
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

    # 2.3 Resolução de Identidade (Movido para o início para Log de Auditoria)
    profile_id = get_or_create_profile(real_user_phone, sender_name or "Usuária") if real_user_phone else None
    
    # Tratamento do ID do Grupo: Z-API envia '@g.us', mas o painel/banco salva como '-group'
    group_id = None
    if chat_id:
        if "@g.us" in str(chat_id):
            formatted_chat_id = str(chat_id).replace("@g.us", "-group")
            group_id = get_group(formatted_chat_id)
        elif "-group" in str(chat_id): # Fallback caso a API mude no futuro
            group_id = get_group(chat_id)

    # 2.5 LOG DE AUDITORIA (Registro de todas as mensagens recebidas)
    try:
        record_mensagem({
            "grupo": group_id,
            "message_type": "text",
            "message_content": message_text,
            "message_sender": profile_id
        })
    except Exception as e:
        print(f"[AVISO] Falha ao registrar log de auditoria: {e}")
    
    # 2.8 FILTRO HEURÍSTICO (Contenção de Custos / Rate Limit)
    # Lista de palavras-chave fortemente associadas a pedidos de indicação
    intent_keywords = [
        "indica", "indicação", "indicacao", "indicar", "recomenda", "recomendação", "recomendacao", "recomende",
        "sugere", "sugestão", "sugestao", "procuro", "procurando", "busco", "buscando", 
        "preciso", "precisando", "queria", "alguem tem", "alguém tem", "alguem conhece", "alguém conhece", 
        "alguem sabe", "alguém sabe", "contato", "telefone", "onde acho", "onde encontro", 
        "profissional", "serviço", "servico", "ajuda com", "conserto", "orçamento", "orcamento"
    ]
    
    msg_lower = message_text.lower()
    
    # Regra 1: Mensagens muito curtas (geralmente saudações, sim/não, emojis)
    if len(message_text.strip().split()) <= 2:
        print(f"[TRIAGEM HEURÍSTICA] Ignorado: Mensagem muito curta ('{message_text}')")
        return None, "Ignorado pela heurística: Mensagem muito curta."
        
    # Regra 2: Ausência de palavras de intenção de busca/pedido
    if not any(keyword in msg_lower for keyword in intent_keywords):
        print(f"[TRIAGEM HEURÍSTICA] Ignorado: Sem intenção de pedido ('{message_text}')")
        return None, "Ignorado pela heurística: Ausência de intenção de pedido."
        
    # 3. RECUPERAR MEMÓRIA E CLASSIFICAR
    # Puxa as últimas interações da n8n_chat_histories para passar contexto à IA
    chat_history = get_chat_history(real_user_phone, limit=5)
    memory_context = f"\n[HISTÓRICO RECENTE DA CONVERSA]\n{chat_history}" if chat_history else ""

    try:
        class_instr = load_directive("classification_directive.md")
        class_prompt = f"{message_text}{memory_context}"
        class_res = call_ai_with_json_retry(class_instr, class_prompt)
        
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

    print(f"\n[DEBUG] Pedido Válido (Confiança: {confidence}). Registrando inicialmente...")
    
    # 4.5 REGISTRO INICIAL DO PEDIDO (Registro bruto conforme pedido pelo usuário)
    pedido_id = None
    try:
        pedido_db_data = {
            "pedido_mensagem": message_text,
            "pedido_grupo": group_id, 
            "profile": profile_id,
            "pedido_por": {"nome": sender_name or "Usuária", "telefone": real_user_phone},
            "recomendacao_feita": False
        }
        pedido_record = record_pedido(pedido_db_data)
        pedido_id = pedido_record["id"] if pedido_record else None
        print(f"[DEBUG] Registro Inicial realizado. ID: {pedido_id}")
    except Exception as e:
        print(f"[AVISO] Falha ao registrar pedido inicial: {e}")

    # 5. CATEGORIZAÇÃO
    try:
        cat_instr = load_directive("categorization_directive.md")
        metadata_context = get_metadata()
        cat_prompt = f"Categorias reais disponíveis:\n{json.dumps(metadata_context)}\n\nPedido do Usuário: {message_text}{memory_context}"
        cat_res = call_ai_with_json_retry(cat_instr, cat_prompt)
        
        pedido_cat = cat_res.get("pedido_categoria")
        pedido_sub = cat_res.get("pedido_subcategoria")
        pedido_desc = cat_res.get("pedido_descricao")

        # 5.5 ATUALIZAÇÃO DO PEDIDO COM CATEGORIZAÇÃO
        if pedido_id:
            update_data = {
                "pedido_categoria": pedido_cat,
                "pedido_subcategoria": pedido_sub,
                "pedido_descricao": pedido_desc
            }
            update_pedido(pedido_id, update_data)
            print(f"[DEBUG] Registro {pedido_id} atualizado com categorização: {pedido_cat}/{pedido_sub}")

    except Exception as e:
        print(f"[ERRO] Falha na categorização: {e}")
        return None, "Erro técnico na categorização."

    # 6. MATCH DE FORNECEDORES (Agentic Flow - Tool Calling)
    valid_suppliers = []
    max_agent_attempts = 2
    try:
        from execution.ai_client import call_ai_agent
        from execution.agent_tools import agentic_tools

        match_instr = load_directive("supplier_match_directive.md")

        # O prompt precisa passar o contexto completo para que a LLM saiba o que executar
        agent_prompt = f"""
Pedido original do usuário: {message_text}
{memory_context}

Contexto processado:
- Categoria ID: {pedido_cat}
- Subcategoria ID: {pedido_sub}
- Descrição da IA de triagem: {pedido_desc}

USE AS FERRAMENTAS DISPONÍVEIS para cumprir seu objetivo de recomendação conforme a diretriz.
"""
        for attempt in range(1, max_agent_attempts + 1):
            print(f"[ORQUESTRAÇÃO] Transferindo controle para o Agente MAIA (Match) - Tentativa {attempt}/{max_agent_attempts}...")
            agent_res = call_ai_agent(match_instr, agent_prompt, tools=agentic_tools)

            valid_suppliers = agent_res.get("recomendacoes", [])
            print(f"[ORQUESTRAÇÃO] O Agente retornou {len(valid_suppliers)} fornecedores validados.")

            if valid_suppliers:
                break
            elif attempt < max_agent_attempts:
                print("[ORQUESTRAÇÃO] Agente retornou vazio. Realizando retry...")
    except Exception as e:
        print(f"[ERRO] Falha no fluxo agêntico de recomendação: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        valid_suppliers = []

    # 9. GERAÇÃO DE RESPOSTA E FLUXO SILENCIOSO
    if not valid_suppliers:
        print(f"[ORQUESTRAÇÃO] Nenhum fornecedor encontrado. Gravando log silencioso (pedido_sem_fornecedor) e abortando envio.")
        if pedido_id:
            try:
                # Gera um log técnico focado nos critérios que falharam (em vez de uma mensagem para o cliente)
                log_instr = '''Atue como um analista de dados do sistema MAIA. 
Sua tarefa é gerar uma justificativa curta, direta e técnica (máximo 2 linhas) do motivo pelo qual nenhum fornecedor foi encontrado para a solicitação abaixo.
Foque nos critérios específicos do pedido que provavelmente não existem na base atual (ex: região, subcategoria muito específica, restrição de dias).
Retorne SOMENTE um JSON válido com a chave "motivo_tecnico".'''
                
                final_prompt = f"Pedido original: '{message_text}'\nCategoria processada: {pedido_cat}\nSubcategoria processada: {pedido_sub}\nDescritivo extraído: {pedido_desc}"
                final_res = call_ai_with_json_retry(log_instr, final_prompt)
                motivo_falha = final_res.get("motivo_tecnico", "Nenhum fornecedor compatível encontrado para os critérios da busca.")
                
                record_pedido_sem_fornecedor({
                    "pedido": pedido_id,
                    "contato": profile_id,
                    "motivo": motivo_falha
                })
                
                # Atualizando status do pedido indicando que o ciclo encerrou (sem successo)
                update_pedido(pedido_id, {"recomendacao_feita": True})
            except Exception as e:
                print(f"[ERRO] Falha ao registrar log de pedido_sem_fornecedor: {e}")
                
        return {"status": "silenced", "reason": "Nenhum fornecedor encontrado"}, None

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
                    "motivo_recomendacao": s.get("motivo_match"),
                    "link_fornecedor": s.get("link_fornecedor"),
                    "recomendacao_enviada": False,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
    except Exception as e:
        print(f"[ERRO] Falha na geração da resposta: {e}")
        mensagem_final = "Oi! No momento tive um probleminha para gerar sua resposta, mas nossa equipe já foi avisada e vai te ajudar logo mais. 🙏"

    # 10. ENVIO WHATSAPP
    if target_phone and mensagem_final:
        # Monta botão único "Falar com parceiros" com IDs dos fornecedores na URL
        supplier_params = []
        for i, s in enumerate(valid_suppliers[:3]):
            fid = s.get("fornecedor_id", 0)
            supplier_params.append(f"supplier{i + 1}={fid}")
        if supplier_params:
            partner_url = "https://maiahub.lovable.app/contato_fornecedor?" + "&".join(supplier_params)
            button_actions = [{
                "type": "URL",
                "label": "Falar com parceiros",
                "url": partner_url
            }]
            send_zapi_button_actions(target_phone, mensagem_final, button_actions)
        else:
             send_zapi_message(target_phone, mensagem_final)
             
    # Atualizando status do pedido indicando que o ciclo encerrou (com sucesso)
    if pedido_id:
        update_pedido(pedido_id, {"recomendacao_feita": True})
        
    # Salvar Interação no Histórico de Longo Prazo
    if real_user_phone:
        save_to_chat_history(real_user_phone, human_text=message_text, ai_text=mensagem_final)
            
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

