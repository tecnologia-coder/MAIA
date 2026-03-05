# Diretiva de Classificação de Pedidos de Indicação

**Objetivo:** Definir regras determinísticas para classificar mensagens recebidas em grupos de WhatsApp como um pedido legítimo de indicação (`PEDIDO_INDICACAO` ou `TRUE`) ou não (`NAO_PEDIDO` ou `FALSE`).

## Regras Obrigatórias e Critérios Semânticos

A análise semântica da mensagem deve seguir as regras abaixo para identificar a **intenção** de buscar uma recomendação que o usuário ainda não possui.

1. **Ignorar mensagens próprias:** Mensagens enviadas pelo próprio sistema (`fromMe = true`) devem ser classificadas como FALSE.
2. **Ignorar grupos excluídos:** Mensagens vindas de grupos configurados como excluídos não devem ser processadas como pedidos (classificar como FALSE).
3. **Pedidos válidos (TRUE):** Um pedido só é válido se o usuário estiver ativamente buscando:
   - Sugestões
   - Indicações
   - Experiências de terceiros para tomar uma decisão
   - Recomendações
   *(Intenções que usam verbos e expressões como "preciso de indicação", "alguém recomenda", "busco", "sabem de" indicam pedidos explícitos)*
4. **Opinião sobre fornecedor específico já conhecido (FALSE):** Se o usuário já selecionou ou conhece um prestador e pergunta *apenas a opinião* sobre ele (Ex: "A clínica X é boa?", "Alguém já usou o serviço do Fulano?"), deve ser classificado como FALSE.
5. **Relatos ou comentários (FALSE):** Mensagens que são relatos pessoais, comentários sem pergunta, desabafos ou constatações, sem solicitação clara de indicação: classificar como FALSE.
6. **Dúvida genérica (FALSE):** Dúvidas que apenas perguntam "como fazer" algo, "o que é" ou pedem informações gerais sem pedir uma recomendação de serviço, produto ou profissional: classificar como FALSE.

## Critério de Confiança e Segurança

Para garantir a integridade do pipeline e evitar falsos positivos que consumam recursos desnecessariamente, aplique as seguintes regras:

1. **Ambiguidade Semântica:** Se houver dúvida relevante sobre o que o usuário deseja, ou se a frase permitir múltiplas interpretações contraditórias, classifique como FALSE.
2. **Precisão sobre Abrangência:** É preferível ignorar um pedido legítimo (falso negativo) do que processar um pedido inválido (falso positivo). Na dúvida, decline.
3. **Indicação Explícita:** Se o pedido não for *explicitamente* uma busca por indicação, recomendação ou sugestão de terceiros, classifique como FALSE.
4. **Mensagens Vagas:** Mensagens muito curtas ou sem contexto suficiente (Ex: "Algum contato?", "Preciso de ajuda.") sem especificar o tipo de serviço/produto devem ser classificadas como FALSE.

## Formato de Saída Obrigatório

A resposta **NÃO DEVE** conter nenhum texto livre, marcações markdown fora do bloco de código ou justificativas adicionais além do exigido. 

A saída deve ser **exclusivamente** um objeto JSON estruturado, conforme o modelo abaixo:

```json
{
  "is_valid_request": boolean,
  "confidence": number,
  "reason": "explicação objetiva"
}
```

### Detalhamento dos Campos:

*   `"is_valid_request"`: Valor booleano. Retorna `true` apenas se a mensagem for um pedido de indicação válido e o nível de confiança for adequado.
*   `"confidence"`: Valor numérico entre **0 e 1**. Representa a certeza da LLM na classificação. 
    *   *Nota: O sistema Python abortará automaticamente se o valor for menor que 0.80.*
*   `"reason"`: String curta, objetiva e direta contendo a explicação da classificação embasada nas regras desta diretriz.

**Proibições:**
- Não permitir respostas textuais fora do JSON.
- Não usar variações na nomenclatura das chaves JSON.
- Não incluir respostas introdutórias como "Aqui está a análise...".

