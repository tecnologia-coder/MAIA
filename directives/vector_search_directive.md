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

## 4. Pré-filtro Estruturado Determinístico (Camada Anterior à Vetorial)

Antes/junto da busca vetorial, o orquestrador executa um **pré-filtro determinístico** direto na
tabela `parceiros` (apenas `status_aprovacao = 'aprovado'`) — `search_suppliers.search_suppliers`:

- **Âncora de taxonomia:** mantém candidatos cuja `subcategoria_id` (score 0.85) ou `categoria_id`
  (score 0.70) bate com a do pedido. A triagem e o cadastro podem usar subcategorias-irmãs
  diferentes (ex.: pedido "PERSONALIZADOS" vs fornecedor "DOCES", ambos em "FESTAS"), por isso a
  **categoria** é uma âncora válida.
- **Atributos booleanos:** quando a triagem sinaliza `requer_espaco_kids`/`requer_menu_kids`/
  `requer_trocador`, filtra por `tem_espaco_kids`/`tem_menu_kids`/`tem_trocador = true` (score 0.65).
- **Região:** NÃO é filtro rígido (bairros como "Cerro Azul" não estão em `cidade`); entra como
  sinal textual na query semântica/lexical.

Os candidatos estruturados e os vetoriais são deduplicados por ID de parceiro (mantendo o maior score).

## 5. Sincronizacao da Base de Parceiros com o Vector Store

`documents` deve refletir somente parceiros disponiveis para recomendacao da MAIA:

- `status_aprovacao = 'aprovado'`: o parceiro deve existir em `documents`.
- `status_aprovacao != 'aprovado'`: o parceiro nao deve existir em `documents`.
- `status_aprovacao = 'cancelado'`: o parceiro deve ser movido para `parceiros_cancelados`, removido de `parceiros` e removido de `documents`.
- `DELETE` em `parceiros`: sempre remove os documentos associados ao parceiro.

O fluxo incremental e recebido em `POST /webhooks/supabase/parceiros` (`main.py`), protegido pelo header `x-webhook-secret` com o valor de `SUPABASE_PARTNER_SYNC_SECRET`. O endpoint recebe eventos de Supabase Database Webhook (`INSERT`, `UPDATE`, `DELETE`) e delega para `execution/sync_documents.py`.

Ferramentas deterministicas:
- `sync_partner(partner_id)`: sincroniza um parceiro aprovado ou remove se nao estiver aprovado.
- `remove_partner_documents(partner_id)`: remove todos os documentos do parceiro no vector store.
- `move_cancelled_partner(partner_id)`: move cancelados para `parceiros_cancelados` e limpa o vector store.
- `reconcile()`: corrige divergencias globais entre `parceiros`, `parceiros_cancelados` e `documents`.

Para reparo manual, usar `python -m execution.sync_documents --reconcile` apos confirmar que o uso de embedding e as remocoes no banco estao autorizados.

## 6. Dependência de Infraestrutura (CRÍTICO)

A busca vetorial depende da função SQL `public.match_documents(query_embedding, filter, match_count)`
existir no banco. Se ela não existir, a chamada falha (`PGRST202`) e o sistema cai no fallback
lexical/estruturado. O SQL de criação está em `sql/001_match_documents_and_indexes.sql`. Também é
necessário o índice ANN (HNSW) em `documents.embedding` para performance.

## 7. Auditoria e Logs
Toda operação da ferramenta loga nativamente o score de similaridade do primeiro candidato para monitoramento de precisão (drift) do modelo de embeddings pelo time de engenharia.

## Ferramentas/Execução
- Implementação: `execution/search_suppliers.py` (`search_suppliers_by_text`, busca
  por similaridade de cosseno) + `execution/ai_client.py::get_embedding` (gera o vetor).
- Exposta ao Agente como a tool `supabase_vector_store` em `execution/agent_tools.py`.
- O vector store (tabela `documents`) é populado por `execution/sync_documents.py::sync`
  a partir da tabela `parceiros`; o fluxo incremental usa `sync_partner`, `remove_partner_documents`,
  `move_cancelled_partner` e `reconcile`.
- Depende da RPC `match_documents` no Supabase (ver estado de infra do projeto).
