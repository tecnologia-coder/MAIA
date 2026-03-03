import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

def get_supabase_client() -> Client:
    """
    Inicializa e retorna o cliente Supabase usando as variáveis de ambiente.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    
    if not url or not key:
        raise ValueError("SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY ou SUPABASE_ANON_KEY devem estar configurados no .env")
    
    return create_client(url, key)
