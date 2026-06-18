import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'

interface Message {
  role: 'user' | 'assistant'
  text: string
  error?: boolean
}

interface ChatApiResponse {
  answer: string
  context_date?: string | null
  model_used?: string | null
  error?: boolean
}

const EXAMPLE_QUESTIONS = [
  '¿Quién ganará el Mundial?',
  '¿Cómo afectan las lesiones a Argentina?',
  '¿Qué diferencia hay entre los modelos?',
  '¿Cuál es el favorito de casa (EE.UU./México/Canadá)?',
]

export default function ChatWidget() {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading, open])

  async function sendQuestion(question: string) {
    const q = question.trim()
    if (!q || loading) return
    setMessages((m) => [...m, { role: 'user', text: q }])
    setInput('')
    setLoading(true)
    try {
      const res = await api.post<ChatApiResponse>('/api/chat', { question: q })
      setMessages((m) => [
        ...m,
        { role: 'assistant', text: res.answer, error: res.error ?? false },
      ])
    } catch {
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          text: 'Lo siento, el servicio no está disponible en este momento.',
          error: true,
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    sendQuestion(input)
  }

  return (
    <>
      {/* Floating trigger button — hidden when panel is open */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          aria-label="Abrir asistente"
          className="fixed bottom-5 right-5 z-40 flex h-14 w-14 items-center justify-center rounded-full shadow-xl text-2xl transition-transform hover:scale-105 active:scale-95"
          style={{ background: 'var(--color-accent, #2563eb)', color: '#fff' }}
        >
          💬
        </button>
      )}

      {/* Chat panel */}
      {open && (
        <div
          className="fixed inset-0 z-50 flex flex-col sm:inset-auto sm:bottom-5 sm:right-5 sm:w-[380px] sm:h-[580px] sm:rounded-xl overflow-hidden shadow-2xl"
          style={{
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
          }}
        >
          {/* Header */}
          <div
            className="flex flex-shrink-0 items-center justify-between px-4 py-3 border-b"
            style={{ borderColor: 'var(--color-border)' }}
          >
            <div>
              <p className="text-sm font-bold" style={{ color: 'var(--color-text)' }}>
                Oráculo Assistant
              </p>
              <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
                Pregunta sobre el torneo
              </p>
            </div>
            <div className="flex items-center gap-2">
              {messages.length > 0 && (
                <button
                  onClick={() => setMessages([])}
                  className="rounded px-2 py-1 text-xs transition-colors hover:opacity-80"
                  style={{
                    background: 'var(--color-surface2)',
                    color: 'var(--color-muted)',
                  }}
                  title="Limpiar historial"
                >
                  Limpiar
                </button>
              )}
              <button
                onClick={() => setOpen(false)}
                className="p-1 rounded transition-colors hover:opacity-80"
                style={{ color: 'var(--color-muted)' }}
                aria-label="Cerrar"
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          </div>

          {/* Message area */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {messages.length === 0 && (
              <div className="space-y-2">
                <p className="text-xs" style={{ color: 'var(--color-muted)' }}>
                  Ejemplos de preguntas:
                </p>
                {EXAMPLE_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    onClick={() => sendQuestion(q)}
                    className="block w-full rounded-lg px-3 py-2 text-left text-xs transition-opacity hover:opacity-80 disabled:opacity-50"
                    style={{
                      background: 'var(--color-surface2)',
                      color: 'var(--color-text)',
                    }}
                    disabled={loading}
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}

            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[85%] rounded-xl px-3 py-2 text-xs leading-relaxed ${
                    msg.role === 'user' ? 'bg-blue-600 text-white' : ''
                  }`}
                  style={
                    msg.role === 'assistant'
                      ? {
                          background: 'var(--color-surface2)',
                          color: 'var(--color-text)',
                          border: msg.error ? '1px solid #b45309' : 'none',
                        }
                      : undefined
                  }
                >
                  {msg.text}
                </div>
              </div>
            ))}

            {loading && (
              <div className="flex justify-start">
                <div
                  className="rounded-xl px-3 py-2 text-xs"
                  style={{
                    background: 'var(--color-surface2)',
                    color: 'var(--color-muted)',
                  }}
                >
                  <span className="animate-pulse">Analizando…</span>
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <form
            onSubmit={handleSubmit}
            className="flex flex-shrink-0 gap-2 border-t p-3"
            style={{ borderColor: 'var(--color-border)' }}
          >
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Pregunta sobre el torneo…"
              disabled={loading}
              maxLength={500}
              className="flex-1 rounded-lg border px-3 py-2 text-xs outline-none disabled:opacity-50"
              style={{
                background: 'var(--color-surface2)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="rounded-lg px-3 py-2 text-xs text-white transition-opacity hover:opacity-90 disabled:opacity-40"
              style={{ background: 'var(--color-accent, #2563eb)' }}
            >
              Enviar
            </button>
          </form>

          {/* Disclaimer */}
          <p
            className="flex-shrink-0 border-t px-4 py-1.5 text-center"
            style={{
              borderColor: 'var(--color-border)',
              color: 'var(--color-muted)',
              fontSize: '10px',
            }}
          >
            Las predicciones son estadísticas basadas en datos históricos. No garantizan resultados reales.
          </p>
        </div>
      )}
    </>
  )
}
