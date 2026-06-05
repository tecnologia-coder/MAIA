"""
Fluxo: Backup quinzenal de membros de grupos em Google Sheets.

A cada execução cria UMA planilha nova (nome + data do backup) numa pasta
dedicada do Drive, com UMA aba por grupo que a MAIA participa. Cada aba lista
os membros NÃO-admins do grupo. Admins e superadmins são filtrados fora.

Camada 3 (execução): determinístico, comentado, com tratamento de erro por grupo
para que a falha em um grupo não derrube o backup dos demais.

Dados de cada membro (vêm em 1 única chamada /group-metadata por grupo):
- telefone, nome, nome_curto (short)
Mais colunas derivadas/contextuais: link_whatsapp, grupo, id_grupo, data_backup.
"""
from __future__ import annotations

import os
import time
from datetime import date

from apscheduler.triggers.cron import CronTrigger

from execution.flows.base import Flow, FlowResult
from execution.flows.registry import register
from execution.zapi_client import list_all_groups, get_group_metadata, send_zapi_message
from execution.google_sheets_client import (
    create_backup_spreadsheet,
    ensure_worksheet,
    write_rows,
    sanitize_tab_name,
    delete_default_sheet,
)

# Grupo de logs do sistema (mesmo usado pelo relatório diário).
GRUPO_SYSTEM_LOGS = "120363406702749765-group"

# Cabeçalho das abas. Ordem importa (casa com _membro_para_linha).
HEADER = ["telefone", "nome", "nome_curto", "link_whatsapp", "grupo", "id_grupo", "data_backup"]

# Cabeçalho da aba consolidada "Contatos Únicos". Ordem casa com _contato_unico_para_linha.
HEADER_UNICOS = ["telefone", "nome", "nome_curto", "link_whatsapp", "grupos", "total_grupos", "data_backup"]

# Nome da aba consolidada (primeira aba da planilha).
ABA_CONTATOS_UNICOS = "Contatos Únicos"

# Pausa entre grupos para não estourar rate limit (Z-API + Sheets API).
SLEEP_ENTRE_GRUPOS = float(os.getenv("BACKUP_GRUPOS_SLEEP", "0.5"))

# Número da própria instância da Maia (excluído de todas as abas).
# Formato esperado: apenas dígitos, ex.: 5511999999999
MAIA_PHONE = str(os.getenv("MAIA_PHONE_NUMBER", "")).strip()


def _is_admin(participant: dict) -> bool:
    return bool(participant.get("isAdmin")) or bool(participant.get("isSuperAdmin"))


def _membro_para_linha(p: dict, nome_grupo: str, id_grupo: str, data_backup: str) -> list:
    telefone = str(p.get("phone", "")).strip()
    link = f"https://wa.me/{telefone}" if telefone else ""
    return [
        telefone,
        p.get("name", "") or "",
        p.get("short", "") or "",
        link,
        nome_grupo,
        id_grupo,
        data_backup,
    ]


def _contato_unico_para_linha(telefone: str, info: dict, data_backup: str) -> list:
    link = f"https://wa.me/{telefone}" if telefone else ""
    grupos = info.get("grupos", [])
    return [
        telefone,
        info.get("nome", "") or "",
        info.get("short", "") or "",
        link,
        ", ".join(grupos),
        len(grupos),
        data_backup,
    ]


