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
2.  **Triagem:** Filtro inicial de mensagens e identificação de identidade (Profiles/Grupos).
3.  **Log de Auditoria:** Registro de todas as mensagens recebidas na tabela `mensagens` (Supabase).
4.  **Classificação:** Determinação da intenção do usuário.
5.  **Decisão de Fluxo (Python):** 
    *   Se **FALSE** (Não é um pedido válido): Encerrar imediatamente.
    *   Se **TRUE**: Prosseguir.
6.  **Categorização:** Vinculação do pedido a categorias e subcategorias do banco de dados.
7.  **Enriquecimento de Contexto (Python — pré-agente):** Antes de chamar o agente de match, o orquestrador calcula o campo `fase_bebe` seguindo este fluxo:
    1. Extrair `telefone` de `pedidos_indicacao.pedido_por` (campo JSONB, chave `"telefone"`).
    2. Buscar em `perfis_maes` onde `telefone = telefone_extraido` → obter `user_id`.
    3. Se `perfis_maes.status_maternidade = 'gestante'` → `fase_bebe = "gestante"` (passar `data_prevista_parto` como contexto adicional no input do agente).
    4. Caso contrário, buscar em `filhos_maes` onde `mae_id = user_id`, ordenar por `data_nascimento DESC`, pegar o primeiro registro.
    5. Calcular meses de vida entre `data_nascimento` e hoje. Resolver o `codigo` consultando a tabela `fase_bebe` no Supabase:
        ```sql
        SELECT codigo FROM fase_bebe
        WHERE (idade_min_meses IS NULL OR idade_min_meses <= :meses)
          AND (idade_max_meses IS NULL OR idade_max_meses >= :meses)
        ORDER BY ordem
        LIMIT 1;
        ```
        O valor de `fase_bebe` a passar ao agente é o `codigo` retornado (ex: `"0-3m"`, `"1-2a"`). Nunca hardcodar o mapeamento de faixas no script — a tabela é a fonte de verdade.
    6. Se nenhum filho encontrado → `fase_bebe = null`.
    7. Passar `fase_bebe` como campo no input do agente de match junto com os demais dados do pedido.
8.  **Match de Fornecedores (Agentic Flow):** A LLM utiliza ferramentas (Vector Store, consultas de ID) para buscar, validar e enriquecer a lista de indicações.
8.  **Persistência:** Registro do pedido estruturado na tabela `pedidos_indicacao`.
9.  **Geração de Resposta:** Síntese da resposta final baseada na persona oficial.
10. **Envio WhatsApp:** Entrega da mensagem via Z-API.

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
