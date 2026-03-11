import json
import os
import sys
import time
from datetime import datetime, timezone
from execution.zapi_client import send_zapi_message, send_zapi_button_actions
from execution.ai_client import call_ai_with_json_retry, call_claude, load_directive, set_telemetry_stage, collect_and_reset_tokens
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
    record_telemetria,
    get_chat_history,
    save_to_chat_history
)

# --- Configurações e Thresholds ---
CONFIDENCE_THRESHOLD = 0.80
SIMILARITY_THRESHOLD = 0.60
GRUPO_COORDENACAO = "120363422760214316-group"


def _log_grupo(titulo, detalhes):
    """Envia log formatado para o grupo de coordenação. Nunca quebra o fluxo."""
    try:
        msg = f"*[MAIA LOG] {titulo}*\n{detalhes}"
        send_zapi_message(GRUPO_COORDENACAO, msg)
    except Exception as e:
        print(f"[LOG GRUPO] Falha ao enviar log: {e}")

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

def _save_telemetria(telemetry_data):
    """Grava telemetria de forma segura (nunca quebra o fluxo principal)."""
    try:
        tokens = collect_and_reset_tokens()
        telemetry_data["tokens_triagem"] = tokens.get("triagem", 0)
        telemetry_data["tokens_validacao"] = tokens.get("validacao", 0)
        telemetry_data["tokens_resposta"] = tokens.get("resposta", 0)
        telemetry_data["tokens_total"] = sum(tokens.values())
        telemetry_data["tempo_total_ms"] = int((time.time() - telemetry_data.pop("_start_time", time.time())) * 1000)
        record_telemetria(telemetry_data)
    except Exception as e:
        print(f"[TELEMETRIA] Erro ao gravar (não-crítico): {e}")

