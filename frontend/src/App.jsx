import { useState, useRef, useEffect } from 'react'

const TOOL_META = {
  search_literature: {
    icon: '🔍',
    label: (input) => `Searching ${input.sources?.join(', ') ?? 'all sources'}: "${input.query}"`,
  },
  fetch_abstracts: {
    icon: '📄',
    label: (input) => `Fetching abstracts for ${input.ids?.length ?? 0} papers`,
  },
  fetch_full_text: {
    icon: '📖',
    label: (input) => `Fetching full text for ${input.ids?.length ?? 0} papers`,
  },
  retrieve_relevant_context: {
    icon: '🧠',
    label: (input) => `Retrieving relevant context: "${input.query}"`,
  },
}

function ToolCallCard({ event }) {
  const meta = TOOL_META[event.name] ?? { icon: '⚙️', label: () => event.name }
  return (
    <div style={styles.toolCall}>
      <span style={styles.eventIcon}>{meta.icon}</span>
      <span>{meta.label(event.input)}</span>
    </div>
  )
}

function ToolResultCard({ event }) {
  const [expanded, setExpanded] = useState(false)
  const preview = event.result?.slice(0, 140)
  const hasMore = (event.result?.length ?? 0) > 140
  return (
    <div style={styles.toolResult}>
      <span style={styles.eventIcon}>✓</span>
      <span style={styles.resultText}>
        {expanded ? event.result : preview}
        {hasMore && !expanded && '…'}
      </span>
      {hasMore && (
        <button style={styles.expandBtn} onClick={() => setExpanded(e => !e)}>
          {expanded ? 'less' : 'more'}
        </button>
      )}
    </div>
  )
}

function RagStoreCard({ event }) {
  const paperCount = event.ids?.length ?? 0
  return (
    <div style={styles.ragStore}>
      <span style={styles.eventIcon}>🗄️</span>
      <span>
        Indexed {event.chunks_added} chunks
        {paperCount > 0 ? ` from ${paperCount} paper${paperCount > 1 ? 's' : ''}` : ''}
      </span>
    </div>
  )
}

function authHeaders() {
  const pw = localStorage.getItem('appPassword')
  return pw ? { 'X-App-Password': pw } : {}
}

function LoginGate({ onAuthed }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [checking, setChecking] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setChecking(true)
    setError(null)
    try {
      const resp = await fetch('/api/kb/count', {
        headers: { 'X-App-Password': password },
      })
      if (resp.status === 401) {
        setError('Incorrect password')
        return
      }
      localStorage.setItem('appPassword', password)
      onAuthed()
    } catch (err) {
      setError('Could not reach the server')
    } finally {
      setChecking(false)
    }
  }

  return (
    <div style={styles.page}>
      <form onSubmit={handleSubmit} style={styles.loginCard}>
        <h1 style={styles.title}>Literature Review Agent</h1>
        <p style={styles.subtitle}>Enter the app password to continue</p>
        <input
          type="password"
          autoFocus
          style={styles.input}
          value={password}
          onChange={e => setPassword(e.target.value)}
          placeholder="Password"
        />
        <button style={{ ...styles.button, marginTop: 12, opacity: checking ? 0.6 : 1 }} type="submit" disabled={checking}>
          {checking ? 'Checking…' : 'Continue'}
        </button>
        {error && <div style={{ ...styles.error, marginTop: 16 }}>{error}</div>}
      </form>
    </div>
  )
}

function ReportBlock({ text }) {
  const lines = text.split('\n')
  return (
    <div style={styles.report}>
      <div style={styles.reportLabel}>Report</div>
      <div style={styles.reportText}>
        {lines.map((line, i) => {
          if (line.startsWith('## ')) {
            return <h3 key={i} style={styles.reportH3}>{line.slice(3)}</h3>
          }
          if (line.startsWith('# ')) {
            return <h2 key={i} style={styles.reportH2}>{line.slice(2)}</h2>
          }
          return <p key={i} style={styles.reportP}>{line || ' '}</p>
        })}
      </div>
    </div>
  )
}

