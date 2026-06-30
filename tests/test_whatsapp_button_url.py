import unittest
from urllib.parse import parse_qs, urlparse

from execution.zapi_client import prepare_whatsapp_button_url


class WhatsAppButtonUrlTests(unittest.TestCase):
    def test_current_database_link_is_rebuilt_with_encoded_text(self):
        raw = (
            "https://wa.me/5544997728642"
            "?text=Oi!%20Conheci%20o%20trabalho%20de%20vocês%20através%20do%20site%20da%20A%20Mãe%20Indica."
            "%20Como%20confio%20muito%20nas%20indicações%20da%20comunidade%2C%20resolvi%20chamar"
            "%20para%20tirar%20algumas%20dúvidas.%20Pode%20me%20ajudar%3F%20🧡"
        )

        prepared = prepare_whatsapp_button_url(raw)

        self.assertIsNotNone(prepared)
        self.assertTrue(prepared.startswith("https://api.whatsapp.com/send?"))
        self.assertNotIn("%2520", prepared)
        self.assertNotIn(" ", prepared)

        parsed = urlparse(prepared)
        params = parse_qs(parsed.query)
        self.assertEqual(params["phone"], ["5544997728642"])
        self.assertEqual(
            params["text"],
            [
                "Oi! Conheci o trabalho de vocês através do site da A Mãe Indica. "
                "Como confio muito nas indicações da comunidade, resolvi chamar "
                "para tirar algumas dúvidas. Pode me ajudar? 🧡"
            ],
        )

    def test_simple_link_without_text_is_preserved(self):
        raw = "https://wa.me/5544997728642"

        self.assertEqual(prepare_whatsapp_button_url(raw), raw)

    def test_existing_api_whatsapp_link_is_normalized(self):
        raw = "https://api.whatsapp.com/send?phone=+55 (44) 99772-8642&text=Oi%20tudo%20bem%3F"

        prepared = prepare_whatsapp_button_url(raw)

        parsed = urlparse(prepared)
        params = parse_qs(parsed.query)
        self.assertEqual(params["phone"], ["5544997728642"])
        self.assertEqual(params["text"], ["Oi tudo bem?"])

    def test_malformed_link_returns_none(self):
        self.assertIsNone(prepare_whatsapp_button_url("not a whatsapp url"))
        self.assertIsNone(prepare_whatsapp_button_url("https://example.com/send?text=Oi"))
        self.assertIsNone(prepare_whatsapp_button_url(None))


if __name__ == "__main__":
    unittest.main()
