import os
import sys
from dotenv import load_dotenv

# Adiciona o diretório raiz ao path para importar de execution
sys.path.append(os.getcwd())

from execution.zapi_client import send_zapi_message

def test_zapi():
    load_dotenv()
    
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        # Substitua pelo seu número para teste se desejar, ex: "5511999999999"
        target = input("Digite o número de telefone para teste (DDI + DDD + Numero): ")
    
    if not target:
        print("Operação cancelada.")
        return

    message = "Olá! Este é um teste da MAIA para validar a integração Z-API."
    
    print(f"\n[INFO] Iniciando teste de envio para: {target}")
    result = send_zapi_message(target, message)
    
    if result:
        print("\n[OK] Teste concluído com sucesso!")
    else:
        print("\n[ERRO] Falha no teste. Verifique os logs acima.")

if __name__ == "__main__":
    test_zapi()
