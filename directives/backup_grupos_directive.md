# Diretiva: Backup Quinzenal de Membros de Grupos (Google Sheets)

## Objetivo
Preservar a base de contatos dos grupos de WhatsApp em que a MAIA participa.
A cada 15 dias, gerar uma planilha do Google Sheets contendo todos os membros
**não-admins** de cada grupo, com uma aba (página) por grupo.

## Periodicidade
- Agendado via APScheduler no `main.py` (a partir do registry de fluxos).
- Trigger atual: `CronTrigger(day="1,16", hour=3)` (timezone America/Sao_Paulo) —
  quinzenal, determinístico e à prova de restart do servidor.
- Alternativa literal "a cada 15 dias": `IntervalTrigger(days=15)`, porém reinicia
  a contagem a cada restart (não há jobstore persistente). Para 15 dias exatos e
  robusto a restart, seria necessário jobstore persistente ou checagem de
  "última execução" numa tabela `automation_runs`.

### Requisito de hospedagem (importante)
- O `BackgroundScheduler` é **in-process**: só dispara enquanto o `uvicorn`
  estiver vivo. Logo, o backup automático **exige host de processo contínuo**
  (Railway / VPS / Render pago). Em **serverless (Vercel) o cron NÃO dispara** —
  ali seria preciso um endpoint HTTP de cron chamando `run_flow("backup_grupos")`.
- **Render free dorme** após ~15 min sem tráfego → se estiver dormindo às 3h, o
  backup não roda. Usar instância que não dorme.
- Rodar com **1 worker** (Procfile atual não passa `--workers`, default=1). Com
  múltiplos workers, cada um agendaria o job → backups duplicados.

### Restart-safety: misfire e coalesce (aprendizado 2026-06)
- O disparo default do APScheduler tem `misfire_grace_time=1s`: se o servidor
  estava **reiniciando exatamente na hora do cron** (deploy/restart), o job é
  **pulado silenciosamente** e o backup quinzenal se perde.
- Correção aplicada em `_agendar_fluxos()` (`main.py`): `misfire_grace_time=3600`
  (ainda dispara se o scheduler subir dentro de 1h da hora agendada) + `coalesce=True`
  (colapsa execuções perdidas acumuladas em UMA só, evitando backup duplo).
- Cobre o caso realista (restart curto perto das 3h). **Downtime do host pela
  janela inteira** ainda perde o disparo — para isso só jobstore persistente ou
  tabela de "última execução".

## Entradas (Z-API)
1. `list_all_groups()` → pagina `GET /chats` e filtra `isGroup == true`.
   Cada grupo traz: `phone` (id do grupo), `name`.
2. `get_group_metadata(group_phone)` → `GET /group-metadata/{phone}`. Retorna:
   - Grupo: `subject` (nome), `phone`, `owner`, `description`, `creation`.
   - `participants[]`: cada um com `phone`, `name`, `short`, `isAdmin`, `isSuperAdmin`.

> Tudo que precisamos vem dessas 2 chamadas (1 por grupo) — sem request por membro.

## Saídas (estrutura da planilha)
- **1 planilha nova por backup**, criada na pasta `GDRIVE_BACKUP_FOLDER_ID` do Drive.
- **Título**: `Backup Grupos MAIA — AAAA-MM-DD` (data do backup).
- **1 aba por grupo**, nome = `subject` do grupo (sanitizado: ≤100 chars, sem
  `[]:*?/\\`, com sufixo ` (2)` para nomes duplicados).
- **Colunas** (cabeçalho na linha 1):

  | telefone | nome | nome_curto | link_whatsapp | grupo | id_grupo | data_backup |
  |---|---|---|---|---|---|---|

  - `telefone` = participant.phone · `nome` = participant.name · `nome_curto` = participant.short
  - `link_whatsapp` = `https://wa.me/{telefone}` (derivado)
  - `grupo` = subject · `id_grupo` = phone do grupo · `data_backup` = data ISO
- **Admins e superadmins são excluídos** das linhas.
- A aba é redimensionada para ter linhas suficientes para todos os membros.
- A aba padrão `Sheet1` é removida ao final.

### Aba "Contatos Únicos" (primeira aba)
- Consolida **todos os contatos da comunidade** sem repetição (dedup por telefone).
- **1 linha por número**, mesmo que ele participe de vários grupos.
- **Colunas**:

  | telefone | nome | nome_curto | link_whatsapp | grupos | total_grupos | data_backup |
  |---|---|---|---|---|---|---|

  - `grupos` = nomes de todos os grupos do contato, separados por vírgula numa célula.
  - `total_grupos` = quantos grupos aquele contato participa.
  - `nome`/`nome_curto` preenchidos a partir de qualquer grupo que tenha o dado.
