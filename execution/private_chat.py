"""
Chatbot de Atendimento Privado da MAIA
Redireciona mensagens privadas para o departamento correto.

Configuração via variáveis de ambiente no .env:
  DEPT_COMERCIAL_PHONE       — telefone do comercial (só números)
  DEPT_SITE_URL              — URL do site
  DEPT_RELACIONAMENTO_PHONE  — telefone do relacionamento
  DEPT_SAC_PHONE             — telefone do SAC
"""

import os
from dotenv import load_dotenv
from execution.zapi_client import send_zapi_message, send_zapi_button_actions

load_dotenv()

# ---------------------------------------------------------------------------
# Contatos dos departamentos (configurar via .env)
# ---------------------------------------------------------------------------
COMERCIAL_PHONE      = os.getenv("DEPT_COMERCIAL_PHONE", "5544998484451")
SITE_URL             = os.getenv("DEPT_SITE_URL", "https://www.amaeindica.com.br")
RELACIONAMENTO_PHONE = os.getenv("DEPT_RELACIONAMENTO_PHONE", "5541988125325")
SAC_PHONE            = os.getenv("DEPT_SAC_PHONE", "5544999566341")

# ---------------------------------------------------------------------------
# Texto do menu principal
# ---------------------------------------------------------------------------
MENU_TEXT = (
    "Oi{name}! Que bom ter você aqui 💛\n\n"
    "Sou a *MAIA*, assistente virtual da *A Mãe Indica*.\n\n"
    "Me conta: como posso te ajudar hoje?\n\n"
    "*1.* 💼 *Comercial* — Parcerias e anúncios\n"
    "*2.* 🌐 *Site* — Conheça nossa plataforma\n"
    "*3.* 💛 *Relacionamento* — Comunidade e membros\n"
    "*4.* 🛠️ *SAC* — Suporte e dúvidas gerais\n\n"
    "_É só responder com o número da opção — ou me contar com suas palavras mesmo, eu entendo!_ 😊"
)

# ---------------------------------------------------------------------------
# Mensagem de fallback (quando MAIA não reconhece a mensagem)
# ---------------------------------------------------------------------------
FALLBACK_TEXT = (
    "Hmm, acho que não entendi direito! 😅\n\n"
    "Me responde com o *número da opção* que faz mais sentido pra você:\n\n"
    "*1.* 💼 Comercial · *2.* 🌐 Site · *3.* 💛 Relacionamento · *4.* 🛠️ SAC"
)

# ---------------------------------------------------------------------------
# Mapeamento de palavras-chave → departamento
# ---------------------------------------------------------------------------
KEYWORD_MAP: dict[str, str] = {
    # Comercial
    "1": "comercial",
    "comercial": "comercial",
    "parceria": "comercial",
    "parcerias": "comercial",
    "anuncio": "comercial",
    "anúncio": "comercial",
    "anuncios": "comercial",
    "anúncios": "comercial",
    "negocio": "comercial",
    "negócio": "comercial",
    # Site
    "2": "site",
    "site": "site",
    "plataforma": "site",
    "como funciona": "site",
    # Relacionamento
    "3": "relacionamento",
    "relacionamento": "relacionamento",
    "comunidade": "relacionamento",
    "membro": "relacionamento",
    "membros": "relacionamento",
    # SAC
    "4": "sac",
    "sac": "sac",
    "suporte": "sac",
    "dúvida": "sac",
    "duvida": "sac",
    "dúvidas": "sac",
    "duvidas": "sac",
    "ajuda": "sac",
    "problema": "sac",
    "reclamação": "sac",
    "reclamacao": "sac",
}

