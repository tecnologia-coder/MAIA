# Diretriz de Busca Vetorial - MAIA

**Objetivo:** Definir a estratégia determinística e técnica para a recuperação de fornecedores candidatos via busca vetorial (Embeddings) e busca lexical (Fallback) no Supabase.

---

## 1. Escopo Técnico

A busca vetorial é a etapa do pipeline responsável por identificar os fornecedores mais semanticamente próximos da necessidade do usuário, garantindo que o orquestrador Python tenha uma lista de candidatos qualificados para a validação final.

## 2. Processo de Execução

O fluxo de busca deve seguir rigorosamente as etapas abaixo:

1.  **Geração de Embedding:** O orquestrador deve gerar o vetor numérico (embedding) a partir do pedido estruturado (resultado da etapa de Categorização).
2.  **Busca Vetorial (Top 10):** Executar a busca de similaridade de cosseno no banco de dados, retornando os **top 10** candidatos com maior score.
3.  **Threshold de Similaridade:** Aplicar um threshold mínimo de **0.78**. 
4.  **Protocolo de Fallback:** 
    *   Se nenhum resultado atingir o threshold de 0.78, o sistema deve executar automaticamente uma **busca lexical** (por palavras-chave nos campos de descrição e especialidade).
5.  **Ordenação:** Os resultados devem ser sempre entregues em ordem **decrescente** de similaridade/relevância.

## 3. Regras de Negócio e Restrições

### 3.1. Limitação de Candidatos
*   **Nesta etapa**, é proibido limitar o resultado a apenas 3 fornecedores. A busca deve retornar até 10 candidatos para permitir que a etapa subsequente (Validação de Fornecedores) tenha volume suficiente para filtragem técnica.
*   A limitação final de 3 fornecedores ocorre exclusivamente na etapa de **Validação Final**.

### 3.2. Proibições Críticas
*   **Seleção por LLM:** É terminantemente proibido que a LLM selecione fornecedores baseada em "conhecimento interno" ou preferência. A seleção deve ser baseada puramente nos scores retornados pelo banco de dados.
*   **Inferência sem Dados:** Não é permitido inferir a qualidade ou relevância de um fornecedor que não possua score de similaridade ou match lexical comprovado.

## 4. Formato de Saída Obrigatório

O módulo de busca deve retornar estritamente um objeto JSON. O score de similaridade deve ser incluído em cada item.

### Caso haja candidatos:
```json
{
  "candidatos": [
    {
      "fornecedor_id": 123,
      "similaridade": 0.895
    },
    {
      "fornecedor_id": 456,
      "similaridade": 0.782
    }
  ]
}
```

### Caso nenhum candidato seja encontrado (mesmo após fallback):
```json
{
  "candidatos": []
}
```

## 5. Auditoria e Logs
Toda operação de busca deve logar o score de similaridade do primeiro candidato para monitoramento de precisão (drift) do modelo de embeddings.
