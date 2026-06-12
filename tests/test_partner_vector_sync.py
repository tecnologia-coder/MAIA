import asyncio
import os
import unittest
from copy import deepcopy
from unittest.mock import MagicMock, patch

from fastapi import BackgroundTasks

from execution import sync_documents
import main


class Result:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, db, table_name, op, payload=None):
        self.db = db
        self.table_name = table_name
        self.op = op
        self.payload = payload
        self.filters = []
        self.in_filters = []
        self.on_conflict = None

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def in_(self, column, values):
        self.in_filters.append((column, set(values)))
        return self

    def _matches(self, row):
        for column, value in self.filters:
            if row.get(column) != value:
                return False
        for column, values in self.in_filters:
            if row.get(column) not in values:
                return False
        return True

    def execute(self):
        table = self.db.tables[self.table_name]
        if self.op == "select":
            return Result([deepcopy(r) for r in table if self._matches(r)])
        if self.op == "delete":
            deleted = [r for r in table if self._matches(r)]
            self.db.tables[self.table_name] = [r for r in table if not self._matches(r)]
            return Result(deepcopy(deleted))
        if self.op == "insert":
            row = deepcopy(self.payload)
            table.append(row)
            return Result([deepcopy(row)])
        if self.op == "update":
            updated = []
            for row in table:
                if self._matches(row):
                    row.update(deepcopy(self.payload))
                    updated.append(deepcopy(row))
            return Result(updated)
        if self.op == "upsert":
            row = deepcopy(self.payload)
            conflict = self.on_conflict or "id"
            for idx, existing in enumerate(table):
                if existing.get(conflict) == row.get(conflict):
                    table[idx] = row
                    return Result([deepcopy(row)])
            table.append(row)
            return Result([deepcopy(row)])
        raise AssertionError(f"Unsupported op: {self.op}")


class FakeTable:
    def __init__(self, db, table_name):
        self.db = db
        self.table_name = table_name

    def select(self, columns):
        return FakeQuery(self.db, self.table_name, "select").select(columns)

    def delete(self):
        return FakeQuery(self.db, self.table_name, "delete")

    def insert(self, payload):
        return FakeQuery(self.db, self.table_name, "insert", payload)

    def update(self, payload):
        return FakeQuery(self.db, self.table_name, "update", payload)

    def upsert(self, payload, on_conflict=None):
        query = FakeQuery(self.db, self.table_name, "upsert", payload)
        query.on_conflict = on_conflict
        return query


class FakeSupabase:
    def __init__(self, parceiros=None, documents=None, cancelados=None):
        self.tables = {
            "parceiros": deepcopy(parceiros or []),
            "documents": deepcopy(documents or []),
            "parceiros_cancelados": deepcopy(cancelados or []),
        }

    def table(self, table_name):
        return FakeTable(self, table_name)


def partner(pid=1, status="aprovado"):
    return {
        "id": pid,
        "nome": f"Parceiro {pid}",
        "categoria": "SAUDE",
        "subcategoria": "PEDIATRA",
        "palavras_chave": "crianca",
        "descricao": "Atendimento infantil",
        "descricao_negocio": "",
        "diferenciais": [],
        "cidade": "Maringa",
        "faixa_preco": "",
        "latitude": None,
        "longitude": None,
        "tem_espaco_kids": False,
        "tem_menu_kids": False,
        "tem_trocador": False,
        "tem_cadeira_alimentacao": False,
        "is_rota_gastronomica": False,
        "status_aprovacao": status,
        "status_pagamento": "ativo",
        "is_vip": True,
        "whatsapp_link": "https://wa.me/5500000000000",
        "foto_espaco1": "https://example.com/foto.jpg",
    }


