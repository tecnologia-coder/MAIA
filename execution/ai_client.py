import json
import os
import time
import threading
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from google import genai
from google.genai import types
from openai import OpenAI
import anthropic
from dotenv import load_dotenv

load_dotenv()

# --- Acumulador de Tokens (thread-safe) ---
# Cada chamada de LLM alimenta esse acumulador silenciosamente.
# O process_message.py coleta e reseta no final de cada execução.
_token_lock = threading.Lock()
_token_accumulator = {"triagem": 0, "validacao": 0, "resposta": 0, "outros": 0}
_current_stage = "outros"

def set_telemetry_stage(stage: str):
    """Define a etapa atual para atribuir tokens corretamente."""
    global _current_stage
    _current_stage = stage

def _accumulate_tokens(count: int):
    """Adiciona tokens ao acumulador na etapa atual."""
    with _token_lock:
        _token_accumulator[_current_stage] = _token_accumulator.get(_current_stage, 0) + count

def collect_and_reset_tokens() -> dict:
    """Coleta os tokens acumulados e reseta o acumulador. Retorna cópia."""
    with _token_lock:
        snapshot = dict(_token_accumulator)
        for k in _token_accumulator:
            _token_accumulator[k] = 0
    return snapshot

# Configuração da API Google
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=GOOGLE_API_KEY)

# Configuração da API OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
oa_client = OpenAI(api_key=OPENAI_API_KEY)

# Configuração da API Anthropic (Claude)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# Nome do modelo padrão (estável e moderno)
MODEL_NAME = "gemini-2.0-flash"
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# --- Configuração de Embeddings (multi-provedor) ---
# O store e a query DEVEM usar o mesmo provedor: vetores de provedores diferentes
# não são comparáveis. Trocar EMBEDDING_PROVIDER obriga re-embeddar tudo (sync --force).
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "google").lower()  # "google" | "openai"
GOOGLE_EMBEDDING_MODEL = os.getenv("GOOGLE_EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))  # casa com a coluna documents.embedding vector(1536)
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"  # 1536 dimensões

# --- Fallback cross-provider para LLMs de texto/JSON ---
LLM_FALLBACK = os.getenv("LLM_FALLBACK", "true").lower() == "true"

def is_retryable_error(exception):
    err_str = str(exception)
    return any(code in err_str for code in ["429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "INTERNAL"])

@retry(
    stop=stop_after_attempt(10),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    retry=retry_if_exception(is_retryable_error),
    reraise=True
)
def call_gemini(system_instruction, user_prompt, model_name=MODEL_NAME, json_mode=True):
    """
    Realiza uma chamada para o Gemini com retry automático para erros de cota (429).
    """
    try:
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type='application/json' if json_mode else 'text/plain'
        )
        
        response = client.models.generate_content(
            model=model_name,
            contents=user_prompt,
            config=config
        )

        # Acumula tokens de uso (Gemini expõe usage_metadata)
        try:
            usage = response.usage_metadata
            if usage:
                total = (usage.prompt_token_count or 0) + (usage.candidates_token_count or 0)
                _accumulate_tokens(total)
        except Exception:
            pass

        return response.text
    except Exception as e:
        if is_retryable_error(e):
            print(f"\n[AVISO] Limite de cota atingido. Tentando novamente em instantes...")
        else:
            print(f"[AI_CLIENT ERROR] Falha no Gemini: {e}")
        raise e

def _gemini_json_with_retry(system_instruction, user_prompt, model_name=MODEL_NAME):
    """Chamada Gemini garantindo saída JSON (1 retry de parse, conforme system_architecture_directive)."""
    attempts = 0
    max_json_attempts = 2

    while attempts < max_json_attempts:
        attempts += 1
        try:
            raw_res = call_gemini(system_instruction, user_prompt, model_name=model_name, json_mode=True)
            # Tenta limpar possíveis invólucros de markdown que a IA possa ter colocado
            clean_res = raw_res.strip()
            if clean_res.startswith("```json"):
                clean_res = clean_res.replace("```json", "", 1).replace("```", "", 1).strip()

            return json.loads(clean_res)
        except json.JSONDecodeError as e:
            if attempts == max_json_attempts:
                print(f"[AI_CLIENT CRITICAL] Falha total no parse JSON após {attempts} tentativas.")
                raise e
            print(f"[AI_CLIENT WARNING] Falha no parse JSON (tentativa {attempts}). Realizando retry...")
        except Exception as e:
            # Outros erros (como de rede/quota) já são tratados pelo decorador de retry
            raise e


def call_ai_with_json_retry(system_instruction, user_prompt, model_name=MODEL_NAME):
    """
    Triagem/validação em JSON. Provedor primário = Gemini; se ele falhar (quota/transport
    após os retries, ou parse JSON irrecuperável) e LLM_FALLBACK estiver ativo, cai para o
    Claude, que também retorna JSON parseado (contrato compatível).
    """
    try:
        return _gemini_json_with_retry(system_instruction, user_prompt, model_name=model_name)
    except Exception as e:
        if LLM_FALLBACK and claude_client:
            print(f"[FALLBACK] Gemini indisponível na triagem/validação ({e}) -> Claude")
            # Chama o Claude "cru" (sem o seu próprio fallback) para não voltar ao Gemini em loop.
            return _call_claude_raw(system_instruction, user_prompt)
        raise e

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=3, max=30),
    retry=retry_if_exception(is_retryable_error),
    reraise=True
)
def _call_claude_raw(system_instruction, user_prompt, model_name=CLAUDE_MODEL):
    """
    Realiza uma chamada para o Claude (Anthropic) e retorna JSON parseado.
    Usado para geração de mensagens humanizadas. Sem fallback — ver call_claude().
    """
    if not claude_client:
        raise RuntimeError("[CLAUDE] ANTHROPIC_API_KEY não configurada no .env")

    try:
        print(f"[CLAUDE] Gerando resposta com {model_name}...")
        response = claude_client.messages.create(
            model=model_name,
            max_tokens=1024,
            system=system_instruction,
            messages=[{"role": "user", "content": user_prompt}]
        )

        # Acumula tokens de uso (Claude expõe usage)
        try:
            usage = response.usage
            if usage:
                total = (usage.input_tokens or 0) + (usage.output_tokens or 0)
                _accumulate_tokens(total)
        except Exception:
            pass

        raw_res = response.content[0].text.strip()

        # Limpa possíveis invólucros de markdown
        if raw_res.startswith("```json"):
            raw_res = raw_res.replace("```json", "", 1).replace("```", "", 1).strip()
        if raw_res.startswith("```"):
            raw_res = raw_res.replace("```", "", 1).rsplit("```", 1)[0].strip()

        print("[CLAUDE] Resposta processada com sucesso.")
        return json.loads(raw_res)

    except json.JSONDecodeError as e:
        print(f"[CLAUDE CRITICAL] Falha no parse JSON: {raw_res[:300]}")
        raise e
    except Exception as e:
        if is_retryable_error(e):
            print(f"[CLAUDE] Erro retentável: {e}")
        else:
            print(f"[CLAUDE ERROR] Falha: {e}")
        raise e


