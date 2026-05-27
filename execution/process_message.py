import json
import os
import sys
import time
from datetime import date, datetime, timezone
from execution.zapi_client import send_zapi_message, send_zapi_button_actions
from execution.ai_client import call_ai_with_json_retry, call_ai_agent, call_claude, load_directive, set_telemetry_stage, collect_and_reset_tokens
from execution.search_suppliers import search_suppliers, search_suppliers_by_text
from execution.get_metadata import get_metadata
from execution.fase_bebe import calcular_fase_bebe
from execution.persistence import (
    get_or_create_profile,
    get_group,
    get_or_create_group,
    record_pedido,
    update_pedido,
    record_recomendacao,
    update_recomendacao,
    record_mensagem,
    record_pedido_sem_fornecedor,
    record_telemetria,
    get_chat_history,
    save_to_chat_history
)

# --- Configurações e Thresholds ---
CONFIDENCE_THRESHOLD = 0.80
SIMILARITY_THRESHOLD = 0.60
GRUPO_INDICACOES = "120363422760214316-group"
GRUPO_SYSTEM_LOGS = "120363406702749765-group"


def _log_sistema(titulo, detalhes):
    """Envia log de sistema para o grupo System Logs. Nunca quebra o fluxo."""
    try:
        msg = f"*[MAIA LOG] {titulo}*\n{detalhes}"
        send_zapi_message(GRUPO_SYSTEM_LOGS, msg)
    except Exception as e:
        print(f"[LOG GRUPO] Falha ao enviar log: {e}")

def _resolver_fase_bebe(telefone: str | None) -> str | None:
    """
    Resolve a fase do bebê para uma mãe a partir do telefone.
    Nunca levanta exceção — retorna None em qualquer falha.
    """
    if not telefone:
        return None
    try:
        from execution.supabase_client import get_supabase_client
        supabase = get_supabase_client()

        # 1. Busca perfil pelo telefone
        perfil_res = (
            supabase.table("perfis_maes")
            .select("user_id, status_maternidade")
            .eq("telefone", telefone)
            .limit(1)
            .execute()
        )
        if not perfil_res.data:
            return None

        perfil = perfil_res.data[0]
        user_id = perfil.get("user_id")
        status_maternidade = perfil.get("status_maternidade")

        if not user_id:
            return None

        # 2. Busca filho mais novo
        filho_res = (
            supabase.table("filhos_maes")
            .select("data_nascimento")
            .eq("mae_id", user_id)
            .order("data_nascimento", desc=True)
            .limit(1)
            .execute()
        )
        data_nascimento = None
        if filho_res.data:
            raw = filho_res.data[0].get("data_nascimento")
            if raw:
                data_nascimento = date.fromisoformat(str(raw)[:10])

        return calcular_fase_bebe(data_nascimento, status_maternidade)
    except Exception as e:
        print(f"[FASE_BEBE] Erro ao resolver fase (não-crítico): {e}")
        return None