- Construída em memória durante o mesmo loop (sem chamadas Z-API extras).
- Criada com `index=0` para ser a **primeira aba**.
- O **total geral de contatos únicos** vai no resumo enviado ao grupo de logs.

## Ferramentas/Execução
- Fluxo: `execution/flows/backup_grupos.py` (`BackupGruposFlow`, `name="backup_grupos"`).
- Z-API (leitura): `execution/zapi_client.py` → `list_all_groups`, `get_group_metadata`.
- Google Sheets: `execution/google_sheets_client.py` → `create_backup_spreadsheet`,
  `ensure_worksheet`, `write_rows`, `sanitize_tab_name`, `delete_default_sheet`.
- Execução manual:
  `python -c "from execution.flows.registry import run_flow; print(run_flow('backup_grupos'))"`

## Configuração necessária
> Autenticação via **OAuth de usuário** (a organização bloqueia chaves de service
> account). As planilhas nascem no Drive do usuário que autorizou.

1. Google Cloud: habilitar **Google Sheets API** e **Google Drive API**.
2. **Tela de consentimento OAuth**: configurar com os escopos de Sheets/Drive.
   - ⚠️ Para token de **longa duração** (não reautenticar a cada 7 dias): usar
     User Type **"Interno"** (se o projeto está numa organização Workspace) **ou**
     publicar o app ("Em produção"). User Type "Externo" + status "Testing" expira
     o refresh token em 7 dias — quebraria o backup quinzenal.
3. Criar **Cliente OAuth** do tipo **"App para computador"** e baixar o JSON como
   `credentials.json` (`GOOGLE_OAUTH_CLIENT_FILE`).
4. Criar a pasta no **Drive do próprio usuário** e copiar o folder ID para
   `GDRIVE_BACKUP_FOLDER_ID` (não precisa compartilhar com ninguém).
5. **1ª autorização** (numa máquina com navegador): rodar o fluxo uma vez para
   gerar `token.json`; subir esse `token.json` para o servidor.
6. `.env`:
   - `GOOGLE_OAUTH_CLIENT_FILE=credentials.json`
   - `GOOGLE_OAUTH_TOKEN_FILE=token.json`
   - `GDRIVE_BACKUP_FOLDER_ID=<id da pasta>`
   - (opcional) `FLOW_BACKUP_GRUPOS_ENABLED=true` · `BACKUP_GRUPOS_DAYS=1,16` ·
     `BACKUP_GRUPOS_HOUR=3` · `BACKUP_GRUPOS_SLEEP=0.5`
7. `requirements.txt`: `gspread`, `google-auth`, `google-auth-oauthlib`.

## Edge cases
- **Grupo só com admins** → aba criada apenas com o cabeçalho.
- **Nome de grupo duplicado/ inválido** → sanitização + sufixo numérico.
- **Falha em um grupo** → registrada em `details.erros`; não interrompe os demais.
- **Rate limit (Z-API/Sheets)** → retry com `tenacity` + `time.sleep` entre grupos.
- **Sem grupos / pasta não configurada** → `FlowResult(success=False, ...)`.
- **Grupos duplicados na API** → `list_all_groups` deduplica por `phone` (Z-API às vezes devolve o mesmo grupo em páginas diferentes).
- **Aba padrão em português** → `delete_default_sheet` tenta "Sheet1", "Página 1" e "Folha1".
- **nome/nome_curto vazios** → comportamento esperado da Z-API: esses campos só contêm dados para participantes salvos como contato na agenda do dispositivo onde a Maia está conectada.
- **Número da Maia na planilha** → filtrado via `MAIA_PHONE_NUMBER` no `.env`.
- **Contato em vários grupos** → consolidado na aba "Contatos Únicos" (dedup por telefone, grupos concatenados).
- Ao final, envia resumo (e amostra de falhas) ao grupo de logs via `send_zapi_message`.

## Como adicionar novos fluxos (framework)
- Criar uma classe que herda de `execution/flows/base.py::Flow`, definir `name`,
  `description`, opcionalmente `schedule` (trigger APScheduler) e implementar `run()`.
- Decorar com `@register` (de `execution/flows/registry.py`) e importar o módulo em
  `registry._import_flows()`.
- Fluxos periódicos (com `schedule`) são agendados automaticamente no startup do
  `main.py`. Fluxos sem `schedule` rodam por gatilho via `run_flow("nome", context)`.