def process_whatsapp_message_e2e(message_text, is_from_me=False, chat_id=None, sender_name=None, target_phone=None, real_user_phone=None):
    """
    Orquestrador Oficial MAIA - Seguindo as 10 etapas da system_architecture_directive.
    """
    # Inicializa contexto de telemetria
    t_start = time.time()
    collect_and_reset_tokens()  # Limpa acumulador de execuções anteriores
    tel = {
        "_start_time": t_start,
        "sender_name": sender_name or "Desconhecido",
        "sender_phone": real_user_phone or "",
        "message_text": message_text,
        "group_name": None,
        "etapa_final": "inicio",
        "confidence": None,
        "categoria": None,
        "subcategoria": None,
        "candidatos_encontrados": 0,
        "fornecedores_validados": 0,
        "resposta_final": None,
    }

    # 1. WEBHOOK / 2. TRIAGEM (Filtros Iniciais)
    if is_from_me:
        return None, "Mensagem própria ignorada pelo sistema."

    # 2.3 Resolução de Identidade (Movido para o início para Log de Auditoria)
    profile_id = get_or_create_profile(real_user_phone, sender_name or "Usuária") if real_user_phone else None
    
    # Tratamento do ID do Grupo: Z-API envia '@g.us', mas o painel/banco salva como '-group'
    group_id = None
    group_name = None
    if chat_id:
        if "@g.us" in str(chat_id):
            formatted_chat_id = str(chat_id).replace("@g.us", "-group")
            group_id, group_name = get_group(formatted_chat_id)
        elif "-group" in str(chat_id): # Fallback caso a API mude no futuro
            group_id, group_name = get_group(chat_id)

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
        tel["etapa_final"] = "heuristica_curta"
        _save_telemetria(tel)
        return None, "Ignorado pela heurística: Mensagem muito curta."

    # Regra 2: Ausência de palavras de intenção de busca/pedido
    if not any(keyword in msg_lower for keyword in intent_keywords):
        print(f"[TRIAGEM HEURÍSTICA] Ignorado: Sem intenção de pedido ('{message_text}')")
        tel["etapa_final"] = "heuristica_sem_intencao"
        _save_telemetria(tel)
        return None, "Ignorado pela heurística: Ausência de intenção de pedido."
        
    # Atualiza telemetria com nome do grupo (se resolvido)
    tel["group_name"] = group_name

    # 3. RECUPERAR MEMÓRIA, CLASSIFICAR E CATEGORIZAR (Chamada Unificada)
    set_telemetry_stage("triagem")
    # Puxa as últimas interações da n8n_chat_histories para passar contexto à IA
    chat_history = get_chat_history(real_user_phone, limit=5)
    memory_context = f"\n[HISTÓRICO RECENTE DA CONVERSA]\n{chat_history}" if chat_history else ""

    try:
        triage_instr = load_directive("triage_directive.md")
        metadata_context = get_metadata()
        triage_prompt = f"Categorias reais disponíveis:\n{json.dumps(metadata_context)}\n\nMensagem do Usuário: {message_text}{memory_context}"
        triage_res = call_ai_with_json_retry(triage_instr, triage_prompt)
        
        # 4. DECISÃO DE FLUXO (Python)
        is_valid = triage_res.get("is_valid_request")
        confidence = triage_res.get("confidence", 0)
        
        # Regra de Confiança: Abortar se < 0.80
        if not is_valid or confidence < CONFIDENCE_THRESHOLD:
            reason = triage_res.get("reason", "Incerteza na classificação.")
            print(f"[TRIAGEM] Pedido recusado. Confidence: {confidence}. Motivo: {reason}")
            tel["etapa_final"] = "triagem_rejeitada"
            tel["confidence"] = confidence
            _save_telemetria(tel)
            return None, reason
        
        # Extrair categorização da mesma resposta
        pedido_cat = triage_res.get("pedido_categoria")
        pedido_sub = triage_res.get("pedido_subcategoria")
        pedido_desc = triage_res.get("pedido_descricao")
            
    except Exception as e:
        print(f"[ERRO] Falha técnica na triagem unificada: {e}")
        tel["etapa_final"] = "erro_triagem"
        _save_telemetria(tel)
        return None, "Erro técnico na triagem."

    print(f"\n[DEBUG] Pedido Válido (Confiança: {confidence}). Cat: {pedido_cat} | Sub: {pedido_sub}")

    _log_grupo("Novo pedido recebido", (
        f"De: *{sender_name or 'Desconhecido'}* ({real_user_phone or '?'})\n"
        f"Grupo: {group_name or 'Privado'}\n"
        f"Mensagem: _{message_text}_\n"
        f"Confiança: {confidence}\n"
        f"Categoria: {pedido_cat} | Sub: {pedido_sub}\n"
        f"Descrição: {pedido_desc}"
    ))

    # 4.5 REGISTRO INICIAL DO PEDIDO (com categorização já inclusa)
    pedido_id = None
    try:
        pedido_db_data = {
            "pedido_mensagem": message_text,
            "pedido_grupo": group_id, 
            "profile": profile_id,
            "pedido_por": {"nome": sender_name or "Usuária", "telefone": real_user_phone},
            "recomendacao_feita": False,
            "pedido_categoria": pedido_cat,
            "pedido_subcategoria": pedido_sub,
            "pedido_descricao": pedido_desc
        }
        pedido_record = record_pedido(pedido_db_data)
        pedido_id = pedido_record["id"] if pedido_record else None
        print(f"[DEBUG] Registro realizado com categorização. ID: {pedido_id}")
    except Exception as e:
        print(f"[AVISO] Falha ao registrar pedido: {e}")

    # Atualiza telemetria com dados da triagem
    tel["confidence"] = confidence
    tel["categoria"] = str(pedido_cat)
    tel["subcategoria"] = str(pedido_sub)

    # 6. MATCH DE FORNECEDORES (Deterministic Search + LLM Validation)
    set_telemetry_stage("validacao")
    valid_suppliers = []
    try:
        from execution.agent_tools import get_categoria, get_subcategoria, link_fornecedor
        from execution.search_suppliers import search_suppliers_by_text

        # 6.1 Resolve nomes de categoria/subcategoria (determinístico)
        cat_name = get_categoria(pedido_cat) or "Desconhecida"
        sub_name = get_subcategoria(pedido_sub) or "Desconhecida"
        print(f"[ORQUESTRAÇÃO] Categoria: {cat_name} | Subcategoria: {sub_name}")

        # 6.2 Busca vetorial (determinístico)
        search_query = f"{cat_name} {sub_name} - {pedido_desc} {message_text}"
        print(f"[ORQUESTRAÇÃO] Query de busca: '{search_query}'")
        candidates = search_suppliers_by_text(search_query)
        print(f"[ORQUESTRAÇÃO] Busca vetorial retornou {len(candidates)} candidatos.")

        if candidates:
            # 6.3 Enriquece candidatos com link de contato (determinístico)
            for c in candidates:
                fid = c.get("metadata", {}).get("id")
                if fid:
                    link_data = json.loads(link_fornecedor(fid))
                    c["whatsapp_link"] = link_data.get("whatsapp_link")
                    c["status_parceiro"] = link_data.get("status")

            # 6.4 Validação pela LLM (chamada simples, sem tool calling)
            match_instr = load_directive("supplier_match_directive.md")
            validation_prompt = f"""Pedido original do usuário: {message_text}
{memory_context}

Contexto processado:
- Categoria: {cat_name} (ID: {pedido_cat})
- Subcategoria: {sub_name} (ID: {pedido_sub})
- Descrição: {pedido_desc}

CANDIDATOS RETORNADOS PELA BUSCA VETORIAL (já executada):
{json.dumps(candidates, ensure_ascii=False)}

IMPORTANTE: A busca vetorial e a recuperação de links JÁ FORAM EXECUTADAS acima.
Sua tarefa é APENAS validar quais candidatos atendem ao pedido e retornar o JSON final.
NÃO tente chamar ferramentas — os dados já estão disponíveis acima.
Para cada fornecedor recomendado, use o whatsapp_link já presente nos dados do candidato."""

            print("[ORQUESTRAÇÃO] Enviando candidatos para validação pela LLM...")
            validation_res = call_ai_with_json_retry(match_instr, validation_prompt)

            valid_suppliers = validation_res.get("recomendacoes", [])
            tel["candidatos_encontrados"] = len(candidates)
            tel["fornecedores_validados"] = len(valid_suppliers)
            print(f"[ORQUESTRAÇÃO] LLM validou {len(valid_suppliers)} fornecedores.")
        else:
            print("[ORQUESTRAÇÃO] Busca vetorial não retornou candidatos.")

    except Exception as e:
        print(f"[ERRO] Falha no fluxo de recomendação: {type(e).__name__}: {e}")
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

                _log_grupo("Pedido SEM fornecedor", (
                    f"De: *{sender_name or 'Desconhecido'}* ({real_user_phone or '?'})\n"
                    f"Grupo: {group_name or 'Privado'}\n"
                    f"Pedido: _{message_text}_\n"
                    f"Motivo: {motivo_falha}"
                ))

                # Atualizando status do pedido indicando que o ciclo encerrou (sem successo)
                update_pedido(pedido_id, {"recomendacao_feita": True})
            except Exception as e:
                print(f"[ERRO] Falha ao registrar log de pedido_sem_fornecedor: {e}")
                
        tel["etapa_final"] = "sem_fornecedor"
        _save_telemetria(tel)
        return {"status": "silenced", "reason": "Nenhum fornecedor encontrado"}, None

    set_telemetry_stage("resposta")
    try:
        persona_instr = load_directive("persona_directive.md")
        resp_instr = load_directive("response_generation_directive.md")
        
        final_instr = f"{persona_instr}\n\n{resp_instr}"

        # Contexto rico para personalização da mensagem
        user_first_name = (sender_name or "").split()[0] if sender_name else ""
        group_context = f"A mensagem foi enviada no grupo \"{group_name}\"." if group_name else "A mensagem foi enviada no privado."

        final_prompt = f"""Dados para personalização:
- Nome da usuária: {user_first_name or 'não informado'}
- {group_context}
- Pedido original da usuária: "{message_text}"
- Descrição processada do pedido: {pedido_desc}
- Categoria: {cat_name}
- Subcategoria: {sub_name}

ESTRUTURA OBRIGATÓRIA DA MENSAGEM (siga TODOS os 5 blocos, nenhum pode ser pulado):
1. Saudação com o nome da usuária
2. Contexto do pedido com empatia (reformule o que ela pediu com suas palavras, mencione o grupo "{group_name}" se houver)
3. Transição natural para os achados ("encontrei...", "separei pra você...")
4. Lista dos fornecedores com descrição aprofundada de cada um (2-3 frases por fornecedor, conectando o serviço com a necessidade específica da usuária)
5. CTA convidando a clicar no botão para falar com o parceiro de preferência

Fornecedores selecionados para recomendar:
{json.dumps(valid_suppliers, ensure_ascii=False)}"""
        
        # Usa Claude para geração humanizada; fallback para Gemini se chave não configurada
        try:
            final_res = call_claude(final_instr, final_prompt)
            print("[ORQUESTRAÇÃO] Mensagem gerada via Claude.")
        except RuntimeError:
            print("[ORQUESTRAÇÃO] Claude não configurado. Usando Gemini como fallback.")
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
        
        button_actions = []
        if supplier_params:
            partner_url = "https://maiahub.lovable.app/contato_fornecedor?" + "&".join(supplier_params)
            button_actions = [{
                "type": "URL",
                "label": "Falar com parceiros",
                "url": partner_url
            }]

        # Envio para a Usuária
        if button_actions:
            send_zapi_button_actions(target_phone, mensagem_final, button_actions)
        else:
            send_zapi_message(target_phone, mensagem_final)

        # 10.1 REPLICAR MENSAGEM NO GRUPO DE COORDENAÇÃO
        try:
            tempo_s = time.time() - t_start
            log_header = (
                f"*[MAIA LOG] Indicação enviada*\n"
                f"De: *{sender_name or 'Desconhecido'}* ({real_user_phone or '?'})\n"
                f"Grupo: {group_name or 'Privado'}\n"
                f"Pedido: _{message_text}_\n"
                f"Fornecedores: {len(valid_suppliers)} | Tempo: {tempo_s:.1f}s\n"
                f"---\n"
            )
            full_msg = log_header + mensagem_final
            if button_actions:
                send_zapi_button_actions(GRUPO_COORDENACAO, full_msg, button_actions)
            else:
                send_zapi_message(GRUPO_COORDENACAO, full_msg)
            print(f"[ORQUESTRAÇÃO] Mensagem replicada no grupo de coordenação.")
        except Exception as e:
            print(f"[AVISO] Falha ao enviar para o grupo de coordenação: {e}")
             
    # Atualizando status do pedido indicando que o ciclo encerrou (com sucesso)
    if pedido_id:
        update_pedido(pedido_id, {"recomendacao_feita": True})
        
    # Salvar Interação no Histórico de Longo Prazo
    if real_user_phone:
        save_to_chat_history(real_user_phone, human_text=message_text, ai_text=mensagem_final)

    # Gravar telemetria de sucesso
    tel["etapa_final"] = "sucesso"
    tel["resposta_final"] = mensagem_final
    _save_telemetria(tel)

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

