import json
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
    # Se o telefone vier com @g.us ou @c.us, mantemos para garantir compatibilidade com grupos/privado
    clean_phone = phone
    
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

    print(f"[Z-API] Tentando enviar para {clean_phone}. Payload: {json.dumps(payload)}")

    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            print(f"[Z-API] Erro {response.status_code}: {response.text}")
        response.raise_for_status()
        res_data = response.json()
        print(f"[Z-API] Mensagem enviada com sucesso para {phone}. ID: {res_data.get('messageId')}")
        return res_data
    except Exception as e:
        print(f"[Z-API] Erro ao enviar mensagem: {e}")
        # Detalhes já impressos acima se status_code != 200
        return None

def send_zapi_button_list(phone, message, button_list):
    """
    Envia uma mensagem de texto contendo botões interativos via Z-API.
    
    :param phone: Número de destino
    :param message: Texto da mensagem principal
    :param button_list: Lista de dicionários representando os botões (ex: [{"id": "1", "label": "Botão A"}])
    """
    clean_phone = phone
    
    if not ZAPI_INSTANCE_ID or not ZAPI_TOKEN:
        print("[Z-API] Erro: ZAPI_INSTANCE_ID ou ZAPI_TOKEN não configurados.")
        return None

    url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-button-list"
    
    headers = {
        "Content-Type": "application/json"
    }
    if ZAPI_CLIENT_TOKEN:
        headers["Client-Token"] = ZAPI_CLIENT_TOKEN

    payload = {
        "phone": clean_phone,
        "message": message,
        "buttonList": button_list
    }

    print(f"[Z-API] Tentando enviar botões para {clean_phone}. Quantidade de botões: {len(button_list)}")

    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            print(f"[Z-API] Erro {response.status_code}: {response.text}")
        response.raise_for_status()
        res_data = response.json()
        print(f"[Z-API] Mensagem com botões enviada com sucesso para {phone}. ID: {res_data.get('messageId')}")
        return res_data
    except Exception as e:
        print(f"[Z-API] Erro ao enviar botões: {e}")
        return None
