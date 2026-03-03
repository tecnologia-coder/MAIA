# Diretriz de Match de Fornecedores (MAIA)

**Objetivo:** Definir critérios rigorosos para a seleção final e indicação de fornecedores vindos da busca vetorial (Supabase), garantindo que apenas profissionais estritamente adequados sejam recomendados ao usuário.

## Contexto da Busca e Base de Dados

Os fornecedores são recuperados através de uma busca por similaridade (vetorial) na tabela `documents` (Vector Store). No entanto, os detalhes finais e a validação devem ser feitos cruzando com a tabela `parceiros`.

## Regras Obrigatórias de Seleção

A filtragem pós-busca deve seguir incondicionalmente as seguintes regras:

1. **Correspondência Exata de Serviço:** O fornecedor só pode ser recomendado se o seu escopo na tabela `parceiros` oferecer *exatamente* o que foi solicitado.
2. **Link Obrigatório:** Somente fornecedores que possuam um `whatsapp_link` válido na tabela `parceiros` podem ser recomendados. A MAIA nunca indica parceiros sem contato direto.
3. **Rejeição por Similaridade Inadequada:** Se a similaridade semântica trouxer áreas correlatas mas não idênticas ao pedido central, o parceiro **deve ser descartado**.
4. **Limite Máximo de Indicações:** Selecionar no **máximo 3 (três)** parceiros.
5. **Preferência por Lista Vazia:** É preferível retornar uma lista vazia (`[]`) do que indicar um parceiro inadequado.
6. **Critério de Status:** Apenas parceiros com `status = 'active'` na tabela `parceiros` são válidos.

## Critérios de Validação e Cruzamento (Match)

Para validar se o fornecedor atende à Regra 1 e 2, a análise deve cruzar o pedido do usuário contra as seguintes propriedades do fornecedor retornado pela busca:
*   A **descrição** completa do fornecedor.
*   As **palavras-chave** (tags) vinculadas ao perfil do fornecedor.
*   A **categoria e subcategoria** na qual o fornecedor está cadastrado.

## Formato de Saída Obrigatório

O retorno da etapa de seleção deve ser **exclusivamente** um objeto JSON estruturado, sem nenhum texto adicional fora da estrutura, contendo os fornecedores aprovados pelas regras acima.

```json
{
  "fornecedores_validos": [
    {
      "fornecedor_id": 0,
      "Motivo_match": "Justificativa objetiva e direta relacionando a especialidade do fornecedor ao pedido."
    }
  ]
}
```

*Nota: Em caso de não haver fornecedores que superem os critérios rigorosos definidos, o retorno deve ser `{"fornecedores_validos": []}`.*

**Proibições Absolutas:**
*   Nunca retorne mais de 3 objetos no array `"fornecedores_validos"`.
*   Nunca invente, alucine ou crie um "fornecedor modelo" que não seja proveniente da resposta real da busca no banco de dados.
