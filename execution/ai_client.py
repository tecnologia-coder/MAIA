import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# Configuração da API
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=GOOGLE_API_KEY)

# Nome do modelo padrão (estável e moderno)
MODEL_NAME = "gemini-2.0-flash"
EMBEDDING_MODEL = "text-embedding-004"

def call_gemini(system_instruction, user_prompt, model_name=MODEL_NAME, json_mode=True):
    """
    Realiza uma chamada para o Gemini usando a nova biblioteca google-genai.
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
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            print("\n[AVISO] Limite de cota do Gemini atingido (429 RESOURCE_EXHAUSTED).")
            print("Isso geralmente ocorre em chaves gratuitas. Aguarde um momento e tente novamente.")
        else:
            print(f"[AI_CLIENT ERROR] Falha no Gemini: {e}")
        raise e

def get_embedding(text, model=EMBEDDING_MODEL):
    """
    Gera embedding vetorial para o texto fornecido.
    """
    try:
        result = client.models.embed_content(
            model=model,
            contents=text,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
        )
        # Na nova lib, result.embeddings é uma lista de objetos Embedding
        return result.embeddings[0].values
    except Exception as e:
        print(f"[AI_CLIENT ERROR] Falha no Embedding: {e}")
        raise e

def load_directive(filename):
    """
    Carrega o conteúdo de uma diretiva da pasta directives/.
    """
    base_path = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(base_path, "directives", filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
