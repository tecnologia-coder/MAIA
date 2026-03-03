# Diretriz de Categorização de Pedidos

**Objetivo:** Classificar cada pedido *válido* de indicação (recebido no WhatsApp) vinculando-o a exatamente uma categoria e uma subcategoria em nosso banco de dados.

## Bases de Referência Obrigatórias
A classificação deve ser baseada nos dados pré-existentes nas tabelas:
- `categorias`
- `subcategorias`

## Regras Obrigatórias de Classificação

1. **Escolha Única (Categoria):** Você deve selecionar exatamente UMA (1) `categoria_id` correspondente ao pedido.
2. **Escolha Única (Subcategoria):** Você deve selecionar exatamente UMA (1) `subcategoria_id` correspondente ao pedido, garantindo que esta pertença à categoria escolhida.
3. **Proibido Nomes em Texto:** Nunca retorne, deduz ou liste nomes (textos) das categorias. Você deve usar e devolver **exclusivamente os identificadores numéricos**.
4. **Somente IDs Numéricos:** Tanto a Categoria quanto a Subcategoria devem ser apresentadas como um `number` no objeto JSON de resposta.
5. **Critério de Ambiguidade:** Caso um mesmo pedido possa se enquadrar em mais de uma árvore de categorias, você deve escolher a ramificação mais **específica** pertinente à solicitação central.
6. **Estrita Adesão ao Cadastro:** Nunca invente, crie ou infira a existência de categorias genéricas que não existam explicitamente na base consultada. 

## Regras de Descrição de Resumo

Além das categorias, um breve resumo descritivo do pedido deve ser formulado em terceira pessoa, respeitando as seguintes restrições:
- A frase inicial **DEVE** começar com: "O usuário busca..." ou "A usuária pediu...".
- Deve ser uma reescrita puramente objetiva, focada na necessidade da indicação (sem julgamentos, opiniões ou detalhes não relacionados ao pedido base).
- O sumário **NÃO PODE** ultrapassar 2 (duas) frases de extensão no total.

## Formato de Saída Obrigatório

A saída deve ser **exclusiva e estritamente** o objeto JSON abaixo, sem blocos de texto adicionais, saudações ou explicações fora das chaves:

```json
{
  "pedido_categoria": 0,
  "pedido_subcategoria": 0,
  "pedido_descricao": "O usuário busca a indicação de um eletricista para reparo de chuveiro na zona leste."
}
```

*Nota: Utilize exatamente os nomes dos campos da tabela `pedidos_indicacao`: `pedido_categoria`, `pedido_subcategoria` e `pedido_descricao`.*
