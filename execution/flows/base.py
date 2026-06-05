"""
Contrato base do framework de fluxos de automação da MAIA.

Um "fluxo" é uma unidade de automação determinística (camada 3 da arquitetura)
que pode ser disparada de duas formas:
- Periódica: define `schedule` (um trigger do APScheduler) e é agendada
  automaticamente no startup do main.py.
- Por gatilho: deixa `schedule = None` e é chamada sob demanda via
  registry.run_flow(nome, context) — ex.: a partir de um webhook.

Cada fluxo concreto herda de `Flow`, define `name`/`description`, opcionalmente
`schedule`, e implementa `run()`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import os


@dataclass
class FlowResult:
    """Resultado padronizado de uma execução de fluxo (para log/telemetria)."""
    success: bool
    summary: str
    details: dict = field(default_factory=dict)


class Flow(ABC):
    # Slug único do fluxo (usado como id de job e chave no registry).
    name: str = "flow"
    # Descrição curta do que o fluxo faz.
    description: str = ""
    # Trigger do APScheduler (CronTrigger/IntervalTrigger). None = só por gatilho.
    schedule = None

    def enabled(self) -> bool:
        """
        Liga/desliga o fluxo via env var FLOW_<NAME>_ENABLED (default: ligado).
        Ex.: FLOW_BACKUP_GRUPOS_ENABLED=false desativa o agendamento.
        """
        var = f"FLOW_{self.name.upper()}_ENABLED"
        return os.getenv(var, "true").strip().lower() == "true"

    def log(self, message: str) -> None:
        """Log padronizado no estilo do projeto: [FLOW:<name>] ..."""
        print(f"[FLOW:{self.name}] {message}")

    @abstractmethod
    def run(self, context: dict | None = None) -> FlowResult:
        """Executa o fluxo. Deve ser idempotente o suficiente para reexecução."""
        raise NotImplementedError
