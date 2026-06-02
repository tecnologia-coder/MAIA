from execution.supabase_client import get_supabase_client

def get_or_create_profile(phone, name="Usuária"):
    """
    Verifica se o perfil da usuária existe no Supabase pelo número.
    Se não existir, cria um novo. Retorna o ID do perfil.
    """
    supabase = get_supabase_client()
    try:
        # Busca perfil existente
        res = supabase.table("profiles").select("id").eq("profile_numero", phone).execute()
        if res.data:
            return res.data[0]["id"]

        # Cria novo perfil se não encontrar
        insert_res = supabase.table("profiles").insert({"profile_numero": phone, "profile_nome": name}).execute()
        return insert_res.data[0]["id"] if insert_res.data else None
    except Exception as e:
        print(f"[PERSISTENCE] Erro ao obter/criar perfil: {e}")
        return None

def _grupo_recebe_pv(row):
    """
    Lê o flag 'enviar_indicacao_pv' de uma linha da tabela 'grupos'.
    Fail-open: ausência da coluna (migração ainda não aplicada) ou valor null
    é tratado como True, preservando o comportamento atual de envio no PV.
    """
    flag = (row or {}).get("enviar_indicacao_pv")
    return True if flag is None else bool(flag)

def get_group(group_id):
    """
    Verifica se o grupo está registrado na tabela 'grupos'.
    Retorna tupla (id_interno, nome_do_grupo, recebe_pv) se existir, ou (None, None, True).
    """
    supabase = get_supabase_client()
    try:
        res = supabase.table("grupos").select("*").eq("grupo_id", group_id).execute()
        if res.data:
            row = res.data[0]
            return row["id"], row.get("grupo_nome"), _grupo_recebe_pv(row)
        return None, None, True
    except Exception as e:
        print(f"[PERSISTENCE] Erro ao buscar grupo: {e}")
        return None, None, True

def get_or_create_group(group_id_raw, group_name=None):
    """
    Busca o grupo pelo ID externo. Se não existir, cria automaticamente para
    fins de auditoria/log.

    Retorna 4-tupla (id_interno, nome_do_grupo, recebe_pv, is_listed):
    - recebe_pv  : coluna enviar_indicacao_pv — False bloqueia envio no PV.
    - is_listed  : True se o grupo JÁ estava cadastrado antes desta mensagem.
                   False para grupos recém-criados automaticamente. Usado para
                   garantir que só grupos pré-cadastrados disparam indicação no PV.
    Fail-open em caso de erro de banco: retorna (None, None, True, False).
    """
    supabase = get_supabase_client()
    try:
        res = supabase.table("grupos").select("*").eq("grupo_id", group_id_raw).execute()
        if res.data:
            row = res.data[0]
            return row["id"], row.get("grupo_nome"), _grupo_recebe_pv(row), True

        # Grupo novo: registra automaticamente para auditoria, mas is_listed=False
        novo_nome = group_name or group_id_raw
        insert_res = supabase.table("grupos").insert({
            "grupo_id": group_id_raw,
            "grupo_nome": novo_nome
        }).execute()
        if insert_res.data:
            print(f"[PERSISTENCE] Novo grupo registrado automaticamente (sem PV): {group_id_raw}")
            row = insert_res.data[0]
            return row["id"], row.get("grupo_nome"), _grupo_recebe_pv(row), False
        return None, None, True, False
    except Exception as e:
        print(f"[PERSISTENCE] Erro ao obter/criar grupo: {e}")
        return None, None, True, False

def record_pedido(data):
    """
    Registra um pedido real na tabela 'pedidos_indicacao'.
    Nível de produção: sem prefixos de teste.
    """
    supabase = get_supabase_client()
    try:
        res = supabase.table("pedidos_indicacao").insert(data).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"[PERSISTENCE] Erro ao registrar pedido: {e}")
        return None

def record_recomendacao(data):
    """
    Registra uma recomendação real na tabela 'recomendacao_fornecedor'.
    """
    supabase = get_supabase_client()
    try:
        res = supabase.table("recomendacao_fornecedor").insert(data).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        import traceback
        print(f"[PERSISTENCE] Erro ao registrar recomendação: {e}\n{traceback.format_exc()}")
        return None