def call_claude(system_instruction, user_prompt, model_name=CLAUDE_MODEL):
    """
    Geração de resposta com Claude (primário). Se o Claude falhar (após os retries, ou
    chave ausente) e LLM_FALLBACK estiver ativo, cai para o Gemini em modo JSON.
    """
    try:
        return _call_claude_raw(system_instruction, user_prompt, model_name=model_name)
    except Exception as e:
        if LLM_FALLBACK:
            print(f"[FALLBACK] Claude indisponivel ({e}) -> Gemini")
            # call_gemini (texto) já tem retry próprio; aqui só garantimos o JSON parseado.
            raw_res = call_gemini(system_instruction, user_prompt, json_mode=True)
            clean_res = raw_res.strip()
            if clean_res.startswith("```json"):
                clean_res = clean_res.replace("```json", "", 1).replace("```", "", 1).strip()
            elif clean_res.startswith("```"):
                clean_res = clean_res.replace("```", "", 1).rsplit("```", 1)[0].strip()
            return json.loads(clean_res)
        raise e


@retry(
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=2, min=3, max=30),
    retry=retry_if_exception(is_retryable_error),
    reraise=True,
)
def _embed_google(text, task_type):
    """Embedding via Google `gemini-embedding-001` (output configurável, default 1536 dims)."""
    response = client.models.embed_content(
        model=GOOGLE_EMBEDDING_MODEL,
        contents=text.replace("\n", " "),
        config=types.EmbedContentConfig(
            output_dimensionality=EMBEDDING_DIM,
            task_type=task_type,  # RETRIEVAL_DOCUMENT (store) | RETRIEVAL_QUERY (busca)
        ),
    )
    return list(response.embeddings[0].values)


