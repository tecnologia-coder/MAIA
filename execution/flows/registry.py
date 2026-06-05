"""
Registro central de fluxos de automação.

Desacopla "quais fluxos existem" de "como são disparados":
- @register marca uma classe Flow para entrar no registro.
- scheduled_flows() devolve os fluxos periódicos habilitados (consumido pelo
  main.py para criar os jobs no APScheduler).
- run_flow(name) executa um fluxo de forma protegida (try/except + tempo),
  servindo como ponto único para logging/telemetria futura.

Importante: importe aqui (em _import_flows) cada módulo de fluxo concreto para
que o decorador @register seja executado e o fluxo apareça no registro.
"""
from __future__ import annotations

import time

from execution.flows.base import Flow, FlowResult

# nome do fluxo -> instância do Flow
FLOWS: dict[str, Flow] = {}


def register(flow_cls: type[Flow]) -> type[Flow]:
    """Decorador: instancia e registra um fluxo pelo seu `name`."""
    instance = flow_cls()
    if not instance.name or instance.name == "flow":
        raise ValueError(f"Fluxo {flow_cls.__name__} precisa definir um `name` único.")
    if instance.name in FLOWS:
        raise ValueError(f"Fluxo duplicado no registro: '{instance.name}'.")
    FLOWS[instance.name] = instance
    return flow_cls


def _import_flows() -> None:
    """Importa os módulos de fluxos concretos para popular o registro."""
    # Cada novo fluxo periódico/por-gatilho deve ser importado aqui.
    from execution.flows import backup_grupos  # noqa: F401
    from execution.flows import daily_report  # noqa: F401


def get_flow(name: str) -> Flow | None:
    if not FLOWS:
        _import_flows()
    return FLOWS.get(name)


def all_flows() -> list[Flow]:
    if not FLOWS:
        _import_flows()
    return list(FLOWS.values())


def scheduled_flows() -> list[Flow]:
    """Fluxos com schedule definido e habilitados (para agendamento)."""
    return [f for f in all_flows() if f.schedule is not None and f.enabled()]


def run_flow(name: str, context: dict | None = None) -> FlowResult:
    """
    Executa um fluxo pelo nome, de forma protegida. Nunca propaga exceção:
    sempre devolve um FlowResult (success=False em caso de falha).
    """
    flow = get_flow(name)
    if flow is None:
        msg = f"Fluxo '{name}' não encontrado no registro."
        print(f"[FLOW] {msg}")
        return FlowResult(success=False, summary=msg)

    if not flow.enabled():
        msg = f"Fluxo '{name}' está desabilitado (env)."
        flow.log(msg)
        return FlowResult(success=False, summary=msg)

    inicio = time.time()
    flow.log("Iniciando execução...")
    try:
        result = flow.run(context)
    except Exception as e:  # rede de segurança: um fluxo nunca derruba o processo
        elapsed = time.time() - inicio
        flow.log(f"Erro não tratado após {elapsed:.1f}s: {e}")
        return FlowResult(success=False, summary=f"Erro: {e}")

    elapsed = time.time() - inicio
    flow.log(f"Concluído em {elapsed:.1f}s — {result.summary}")
    return result
