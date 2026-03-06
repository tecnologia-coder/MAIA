# Diretriz da Ferramenta de Busca Vetorial (Supabase Vector Store)

**Objetivo:** Definir o funcionamento e o contrato de dados da ferramenta de busca vetorial (Embeddings) no Supabase, que agora atua como uma **Tool (Ferramenta)** à disposição do Agente MAIA na etapa de recomendação.

---

## 1. Escopo Técnico da Ferramenta

A busca vetorial é a ferramenta responsável por consultar o banco de dados (`documents`) e identificar os fornecedores mais semanticamente próximos da query fornecida pelo Agente. Ela deve ser invocada pela LLM durante o processo de *Tool Calling*.

## 2. Processo de Execução (Under the Hood)

Quando o Agente invoca a ferramenta `Supabase Vector Store(query)`, o sistema em Python executa rigorosamente as etapas abaixo:

1.  **Geração de Embedding:** O orquestrador converte a `query` (string) fornecida pelo Agente em um vetor numérico (embedding).
2.  **Busca Vetorial (Top 10):** Executa a busca de similaridade de cosseno no banco de dados, retornando os **top 10** candidatos com maior score.
3.  **Threshold de Similaridade:** Aplica um threshold mínimo de **0.60**. 
4.  **Protocolo de Fallback:** 
    *   Se nenhum resultado atingir o threshold de 0.60, o sistema executa automaticamente uma **busca lexical** no banco de dados.
5.  **Ordenação:** Retorna a lista ao Agente, sempre em ordem **decrescente** de similaridade/relevância.

## 3. Contrato da Ferramenta (Interface para o Agente)

### A. Entrada (Input)
*   **Parâmetro:** `query` (tipo: string).
*   **Definição:** Uma frase ou conjunto de palavras-chave ricas e descritivas elaborada pelo Agente MAIA com base no contexto do usuário, na categoria e na subcategoria do pedido. Exemplo: `"Saúde e Bem-estar Personal Trainer - personal trainer preciso de treino funcional 3x por semana"`.

### B. Saída (Output)
A ferramenta retorna para o Agente uma lista bruta (JSON) de candidatos pré-qualificados. O Agente usará este retorno para aplicar sua validação rigorosa final.

**Caso haja candidatos (Formato de Retorno):**
```json
{
  "candidatos": [
    {
      "metadata": {
        "id": 123
      },
      "pageContent": "Texto descritivo do fornecedor, suas especialidades e tags.",
      "similaridade": 0.895
    }
  ]
}
```

**Caso nenhum candidato seja encontrado (Formato de Retorno):**
```json
{
  "candidatos": []
}
```

## 4. Auditoria e Logs
Toda operação da ferramenta loga nativamente o score de similaridade do primeiro candidato para monitoramento de precisão (drift) do modelo de embeddings pelo time de engenharia.
