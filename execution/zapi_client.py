import os
import requests
from dotenv import load_dotenv

load_dotenv()

ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN") # Opcional
# Configurações removidas: N8N_RECEIVING_WEBHOOK_URL (Relay desativado conforme solicitado)


def send_zapi_message(phone, message):
    """
    Envia uma mensagem de texto via Z-API.
    """
    # Limpa sufíxos padrão do WhatsApp
    clean_phone = phone.split("@")[0]
    
    if not ZAPI_INSTANCE_ID or not ZAPI_TOKEN:
        print("[Z-API] Erro: ZAPI_INSTANCE_ID ou ZAPI_TOKEN não configurados.")
        return None

    url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
    
    headers = {
        "Content-Type": "application/json"
    }
    if ZAPI_CLIENT_TOKEN:
        headers["Client-Token"] = ZAPI_CLIENT_TOKEN

    payload = {
        "phone": clean_phone,
        "message": message
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        res_data = response.json()
        print(f"[Z-API] Mensagem enviada com sucesso para {phone}. ID: {res_data.get('messageId')}")
        return res_data
    except Exception as e:
        print(f"[Z-API] Erro ao enviar mensagem: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"[Z-API] Detalhes do erro: {e.response.text}")
        return None
