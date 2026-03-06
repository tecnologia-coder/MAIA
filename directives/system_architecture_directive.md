# Diretriz de Arquitetura de Sistema - MAIA

**Versão:** 1.0  
**Status:** Oficial / Normativo  
**Objetivo:** Definir a arquitetura determinística oficial da MAIA, estabelecendo as fronteiras entre lógica de orquestração (Python) e módulos de inteligência (LLM).

---

## 1. Premissa Fundamental

A **MAIA** atua primariamente como um sistema orquestrado de forma determinística por código **Python**. Na maioria das etapas do fluxo, as LLMs são tratadas estritamente como módulos de processamento de linguagem natural internos, encarregados de tarefas de extração ou síntese.

**Exceção de Autonomia (Agentic Flow):** Apenas e unicamente na etapa de **Busca e Validação de Fornecedores**, a MAIA recebe autonomia controlada para atuar como um **Agente**. Nesta etapa, a LLM é instruída a realizar Tool Calling (chamadas de ferramentas em Python) para cumprir os seguintes objetivos:
1. Interpretar o pedido de indicação do usuário.
2. Realizar busca semântica inteligente na base de fornecedores.
3. Validar rigorosamente a correspondência entre pedido e fornecedor.
4. Retornar apenas fornecedores que atendam **exatamente** ao solicitado.
5. Enriquecer cada recomendação com dados reais e link de contato.

## 2. Fluxo de Execução

O pipeline de processamento segue uma sequência estruturada:

1.  **Webhook:** Recebimento do evento de entrada (Z-API).
2.  **Triagem:** Filtro inicial de mensagens e validação de pacotes.
3.  **Classificação:** Determinação da intenção do usuário.
4.  **Decisão de Fluxo (Python):** 
    *   Se **FALSE** (Não é um pedido válido): Encerrar imediatamente.
    *   Se **TRUE**: Prosseguir.
5.  **Categorização:** Vinculação do pedido a categorias e subcategorias do banco de dados.
6.  **Match de Fornecedores (Agentic Flow):** A LLM utiliza ferramentas (Vector Store, consultas de ID) para buscar, validar e enriquecer a lista de indicações.
7.  **Persistência:** Registro do estado e do pedido no banco de dados (Supabase).
8.  **Geração de Resposta:** Síntese da resposta final baseada na persona oficial.
9.  **Envio WhatsApp:** Entrega da mensagem via Z-API.

## 3. Regras de Orquestração e Controle

### 3.1. Soberania do Código (Python) vs. Autonomia do Agente
*   Toda decisão macro de roteamento (if/else principal do sistema) deve ser implementada em Python.
*   Modelos de linguagem (LLMs) possuem autonomia **apenas na etapa 6** para uso múltiplo de ferramentas até concluir a montagem do JSON final de `recomendacoes`.

### 3.2. Contratos de Dados (JSON)
*   Toda e qualquer saída final de um módulo LLM deve ser obrigatoriamente um **JSON válido**.
*   **Protocolo de Erro:**
    1. Se a saída final não for um JSON válido, o orquestrador deve realizar **exatamente uma (1) tentativa de retry**.
    2. Caso o erro persista após o retry, o sistema deve **logar o erro e abortar a execução** daquela requisição.
*   É terminantemente proibido o uso de texto livre (string pura) vindo de LLMs para decidir a próxima etapa global fora do escopo agêntico.

### 3.3. Restrições de Acesso e Segurança
*   **Supabase / Banco de Dados:** LLMs nunca devem acessar o banco de dados via raw SQL. O acesso aos dados e a busca vetorial só podem ser executados consumindo as Ferramentas exclusivas (Functions) fornecidas pelo orquestrador Python.

## 4. Conformidade

Qualquer modificação no código que viole estes princípios arquiteturais será considerada um bug crítico. O sistema deve priorizar a previsibilidade e a rastreabilidade sobre a flexibilidade emergente comum em agentes puramente generativos.