export default function App() {
  const [question, setQuestion] = useState('')
  const [domain, setDomain] = useState('')
  const [events, setEvents] = useState([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [kbCount, setKbCount] = useState(0)
  const [sources, setSources] = useState([])
  const [authed, setAuthed] = useState(null)
  const bottomRef = useRef(null)

  useEffect(() => {
    fetch('/api/kb/count', { headers: authHeaders() })
      .then(r => {
        if (r.status === 401) {
          localStorage.removeItem('appPassword')
          setAuthed(false)
          throw new Error('unauthorized')
        }
        setAuthed(true)
        return r.json()
      })
      .then(d => setKbCount(d.count))
      .catch(() => {})
    fetch('/api/sources', { headers: authHeaders() })
      .then(r => r.json())
      .then(d => setSources(d.sources ?? []))
      .catch(() => {})
  }, [])

  if (authed === false) {
    return <LoginGate onAuthed={() => setAuthed(true)} />
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events])

  function appendText(delta) {
    setEvents(prev => {
      const last = prev[prev.length - 1]
      if (last?.type === 'text') {
        return [...prev.slice(0, -1), { ...last, text: last.text + delta }]
      }
      return [...prev, { type: 'text', text: delta }]
    })
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!question.trim() || running) return

    setRunning(true)
    setError(null)
    setEvents([])

    try {
      const resp = await fetch('/api/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ question, domain }),
      })

      if (resp.status === 401) {
        localStorage.removeItem('appPassword')
        setAuthed(false)
        throw new Error('Session expired — please re-enter the password')
      }
      if (!resp.ok) throw new Error(`Server error: ${resp.status}`)

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          let data
          try { data = JSON.parse(line.slice(6)) } catch { continue }

          if (data.type === 'text_delta') {
            appendText(data.text)
          } else if (data.type === 'tool_call') {
            setEvents(prev => [...prev, { type: 'tool_call', name: data.name, input: data.input }])
          } else if (data.type === 'tool_result') {
            setEvents(prev => [...prev, { type: 'tool_result', name: data.name, result: data.result }])
          } else if (data.type === 'rag_store') {
            setEvents(prev => [...prev, { type: 'rag_store', chunks_added: data.chunks_added, ids: data.ids }])
            setKbCount(c => c + data.chunks_added)
          } else if (data.type === 'error') {
            setError(data.message)
          } else if (data.type === 'done') {
            setRunning(false)
          }
        }
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.container}>
        <div style={styles.header}>
          <div>
            <h1 style={styles.title}>Literature Review Agent</h1>
            <p style={styles.subtitle}>Synthesizes findings across multiple research databases</p>
            {sources.length > 0 && (
              <div style={styles.sourceRow}>
                {sources.map(s => (
                  <span key={s.key} style={styles.sourceBadge}>{s.label}</span>
                ))}
              </div>
            )}
          </div>
          {kbCount > 0 && (
            <div style={styles.kbBadge}>
              <span>🗄️</span>
              <span>{kbCount.toLocaleString()} chunks indexed</span>
            </div>
          )}
        </div>

        <form onSubmit={handleSubmit} style={styles.form}>
          <div style={styles.inputGroup}>
            <input
              style={styles.input}
              value={question}
              onChange={e => setQuestion(e.target.value)}
              placeholder="Research question — e.g. BRCA1 pathogenic variant population frequency"
              disabled={running}
            />
            <input
              style={styles.domainInput}
              value={domain}
              onChange={e => setDomain(e.target.value)}
              placeholder="Domain (optional) — e.g. cardiology, machine learning, oncology"
              disabled={running}
            />
          </div>
          <button
            style={{ ...styles.button, opacity: running ? 0.6 : 1 }}
            type="submit"
            disabled={running}
          >
            {running ? 'Running…' : 'Search'}
          </button>
        </form>

        {error && <div style={styles.error}>{error}</div>}

        {events.length > 0 && (
          <div style={styles.feed}>
            {events.map((ev, i) => {
              if (ev.type === 'tool_call') return <ToolCallCard key={i} event={ev} />
              if (ev.type === 'tool_result') return <ToolResultCard key={i} event={ev} />
              if (ev.type === 'rag_store') return <RagStoreCard key={i} event={ev} />
              if (ev.type === 'text') return <ReportBlock key={i} text={ev.text} />
              return null
            })}
            {running && <div style={styles.cursor}>▍</div>}
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  )
}

