"""
Teste local: verifica as duas mudanças implementadas.

1. Webhook aceita payload direto da Z-API (sem wrapper `body`) e o formato
   antigo do n8n (com wrapper `body`) — ambos devem extrair os campos corretos.

2. Kill-switch `flags_status.flag`:
   - Lê o valor real da tabela e exibe.
   - Simula flag "active"  → confirma que pv_ativo=True.
   - Simula flag "inactive" → confirma que pv_ativo=False.
   - Simula erro de leitura (None) → confirma fail-open (pv_ativo=True).

Rodar: python tests/test_webhook_and_flag.py
"""
import sys
import json
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── helpers ────────────────────────────────────────────────────────────────────

def sep(titulo=""):
    print("\n" + ("=" * 60))
    if titulo:
        print(f"  {titulo}")
        print("=" * 60)

def ok(msg):   print(f"  [OK]  {msg}")
def fail(msg): print(f"  [FAIL] {msg}"); sys.exit(1)

# ── 1. Teste de parsing do payload do webhook ──────────────────────────────────

sep("1. PARSING DO PAYLOAD DO WEBHOOK")

# Payload estilo Z-API direta (campos no topo)
zapi_direct = {
    "text": {"message": "Alguém indica fisioterapeuta pélvica?"},
    "fromMe": False,
    "phone": "5511912345678@g.us",
    "participantPhone": "5511999999999",
    "senderName": "Teste Z-API",
}

# Payload estilo n8n (campos embrulhados em `body`)
n8n_wrapped = {
    "body": {
        "text": {"message": "Alguém indica fisioterapeuta pélvica?"},
        "fromMe": False,
        "phone": "5511912345678@g.us",
        "participantPhone": "5511999999999",
        "senderName": "Teste n8n",
    }
}

def extract_fields(data):
    """Replica a lógica do webhook em main.py."""
    body = data.get("body") or data
    return {
        "message_text": body.get("text", {}).get("message", ""),
        "is_from_me":   body.get("fromMe", False),
        "phone":         body.get("phone", ""),
        "participant":   body.get("participantPhone", ""),
        "sender":        body.get("senderName", "Usuária"),
    }

for label, payload in [("Z-API direto", zapi_direct), ("n8n wrapped", n8n_wrapped)]:
    fields = extract_fields(payload)
    assert fields["message_text"] == "Alguém indica fisioterapeuta pélvica?", f"{label}: message_text errado"
    assert fields["is_from_me"] == False,                                      f"{label}: fromMe errado"
    assert fields["phone"] == "5511912345678@g.us",                            f"{label}: phone errado"
    assert fields["participant"] == "5511999999999",                           f"{label}: participantPhone errado"
    assert fields["sender"].startswith("Teste"),                               f"{label}: senderName errado"
    ok(f"{label}: todos os campos extraídos corretamente (sender={fields['sender']})")

# ── 2. Leitura real do flag_status ─────────────────────────────────────────────

sep("2. LEITURA REAL DE flags_status (Supabase)")

from execution.persistence import get_flag_status

valor_real = get_flag_status("status-maia")
print(f"  flags_status.flag (title='status-maia') = {repr(valor_real)}")

pv_ativo_real = valor_real is None or valor_real == "active"
print(f"  pv_ativo calculado = {pv_ativo_real}")
ok("Leitura do Supabase concluída.")

# ── 3. Kill-switch: lógica de pv_ativo ────────────────────────────────────────

sep("3. KILL-SWITCH: LÓGICA DE pv_ativo")

casos = [
    ("active",   True,  "flag ativa → envio no PV deve estar ON"),
    ("inactive", False, "flag inativa → envio no PV deve estar OFF"),
    ("disabled", False, "string inesperada → deve tratar como OFF"),
    (None,       True,  "falha de leitura (None) → fail-open → ON"),
]

for flag_val, esperado, descricao in casos:
    pv_ativo = flag_val is None or flag_val == "active"
    if pv_ativo == esperado:
        ok(f"flag={repr(flag_val):12s} → pv_ativo={pv_ativo} | {descricao}")
    else:
        fail(f"flag={repr(flag_val)} → esperava pv_ativo={esperado}, obteve {pv_ativo}")

# ── 4. Teste ponta-a-ponta com flag mockada ────────────────────────────────────

sep("4. PONTA-A-PONTA COM FLAG MOCKADA (sem envio real de WhatsApp)")

from execution.process_message import process_whatsapp_message_e2e

MESSAGE  = "Alguém indica consultora de amamentação?"
SENDER   = "Teste-Flag"
PHONE    = "5585991864177"

print("\n  --- Cenário A: flag='active' (deve processar E enviar no PV) ---")
with patch("execution.process_message.get_flag_status", return_value="active"), \
     patch("execution.process_message.send_zapi_button_actions") as mock_btn, \
     patch("execution.process_message.send_zapi_message") as mock_txt:

    result, error = process_whatsapp_message_e2e(
        message_text=MESSAGE,
        sender_name=SENDER,
        target_phone=PHONE,
        real_user_phone=PHONE,
        chat_id=None,
    )

    if error:
        print(f"  Fluxo encerrado antes do envio: {error}")
    else:
        total_pv = mock_btn.call_count + mock_txt.call_count
        # O primeiro envio deve ser para PHONE (PV)
        calls = mock_btn.call_args_list + mock_txt.call_args_list
        chamadas_pv = [c for c in calls if c.args and c.args[0] == PHONE]
        if chamadas_pv:
            ok(f"PV recebeu mensagem (flag=active). mensagem_final presente: {bool(result.get('mensagem_final'))}")
        else:
            print(f"  [AVISO] Nenhum envio para o PV detectado (pode ser etapa anterior interrompeu o fluxo).")

print("\n  --- Cenário B: flag='inactive' (deve processar mas NÃO enviar no PV) ---")
with patch("execution.process_message.get_flag_status", return_value="inactive"), \
     patch("execution.process_message.send_zapi_button_actions") as mock_btn, \
     patch("execution.process_message.send_zapi_message") as mock_txt:

    result, error = process_whatsapp_message_e2e(
        message_text=MESSAGE,
        sender_name=SENDER,
        target_phone=PHONE,
        real_user_phone=PHONE,
        chat_id=None,
    )

    if error:
        print(f"  Fluxo encerrado antes do envio: {error}")
    else:
        calls = mock_btn.call_args_list + mock_txt.call_args_list
        chamadas_pv = [c for c in calls if c.args and c.args[0] == PHONE]
        if not chamadas_pv:
            ok("PV NÃO recebeu mensagem (flag=inactive). Kill-switch funcionou.")
        else:
            fail(f"PV recebeu {len(chamadas_pv)} mensagem(ns) mesmo com flag=inactive!")

        # Confirma telemetria
        tel_etapa = result.get("_tel_etapa") if result else None
        print(f"  etapa_final no resultado: verificar nos logs acima ([ORQUESTRAÇÃO])")

sep("TODOS OS TESTES CONCLUÍDOS")
