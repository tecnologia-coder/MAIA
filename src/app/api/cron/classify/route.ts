import { createClient } from '@supabase/supabase-js'
import { NextResponse } from 'next/server'

const CATEGORIES = [
  'BEBÊS E CRIANÇAS',
  'GESTANTES',
  'MÃES',
  'UTILIDADES',
  'FESTAS',
  'SAÚDE',
  'GASTRONOMIA',
]

const SYSTEM_PROMPT = `Você é um classificador de pedidos de indicação recebidos em grupos de WhatsApp de mães.
Categorias disponíveis: ${CATEGORIES.join(', ')}.
Para cada pedido, atribua de 1 a 3 tags da lista acima que melhor descrevem o assunto.
Retorne APENAS um JSON array, sem texto adicional: [{"id": N, "tags": ["TAG1", "TAG2"]}]`

export async function GET(request: Request) {
  const authHeader = request.headers.get('authorization')
  if (authHeader !== `Bearer ${process.env.CRON_SECRET}`) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!
  )

  const { data: pedidos, error: fetchError } = await supabase
    .from('pedidos_indicacao')
    .select('id, pedido_mensagem, pedido_descricao')
    .is('tags_semanticas', null)
    .limit(100)

  if (fetchError) {
    return NextResponse.json({ error: fetchError.message }, { status: 500 })
  }

  if (!pedidos || pedidos.length === 0) {
    return NextResponse.json({ processed: 0, message: 'Nenhum pedido pendente de classificação.' })
  }

  const BATCH_SIZE = 20
  let processed = 0
  let errors = 0

  for (let i = 0; i < pedidos.length; i += BATCH_SIZE) {
    const batch = pedidos.slice(i, i + BATCH_SIZE)

    try {
      const userPrompt = batch
        .map((p) => `ID: ${p.id} | ${p.pedido_mensagem ?? p.pedido_descricao ?? 'sem texto'}`)
        .join('\n')

      const geminiRes = await fetch(
        `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent?key=${process.env.GEMINI_API_KEY}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            system_instruction: { parts: [{ text: SYSTEM_PROMPT }] },
            contents: [{ parts: [{ text: userPrompt }] }],
            generationConfig: { response_mime_type: 'application/json' },
          }),
        }
      )

      if (!geminiRes.ok) {
        console.error(`[classify] Gemini HTTP ${geminiRes.status}`)
        errors++
        continue
      }

      const geminiData = await geminiRes.json()
      const rawText: string | undefined =
        geminiData.candidates?.[0]?.content?.parts?.[0]?.text

      if (!rawText) {
        errors++
        continue
      }

      const classifications = JSON.parse(rawText) as Array<{ id: number; tags: string[] }>

      for (const cls of classifications) {
        const validTags = cls.tags.filter((t) => CATEGORIES.includes(t))
        if (validTags.length === 0) continue

        const { error: updateError } = await supabase
          .from('pedidos_indicacao')
          .update({ tags_semanticas: validTags })
          .eq('id', cls.id)

        if (updateError) {
          console.error(`[classify] Erro ao atualizar pedido ${cls.id}: ${updateError.message}`)
          errors++
        } else {
          processed++
        }
      }
    } catch (err) {
      console.error(`[classify] Erro no batch ${i / BATCH_SIZE + 1}:`, err)
      errors++
    }
  }

  return NextResponse.json({ processed, errors, total: pedidos.length })
}