def _embed_openai(text):
    """Embedding via OpenAI `text-embedding-3-small` (1536 dims)."""
    response = oa_client.embeddings.create(
        input=[text.replace("\n", " ")],
        model=OPENAI_EMBEDDING_MODEL,
    )
    return response.data[0].embedding


def get_embedding(text, task_type="RETRIEVAL_DOCUMENT"):
    """
    Gera embedding vetorial para o texto, despachando para o provedor configurado
    em EMBEDDING_PROVIDER ("google" | "openai"). O contrato (list[float]) é estável.

    `task_type` só afeta o Google (retrieval assimétrico): use RETRIEVAL_DOCUMENT ao
    indexar o store e RETRIEVAL_QUERY ao embedar a consulta.
    """
    try:
        if not text or not text.strip():
            return []
        if EMBEDDING_PROVIDER == "openai":
            return _embed_openai(text)
        return _embed_google(text, task_type)
    except Exception as e:
        print(f"[AI_CLIENT ERROR] Falha no Embedding ({EMBEDDING_PROVIDER}): {e}")
        raise e


def get_embedding_provider_info():
    """Provedor/dimensão ativos — usado pelo sync para gravar no metadata e detectar store misto."""
    return {
        "embedding_provider": EMBEDDING_PROVIDER,
        "embedding_dim": EMBEDDING_DIM,
    }

def load_directive(filename):
    """
    Carrega o conteúdo de uma diretiva da pasta directives/.
    """
    base_path = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(base_path, "directives", filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

@retry(
    stop=stop_after_attempt(10),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    retry=retry_if_exception(is_retryable_error),
    reraise=True
)
def _call_ai_agent_gemini(system_instruction, user_prompt, tools, model_name=MODEL_NAME):
    """
    Inicia uma sessão de chat com a LLM habilitada para Tool Calling (Agentic Flow).
    O cliente interage automaticamente com as funções Python fornecidas até compilar a resposta final em JSON.
    """
    try:
        print("[AI_AGENT] Iniciando sessão do Agente MAIA (Tool Calling)...")
        # Usamos application/json para forçar a entrega final conforme a diretiva
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=tools,
            temperature=0.2, # Baixa temperatura para validação determinística
            response_mime_type='application/json'
        )
        
        # O cliente Gemini com a versão moderna (google-genai) resolve as requisições de 
        # ferramentas em loop (automatic_function_calling não nativo na v1 precisa ser emulado ou 
        # repassado como tools na chamada se a sdk nova cuidar disso).
        # A API moderna do genai suporta automatic_function_calling=True no chat.
        chat_config = types.GenerateContentConfig(
             system_instruction=system_instruction,
             tools=tools,
             temperature=0.2,
             automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False)
        )

        chat = client.chats.create(model=model_name, config=chat_config)
        
        print("[AI_AGENT] Enviando Pedido e aguardando resoluções (Tools)...")
        response = chat.send_message(user_prompt)
        
        raw_res = response.text
        
        clean_res = raw_res.strip()
        if clean_res.startswith("```json"):
            clean_res = clean_res.replace("```json", "", 1).replace("```", "", 1).strip()
            
        print("[AI_AGENT] Retorno JSON processado com sucesso.")
        return json.loads(clean_res)

    except json.JSONDecodeError as e:
        print(f"[AI_AGENT CRITICAL] Falha no parse JSON final retornado pelo Agente.")
        print(f"[AI_AGENT CRITICAL] Raw response: {raw_res[:500]}")
        raise e
    except Exception as e:
        if is_retryable_error(e):
            print(f"\n[AVISO] Limite de cota atingido no Agente. Tentando novamente...")
        else:
            print(f"[AI_AGENT ERROR] Falha no fluxo do Agente: {e}")
        raise e


def call_ai_agent(system_instruction, user_prompt, tools, model_name=MODEL_NAME):
    """
    Agente de validação com tool-calling (Gemini, primário). Se o Gemini falhar de vez
    e LLM_FALLBACK estiver ativo, degrada para uma validação JSON SEM tools
    (call_ai_with_json_retry -> Gemini->Claude). Sem tools o agente não chama
    link_fornecedor, mas o backfill defensivo em process_message.py cobre o contato.
    """
    try:
        return _call_ai_agent_gemini(system_instruction, user_prompt, tools, model_name=model_name)
    except Exception as e:
        if LLM_FALLBACK:
            print(f"[FALLBACK] Agente (tool-calling) indisponível ({e}) -> validação JSON sem tools")
            return call_ai_with_json_retry(system_instruction, user_prompt)
        raise e
