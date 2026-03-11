"""
Relatório diário de telemetria da MAIA.
Consulta a tabela 'telemetria' no Supabase (últimas 24h),
agrega métricas e envia resumo formatado via WhatsApp (Z-API).
"""
from datetime import datetime, timedelta, timezone
from execution.supabase_client import get_supabase_client
from execution.zapi_client import send_zapi_message

GRUPO_TELEMETRIA = "120363422760214316-group"


def fetch_last_24h():
    """Busca registros de telemetria das últimas 24 horas."""
    supabase = get_supabase_client()
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    res = supabase.table("telemetria").select("*").gte("created_at", since).execute()
    return res.data or []


def build_report(records):
    """Agrega métricas e monta texto formatado para WhatsApp."""
    total = len(records)
    if total == 0:
        return (
            "*MAIA - Relatório Diário*\n"
            f"Período: últimas 24h\n\n"
            "Nenhuma mensagem processada no período."
        )

    # Contadores por etapa
    etapas = {}
    for r in records:
        etapa = r.get("etapa_final", "desconhecido")
        etapas[etapa] = etapas.get(etapa, 0) + 1

    sucessos = etapas.get("sucesso", 0)
    heuristica = etapas.get("heuristica_curta", 0) + etapas.get("heuristica_sem_intencao", 0)
    triagem_rej = etapas.get("triagem_rejeitada", 0)
    sem_forn = etapas.get("sem_fornecedor", 0)
    erros = etapas.get("erro_triagem", 0)

    # Tokens
    tokens_total = sum(r.get("tokens_total", 0) or 0 for r in records)
    tokens_triagem = sum(r.get("tokens_triagem", 0) or 0 for r in records)
    tokens_validacao = sum(r.get("tokens_validacao", 0) or 0 for r in records)
    tokens_resposta = sum(r.get("tokens_resposta", 0) or 0 for r in records)

    # Tempo médio (só dos que têm tempo > 0)
    tempos = [r.get("tempo_total_ms", 0) or 0 for r in records if (r.get("tempo_total_ms") or 0) > 0]
    tempo_medio_s = (sum(tempos) / len(tempos) / 1000) if tempos else 0

    # Detalhes dos pedidos com sucesso
    pedidos_sucesso = [r for r in records if r.get("etapa_final") == "sucesso"]

    # --- Monta texto ---
    now_br = datetime.now(timezone(timedelta(hours=-3)))
    header = (
        f"*MAIA - Relatório Diário*\n"
        f"{now_br.strftime('%d/%m/%Y %H:%M')} (Brasília)\n"
        f"Período: últimas 24h\n"
    )

    resumo = (
        f"\n*Resumo Geral*\n"
        f"Total de mensagens: {total}\n"
        f"Respondidas com sucesso: {sucessos}\n"
        f"Filtradas (heurística): {heuristica}\n"
        f"Rejeitadas (triagem IA): {triagem_rej}\n"
        f"Sem fornecedor: {sem_forn}\n"
        f"Erros: {erros}\n"
    )

    perf = (
        f"\n*Performance*\n"
        f"Tempo médio de resposta: {tempo_medio_s:.1f}s\n"
        f"Tokens consumidos: {tokens_total:,}\n"
        f"  - Triagem: {tokens_triagem:,}\n"
        f"  - Validação: {tokens_validacao:,}\n"
        f"  - Resposta: {tokens_resposta:,}\n"
    )

    # Detalhes dos pedidos atendidos (últimos 10 para não estourar limite de mensagem)
    detalhes = ""
    if pedidos_sucesso:
        detalhes = f"\n*Pedidos Atendidos ({len(pedidos_sucesso)})*\n"
        for i, p in enumerate(pedidos_sucesso[:10], 1):
            nome = p.get("sender_name", "?")
            telefone = p.get("sender_phone", "?")
            msg = (p.get("message_text") or "")[:80]
            grupo = p.get("group_name") or "Privado"
            forn = p.get("fornecedores_validados", 0) or 0
            tempo_s = (p.get("tempo_total_ms", 0) or 0) / 1000
            resposta = (p.get("resposta_final") or "")[:120]

            detalhes += (
                f"\n{i}. *{nome}* ({telefone})\n"
                f"   Grupo: {grupo}\n"
                f"   Pedido: _{msg}_\n"
                f"   Fornecedores: {forn} | Tempo: {tempo_s:.1f}s\n"
                f"   Resposta: _{resposta}{'...' if len(p.get('resposta_final', '') or '') > 120 else ''}_\n"
            )

        if len(pedidos_sucesso) > 10:
            detalhes += f"\n... e mais {len(pedidos_sucesso) - 10} pedidos.\n"

    return header + resumo + perf + detalhes


def send_daily_report():
    """Função principal: busca dados, monta relatório e envia via WhatsApp."""
    try:
        print("[TELEMETRIA] Gerando relatório diário...")
        records = fetch_last_24h()
        report_text = build_report(records)
        send_zapi_message(GRUPO_TELEMETRIA, report_text)
        print(f"[TELEMETRIA] Relatório enviado para {GRUPO_TELEMETRIA}. {len(records)} registros.")
    except Exception as e:
        print(f"[TELEMETRIA] Erro ao enviar relatório diário: {e}")


if __name__ == "__main__":
    send_daily_report()