const styles = {
  page: {
    minHeight: '100vh',
    background: '#f8f9fa',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    padding: '40px 16px',
  },
  container: {
    maxWidth: 780,
    margin: '0 auto',
  },
  loginCard: {
    maxWidth: 360,
    margin: '120px auto 0',
    background: '#fff',
    border: '1px solid #e5e7eb',
    borderRadius: 10,
    padding: '32px 28px',
    display: 'flex',
    flexDirection: 'column',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 28,
  },
  title: {
    fontSize: 28,
    fontWeight: 700,
    color: '#111',
    margin: '0 0 4px',
  },
  subtitle: {
    color: '#666',
    margin: 0,
    fontSize: 15,
  },
  sourceRow: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: 10,
  },
  sourceBadge: {
    padding: '3px 10px',
    background: '#f1f5f9',
    border: '1px solid #e2e8f0',
    borderRadius: 12,
    fontSize: 12,
    color: '#475569',
    fontWeight: 500,
  },
  kbBadge: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '6px 12px',
    background: '#f3e8ff',
    border: '1px solid #d8b4fe',
    borderRadius: 20,
    fontSize: 13,
    color: '#7e22ce',
    fontWeight: 500,
    whiteSpace: 'nowrap',
  },
  form: {
    display: 'flex',
    gap: 10,
    marginBottom: 24,
    alignItems: 'flex-start',
  },
  inputGroup: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  input: {
    width: '100%',
    padding: '10px 14px',
    fontSize: 15,
    border: '1.5px solid #ddd',
    borderRadius: 8,
    outline: 'none',
    background: '#fff',
    boxSizing: 'border-box',
  },
  domainInput: {
    width: '100%',
    padding: '8px 14px',
    fontSize: 14,
    border: '1.5px solid #ddd',
    borderRadius: 8,
    outline: 'none',
    background: '#fff',
    color: '#555',
    boxSizing: 'border-box',
  },
  button: {
    padding: '10px 22px',
    fontSize: 15,
    fontWeight: 600,
    background: '#2563eb',
    color: '#fff',
    border: 'none',
    borderRadius: 8,
    cursor: 'pointer',
    whiteSpace: 'nowrap',
    alignSelf: 'flex-start',
  },
  feed: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  eventIcon: {
    fontSize: 15,
    flexShrink: 0,
  },
  toolCall: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '10px 14px',
    background: '#eff6ff',
    border: '1px solid #bfdbfe',
    borderRadius: 8,
    fontSize: 14,
    color: '#1e40af',
    fontWeight: 500,
  },
  toolResult: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 8,
    padding: '8px 14px',
    background: '#f0fdf4',
    border: '1px solid #bbf7d0',
    borderRadius: 8,
    fontSize: 13,
    color: '#166534',
  },
  resultText: {
    flex: 1,
    fontFamily: 'monospace',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
  expandBtn: {
    background: 'none',
    border: 'none',
    color: '#15803d',
    cursor: 'pointer',
    fontSize: 12,
    textDecoration: 'underline',
    flexShrink: 0,
    padding: 0,
  },
  ragStore: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '8px 14px',
    background: '#faf5ff',
    border: '1px solid #e9d5ff',
    borderRadius: 8,
    fontSize: 13,
    color: '#7e22ce',
    fontWeight: 500,
  },
  report: {
    marginTop: 8,
    background: '#fff',
    border: '1px solid #e5e7eb',
    borderRadius: 10,
    padding: '20px 24px',
  },
  reportLabel: {
    fontSize: 11,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: '#9ca3af',
    marginBottom: 16,
  },
  reportText: {
    margin: 0,
  },
  reportH2: {
    fontSize: 18,
    fontWeight: 700,
    color: '#111',
    margin: '20px 0 8px',
  },
  reportH3: {
    fontSize: 16,
    fontWeight: 600,
    color: '#1e40af',
    margin: '16px 0 6px',
    borderBottom: '1px solid #e5e7eb',
    paddingBottom: 4,
  },
  reportP: {
    fontSize: 15,
    lineHeight: 1.7,
    color: '#222',
    margin: '4px 0',
  },
  cursor: {
    color: '#2563eb',
    fontSize: 18,
    paddingLeft: 4,
  },
  error: {
    padding: '12px 16px',
    background: '#fef2f2',
    border: '1px solid #fecaca',
    borderRadius: 8,
    color: '#dc2626',
    fontSize: 14,
    marginBottom: 16,
  },
}
