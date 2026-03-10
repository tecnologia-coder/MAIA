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

def get_group(group_id):
    """
    Verifica se o grupo está registrado na tabela 'grupos'.
    Retorna tupla (id_interno, nome_do_grupo) se existir, ou (None, None).
    """
    supabase = get_supabase_client()
    try:
        res = supabase.table("grupos").select("id, grupo_nome").eq("grupo_id", group_id).execute()
        if res.data:
            return res.data[0]["id"], res.data[0].get("grupo_nome")
        return None, None
    except Exception as e:
        print(f"[PERSISTENCE] Erro ao buscar grupo: {e}")
        return None, None

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
        print(f"[PERSISTENCE] Erro ao registrar recomendação: {e}")
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
