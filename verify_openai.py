import sys
import os

# Adiciona o diretório atual ao sys.path para importar execution
sys.path.append(os.getcwd())

from execution.ai_client import get_embedding
from dotenv import load_dotenv

load_dotenv()

def test_embedding():
    print("--- Testando Embedding OpenAI ---")
    test_text = "Teste de busca por fornecedores de tubos de aço."
    
    try:
        embedding = get_embedding(test_text)
        dimension = len(embedding)
        
        print(f"Embedding gerado com sucesso!")
        print(f"Dimensões do vetor: {dimension}")
        print(f"Primeiros 5 valores: {embedding[:5]}")
        
        if dimension == 1536:
            print("\n[SUCESSO] Dimensão correta (1536) detectada!")
        else:
            print(f"\n[ERRO] Dimensão inesperada: {dimension}. Esperado: 1536.")
            
    except Exception as e:
        print(f"\n[FALHA] Erro ao gerar embedding: {e}")
        print("Certifique-se de que a OPENAI_API_KEY no arquivo .env seja válida.")

if __name__ == "__main__":
    test_embedding()