@register
class BackupGruposFlow(Flow):
    name = "backup_grupos"
    description = "Backup quinzenal dos membros (não-admins) de cada grupo em uma planilha do Google Sheets."

    # ~Quinzenal e restart-safe (dias 1 e 16). Veja a diretiva para a discussão
    # sobre IntervalTrigger(days=15) vs cron determinístico.
    schedule = CronTrigger(
        day=os.getenv("BACKUP_GRUPOS_DAYS", "1,16"),
        hour=int(os.getenv("BACKUP_GRUPOS_HOUR", "3")),
        minute=0,
        timezone="America/Sao_Paulo",
    )

    def run(self, context: dict | None = None) -> FlowResult:
        folder_id = os.getenv("GDRIVE_BACKUP_FOLDER_ID")
        if not folder_id:
            return FlowResult(success=False, summary="GDRIVE_BACKUP_FOLDER_ID não configurado.")

        data_backup = date.today().isoformat()  # ex.: 2026-06-02

        grupos = list_all_groups()
        if not grupos:
            return FlowResult(success=False, summary="Nenhum grupo retornado pela Z-API.")

        titulo = f"Backup Grupos MAIA — {data_backup}"
        self.log(f"Criando planilha '{titulo}' na pasta {folder_id}...")
        spreadsheet = create_backup_spreadsheet(titulo, folder_id=folder_id)

        used_tab_names: set[str] = set()
        total_membros = 0
        grupos_ok = 0
        erros: list[str] = []
        # Consolidação cross-grupo: telefone -> {nome, short, grupos[]}.
        contatos_unicos: dict[str, dict] = {}

        for grupo in grupos:
            group_id = str(grupo.get("phone", "")).strip()
            nome_fallback = grupo.get("name") or group_id
            try:
                meta = get_group_metadata(group_id)
                if not meta:
                    erros.append(f"{nome_fallback}: metadata vazio")
                    continue

                nome_grupo = meta.get("subject") or nome_fallback
                participantes = meta.get("participants") or []
                membros = [
                    p for p in participantes
                    if not _is_admin(p) and str(p.get("phone", "")).strip() != MAIA_PHONE
                ]

                if not membros:
                    self.log(f"Grupo '{nome_grupo}': sem membros elegíveis — aba não criada.")
                    continue

                # Acumula na base consolidada (dedup por telefone, junta grupos).
                for p in membros:
                    tel = str(p.get("phone", "")).strip()
                    if not tel:
                        continue
                    entry = contatos_unicos.get(tel)
                    if entry is None:
                        entry = {"nome": p.get("name", "") or "", "short": p.get("short", "") or "", "grupos": []}
                        contatos_unicos[tel] = entry
                    # Preenche nome/short a partir de qualquer grupo que tenha o dado.
                    if not entry["nome"] and p.get("name"):
                        entry["nome"] = p.get("name")
                    if not entry["short"] and p.get("short"):
                        entry["short"] = p.get("short")
                    if nome_grupo not in entry["grupos"]:
                        entry["grupos"].append(nome_grupo)

                linhas = [
                    _membro_para_linha(p, nome_grupo, group_id, data_backup)
                    for p in membros
                ]

                tab_name = sanitize_tab_name(nome_grupo, used_tab_names)
                ws = ensure_worksheet(spreadsheet, tab_name, rows=len(linhas) + 1, cols=len(HEADER))
                write_rows(ws, HEADER, linhas)

                total_membros += len(linhas)
                grupos_ok += 1
                self.log(f"Grupo '{nome_grupo}': {len(linhas)} membros (aba '{tab_name}').")
            except Exception as e:
                erros.append(f"{nome_fallback}: {e}")
                self.log(f"Falha no grupo '{nome_fallback}': {e}")

            time.sleep(SLEEP_ENTRE_GRUPOS)

        # Aba consolidada "Contatos Únicos" (primeira aba): 1 linha por telefone,
        # com todos os grupos daquele contato e a contagem de grupos.
        total_unicos = len(contatos_unicos)
        if total_unicos:
            linhas_unicos = [
                _contato_unico_para_linha(tel, info, data_backup)
                for tel, info in sorted(contatos_unicos.items())
            ]
            ws_unicos = ensure_worksheet(
                spreadsheet, ABA_CONTATOS_UNICOS,
                rows=len(linhas_unicos) + 1, cols=len(HEADER_UNICOS), index=0,
            )
            write_rows(ws_unicos, HEADER_UNICOS, linhas_unicos)
            self.log(f"Aba '{ABA_CONTATOS_UNICOS}': {total_unicos} contatos únicos.")

        # Remove a aba padrão 'Sheet1' que nasce com a planilha.
        delete_default_sheet(spreadsheet)

        summary = (
            f"Backup {data_backup}: {grupos_ok}/{len(grupos)} grupos, "
            f"{total_membros} membros, {total_unicos} contatos únicos. Erros: {len(erros)}."
        )
        details = {
            "spreadsheet_url": spreadsheet.url,
            "data_backup": data_backup,
            "grupos_total": len(grupos),
            "grupos_ok": grupos_ok,
            "total_membros": total_membros,
            "total_contatos_unicos": total_unicos,
            "erros": erros,
        }

        # Notifica o grupo de logs (mesmo padrão do relatório diário).
        self._notificar(summary, spreadsheet.url, erros)

        return FlowResult(success=len(erros) == 0, summary=summary, details=details)

    def _notificar(self, summary: str, url: str, erros: list[str]) -> None:
        try:
            msg = f"🗂️ *Backup de grupos*\n{summary}\n{url}"
            if erros:
                amostra = "\n".join(f"- {e}" for e in erros[:5])
                msg += f"\n\n⚠️ Falhas:\n{amostra}"
                if len(erros) > 5:
                    msg += f"\n... e mais {len(erros) - 5}."
            send_zapi_message(GRUPO_SYSTEM_LOGS, msg)
        except Exception as e:
            self.log(f"Não foi possível notificar o grupo de logs: {e}")