# ---------------------------------------------------------------------------
# Informações de cada departamento
# ---------------------------------------------------------------------------
def _build_dept_info() -> dict:
    """Constrói o dict de departamentos respeitando as env vars atuais."""
    return {
        "comercial": {
            "msg": (
                "Ótimo! Vou te conectar com nossa equipe *Comercial* 💼\n\n"
                "Eles cuidam de parcerias, anúncios e oportunidades de negócio "
                "dentro da A.M.I. É só clicar abaixo — eles adoram uma boa conversa. 😉"
            ),
            "button_label": "Falar com Comercial",
            "url": f"https://wa.me/{COMERCIAL_PHONE}" if COMERCIAL_PHONE else None,
        },
        "site": {
            "msg": (
                "Vem conhecer a *A Mãe Indica* de pertinho! 🌐\n\n"
                "No nosso site você entende como a plataforma funciona e como se "
                "tornar parceira da nossa comunidade. Vale muito a visita! ✨"
            ),
            "button_label": "Acessar o Site",
            "url": SITE_URL or None,
        },
        "relacionamento": {
            "msg": (
                "Que bom! Vou te conectar com nossa equipe de *Relacionamento* 💛\n\n"
                "São elas que cuidam da nossa comunidade com todo o carinho — "
                "e vão adorar te receber e ajudar no que precisar."
            ),
            "button_label": "Falar com Relacionamento",
            "url": f"https://wa.me/{RELACIONAMENTO_PHONE}" if RELACIONAMENTO_PHONE else None,
        },
        "sac": {
            "msg": (
                "Sem problema! Nossa equipe de *Suporte* está aqui pra isso. 🛠️\n\n"
                "Clica no botão abaixo e a gente resolve junto — sem burocracia, prometo. 😊"
            ),
            "button_label": "Falar com SAC",
            "url": f"https://wa.me/{SAC_PHONE}" if SAC_PHONE else None,
        },
    }


# ---------------------------------------------------------------------------
# Controle de estado: rastreia se o menu já foi exibido para o usuário
# (em memória — para persistência, substituir por Redis ou banco de dados)
# ---------------------------------------------------------------------------
_menu_shown: set[str] = set()


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------
def handle_private_message(
    phone: str,
    message_text: str,
    sender_name: str | None = None,
    is_from_me: bool = False,
) -> dict | None:
    """
    Processa mensagem privada recebida pela MAIA.

    Fluxo:
      1. Primeira mensagem → exibe menu de boas-vindas.
      2. Mensagem seguinte mapeia para departamento → redireciona.
      3. Mensagem não reconhecida (após menu) → exibe fallback.

    Returns:
        dict com status e departamento, ou None se mensagem própria.
    """
    if is_from_me:
        return None

    first_name = (sender_name or "").split()[0]
    name_part = f", {first_name}" if first_name else ""
    msg_lower = message_text.strip().lower()

    # Verificação primária: match exato
    dept_key = KEYWORD_MAP.get(msg_lower)

    # Verificação secundária: keyword contida na mensagem
    # (ex.: "quero falar com o sac")
    if not dept_key:
        for keyword, dept in KEYWORD_MAP.items():
            if len(keyword) > 1 and keyword in msg_lower:
                dept_key = dept
                break

    dept_info = _build_dept_info()

    if dept_key:
        # Departamento identificado — redireciona
        dept = dept_info[dept_key]
        _menu_shown.discard(phone)  # reseta estado após escolha
        print(f"[PRIVADO] '{sender_name}' → departamento: {dept_key}")

        if dept["url"]:
            send_zapi_button_actions(
                phone,
                dept["msg"],
                [{"type": "URL", "label": dept["button_label"], "url": dept["url"]}],
            )
        else:
            send_zapi_message(
                phone,
                dept["msg"] + "\n\n_(Estamos configurando esse contato. Tente novamente em breve!)_",
            )
        return {"status": "handled", "dept": dept_key}

    elif phone not in _menu_shown:
        # Primeira interação — exibe menu de boas-vindas
        print(f"[PRIVADO] Exibindo menu para '{sender_name}'")
        _menu_shown.add(phone)
        send_zapi_message(phone, MENU_TEXT.format(name=name_part))
        return {"status": "menu", "dept": None}

    else:
        # Já viu o menu, mas a mensagem não foi reconhecida — fallback
        print(f"[PRIVADO] Fallback para '{sender_name}' (msg: '{message_text}')")
        send_zapi_message(phone, FALLBACK_TEXT)
        return {"status": "fallback", "dept": None}
