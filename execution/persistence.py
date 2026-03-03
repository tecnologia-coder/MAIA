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

def get_or_create_group(group_id, chat_name="Grupo WhatsApp"):
    """
    Verifica se o grupo está registrado na tabela 'grupos'.
    Se não existir, registra. Retorna o ID interno do grupo.
    """
    supabase = get_supabase_client()
    try:
        # Busca grupo existente pelo ID do WhatsApp (ex: 120363...-group)
        res = supabase.table("grupos").select("id").eq("grupo_id", group_id).execute()
        if res.data:
            return res.data[0]["id"]

        # Registra novo grupo
        insert_res = supabase.table("grupos").insert({"grupo_id": group_id, "grupo_nome": chat_name}).execute()
        return insert_res.data[0]["id"] if insert_res.data else None
    except Exception as e:
        print(f"[PERSISTENCE] Erro ao obter/criar grupo: {e}")
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
