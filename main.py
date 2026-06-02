from fastapi import FastAPI, Request, BackgroundTasks
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from execution.process_message import process_whatsapp_message_e2e
from execution.private_chat import handle_private_message
from execution.daily_report import send_daily_report
import uvicorn
import os

# --- Scheduler: Relatório diário às 10h (Brasília, UTC-3) ---
scheduler = BackgroundScheduler()
scheduler.add_job(
    send_daily_report,
    trigger=CronTrigger(hour=10, minute=0, timezone="America/Sao_Paulo"),
    id="daily_telemetry_report",
    replace_existing=True
)

@asynccontextmanager
async def lifespan(app):
    scheduler.start()
    print("[SCHEDULER] Relatório diário agendado para 10:00 (Brasília).")
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
