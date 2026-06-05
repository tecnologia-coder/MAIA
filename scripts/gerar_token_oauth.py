"""
Script de uso único: gera o token.json do OAuth Google.

Execute UMA VEZ na sua máquina (com navegador) para autorizar o acesso.
O token.json gerado pode então ser copiado para o servidor headless.

Uso:
    .venv/Scripts/python.exe .tmp/gerar_token_oauth.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from google_auth_oauthlib.flow import InstalledAppFlow
from execution.google_sheets_client import (
    GOOGLE_OAUTH_CLIENT_FILE,
    GOOGLE_OAUTH_TOKEN_FILE,
    SCOPES,
    _salvar_token,
)

if os.path.exists(GOOGLE_OAUTH_TOKEN_FILE):
    print(f"[AUTH] token.json já existe em '{GOOGLE_OAUTH_TOKEN_FILE}'. Delete-o se quiser reautorizar.")
    sys.exit(0)

if not os.path.exists(GOOGLE_OAUTH_CLIENT_FILE):
    print(f"[AUTH] ERRO: '{GOOGLE_OAUTH_CLIENT_FILE}' não encontrado. Baixe o JSON do cliente OAuth.")
    sys.exit(1)

print("[AUTH] Abrindo navegador para autorização Google...")
print("[AUTH] Após fazer login e aceitar as permissões, aguarde a mensagem de sucesso abaixo.")
print("[AUTH] NÃO feche o terminal enquanto o processo estiver rodando.\n")

flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_OAUTH_CLIENT_FILE, SCOPES)
creds = flow.run_local_server(port=0)
_salvar_token(creds)

print(f"\n[AUTH] token.json gerado com sucesso em '{GOOGLE_OAUTH_TOKEN_FILE}'.")
print("[AUTH] Você pode fechar este terminal agora.")