def validate_supplier_2_3_rule(supplier, pedido_subcategoria_id, pedido_categoria_id, pedido_texto, metadata_context, flags=None):
    """
    Implementa a 'Regra dos 2/3' (pré-filtro determinístico antes do Agente LLM):
    1. Similaridade/score de pré-filtro >= SIMILARITY_THRESHOLD
    2. Aderência à taxonomia: subcategoria_id OU categoria_id igual (fallback por nome p/ docs antigos)
    3. Palavra-chave no conteúdo OU atributo booleano exigido (espaço kids/menu kids/trocador) satisfeito
    """
    flags = flags or {}
    matches = 0
    metadata = supplier.get("metadata", {}) or {}

    # Critério 1: Similaridade / score
    if supplier.get("similarity", 0) >= SIMILARITY_THRESHOLD:
        matches += 1

    # Critério 2: Aderência à taxonomia (por ID — determinístico; com fallback por nome)
    meta_sub_id = str(metadata.get("subcategoria_id") or "")
    meta_cat_id = str(metadata.get("categoria_id") or "")
    taxonomy_ok = False
    if pedido_subcategoria_id and meta_sub_id == str(pedido_subcategoria_id):
        taxonomy_ok = True
    elif pedido_categoria_id and meta_cat_id == str(pedido_categoria_id):
        taxonomy_ok = True
    else:
        # Fallback por nome (compatível com documentos antigos sem *_id no metadata)
        sub_pedida_nome = ""
        for s in metadata_context.get("subcategorias", []):
            if str(s.get("id")) == str(pedido_subcategoria_id):
                sub_pedida_nome = (s.get("nome") or "").upper()
                break
        if sub_pedida_nome and sub_pedida_nome == str(metadata.get("subcategoria", "")).upper():
            taxonomy_ok = True
    if taxonomy_ok:
        matches += 1

    # Critério 3: Palavra-chave no conteúdo OU atributo booleano exigido satisfeito
    content = (supplier.get("content") or "").lower()
    pedido_terms = [t for t in (pedido_texto or "").lower().split() if len(t) > 3]
    keyword_ok = any(term in content for term in pedido_terms)
    attr_ok = any(
        flags.get(flag) and metadata.get(col)
        for flag, col in (("requer_espaco_kids", "tem_espaco_kids"),
                          ("requer_menu_kids", "tem_menu_kids"),
                          ("requer_trocador", "tem_trocador"))
    )
    if keyword_ok or attr_ok:
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
            group_id, group_name = get_or_create_group(formatted_chat_id)
        elif "-group" in str(chat_id): # Fallback caso a API mude no futuro
            group_id, group_name = get_or_create_group(chat_id)

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

        # Sinais estruturais para o pré-filtro determinístico (atributos/região)
        pedido_flags = {
            "requer_espaco_kids": bool(triage_res.get("requer_espaco_kids")),
            "requer_menu_kids": bool(triage_res.get("requer_menu_kids")),
            "requer_trocador": bool(triage_res.get("requer_trocador")),
            "cidade_mencionada": triage_res.get("cidade_mencionada"),
        }
            
    except Exception as e:
        print(f"[ERRO] Falha técnica na triagem unificada: {e}")
        tel["etapa_final"] = "erro_triagem"
        _save_telemetria(tel)
        return None, "Erro técnico na triagem."

    print(f"\n[DEBUG] Pedido Válido (Confiança: {confidence}). Cat: {pedido_cat} | Sub: {pedido_sub}")

    _log_sistema("Novo pedido recebido", (
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
            "profile": profile_id,
            "pedido_por": {"nome": sender_name or "Usuária", "telefone": real_user_phone},
            "recomendacao_feita": False,
            "pedido_categoria": pedido_cat,
            "pedido_subcategoria": pedido_sub,
            "pedido_descricao": pedido_desc
        }
        if group_id is not None:
            pedido_db_data["pedido_grupo"] = group_id
        pedido_record = record_pedido(pedido_db_data)
        pedido_id = pedido_record["id"] if pedido_record else None
        print(f"[DEBUG] Registro realizado com categorização. ID: {pedido_id}")
    except Exception as e:
        print(f"[AVISO] Falha ao registrar pedido: {e}")

    # Atualiza telemetria com dados da triagem
    tel["confidence"] = confidence
    tel["categoria"] = str(pedido_cat)
    tel["subcategoria"] = str(pedido_sub)

    # 5.5 ENRIQUECIMENTO DE CONTEXTO: fase do bebê (nunca bloqueia o fluxo)
    fase_bebe = _resolver_fase_bebe(real_user_phone)
    print(f"[ORQUESTRAÇÃO] Fase do bebê resolvida: {fase_bebe!r}")

    # 6. MATCH DE FORNECEDORES (Busca Vetorial + Regra 2/3 + Agente LLM com Tool Calling)
    set_telemetry_stage("validacao")
    valid_suppliers = []
    try:
        from execution.agent_tools import get_categoria, get_subcategoria, agentic_tools

        # 6.1 Resolve nomes de categoria/subcategoria (determinístico)
        cat_name = get_categoria(pedido_cat) or "Desconhecida"
        sub_name = get_subcategoria(pedido_sub) or "Desconhecida"
        print(f"[ORQUESTRAÇÃO] Categoria: {cat_name} | Subcategoria: {sub_name}")

        # 6.2 Busca de candidatos: estruturada (determinística) + vetorial (ranqueamento)
        cidade_hint = pedido_flags.get("cidade_mencionada") or ""
        search_query = f"{cat_name} {sub_name} - {pedido_desc} {message_text} {cidade_hint}".strip()
        print(f"[ORQUESTRAÇÃO] Query de busca: '{search_query}' | flags: {pedido_flags}")
        candidates = search_suppliers(
            search_query,
            categoria_id=pedido_cat,
            subcategoria_id=pedido_sub,
            flags=pedido_flags,
        )
        print(f"[ORQUESTRAÇÃO] Busca retornou {len(candidates)} candidatos (estruturado + vetorial).")

        if candidates:
            # 6.3 Regra dos 2/3: pré-filtro determinístico antes da validação agêntica
            pre_filtered = [
                c for c in candidates
                if validate_supplier_2_3_rule(c, pedido_sub, pedido_cat, pedido_desc, metadata_context, pedido_flags)
            ]
            print(f"[ORQUESTRAÇÃO] Regra 2/3: {len(pre_filtered)}/{len(candidates)} candidatos aprovados.")
            tel["candidatos_encontrados"] = len(candidates)

            agent_candidates = pre_filtered if pre_filtered else candidates

            # 6.4 Validação e enriquecimento pelo Agente LLM (Tool Calling)
            match_instr = load_directive("supplier_match_directive.md")
            agent_prompt = f"""Pedido original do usuário: {message_text}
{memory_context}

Contexto processado:
- Categoria: {cat_name} (ID: {pedido_cat})
- Subcategoria: {sub_name} (ID: {pedido_sub})
- Descrição: {pedido_desc}
- Fase do bebê: {fase_bebe if fase_bebe is not None else "não informada"}

CANDIDATOS PRÉ-FILTRADOS PELA REGRA 2/3 (busca vetorial já executada):
{json.dumps(agent_candidates, ensure_ascii=False)}

Para cada fornecedor que você decidir recomendar, chame a ferramenta `link_fornecedor` com o seu ID para obter os dados reais de contato. Não invente links."""

            print("[ORQUESTRAÇÃO] Iniciando Agente LLM com Tool Calling para validação...")
            validation_res = call_ai_agent(match_instr, agent_prompt, agentic_tools)

            valid_suppliers = validation_res.get("recomendacoes", [])

            # Backfill defensivo: garante whatsapp_link e nome reais (da tabela parceiros)
            # para cada fornecedor. O nome é necessário para o label do botão e a
            # linha-resumo no texto. Nunca inventar link.
            for s in valid_suppliers:
                if (not s.get("link_fornecedor") or not s.get("nome")) and s.get("fornecedor_id"):
                    try:
                        import json as _json
                        from execution.agent_tools import link_fornecedor as _link
                        dados = _json.loads(_link(s["fornecedor_id"]))
                        if not s.get("link_fornecedor") and dados.get("whatsapp_link"):
                            s["link_fornecedor"] = dados["whatsapp_link"]
                        if not s.get("nome") and dados.get("nome"):
                            s["nome"] = dados["nome"]
                    except Exception as e:
                        print(f"[ORQUESTRAÇÃO] Backfill falhou p/ {s.get('fornecedor_id')}: {e}")

            tel["fornecedores_validados"] = len(valid_suppliers)
            print(f"[ORQUESTRAÇÃO] Agente validou {len(valid_suppliers)} fornecedores.")
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

                _log_sistema("Pedido SEM fornecedor", (
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

ESTRUTURA OBRIGATÓRIA DA MENSAGEM (mensagem CURTA, sem nenhum link no corpo):
1. Saudação com o nome da usuária
2. Contexto do pedido com empatia (1-2 frases; reformule o que ela pediu, mencione o grupo "{group_name}" se houver)
3. UMA linha-resumo curta por fornecedor no formato "• *Nome* — destaque em poucas palavras" (NÃO escreva 2-3 frases; é só um realce de uma linha)
4. CTA curto convidando a tocar nos botões abaixo (plural) para falar direto no WhatsApp do parceiro de preferência

Fornecedores selecionados para recomendar (use o campo "nome" no realce):
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
        rec_ids = []
        if pedido_id and valid_suppliers:
            for s in valid_suppliers:
                rec = record_recomendacao({
                    "pedido_indicacao": pedido_id,
                    "fornecedor_recomendado": s.get("fornecedor_id"),
                    "motivo_recomendacao": s.get("motivo_recomendacao"),
                    "link_fornecedor": s.get("link_fornecedor"),
                    "recomendacao_enviada": False,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
                if rec and rec.get("id"):
                    rec_ids.append(rec["id"])
    except Exception as e:
        print(f"[ERRO] Falha na geração da resposta: {e}")
        mensagem_final = "Oi! No momento tive um probleminha para gerar sua resposta, mas nossa equipe já foi avisada e vai te ajudar logo mais. 🙏"

    # 10. ENVIO WHATSAPP
    if mensagem_final:
        # Monta até 3 botões: um por fornecedor, levando direto ao seu whatsapp_link
        button_actions = []
        for s in valid_suppliers[:3]:
            link = s.get("link_fornecedor")
            if not link:
                continue  # sem whatsapp_link não há botão (nunca inventar)
            nome = (s.get("nome") or "Falar com parceiro").strip()
            button_actions.append({
                "type": "URL",
                "label": nome[:24],  # limite de caracteres do label de botão no WhatsApp
                "url": link
            })

        # Envio para a Usuária
        zapi_result = None
        if button_actions:
            zapi_result = send_zapi_button_actions(target_phone, mensagem_final, button_actions)
        else:
            zapi_result = send_zapi_message(target_phone, mensagem_final)

        # Marca recomendações como enviadas somente após confirmação da Z-API
        if zapi_result and rec_ids:
            for rec_id in rec_ids:
                update_recomendacao(rec_id, {
                    "recomendacao_enviada": True,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })

        # 10.1 REPLICAR INDICAÇÃO NO GRUPO MAIA INDICAÇÕES (como a usuária recebe)
        try:
            if button_actions:
                send_zapi_button_actions(GRUPO_INDICACOES, mensagem_final, button_actions)
            else:
                send_zapi_message(GRUPO_INDICACOES, mensagem_final)
            print(f"[ORQUESTRAÇÃO] Indicação replicada no grupo MAIA INDICAÇÕES.")
        except Exception as e:
            print(f"[AVISO] Falha ao enviar para o grupo de indicações: {e}")

        # 10.2 LOG DE SISTEMA (System Logs)
        _log_sistema("Indicação enviada", (
            f"De: *{sender_name or 'Desconhecido'}* ({real_user_phone or '?'})\n"
            f"Grupo: {group_name or 'Privado'}\n"
            f"Pedido: _{message_text}_\n"
            f"Fornecedores: {len(valid_suppliers)} | Tempo: {time.time() - t_start:.1f}s"
        ))
             
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

