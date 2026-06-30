import json
import os
import time
from urllib.parse import parse_qsl, quote, urlparse

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from dotenv import load_dotenv

load_dotenv()

ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN") # Opcional
# Configurações removidas: N8N_RECEIVING_WEBHOOK_URL (Relay desativado conforme solicitado)


def _zapi_base_url() -> str | None:
    """Monta a base da URL Z-API ou retorna None se faltar credencial."""
    if not ZAPI_INSTANCE_ID or not ZAPI_TOKEN:
        print("[Z-API] Erro: ZAPI_INSTANCE_ID ou ZAPI_TOKEN não configurados.")
        return None
    return f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}"


def _zapi_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if ZAPI_CLIENT_TOKEN:
        headers["Client-Token"] = ZAPI_CLIENT_TOKEN
    return headers


def _is_retryable_zapi_error(exception) -> bool:
    """Repete apenas em erros transitórios (rate limit / indisponibilidade)."""
    err_str = str(exception)
    return any(code in err_str for code in ["429", "500", "502", "503", "504"])


def prepare_whatsapp_button_url(raw_link: str | None) -> str | None:
    """
    Prepara links de WhatsApp vindos do banco para uso em botoes URL da Z-API.

    A coluna `whatsapp_link` ja traz a mensagem pronta no parametro `text`.
    Aqui nos apenas normalizamos o encoding para evitar texto visivel como
    `%20`, `%2C` ou `%3F` quando o botao abre o WhatsApp.
    """
    if not raw_link or not isinstance(raw_link, str):
        return None

    raw_link = raw_link.strip()
    if not raw_link:
        return None

    parsed = urlparse(raw_link)
    host = (parsed.netloc or "").lower()
    if parsed.scheme not in {"http", "https"}:
        return None

    query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))

    phone = None
    if host in {"wa.me", "www.wa.me"}:
        phone = parsed.path.strip("/")
    elif host in {"api.whatsapp.com", "www.api.whatsapp.com", "web.whatsapp.com"}:
        if parsed.path.rstrip("/") != "/send":
            return None
        phone = query_params.get("phone")
    else:
        return None

    phone = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not phone:
        return None

    text = query_params.get("text")
    if text is None:
        return raw_link

    encoded_text = quote(text, safe="")
    return f"https://api.whatsapp.com/send?phone={phone}&text={encoded_text}"


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

    print(f"[Z-API] Tentando enviar mensagem para {clean_phone}...")

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
    Envia uma mensagem contendo botões de resposta simples via Z-API.
    Nota: Para botões com links (URL), use send_zapi_button_actions.
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
        "buttonList": {
            "buttons": button_list
        }
    }

    print(f"[Z-API] Tentando enviar botões simples para {clean_phone}. Quantidade: {len(button_list)}")

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

def send_zapi_button_actions(phone, message, button_actions):
    """
    Envia uma mensagem contendo botões de ação (URL, Call, Reply) via Z-API.
    
    :param phone: Número de destino
    :param message: Texto da mensagem principal
    :param button_actions: Lista de dicionários representando as ações (ex: [{"type": "URL", "label": "Site", "url": "https://..." }])
    """
    clean_phone = phone
    
    if not ZAPI_INSTANCE_ID or not ZAPI_TOKEN:
        print("[Z-API] Erro: ZAPI_INSTANCE_ID ou ZAPI_TOKEN não configurados.")
        return None

    url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-button-actions"
    
    headers = {
        "Content-Type": "application/json"
    }
    if ZAPI_CLIENT_TOKEN:
        headers["Client-Token"] = ZAPI_CLIENT_TOKEN

    payload = {
        "phone": clean_phone,
        "message": message,
        "buttonActions": button_actions
    }

    print(f"[Z-API] Tentando enviar botões de ação para {clean_phone}. Quantidade: {len(button_actions)}")

    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            print(f"[Z-API] Erro {response.status_code}: {response.text}")
        response.raise_for_status()
        res_data = response.json()
        print(f"[Z-API] Mensagem com ações enviada com sucesso para {phone}. ID: {res_data.get('messageId')}")
        return res_data
    except Exception as e:
        print(f"[Z-API] Erro ao enviar botões de ação: {e}")
        return None


# ---------------------------------------------------------------------------
# Leitura: listagem de chats/grupos e metadados de participantes
# Usado por fluxos de automação (ex.: backup quinzenal de membros de grupos).
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=3, max=30),
    retry=retry_if_exception(_is_retryable_zapi_error),
    reraise=True,
)
def list_chats(page: int = 1, page_size: int = 100) -> list[dict]:
    """
    Lista chats (grupos e contatos) via Z-API, de forma paginada.
    GET /chats?page=N&pageSize=M
    Retorna a lista de chats da página (vazia quando não há mais resultados).
    """
    base = _zapi_base_url()
    if not base:
        return []

    url = f"{base}/chats"
    params = {"page": page, "pageSize": page_size}

    response = requests.get(url, headers=_zapi_headers(), params=params)
    if response.status_code != 200:
        print(f"[Z-API] Erro {response.status_code} ao listar chats (página {page}): {response.text}")
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


def list_all_groups(page_size: int = 100, sleep_between_pages: float = 0.3) -> list[dict]:
    """
    Pagina /chats até esgotar e devolve apenas os chats que são grupos
    (campo isGroup == True). Cada item traz pelo menos: phone, name, isGroup.
    """
    grupos: list[dict] = []
    seen_phones: set[str] = set()
    page = 1
    while True:
        chats = list_chats(page=page, page_size=page_size)
        if not chats:
            break
        for c in chats:
            if c.get("isGroup"):
                phone = str(c.get("phone", "")).strip()
                if phone and phone not in seen_phones:
                    seen_phones.add(phone)
                    grupos.append(c)
        if len(chats) < page_size:
            break  # última página
        page += 1
        time.sleep(sleep_between_pages)  # respeita rate limit

    print(f"[Z-API] {len(grupos)} grupos encontrados (únicos).")
    return grupos


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=3, max=30),
    retry=retry_if_exception(_is_retryable_zapi_error),
    reraise=True,
)
def get_group_metadata(group_phone: str) -> dict | None:
    """
    Busca metadados de um grupo (nome + participantes) via Z-API.
    GET /group-metadata/{group_phone}

    Retorna dict com, entre outros: subject, phone, owner, description,
    e participants[] (cada um com phone, name, short, isAdmin, isSuperAdmin).
    Retorna None em caso de credencial ausente ou resposta inesperada.
    """
    base = _zapi_base_url()
    if not base:
        return None

    url = f"{base}/group-metadata/{group_phone}"

    response = requests.get(url, headers=_zapi_headers())
    if response.status_code != 200:
        print(f"[Z-API] Erro {response.status_code} ao buscar metadata do grupo {group_phone}: {response.text}")
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, dict) else None
