from datetime import date
from execution.supabase_client import get_supabase_client


def calcular_fase_bebe(data_nascimento: date | None, status_maternidade: str | None) -> str | None:
    """
    Retorna o codigo da fase do bebê consultando a tabela fase_bebe no Supabase.

    Args:
        data_nascimento: data de nascimento do filho mais novo (filhos_maes.data_nascimento).
                         Pode ser None se a mãe não tiver filhos cadastrados.
        status_maternidade: valor de perfis_maes.status_maternidade (ex: 'gestante', 'mae').

    Returns:
        str com o codigo da fase (ex: "0-3m", "gestante") ou None se não houver dados.
    """
    if status_maternidade == "gestante":
        return "gestante"

    if data_nascimento is None:
        return None

    hoje = date.today()
    meses = (hoje.year - data_nascimento.year) * 12 + (hoje.month - data_nascimento.month)
    # Ajuste: se ainda não completou o dia do mês de nascimento, subtrai 1 mês
    if hoje.day < data_nascimento.day:
        meses -= 1

    supabase = get_supabase_client()
    try:
        # Filtra fases onde o range de meses abrange o valor calculado.
        # Condição: (idade_min_meses <= meses OR idade_min_meses IS NULL)
        #       AND (idade_max_meses IS NULL OR idade_max_meses >= meses)
        # 'gestante' é excluída explicitamente (já tratada acima).
        res = (
            supabase.table("fase_bebe")
            .select("codigo")
            .or_(f"idade_min_meses.lte.{meses},idade_min_meses.is.null")
            .or_(f"idade_max_meses.is.null,idade_max_meses.gte.{meses}")
            .neq("codigo", "gestante")
            .order("ordem")
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]["codigo"]
        return None
    except Exception as e:
        print(f"[FASE_BEBE] Erro ao consultar tabela fase_bebe: {e}")
        return None
