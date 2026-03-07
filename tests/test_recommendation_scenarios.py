import json
import unittest
from unittest.mock import patch, MagicMock
from execution.process_message import process_whatsapp_message_e2e

# Cenários de Teste definidos no plano
TEST_SCENARIOS = [
    {
        "name": "POS_01: Saúde Infantil (Pediatra)",
        "message": "Preciso de indicação de uma pediatra ou especialista em saúde infantil em SP.",
        "expected": "Positive"
    },
    {
        "name": "POS_02: Amamentação (Gêmeos)",
        "message": "Alguém conhece consultoria de amamentação para quem vai ter gêmeos?",
        "expected": "Positive"
    },
    {
        "name": "POS_03: Educação (Robótica/STEAM)",
        "message": "Queria indicação de cursos ou atividades educativas tipo robótica ou steam para crianças.",
        "expected": "Positive"
    },
    {
        "name": "NEG_01: Mecânico Automotivo",
        "message": "Alguém indica um mecânico de confiança para trocar o óleo do carro?",
        "expected": "Negative"
    },
    {
        "name": "NEG_02: Alemão para Negócios",
        "message": "Preciso de um professor particular de Alemão para negócios.",
        "expected": "Negative"
    },
    {
        "name": "NEG_03: Hotelzinho Pet",
        "message": "Procuro indicação de hotelzinho ou adestrador para cães de grande porte.",
        "expected": "Negative"
    }
]

def run_scenarios():
    print("\n" + "="*60)
    print("      INICIANDO TESTES DE RECOMENDAÇÃO MAIA (MOCK MODE)")
    print("="*60)

    # Mocar as funções de envio para não disparar mensagens reais
    with patch('execution.process_message.send_zapi_message') as mock_send, \
         patch('execution.process_message.send_zapi_button_actions') as mock_buttons:
        
        mock_send.return_value = {"status": "success", "messageId": "mock_id"}
        mock_buttons.return_value = {"status": "success", "messageId": "mock_id"}

        for scenario in TEST_SCENARIOS:
            print(f"\n>>> TESTE: {scenario['name']}")
            print(f"MENSAGEM: '{scenario['message']}'")
            
            try:
                result, error = process_whatsapp_message_e2e(
                    scenario["message"],
                    real_user_phone="5511999999999",
                    target_phone="5511999999999"
                )
                
                if error:
                    print(f"STATUS: FALHA NA TRIAGEM/ERRO - {error}")
                else:
                    msg = result.get("mensagem_final", "")
                    print(f"STATUS: SUCESSO NO PROCESSAMENTO")
                    print("-" * 20)
                    # Encodamos para evitar erro de charmap no windows console ao printar emojis
                    print(f"RESPOSTA MAIA:\n{msg.encode('ascii', 'ignore').decode('ascii')}")
                    print("-" * 20)
                    
                    # Verificar se enviou botões ou texto
                    if mock_buttons.called:
                        print(f"ENVIO: Botões de Ação (URL) utilizados. Chamadas: {mock_buttons.call_count}")
                    else:
                        print(f"ENVIO: Texto Simples utilizado.")
                
            except Exception as e:
                print(f"STATUS: ERRO CRÍTICO NO TESTE - {str(e)}")
            
            # Resetar mocks para o próximo cenário
            mock_send.reset_mock()
            mock_buttons.reset_mock()

    print("\n" + "="*60)
    print("      FIM DOS TESTES")
    print("="*60)

if __name__ == "__main__":
    run_scenarios()
