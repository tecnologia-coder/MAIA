import { serve } from "https://deno.land/std@0.190.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.90.1";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-webhook-secret, cyclopay-webhook-sec, cyclopay_webhook_sec, x-signature",
};

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });

const CANCELADOS = ["canceled", "cancelled", "expired"];
const REEMBOLSADOS = ["refunded", "chargeback"];
const CANCELLED_COPY_COLUMNS = new Set([
  "id",
  "nome",
  "categoria",
  "subcategoria",
  "palavras_chave",
  "cidade",
  "instagram_url",
  "email",
  "endereco_fisico",
  "site_url",
  "is_vip",
  "logo_url",
  "created_at",
  "status_aprovacao",
  "termos_aceitos",
  "vantagem_exclusiva",
  "telefone_whatsapp",
  "is_rota_gastronomica",
  "tem_espaco_kids",
  "tem_menu_kids",
  "tem_trocador",
  "tem_cadeira_alimentacao",
  "diagnostico_babyfriendly",
  "user_id",
  "data_fim_trial",
  "plano_escolhido",
  "recorrencia",
  "status_pagamento",
  "diferenciais",
  "descricao_negocio",
  "descricao",
  "latitude",
  "longitude",
  "horario_funcionamento",
  "faixa_preco",
  "id_assinatura_cyclopay",
  "ultima_sincronizacao_cyclopay",
  "data_termos",
  "ultimo_email_enviado",
  "ultima_alteracao_senha",
  "contato_gerente_interno",
  "texto_adesao",
  "data_cancelamento_registro",
  "plano",
  "assinatura_cyclopay",
  "cancelado_em",
]);

async function removePartnerDocuments(admin: any, parceiroId: number) {
  const { data: docs, error: selectErr } = await admin
    .from("documents")
    .select("id, metadata");

  if (selectErr) return { error: selectErr, deleted: 0 };

  const ids = (docs || [])
    .filter((doc: any) => Number(doc?.metadata?.ID ?? doc?.metadata?.id) === Number(parceiroId))
    .map((doc: any) => doc.id);

  if (ids.length === 0) return { deleted: 0 };

  const { error: deleteErr } = await admin.from("documents").delete().in("id", ids);
  if (deleteErr) return { error: deleteErr, deleted: 0 };

  return { deleted: ids.length };
}

serve(async (req) => {
  if (req.method === "OPTIONS") return new Response(null, { headers: corsHeaders });

  let rawBody = "";
  try {
    rawBody = await req.text();
  } catch (_e) {
    return json({ ok: false, error: "Cannot read body" }, 400);
  }

  let body: any = {};
  try {
    body = rawBody ? JSON.parse(rawBody) : {};
  } catch {
    return json({ ok: false, error: "Invalid JSON" }, 400);
  }

  try {
    const data = body.data || body.subscription || body;
    const subscriptionId: string = String(data.subscription_id || data.id || "").trim();
    const status: string = String(data.status || "").toLowerCase().trim();
    const customer = data.customer || {};
    const customerEmail: string = String(customer.email || "").trim().toLowerCase();

    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const admin = createClient(supabaseUrl, serviceRoleKey, { auth: { persistSession: false } });

    let parceiro: any = null;

    if (subscriptionId) {
      const { data: p } = await admin
        .from("parceiros")
        .select("*")
        .eq("id_assinatura_cyclopay", subscriptionId)
        .maybeSingle();
      parceiro = p;
    }

    if (!parceiro && customerEmail) {
      const { data: p } = await admin
        .from("parceiros")
        .select("*")
        .ilike("email", customerEmail)
        .maybeSingle();
      parceiro = p;
    }

    if (!parceiro) return json({ ok: false, error: "Partner not found" }, 200);

    if (CANCELADOS.includes(status) || REEMBOLSADOS.includes(status)) {
      const dadosParaCopiar = Object.fromEntries(
        Object.entries(parceiro).filter(([key]) => CANCELLED_COPY_COLUMNS.has(key)),
      ) as Record<string, unknown>;

      dadosParaCopiar.status_pagamento = "cancelado";
      dadosParaCopiar.status_aprovacao = "cancelado";
      dadosParaCopiar.is_vip = false;
      dadosParaCopiar.data_cancelamento_registro = new Date().toISOString();

      const { error: insertErr } = await admin.from("parceiros_cancelados").insert(dadosParaCopiar);
      if (insertErr) {
        return json({ ok: false, error: "Falha ao mover para cancelados", details: insertErr.message }, 500);
      }

      const vectorCleanup = await removePartnerDocuments(admin, Number(parceiro.id));
      if (vectorCleanup.error) {
        return json({ ok: false, error: "Falha ao remover do vector store", details: vectorCleanup.error.message }, 500);
      }

      const { error: deleteErr } = await admin.from("parceiros").delete().eq("id", parceiro.id);
      if (deleteErr) {
        return json({ ok: false, error: "Falha ao deletar da tabela principal", details: deleteErr.message }, 500);
      }

      return json({
        ok: true,
        message: "Parceiro movido para a tabela de cancelados com sucesso!",
        parceiro: parceiro.nome,
        documents_removed: vectorCleanup.deleted,
      });
    }

    return json({ ok: true, message: "Status processado (nao era cancelamento)" });
  } catch (error) {
    return json({ ok: false, error: (error as Error)?.message }, 500);
  }
});
