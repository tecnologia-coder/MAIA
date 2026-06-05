"""
Fluxo: Relatório diário de telemetria da MAIA (10h, Brasília).

Wrapper do framework de fluxos sobre a lógica já existente em
`execution/daily_report.py` (fetch_last_24h + build_report + envio Z-API).
Antes este job era agendado "à mão" no main.py; agora segue o mesmo padrão
dos demais fluxos periódicos (Camada 3), agendado automaticamente pelo registry.
"""
from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger

from execution.flows.base import Flow, FlowResult
from execution.flows.registry import register
from execution.daily_report import fetch_last_24h, build_report, GRUPO_SYSTEM_LOGS
from execution.zapi_client import send_zapi_message


@register
class DailyReportFlow(Flow):
    name = "daily_report"
    description = "Relatório diário de telemetria (últimas 24h) enviado ao grupo de logs."

    # 10:00 Brasília — mesmo horário do agendamento manual anterior.
    schedule = CronTrigger(hour=10, minute=0, timezone="America/Sao_Paulo")

    def run(self, context: dict | None = None) -> FlowResult:
        self.log("Gerando relatório diário de telemetria...")
        records = fetch_last_24h()
        report_text = build_report(records)
        send_zapi_message(GRUPO_SYSTEM_LOGS, report_text)
        summary = f"Relatório diário enviado ({len(records)} registros nas últimas 24h)."
        self.log(summary)
        return FlowResult(success=True, summary=summary, details={"registros": len(records)})