def update_recomendacao(rec_id, update_data):
    """
    Atualiza um registro existente na tabela 'recomendacao_fornecedor'.
    """
    supabase = get_supabase_client()
    try:
        res = supabase.table("recomendacao_fornecedor").update(update_data).eq("id", rec_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        import traceback
        print(f"[PERSISTENCE] Erro ao atualizar recomendação {rec_id}: {e}\n{traceback.format_exc()}")
        return None

def record_mensagem(data):
    """
    Registra uma mensagem na tabela 'mensagens' para log de auditoria.
    Campos esperados: grupo, message_type, message_content, message_sender
    """
    supabase = get_supabase_client()
    try:
        res = supabase.table("mensagens").insert(data).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"[PERSISTENCE] Erro ao registrar mensagem de auditoria: {e}")
        return None

def get_flag_status(title="status-maia"):
    """
    Lê a coluna 'flag' da tabela 'flags_status' para o 'title' informado.
    Usada como kill-switch para o envio de indicações no PV (alterada por uma
    interface frontend externa).

    Fail-open: em caso de erro de leitura retorna None, e o chamador deve tratar
    None como ativo para preservar o comportamento atual (não derrubar entregas
    por um problema pontual de banco).
    """
    supabase = get_supabase_client()
    try:
        res = (
            supabase.table("flags_status")
            .select("flag")
            .eq("title", title)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0].get("flag")
    except Exception as e:
        print(f"[PERSISTENCE] Erro ao ler flags_status ({title}): {e}")
    return None

def update_pedido(pedido_id, update_data):
    """
    Atualiza um pedido existente na tabela 'pedidos_indicacao'.
    """
    supabase = get_supabase_client()
    try:
        res = supabase.table("pedidos_indicacao").update(update_data).eq("id", pedido_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"[PERSISTENCE] Erro ao atualizar pedido {pedido_id}: {e}")
        return None

def record_pedido_sem_fornecedor(data):
    """
    Registra uma ocorrência onde nenhum fornecedor foi encontrado para a query na tabela 'pedido_sem_fornecedor'.
    """
    supabase = get_supabase_client()
    try:
        res = supabase.table("pedido_sem_fornecedor").insert(data).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"[PERSISTENCE] Erro ao registrar pedido sem fornecedor: {e}")
        return None

def get_chat_history(session_id, limit=6):
    """
    Busca as últimas mensagens da tabela n8n_chat_histories para um usuário específico.
    Retorna uma string formatada contendo o contexto recente.
    """
    supabase = get_supabase_client()
    try:
        # Busca ordenando da mais recente para mais antiga, depois inverte para ter ordem cronológica
        res = supabase.table("n8n_chat_histories").select("message").eq("session_id", session_id).order("id", desc=True).limit(limit).execute()
        if not res.data:
            return ""
            
        history_str = ""
        # res.data vem do mais recente pro mais antigo (desc=True). Invertemos para leitura natural.
        for row in reversed(res.data):
            msg = row.get("message", {})
            msg_type = msg.get("type", "")
            content = msg.get("content", "")
            
            if msg_type == "human":
                history_str += f"Usuária: {content}\\n"
            elif msg_type == "ai":
                history_str += f"MAIA: {content}\\n"
                
        return history_str.strip()
    except Exception as e:
        print(f"[PERSISTENCE] Erro ao buscar histórico de chat: {e}")
        return ""

def record_telemetria(data):
    """
    Registra métricas de telemetria na tabela 'telemetria'.
    Campos: sender_name, sender_phone, message_text, group_name,
            etapa_final, confidence, categoria, subcategoria,
            candidatos_encontrados, fornecedores_validados,
            tokens_triagem, tokens_validacao, tokens_resposta, tokens_total,
            tempo_total_ms, resposta_final
    """
    supabase = get_supabase_client()
    try:
        res = supabase.table("telemetria").insert(data).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"[TELEMETRIA] Erro ao registrar telemetria: {e}")
        return None

def save_to_chat_history(session_id, human_text=None, ai_text=None):
    """
    Salva a mensagem do usuário e/ou a resposta da IA na tabela n8n_chat_histories.
    """
    supabase = get_supabase_client()
    try:
        inserts = []
        if human_text:
            inserts.append({
                "session_id": session_id,
                "message": {"type": "human", "content": human_text, "additional_kwargs": {}, "response_metadata": {}}
            })
        if ai_text:
            inserts.append({
                "session_id": session_id,
                "message": {"type": "ai", "content": ai_text, "additional_kwargs": {}, "response_metadata": {}, "invalid_tool_calls": [], "tool_calls": []}
            })
            
        if inserts:
            supabase.table("n8n_chat_histories").insert(inserts).execute()
            
    except Exception as e:
        print(f"[PERSISTENCE] Erro ao salvar log no histórico de chat: {e}")
