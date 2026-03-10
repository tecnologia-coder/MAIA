"""
Script de diagnóstico para isolar onde a busca de fornecedores está falhando.
Testa cada etapa da pipeline individualmente.
"""
import json
import sys
import os

# Adiciona a raiz do projeto ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

TEST_MESSAGE = "Alguém conhece consultoria de amamentação para quem vai ter gêmeos?"

def step1_vector_search():
    """Testa a busca vetorial diretamente."""
    print("\n" + "="*60)
    print("ETAPA 1: BUSCA VETORIAL DIRETA")
    print("="*60)

    from execution.search_suppliers import search_suppliers_by_text

    queries = [
        "consultoria amamentação gêmeos",
        "Saúde Materno-infantil amamentação gêmeos consultoria",
        "amamentação gêmeos",
    ]

    for q in queries:
        print(f"\n--- Query: '{q}' ---")
        results = search_suppliers_by_text(q)
        print(f"Resultados: {len(results)}")
        for r in results[:5]:
            meta = r.get("metadata", {})
            sim = r.get("similarity", "N/A")
            nome = meta.get("nome", "?")
            fid = meta.get("id", "?")
            subcat = meta.get("subcategoria", "?")
            content_preview = r.get("content", "")[:120]
            print(f"  - [{sim:.3f}] ID={fid} | {nome} | Sub: {subcat}")
            print(f"    Content: {content_preview}...")

def step2_categorization():
    """Testa a categorização da mensagem."""
    print("\n" + "="*60)
    print("ETAPA 2: CATEGORIZAÇÃO")
    print("="*60)

    from execution.ai_client import call_ai_with_json_retry, load_directive
    from execution.get_metadata import get_metadata

    cat_instr = load_directive("categorization_directive.md")
    metadata_context = get_metadata()
    cat_prompt = f"Categorias reais disponíveis:\n{json.dumps(metadata_context)}\n\nPedido do Usuário: {TEST_MESSAGE}"

    cat_res = call_ai_with_json_retry(cat_instr, cat_prompt)
    print(f"Resultado categorização: {json.dumps(cat_res, ensure_ascii=False, indent=2)}")
    return cat_res

def step3_agent_tools_direct(cat_res):
    """Testa as tools do agente diretamente (sem passar pela LLM)."""
    print("\n" + "="*60)
    print("ETAPA 3: TOOLS DO AGENTE (CHAMADA DIRETA)")
    print("="*60)

    from execution.agent_tools import supabase_vector_store, get_categoria, get_subcategoria, link_fornecedor

    pedido_cat = cat_res.get("pedido_categoria")
    pedido_sub = cat_res.get("pedido_subcategoria")
    pedido_desc = cat_res.get("pedido_descricao", "")

    cat_name = get_categoria(pedido_cat)
    sub_name = get_subcategoria(pedido_sub)
    print(f"Categoria: {cat_name} (ID: {pedido_cat})")
    print(f"Subcategoria: {sub_name} (ID: {pedido_sub})")

    # Simulando a query que o agente construiria
    query = f"{cat_name} {sub_name} - {pedido_desc} {TEST_MESSAGE}"
    print(f"\nQuery construída: '{query}'")

    raw = supabase_vector_store(query)
    candidates = json.loads(raw)
    cands = candidates.get("candidatos", [])
    print(f"\nCandidatos retornados: {len(cands)}")
    for c in cands:
        meta = c.get("metadata", {})
        sim = c.get("similarity", "N/A")
        nome = meta.get("nome", "?")
        fid = meta.get("id", "?")
        content_preview = c.get("content", "")[:120]
        print(f"  - [{sim if isinstance(sim, str) else f'{sim:.3f}'}] ID={fid} | {nome}")
        print(f"    Content: {content_preview}...")

    # Testa link_fornecedor para cada candidato
    for c in cands[:3]:
        fid = c.get("metadata", {}).get("id")
        if fid:
            link_data = link_fornecedor(fid)
            print(f"\n  link_fornecedor({fid}): {link_data}")

def step4_full_agent():
    """Testa o fluxo completo do agente (com LLM + Tool Calling)."""
    print("\n" + "="*60)
    print("ETAPA 4: AGENTE COMPLETO (LLM + TOOL CALLING)")
    print("="*60)

    from execution.ai_client import call_ai_agent, load_directive
    from execution.agent_tools import agentic_tools
    from execution.get_metadata import get_metadata

    cat_res = step2_categorization()
    pedido_cat = cat_res.get("pedido_categoria")
    pedido_sub = cat_res.get("pedido_subcategoria")
    pedido_desc = cat_res.get("pedido_descricao", "")

    match_instr = load_directive("supplier_match_directive.md")
    agent_prompt = f"""
Pedido original do usuário: {TEST_MESSAGE}

Contexto processado:
- Categoria ID: {pedido_cat}
- Subcategoria ID: {pedido_sub}
- Descrição da IA de triagem: {pedido_desc}

USE AS FERRAMENTAS DISPONÍVEIS para cumprir seu objetivo de recomendação conforme a diretriz.
"""
    print(f"Prompt para o Agente:\n{agent_prompt}")

    try:
        agent_res = call_ai_agent(match_instr, agent_prompt, tools=agentic_tools)
        print(f"\nResultado do Agente:")
        print(json.dumps(agent_res, ensure_ascii=False, indent=2))

        recs = agent_res.get("recomendacoes", [])
        print(f"\nFornecedores recomendados: {len(recs)}")
        for r in recs:
            print(f"  - ID: {r.get('fornecedor_id')} | Motivo: {r.get('motivo_recomendacao', '')[:80]}")
    except Exception as e:
        print(f"\nERRO NO AGENTE: {type(e).__name__}: {e}")

if __name__ == "__main__":
    print("DIAGNÓSTICO DE MATCHING - MAIA")
    print(f"Mensagem de teste: '{TEST_MESSAGE}'")

    if len(sys.argv) > 1:
        step = sys.argv[1]
    else:
        step = "all"

    if step in ("1", "all"):
        step1_vector_search()

    if step in ("2", "all", "2+"):
        cat_res = step2_categorization()

    if step in ("3", "all", "2+"):
        if 'cat_res' not in dir():
            cat_res = step2_categorization()
        step3_agent_tools_direct(cat_res)

    if step in ("4", "all"):
        step4_full_agent()

    print("\n" + "="*60)
    print("DIAGNÓSTICO CONCLUÍDO")
    print("="*60)
