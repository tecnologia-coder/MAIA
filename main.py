from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from execution.process_message import process_whatsapp_message_e2e
from execution.private_chat import handle_private_message
from execution.flows.registry import scheduled_flows, run_flow
from execution.sync_documents import move_cancelled_partner, remove_partner_documents, sync_partner
import uvicorn
import os

# Scheduler dos fluxos periódicos. Todos os jobs (inclusive o relatório diário)
# vêm do registry de fluxos — ver _agendar_fluxos().
scheduler = BackgroundScheduler()


def _agendar_fluxos():
    """
    Agenda todos os fluxos periódicos habilitados do registry.
    Novos fluxos passam a ser agendados só por existirem — sem editar este arquivo.
    """
    for flow in scheduled_flows():
        scheduler.add_job(
            run_flow,
            trigger=flow.schedule,
            args=[flow.name],
            id=f"flow_{flow.name}",
            replace_existing=True,
            # Restart-safety: se o servidor estava reiniciando na hora do cron,
            # ainda dispara desde que suba dentro de 1h da hora agendada.
            misfire_grace_time=3600,
            # Colapsa execuções perdidas acumuladas em UMA só (evita backup duplo).
            coalesce=True,
        )
        print(f"[SCHEDULER] Fluxo '{flow.name}' agendado.")


@asynccontextmanager
async def lifespan(app):
    _agendar_fluxos()
    scheduler.start()
    print("[SCHEDULER] Fluxos periódicos agendados.")
    yield
    scheduler.shutdown()

app = FastAPI(title="MAIA WhatsApp Webhook", lifespan=lifespan)

@app.get("/")
def health_check():
    return {"status": "MAIA is online", "version": "1.0.0"}

@app.post("/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint para receber mensagens diretamente da Z-API (webhook "Ao receber").
    Mantém compatibilidade com o formato antigo do n8n, que embrulhava o payload
    da Z-API dentro de uma chave `body`.
    """
    data = await request.json()

    # Z-API direta envia os campos no topo do JSON; o n8n os colocava em `body`.
    body = data.get("body") or data
    
    message_text = body.get("text", {}).get("message", "")
    is_from_me = body.get("fromMe", False)
    phone = body.get("phone", "")
    participant_phone = body.get("participantPhone", "")
    sender_name = body.get("senderName", "Usuária")
    # Lógica de Direcionamento:
    if not message_text:
        print("[WEBHOOK] Mensagem recebida sem conteúdo de texto. Ignorando.")
        return {"status": "ignored", "reason": "No text content"}

    if not participant_phone:
        # Mensagem privada — chatbot de redirecionamento
        print(f"[WEBHOOK] Mensagem privada de '{sender_name}' ({phone}). Acionando chatbot privado.")
        background_tasks.add_task(
            handle_private_message,
            phone=phone,
            message_text=message_text,
            sender_name=sender_name,
            is_from_me=is_from_me,
        )
        return {"status": "received", "info": "Mensagem privada encaminhada para o chatbot."}

    # Processamento em background
    background_tasks.add_task(
        process_whatsapp_message_e2e,
        message_text,
        is_from_me=is_from_me,
        chat_id=phone, # ID de onde veio (grupo de origem)
        sender_name=sender_name,
        target_phone=participant_phone, # Resposta vai para o privado de quem pediu
        real_user_phone=participant_phone # Para gestão de perfil
    )
    
    return {
        "status": "received", 
        "info": "A MAIA enviará a resposta diretamente via Z-API em alguns instantes."
    }

def _partner_id_from_payload(payload: dict):
    record = payload.get("record") or {}
    old_record = payload.get("old_record") or {}
    return record.get("id") or old_record.get("id")


def _handle_partner_webhook(payload: dict):
    event_type = (payload.get("type") or payload.get("eventType") or "").upper()
    record = payload.get("record") or {}
    old_record = payload.get("old_record") or {}
    partner_id = record.get("id") or old_record.get("id")

    if not partner_id:
        print("[PARTNER SYNC] Payload sem id de parceiro. Ignorando.")
        return

    if event_type == "DELETE":
        remove_partner_documents(partner_id)
        return

    status = record.get("status_aprovacao")
    if status == "cancelado":
        move_cancelled_partner(partner_id)
        return

    sync_partner(partner_id)


@app.post("/webhooks/supabase/parceiros")
async def supabase_partner_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Recebe Supabase Database Webhook da tabela `parceiros` e mantem
    `documents` consistente com `status_aprovacao`.
    """
    expected_secret = os.environ.get("SUPABASE_PARTNER_SYNC_SECRET")
    received_secret = request.headers.get("x-webhook-secret")

    if not expected_secret:
        raise HTTPException(status_code=503, detail="SUPABASE_PARTNER_SYNC_SECRET not configured")
    if received_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await request.json()
    partner_id = _partner_id_from_payload(payload)
    if not partner_id:
        raise HTTPException(status_code=400, detail="Payload missing partner id")

    background_tasks.add_task(_handle_partner_webhook, payload)
    return {"status": "received", "partner_id": partner_id}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
