"""
Teste local: fluxo completo MAIA — triagem → busca Supabase → agente LLM → mensagem → botões Z-API.
Simula recebimento de mensagem privada válida e executa process_whatsapp_message_e2e().
Destino fixo: TARGET_PHONE.

Rodar: python test_buttons_local.py
"""
import sys
import json

# Forca UTF-8 no stdout para evitar UnicodeEncodeError no terminal Windows (cp1252)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from execution.process_message import process_whatsapp_message_e2e

MESSAGE_TEXT = "Alguém indica profissionais que fazem laserterapia nas mamas pra amamentação?"
SENDER_NAME  = "Vanderley"
TARGET_PHONE = "5585991864177"


def main():
    print("=" * 55)
    print("  TESTE LOCAL: FLUXO COMPLETO MAIA (sem atalhos)")
    print("=" * 55)
    print(f"\nMensagem : {MESSAGE_TEXT}")
    print(f"Remetente: {SENDER_NAME}")
    print(f"Destino  : {TARGET_PHONE}")
    print("-" * 55)

    result, error = process_whatsapp_message_e2e(
        message_text=MESSAGE_TEXT,
        sender_name=SENDER_NAME,
        target_phone=TARGET_PHONE,
        real_user_phone=TARGET_PHONE,
        chat_id=None,
    )

    print("\n" + "=" * 55)
    if error:
        print(f"[ENCERRADO] {error}")
    elif result:
        print("RESPOSTA ENVIADA:")
        print("-" * 55)
        print(result.get("mensagem_final") or json.dumps(result, ensure_ascii=False, indent=2))
    print("=" * 55)


if __name__ == "__main__":
    main()
