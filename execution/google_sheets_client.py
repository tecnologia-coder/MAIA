"""
Cliente Google Sheets/Drive via OAuth de usuário (token.json).

Usado por fluxos de automação que precisam gerar planilhas (ex.: backup
quinzenal de membros de grupos). As planilhas nascem no Drive do próprio
usuário que autorizou (não numa service account).

Por que OAuth e não service account? A organização Google bloqueia a criação
de chaves JSON de service account (política iam.disableServiceAccountKeyCreation).
OAuth de usuário contorna isso e é viável aqui porque o deploy é um servidor
persistente: autoriza-se UMA vez (gera token.json com refresh token) e o token
é renovado automaticamente nas execuções seguintes.

Pré-requisitos (ver directives/backup_grupos_directive.md):
- Sheets API + Drive API habilitadas no projeto Google Cloud.
- Cliente OAuth do tipo "App para computador" criado; JSON baixado como
  GOOGLE_OAUTH_CLIENT_FILE (default: credentials.json).
- Tela de consentimento com escopos de Sheets/Drive. Para token de longa
  duração sem reautenticar, use User Type "Interno" (org) OU app publicado.
- 1ª execução gera GOOGLE_OAUTH_TOKEN_FILE (default: token.json) via navegador.
- Pasta de destino: GDRIVE_BACKUP_FOLDER_ID no Drive do usuário autorizado.
"""
import os
import re
import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv

load_dotenv()

# Sheets para ler/escrever células; Drive para criar arquivos dentro de pastas.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Segredo do cliente OAuth (baixado do Google Cloud) e token do usuário (gerado na 1ª auth).
GOOGLE_OAUTH_CLIENT_FILE = os.getenv("GOOGLE_OAUTH_CLIENT_FILE", "credentials.json")
GOOGLE_OAUTH_TOKEN_FILE = os.getenv("GOOGLE_OAUTH_TOKEN_FILE", "token.json")

# Limites do Google Sheets para nomes de aba.
_MAX_TAB_LEN = 100
_INVALID_TAB_CHARS = re.compile(r"[\[\]:\*\?/\\]")

_gc = None  # singleton de processo


def _load_oauth_credentials() -> Credentials:
    """
    Carrega as credenciais OAuth do usuário:
    1. Se token.json existe e é válido, usa direto.
    2. Se expirou mas tem refresh_token, renova silenciosamente (sem navegador).
    3. Caso contrário, dispara o fluxo interativo (abre o navegador) usando o
       credentials.json e salva o token.json resultante.
    Em servidor headless, rode o passo 3 UMA vez numa máquina com navegador e
    suba o token.json gerado.
    """
    creds = None
    if os.path.exists(GOOGLE_OAUTH_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(GOOGLE_OAUTH_TOKEN_FILE, SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _salvar_token(creds)
        return creds

    if not os.path.exists(GOOGLE_OAUTH_CLIENT_FILE):
        raise FileNotFoundError(
            f"Credenciais OAuth não encontradas: '{GOOGLE_OAUTH_CLIENT_FILE}'. "
            "Baixe o JSON do cliente OAuth (App para computador) e configure "
            "GOOGLE_OAUTH_CLIENT_FILE no .env."
        )

    flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_OAUTH_CLIENT_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    _salvar_token(creds)
    return creds


def _salvar_token(creds: Credentials) -> None:
    with open(GOOGLE_OAUTH_TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())


def get_gspread_client() -> gspread.Client:
    """Autentica via OAuth de usuário e retorna um cliente gspread (cacheado)."""
    global _gc
    if _gc is not None:
        return _gc

    creds = _load_oauth_credentials()
    _gc = gspread.authorize(creds)
    return _gc


def create_backup_spreadsheet(title: str, folder_id: str | None = None):
    """
    Cria uma nova planilha. Se folder_id for informado, cria-a dentro da pasta
    (a pasta precisa estar compartilhada com a service account).
    Retorna o objeto Spreadsheet do gspread.
    """
    gc = get_gspread_client()
    if folder_id:
        return gc.create(title, folder_id=folder_id)
    return gc.create(title)


def sanitize_tab_name(name: str, used_names: set[str] | None = None) -> str:
    """
    Adapta um nome de grupo para um nome de aba válido no Sheets:
    - remove caracteres inválidos ([]:*?/\\);
    - corta para no máximo 100 caracteres;
    - garante unicidade adicionando sufixo ' (2)', ' (3)'... quando necessário.
    """
    cleaned = _INVALID_TAB_CHARS.sub(" ", (name or "").strip()) or "Grupo sem nome"
    cleaned = cleaned[:_MAX_TAB_LEN].strip()

    if used_names is None:
        return cleaned

    candidate = cleaned
    counter = 2
    while candidate in used_names:
        suffix = f" ({counter})"
        candidate = (cleaned[: _MAX_TAB_LEN - len(suffix)]).strip() + suffix
        counter += 1
    used_names.add(candidate)
    return candidate


def ensure_worksheet(spreadsheet, name: str, rows: int, cols: int, index: int | None = None):
    """
    Cria (ou redimensiona) uma aba com pelo menos `rows` linhas e `cols` colunas.
    Garante que a planilha sempre tenha linhas suficientes para todos os membros.
    `index` (opcional) define a posição da aba na criação (0 = primeira aba).
    """
    rows = max(rows, 1)
    cols = max(cols, 1)
    try:
        ws = spreadsheet.worksheet(name)
        if ws.row_count < rows or ws.col_count < cols:
            ws.resize(rows=max(ws.row_count, rows), cols=max(ws.col_count, cols))
        return ws
    except gspread.WorksheetNotFound:
        if index is not None:
            return spreadsheet.add_worksheet(title=name, rows=rows, cols=cols, index=index)
        return spreadsheet.add_worksheet(title=name, rows=rows, cols=cols)


def write_rows(worksheet, header: list[str], rows: list[list]):
    """
    Escreve cabeçalho + linhas de uma vez (1 chamada de escrita), respeitando a
    quota da API do Sheets. Redimensiona a aba se faltarem linhas.
    """
    all_rows = [header] + rows
    needed = len(all_rows)
    if worksheet.row_count < needed:
        worksheet.resize(rows=needed, cols=max(worksheet.col_count, len(header)))
    worksheet.update(range_name="A1", values=all_rows)


def delete_default_sheet(spreadsheet):
    """
    Remove a aba padrão criada automaticamente quando há outras abas.
    Tenta nomes em inglês ('Sheet1') e português ('Página 1', 'Folha1').
    """
    for default_name in ("Página1", "Sheet1", "Folha1"):
        try:
            default = spreadsheet.worksheet(default_name)
            if len(spreadsheet.worksheets()) > 1:
                spreadsheet.del_worksheet(default)
            return
        except gspread.WorksheetNotFound:
            continue
