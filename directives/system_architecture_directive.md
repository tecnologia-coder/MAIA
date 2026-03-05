# Diretriz de Arquitetura de Sistema - MAIA

**Versão:** 1.0  
**Status:** Oficial / Normativo  
**Objetivo:** Definir a arquitetura determinística oficial da MAIA, estabelecendo as fronteiras entre lógica de orquestração (Python) e módulos de inteligência (LLM).

---

## 1. Premissa Fundamental

A **MAIA** não é um agente autônomo baseado em LLM. Ela é um sistema de automação orquestrado de forma determinística por código **Python**. LLMs são tratadas estritamente como módulos de processamento de linguagem natural internos, encarregados de tarefas específicas de extração, classificação ou síntese, sem autoridade sobre o fluxo de execução do sistema.

## 2. Fluxo de Execução Imutável

O pipeline de processamento segue uma sequência linear e fixa. Nenhuma etapa pode ser pulada ou alterada dinamicamente por subsistemas de IA.

1.  **Webhook:** Recebimento do evento de entrada (Z-API).
2.  **Triagem:** Filtro inicial de mensagens e validação de pacotes.
3.  **Classificação:** Determinação da intenção do usuário.
4.  **Decisão de Fluxo (Python):** 
    *   Se **FALSE** (Não é um pedido válido): Encerrar imediatamente.
    *   Se **TRUE**: Prosseguir.
5.  **Categorização:** Vinculação do pedido a categorias e subcategorias do banco de dados.
6.  **Busca Vetorial:** Recuperação de contexto e fornecedores relevantes (Embeddings).
7.  **Validação de Fornecedores:** Cruzamento de dados técnicos e disponibilidade.
8.  **Persistência:** Registro do estado e do pedido no banco de dados (Supabase).
9.  **Geração de Resposta:** Síntese da resposta final baseada na persona oficial.
10. **Envio WhatsApp:** Entrega da mensagem via Z-API.

## 3. Regras de Orquestração e Controle

### 3.1. Soberania do Código (Python)
*   Toda decisão condicional (if/else, loops, roteamento) deve ser implementada exclusivamente em Python.
*   Modelos de linguagem (LLMs) são proibidos de decidir "o que fazer a seguir" no sistema.

### 3.2. Contratos de Dados (JSON)
*   Toda e qualquer saída de um módulo LLM deve ser obrigatoriamente um **JSON válido**.
*   **Protocolo de Erro:**
    1. Se a saída não for um JSON válido, o orquestrador deve realizar **exatamente uma (1) tentativa de retry**.
    2. Caso o erro persista após o retry, o sistema deve **logar o erro e abortar a execução** daquela requisição.
*   É terminantemente proibido o uso de texto livre (string pura) vindo de LLMs como base para lógica de decisão ou branches do sistema.

### 3.3. Restrições de Acesso e Segurança
*   **Seleção de Fornecedores:** A LLM não tem permissão para selecionar fornecedores diretamente. Ela pode apenas classificar a necessidade; o "match" final é uma operação de banco de dados/lógica Python.
*   **Acesso a Dados:** LLMs nunca devem acessar o banco de dados diretamente. Toda interação com o banco (Read/Write) deve ser mediada por funções determinísticas em Python.

## 4. Conformidade

Qualquer modificação no código que viole estes princípios arquiteturais será considerada um bug crítico. O sistema deve priorizar a previsibilidade e a rastreabilidade sobre a flexibilidade emergente comum em agentes puramente generativos.
