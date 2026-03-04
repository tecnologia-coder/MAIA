import os
from google import genai
from google.genai import types
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Configuração da API Google
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=GOOGLE_API_KEY)

# Configuração da API OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
oa_client = OpenAI(api_key=OPENAI_API_KEY)

# Nome do modelo padrão (estável e moderno)
MODEL_NAME = "gemini-3.1-flash"
EMBEDDING_MODEL = "text-embedding-3-small" # 1536 dimensões

import time
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

def is_quota_error(exception):
    return "429" in str(exception) or "RESOURCE_EXHAUSTED" in str(exception)

@retry(
    stop=stop_after_attempt(10),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    retry=retry_if_exception(is_quota_error),
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
        
        return response.text
    except Exception as e:
        if is_quota_error(e):
            print(f"\n[AVISO] Limite de cota atingido. Tentando novamente em instantes...")
        else:
            print(f"[AI_CLIENT ERROR] Falha no Gemini: {e}")
        raise e

def get_embedding(text, model=EMBEDDING_MODEL):
    """
    Gera embedding vetorial para o texto fornecido usando OpenAI.
    """
    try:
        # Garante que o texto não esteja vazio
        if not text or not text.strip():
            return []

        response = oa_client.embeddings.create(
            input=[text.replace("\n", " ")],
            model=model
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"[AI_CLIENT ERROR] Falha no Embedding OpenAI: {e}")
        raise e

def load_directive(filename):
    """
    Carrega o conteúdo de uma diretiva da pasta directives/.
    """
    base_path = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(base_path, "directives", filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
