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
    Retorna o ID interno se existir, ou None se não encontrar.
    """
    supabase = get_supabase_client()
    try:
        res = supabase.table("grupos").select("id").eq("grupo_id", group_id).execute()
        if res.data:
            return res.data[0]["id"]
        return None
    except Exception as e:
        print(f"[PERSISTENCE] Erro ao buscar grupo: {e}")
        return None

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
