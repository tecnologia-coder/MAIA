# Diretriz de Match de Fornecedores (MAIA)

**Objetivo:** Definir critérios rigorosos para a seleção final e indicação de fornecedores vindos da busca vetorial (Supabase), garantindo que apenas profissionais estritamente adequados sejam recomendados ao usuário.

## Contexto da Busca e Base de Dados

Os fornecedores são recuperados através de uma busca por similaridade (vetorial) na tabela `documents` (Vector Store). No entanto, os detalhes finais e a validação devem ser feitos cruzando com a tabela `parceiros`.

## Critério Objetivo de Validação (Regra dos 2/3)

Para tornar a validação determinística e reduzir a subjetividade, um fornecedor só pode ser aprovado se cumprir pelo menos **2 dos 3 critérios** abaixo:

1.  **Similaridade Técnica:** Score de similaridade >= threshold definido na `vector_search_directive` (atualmente 0.78).
2.  **Match de Categorização:** Subcategoria cadastrada do parceiro exatamente igual à subcategoria identificada no pedido.
3.  **Presença de Palavra-Chave:** Existência de palavra-chave explícita nas tags ou descrição do fornecedor que corresponda diretamente ao serviço solicitado.

### Regras de Descarte:
*   Se o fornecedor cumprir apenas **1 critério**: Rejeitar incondicionalmente.
*   Se o fornecedor cumprir **0 critérios**: Rejeitar incondicionalmente.
*   **Proibição de Similaridade Pura:** Nunca selecione um fornecedor baseado apenas no score de similaridade sem a validação cruzada dos outros dois critérios.

## Regras de Seleção Final

1. **Prioridade para Lista Vazia:** É preferível retornar uma lista vazia (`[]`) do que indicar um parceiro incorreto. A MAIA preza pela confiança da indicação.
2. **Limite Máximo:** Selecionar no **máximo 3 (três)** parceiros que tenham passado na validação técnica acima.
3. **Status:** Apenas parceiros com `status = 'active'` são elegíveis.
4. **Contato:** Somente parceiros com `whatsapp_link` válido podem ser recomendados.


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
