from fastapi import FastAPI, Request, BackgroundTasks
from execution.process_message import process_whatsapp_message_e2e
import uvicorn
import os

app = FastAPI(title="MAIA WhatsApp Webhook")

@app.get("/")
def health_check():
    return {"status": "MAIA is online", "version": "1.0.0"}

@app.post("/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint para receber mensagens da Z-API via n8n.
    """
    data = await request.json()
    
    # Extração baseada na estrutura da Z-API enviada pelo n8n
    body = data.get("body", {})
    
    message_text = body.get("text", {}).get("message", "")
    is_from_me = body.get("fromMe", False)
    phone = body.get("phone", "") # ID do Chat (Grupo ou Private)
    participant_phone = body.get("participantPhone", "") # Quem enviou (em grupos)
    sender_name = body.get("senderName", "Usuária")
    
    # Lógica de Direcionamento: 
    # REGRAS DO USUÁRIO:
    # 1. Ignorar se não for texto (já verificado via if not message_text)
    # 2. Resposta fixada no número de teste: 5585991864177 (temporário)
    target_private_phone = "5585991864177"
    
    if not message_text:
        print("[WEBHOOK] Mensagem recebida sem conteúdo de texto. Ignorando.")
        return {"status": "ignored", "reason": "No text content"}

    # Processamento em background
    background_tasks.add_task(
        process_whatsapp_message_e2e, 
        message_text, 
        is_from_me=is_from_me,
        chat_id=phone, # ID de onde veio (para log de grupo)
        sender_name=sender_name,
        target_phone=target_private_phone # Para onde a resposta deve ir (fixado para teste)
    )
    
    return {
        "status": "received", 
        "info": "A MAIA enviará a resposta diretamente via Z-API em alguns instantes."
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
