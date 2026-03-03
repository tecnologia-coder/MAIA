import sys
import os

# Adiciona o diretório atual ao sys.path para importar execution
sys.path.append(os.getcwd())

from execution.zapi_client import send_to_n8n_relay
from dotenv import load_dotenv

load_dotenv()

def test_n8n_relay():
    print("--- Testando Relay para o n8n ---")
    
    # Dados de teste
    test_phone = "5512999999999" # Mock phone
    test_message = "Esta é uma mensagem de teste da MAIA enviada para o n8n para validação do relay."
    
    try:
        print(f"Enviando mensagem para o relay do n8n...")
        result = send_to_n8n_relay(test_phone, test_message)
        
        if result:
            print("\n[SUCESSO] Relay executado com sucesso!")
            print(f"Resposta do n8n: {result}")
        else:
            print("\n[FALHA] O relay não retornou sucesso. Verifique os logs e a URL no .env.")
            
    except Exception as e:
        print(f"\n[ERRO] Falha crítica no teste de relay: {e}")

if __name__ == "__main__":
    test_n8n_relay()