class PartnerVectorSyncTests(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch("execution.sync_documents.build_taxonomy_lookup", return_value=({}, {}, {})),
            patch("execution.sync_documents.get_embedding_provider_info", return_value={
                "embedding_provider": "test",
                "embedding_dim": 1536,
            }),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_sync_partner_inserts_approved_partner(self):
        db = FakeSupabase(parceiros=[partner(1, "aprovado")])
        with patch("execution.sync_documents.get_embedding", return_value=[0.1, 0.2]):
            result = sync_documents.sync_partner(1, sb=db)

        self.assertEqual(result["inserted"], 1)
        self.assertEqual(len(db.tables["documents"]), 1)
        self.assertEqual(db.tables["documents"][0]["metadata"]["ID"], 1)

    def test_sync_partner_removes_pending_partner_from_documents(self):
        db = FakeSupabase(
            parceiros=[partner(2, "pendente")],
            documents=[{"id": 10, "content": "old", "metadata": {"ID": 2}}],
        )
        result = sync_documents.sync_partner(2, sb=db)

        self.assertEqual(result["deleted"], 1)
        self.assertEqual(db.tables["documents"], [])

    def test_move_cancelled_partner_moves_and_removes_documents(self):
        db = FakeSupabase(
            parceiros=[partner(3, "cancelado")],
            documents=[{"id": 11, "content": "old", "metadata": {"ID": 3}}],
        )
        result = sync_documents.move_cancelled_partner(3, sb=db)

        self.assertEqual(result["moved"], 1)
        self.assertEqual(db.tables["documents"], [])
        self.assertEqual(db.tables["parceiros"], [])
        self.assertEqual(db.tables["parceiros_cancelados"][0]["id"], 3)
        self.assertEqual(db.tables["parceiros_cancelados"][0]["status_aprovacao"], "cancelado")
        self.assertNotIn("whatsapp_link", db.tables["parceiros_cancelados"][0])
        self.assertNotIn("foto_espaco1", db.tables["parceiros_cancelados"][0])

    def test_sync_partner_same_content_does_not_reembed(self):
        p = partner(4, "aprovado")
        content = sync_documents.build_content(p)
        db = FakeSupabase(
            parceiros=[p],
            documents=[{
                "id": 12,
                "content": content,
                "metadata": {"ID": 4, "embedding_provider": "test"},
            }],
        )
        embed = MagicMock()
        with patch("execution.sync_documents.get_embedding", embed):
            result = sync_documents.sync_partner(4, sb=db)

        embed.assert_not_called()
        self.assertEqual(result["skipped"], 1)


class PartnerWebhookTests(unittest.TestCase):
    def test_handle_delete_event_removes_documents(self):
        with patch("main.remove_partner_documents") as remove:
            main._handle_partner_webhook({"type": "DELETE", "old_record": {"id": 9}})
        remove.assert_called_once_with(9)

    def test_handle_cancelled_update_moves_partner(self):
        with patch("main.move_cancelled_partner") as move:
            main._handle_partner_webhook({"type": "UPDATE", "record": {"id": 8, "status_aprovacao": "cancelado"}})
        move.assert_called_once_with(8)

    def test_endpoint_accepts_valid_webhook_and_schedules_task(self):
        class Request:
            headers = {"x-webhook-secret": "secret"}

            async def json(self):
                return {"type": "INSERT", "record": {"id": 7, "status_aprovacao": "aprovado"}}

        old_secret = os.environ.get("SUPABASE_PARTNER_SYNC_SECRET")
        os.environ["SUPABASE_PARTNER_SYNC_SECRET"] = "secret"
        background = BackgroundTasks()
        try:
            response = asyncio.run(main.supabase_partner_webhook(Request(), background))
            self.assertEqual(response["partner_id"], 7)
            with patch("main.sync_partner") as sync:
                asyncio.run(background())
            sync.assert_called_once_with(7)
        finally:
            if old_secret is None:
                os.environ.pop("SUPABASE_PARTNER_SYNC_SECRET", None)
            else:
                os.environ["SUPABASE_PARTNER_SYNC_SECRET"] = old_secret


if __name__ == "__main__":
    unittest.main()
