-- =====================================================================
-- MAIA — Migration 001
-- Restaura a busca vetorial e cria índices de performance.
-- Aplicar no SQL Editor do Supabase (projeto elbospxpocdzpsipqfof).
--
-- Contexto: a função `match_documents` não existia no banco, fazendo a
-- busca vetorial falhar (PGRST202) e cair sempre no fallback lexical.
-- =====================================================================

-- 1. Extensão pgvector (idempotente)
create extension if not exists vector;

-- 2. Função de busca por similaridade de cosseno usada por
--    execution/search_suppliers.search_suppliers_by_text.
--    Assinatura compatível com a chamada: query_embedding, filter, match_count.
--    OBS: o tipo de retorno de `id` segue documents.id (bigint). Se a coluna
--    for de outro tipo (ex.: uuid), ajustar a declaração abaixo.
create or replace function public.match_documents(
    query_embedding vector(1536),
    filter jsonb default '{}',
    match_count int default 10
)
returns table (
    id bigint,
    content text,
    metadata jsonb,
    similarity float
)
language plpgsql
as $$
begin
    return query
    select
        d.id,
        d.content,
        d.metadata,
        1 - (d.embedding <=> query_embedding) as similarity
    from documents d
    where d.metadata @> filter
    order by d.embedding <=> query_embedding
    limit match_count;
end;
$$;

-- 3. Índice ANN (HNSW, cosseno) para acelerar a busca vetorial.
--    Sem ele a busca faz full scan. Requer pgvector >= 0.5.
create index if not exists idx_documents_embedding_hnsw
    on documents using hnsw (embedding vector_cosine_ops);

-- 4. Índices para o pré-filtro estruturado determinístico em `parceiros`.
create index if not exists idx_parceiros_status_aprovacao on parceiros (status_aprovacao);
create index if not exists idx_parceiros_tem_espaco_kids on parceiros (tem_espaco_kids);
create index if not exists idx_parceiros_tem_menu_kids on parceiros (tem_menu_kids);
create index if not exists idx_parceiros_tem_trocador on parceiros (tem_trocador);

-- 5. (Opcional / performance do fallback lexical) busca por similaridade textual.
create extension if not exists pg_trgm;
create index if not exists idx_documents_content_trgm
    on documents using gin (content gin_trgm_ops);

-- 6. Recarrega o schema cache do PostgREST para expor a função imediatamente.
notify pgrst, 'reload schema';
