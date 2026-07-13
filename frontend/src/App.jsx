import { useState, useRef, useEffect } from 'react'

// Empty in local dev (Vite's dev-server proxy handles relative /api calls). Set at build time
// to the deployed backend's URL (e.g. https://your-app.up.railway.app) for production builds.
const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

const TOOL_META = {
  search_literature: {
    label: (input, sourceLabels) => {
      const names = input.sources?.map(key => sourceLabels[key] ?? key).join(', ')
      return `Searching for "${input.query}" across ${names || 'all sources'}`
    },
  },
  fetch_abstracts: {
    label: (input) => `Fetching abstracts for ${input.ids?.length ?? 0} papers`,
  },
  fetch_full_text: {
    label: (input) => `Fetching full text for ${input.ids?.length ?? 0} papers`,
  },
  retrieve_relevant_context: {
    label: (input) => `Retrieving relevant context for "${input.query}"`,
  },
}

function LogRow({ dotColor, children }) {
  return (
    <div style={styles.logRow}>
      <span style={{ ...styles.logDot, background: dotColor }} />
      <span style={styles.logText}>{children}</span>
    </div>
  )
}

function ToolCallCard({ event, sourceLabels }) {
  const meta = TOOL_META[event.name] ?? { label: () => event.name }
  return <LogRow dotColor="#6b2737">{meta.label(event.input, sourceLabels)}</LogRow>
}

function ToolResultCard({ event }) {
  const [expanded, setExpanded] = useState(false)
  const preview = event.result?.slice(0, 140)
  const hasMore = (event.result?.length ?? 0) > 140
  return (
    <div style={styles.logRow}>
      <span style={{ ...styles.logDot, background: '#5c7a2e' }} />
      <span style={styles.logText}>
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
    <LogRow dotColor="#c1502a">
      Indexed {event.chunks_added} chunks
      {paperCount > 0 ? ` from ${paperCount} paper${paperCount > 1 ? 's' : ''}` : ''}
    </LogRow>
  )
}

function authHeaders() {
  const pw = localStorage.getItem('appPassword')
  return pw ? { 'X-App-Password': pw } : {}
}

function userKeyHeaders() {
  const key = localStorage.getItem('userAnthropicKey')
  return key ? { 'X-User-Api-Key': key } : {}
}

function LoginGate({ onAuthed }) {
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState(null)
  const [checking, setChecking] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setChecking(true)
    setError(null)
    try {
      const resp = await fetch(`${API_BASE}/api/kb/count`, {
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
        <div style={styles.passwordWrap}>
          <input
            type={showPassword ? 'text' : 'password'}
            autoFocus
            style={{ ...styles.input, flex: 1 }}
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder="Password"
          />
          <button
            type="button"
            style={styles.passwordToggle}
            onClick={() => setShowPassword(s => !s)}
            tabIndex={-1}
          >
            {showPassword ? 'Hide' : 'Show'}
          </button>
        </div>
        <button style={{ ...styles.button, marginTop: 12, opacity: checking ? 0.6 : 1 }} type="submit" disabled={checking}>
          {checking ? 'Checking…' : 'Continue'}
        </button>
        {error && <div style={{ ...styles.error, marginTop: 16 }}>{error}</div>}
      </form>
    </div>
  )
}

const SOURCE_KEYS = ['pubmed', 'semantic_scholar', 'openalex', 'europepmc', 'crossref']
const CITATION_ID = `(?:${SOURCE_KEYS.join('|')}):[^\\s,;()]+`
const CITATION_GROUP = new RegExp(
  `\\(${CITATION_ID}(?:[,;]\\s*${CITATION_ID})*\\)`,
  'g'
)

function splitCitationIds(group) {
  return group.slice(1, -1).split(/[,;]/).map(s => s.trim())
}

// Same paper found via two sources (e.g. pubmed + openalex) has two different ids but the same
// DOI — group by DOI when it's available so it shows up as one reference, not two.
function canonicalKeyFor(id, paperMap) {
  const doi = paperMap[id]?.doi?.trim().toLowerCase()
  return doi ? `doi:${doi}` : id
}

function collectCitations(text, paperMap) {
  const order = []
  const seenCanonical = new Set()
  const representativeId = {}
  const idsByCanonical = {}
  const allLiteralIds = []

  for (const group of text.match(CITATION_GROUP) ?? []) {
    for (const id of splitCitationIds(group)) {
      allLiteralIds.push(id)
      const key = canonicalKeyFor(id, paperMap)
      if (!seenCanonical.has(key)) {
        seenCanonical.add(key)
        order.push(key)
        representativeId[key] = id
        idsByCanonical[key] = []
      }
      if (!idsByCanonical[key].includes(id)) idsByCanonical[key].push(id)
    }
  }

  const numberByCanonical = Object.fromEntries(order.map((key, i) => [key, i + 1]))
  const numberByLiteralId = {}
  for (const id of allLiteralIds) {
    numberByLiteralId[id] = numberByCanonical[canonicalKeyFor(id, paperMap)]
  }

  return { order, representativeId, idsByCanonical, numberByLiteralId }
}

function renderLineWithCitations(line, numberByLiteralId, key) {
  const parts = []
  let lastIndex = 0
  let match
  const re = new RegExp(CITATION_GROUP)
  while ((match = re.exec(line)) !== null) {
    if (match.index > lastIndex) parts.push(line.slice(lastIndex, match.index))
    const ids = splitCitationIds(match[0])
    parts.push(
      <sup key={`${key}-${match.index}`} style={styles.citation}>
        [{ids.map((id, i) => (
          <span key={id}>
            {i > 0 && ','}
            <a href={`#ref-${numberByLiteralId[id]}`} style={styles.citationLink}>{numberByLiteralId[id] ?? '?'}</a>
          </span>
        ))}]
      </sup>
    )
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < line.length) parts.push(line.slice(lastIndex))
  return parts.length ? parts : [' ']
}

const EVIDENCE_TIERS = {
  systematic_review: { label: 'Systematic Review / Meta-Analysis', color: '#2d5220', bg: '#dceed1' },
  rct: { label: 'RCT', color: '#2c4a6b', bg: '#d8e2ea' },
  observational: { label: 'Observational Study', color: '#8a5f10', bg: '#f7e3b8' },
  case_report: { label: 'Case Report', color: '#a34419', bg: '#f5d5bd' },
  review: { label: 'Review (non-systematic)', color: '#6f6656', bg: '#ece7dc' },
  unclassified: { label: 'Not classified', color: '#a39980', bg: '#ece7dc' },
}

function EvidenceTierBadge({ tier }) {
  const meta = EVIDENCE_TIERS[tier] ?? EVIDENCE_TIERS.unclassified
  return (
    <span style={{ ...styles.tierBadge, color: meta.color, background: meta.bg }}>
      {meta.label}
    </span>
  )
}

const TIER_RANK = ['systematic_review', 'rct', 'observational', 'case_report', 'review', 'unclassified']

function bestTier(tiers) {
  return tiers.reduce((best, t) => (TIER_RANK.indexOf(t) < TIER_RANK.indexOf(best) ? t : best), 'unclassified')
}

function ReferenceList({ order, representativeId, idsByCanonical, paperMap, sourceLabels, ungroundedIds, abstractOnlyIds }) {
  if (order.length === 0) return null
  return (
    <div style={styles.references}>
      <div style={styles.reportLabel}>References</div>
      <ol style={styles.referenceList}>
        {order.map((key, i) => {
          const aliasIds = idsByCanonical[key]
          const repId = representativeId[key]
          const paper = paperMap[repId]
          const groundedIds = aliasIds.filter(id => !ungroundedIds.has(id))
          const ungrounded = groundedIds.length === 0
          const abstractOnly = !ungrounded && groundedIds.every(id => abstractOnlyIds.has(id))
          const tier = bestTier(aliasIds.map(id => paperMap[id]?.evidence_tier ?? 'unclassified'))
          const sourceNames = [...new Set(aliasIds.map(id => paperMap[id]?.source).filter(Boolean))]
            .map(s => sourceLabels[s] ?? s)
          return (
            <li key={key} id={`ref-${i + 1}`} style={styles.referenceItem}>
              {paper && <EvidenceTierBadge tier={tier} />}
              {paper ? (
                <>
                  <a href={paper.url} target="_blank" rel="noreferrer" style={styles.referenceTitle}>
                    {paper.title || repId}
                  </a>
                  <span style={styles.referenceMeta}>
                    {' '}· {paper.authors || 'Unknown authors'}
                    {paper.year ? ` (${paper.year})` : ''} · {sourceNames.join(', ') || paper.source}
                  </span>
                </>
              ) : (
                <span style={styles.referenceMeta}>{repId} (details unavailable)</span>
              )}
              {ungrounded && (
                <span style={styles.ungroundedNote} title="Cited, but its content was never pulled into the retrieval context used to write the report. Treat with extra scrutiny.">
                  {' '}not retrieved into context
                </span>
              )}
              {abstractOnly && (
                <span style={styles.abstractOnlyNote} title="This claim is grounded in the abstract only. Full text wasn't available or wasn't fetched, so methodology and effect-size details are unverified.">
                  {' '}· abstract only
                </span>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function ReportBlock({ text, paperMap, sourceLabels, ungroundedIds, abstractOnlyIds }) {
  const lines = text.split('\n')
  const { order, representativeId, idsByCanonical, numberByLiteralId } = collectCitations(text, paperMap)
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
          return <p key={i} style={styles.reportP}>{renderLineWithCitations(line, numberByLiteralId, i)}</p>
        })}
      </div>
      <ReferenceList
        order={order}
        representativeId={representativeId}
        idsByCanonical={idsByCanonical}
        paperMap={paperMap}
        sourceLabels={sourceLabels}
        ungroundedIds={ungroundedIds}
        abstractOnlyIds={abstractOnlyIds}
      />
    </div>
  )
}

const EXAMPLE_QUESTIONS = [
  'do statins increase the risk of new-onset diabetes?',
  'does intermittent fasting improve HbA1c?',
  'what is the effectiveness of GLP-1 agonists for obesity?',
  'how does vitamin D affect depression risk?',
]

const CHIP_EXAMPLES = [
  'Do statins increase diabetes risk?',
  'Does intermittent fasting improve HbA1c?',
  'GLP-1 agonists for obesity',
  'Vitamin D and depression',
]

function useTypewriterPlaceholder(active) {
  const [text, setText] = useState('')

  useEffect(() => {
    if (!active) {
      setText('')
      return
    }
    let exampleIndex = 0
    let charIndex = 0
    let deleting = false
    let timeoutId

    function tick() {
      const full = EXAMPLE_QUESTIONS[exampleIndex]
      if (!deleting) {
        charIndex++
        setText(full.slice(0, charIndex))
        timeoutId = setTimeout(tick, charIndex === full.length ? 1500 : 35)
        if (charIndex === full.length) deleting = true
      } else {
        charIndex--
        setText(full.slice(0, charIndex))
        if (charIndex === 0) {
          deleting = false
          exampleIndex = (exampleIndex + 1) % EXAMPLE_QUESTIONS.length
          timeoutId = setTimeout(tick, 400)
        } else {
          timeoutId = setTimeout(tick, 18)
        }
      }
    }
    timeoutId = setTimeout(tick, 600)
    return () => clearTimeout(timeoutId)
  }, [active])

  return text
}

function HowItWorks() {
  return (
    <div style={styles.howItWorks}>
      <h2 style={styles.howItWorksH2}>How it works</h2>
      <p style={styles.howItWorksP}>
        Ask a research question and the agent searches PubMed, Semantic Scholar, OpenAlex, and Europe PMC,
        reads the most relevant papers, and writes back a structured summary with citations you can verify.
      </p>

      <h3 style={styles.howItWorksH3}>The process</h3>
      <ol style={styles.howItWorksOl}>
        <li>
          Claude runs an agentic tool-use loop: it searches PubMed, Semantic Scholar, OpenAlex, and Europe PMC by
          default (it can narrow that list or add Crossref for DOI verification, though it usually searches all
          four), deciding how to phrase each query and when to stop, up to 3 rounds, refining the query if
          initial results are sparse or off-topic
        </li>
        <li>Screens abstracts to identify the papers worth reading in full, rather than reading everything indiscriminately</li>
        <li>
          Fetches full text for the top 2-3 papers where it's open-access (PubMed Central, Europe PMC); Semantic
          Scholar and OpenAlex often yield an open-access link instead, since full-text extraction isn't
          available everywhere, and Crossref never provides full text at all
        </li>
        <li>
          Chunks and embeds everything it reads into a vector database scoped to that single search, then
          retrieves the most relevant passages before writing, so the synthesis is grounded in actual text
          rather than the model's memory
        </li>
        <li>Writes a structured summary: key findings, common themes, implications, and research gaps</li>
      </ol>

      <h3 style={styles.howItWorksH3}>Why you can trust the citations</h3>
      <p style={styles.howItWorksP}>
        Every citation links to the real paper. The agent separately tracks which papers were actually pulled
        into the retrieval step versus only ever seen as a search result, and flags any citation to a paper
        that was never actually retrieved into context.
      </p>
      <p style={styles.howItWorksP}>
        Each paper is tagged by evidence strength, systematic review/meta-analysis, RCT, observational study,
        or case report, using real publication-type metadata from PubMed and Europe PMC, not a model guess.
        Papers from sources without that data are honestly labeled "not classified." Citations grounded only
        in an abstract rather than full text are labeled as such too, since abstracts often omit the
        methodology and effect-size detail that actually matters.
      </p>

      <h3 style={styles.howItWorksH3}>Built for reliability, not just output</h3>
      <p style={styles.howItWorksP}>
        An eval harness can be run on demand to check retrieval quality, agent behavior (search budget, whether
        retrieval happened before synthesis, groundedness), and report quality against a golden set of test
        questions. Every run also writes a structured trace (token usage, latency, tool calls) for debugging
        and analysis.
      </p>
    </div>
  )
}

export default function App() {
  const [view, setView] = useState('search')
  const [question, setQuestion] = useState('')
  const [events, setEvents] = useState([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [kbCount, setKbCount] = useState(0)
  const [sources, setSources] = useState([])
  const [paperMap, setPaperMap] = useState({})
  const [ungroundedIds, setUngroundedIds] = useState(new Set())
  const [abstractOnlyIds, setAbstractOnlyIds] = useState(new Set())
  const [authed, setAuthed] = useState(null)
  const [mockMode, setMockMode] = useState(false)
  const [userApiKey, setUserApiKey] = useState(() => localStorage.getItem('userAnthropicKey') || '')
  const [showKeyInput, setShowKeyInput] = useState(false)
  const [keyDraft, setKeyDraft] = useState('')
  const [marqueePaused, setMarqueePaused] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    if (!authed) return
    fetch(`${API_BASE}/api/mode`, { headers: authHeaders() })
      .then(r => r.json())
      .then(d => setMockMode(!!d.mock_mode))
      .catch(() => {})
  }, [authed])

  function saveApiKey() {
    const trimmed = keyDraft.trim()
    if (trimmed) localStorage.setItem('userAnthropicKey', trimmed)
    setUserApiKey(trimmed)
    setKeyDraft('')
    setShowKeyInput(false)
  }

  function removeApiKey() {
    localStorage.removeItem('userAnthropicKey')
    setUserApiKey('')
  }

  useEffect(() => {
    fetch(`${API_BASE}/api/kb/count`, { headers: authHeaders() })
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
    fetch(`${API_BASE}/api/sources`, { headers: authHeaders() })
      .then(r => r.json())
      .then(d => setSources(d.sources ?? []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (events.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [events])

  const isEmptyState = view === 'search' && events.length === 0
  const typedPlaceholder = useTypewriterPlaceholder(isEmptyState)

  if (authed === false) {
    return <LoginGate onAuthed={() => setAuthed(true)} />
  }

  const sourceLabels = Object.fromEntries(sources.map(s => [s.key, s.label]))

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
    setPaperMap({})
    setUngroundedIds(new Set())
    setAbstractOnlyIds(new Set())

    try {
      const resp = await fetch(`${API_BASE}/api/research`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders(), ...userKeyHeaders() },
        body: JSON.stringify({ question }),
      })

      if (resp.status === 401) {
        localStorage.removeItem('appPassword')
        setAuthed(false)
        throw new Error('Session expired. Please re-enter the password.')
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
          } else if (data.type === 'references') {
            setPaperMap(prev => {
              const next = { ...prev }
              for (const p of data.papers) next[p.id] = p
              return next
            })
          } else if (data.type === 'grounding') {
            setUngroundedIds(new Set(data.ungrounded_ids))
            setAbstractOnlyIds(new Set(data.abstract_only_ids))
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
      <div style={styles.topBar}>
        <span style={styles.topBarBrand}>Literature Review Agent</span>
        <div style={styles.topBarLinks}>
          <button
            type="button"
            style={styles.topBarLink}
            onClick={() => setView(v => (v === 'how' ? 'search' : 'how'))}
          >
            {view === 'how' ? 'Back to search' : 'How it works'}
          </button>
          <a
            href="https://github.com/shwe-kandhalu/litreview_agent"
            target="_blank"
            rel="noreferrer"
            style={styles.topBarLink}
          >
            GitHub
          </a>
        </div>
      </div>

      <div style={{ ...styles.main, justifyContent: isEmptyState ? 'center' : 'flex-start' }}>
        <div style={styles.container}>
          {view === 'how' ? (
            <HowItWorks />
          ) : (
            <>
              <div style={styles.header}>
                <div style={styles.titleBlock}>
                  <h1 style={styles.title}>Literature Review Agent</h1>
                  <p style={styles.subtitle}>
                    Ask a research question and receive an evidence synthesis with citations you can verify.
                  </p>
                  {sources.length > 0 && (
                    <p style={styles.poweredBy}>Powered by {sources.map(s => s.label).join(' · ')}</p>
                  )}
                </div>
                {kbCount > 0 && (
                  <div style={styles.kbBadge}>
                    <span>{kbCount.toLocaleString()} chunks indexed</span>
                  </div>
                )}
              </div>

              <form onSubmit={handleSubmit} style={styles.form}>
                <label style={styles.inputLabel} htmlFor="research-question">Ask a research question</label>
                <div style={styles.inputRow}>
                  <input
                    id="research-question"
                    style={styles.input}
                    value={question}
                    onChange={e => setQuestion(e.target.value)}
                    placeholder={isEmptyState && typedPlaceholder ? typedPlaceholder : 'Ask a research question...'}
                    disabled={running}
                  />
                  <button
                    style={{ ...styles.button, opacity: running ? 0.6 : 1 }}
                    type="submit"
                    disabled={running}
                  >
                    {running ? 'Running…' : 'Search'}
                  </button>
                </div>
              </form>

              {mockMode && (
                <div style={styles.keyNotice}>
                  {userApiKey ? (
                    <span>
                      Using your own Anthropic API key for real searches.{' '}
                      <button type="button" style={styles.keyNoticeLink} onClick={removeApiKey}>Remove</button>
                    </span>
                  ) : showKeyInput ? (
                    <span style={styles.keyInputRow}>
                      <input
                        type="password"
                        style={styles.keyInput}
                        value={keyDraft}
                        onChange={e => setKeyDraft(e.target.value)}
                        placeholder="sk-ant-..."
                        autoFocus
                      />
                      <button type="button" style={styles.keyNoticeLink} onClick={saveApiKey}>Save</button>
                      <button type="button" style={styles.keyNoticeLink} onClick={() => setShowKeyInput(false)}>Cancel</button>
                    </span>
                  ) : (
                    <span>
                      Demo mode — showing mock results, no API calls made.{' '}
                      <button type="button" style={styles.keyNoticeLink} onClick={() => setShowKeyInput(true)}>
                        Use your own Anthropic API key for real searches
                      </button>
                    </span>
                  )}
                </div>
              )}

              {isEmptyState && (
                <div
                  style={styles.marqueeOuter}
                  onMouseEnter={() => setMarqueePaused(true)}
                  onMouseLeave={() => setMarqueePaused(false)}
                >
                  <style>{`
                    @keyframes example-marquee {
                      from { transform: translateX(0); }
                      to { transform: translateX(-50%); }
                    }
                  `}</style>
                  <div
                    style={{
                      ...styles.marqueeTrack,
                      animationPlayState: marqueePaused ? 'paused' : 'running',
                    }}
                  >
                    {[...CHIP_EXAMPLES, ...CHIP_EXAMPLES].map((ex, i) => (
                      <button
                        key={i}
                        type="button"
                        style={styles.exampleChip}
                        onClick={() => setQuestion(ex)}
                      >
                        {ex}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {isEmptyState && (
                <div style={styles.featureRow}>
                  <div style={styles.featureCard}>
                    <h3 style={styles.featureTitle}>Search</h3>
                    <p style={styles.featureText}>Find relevant papers from multiple scientific databases.</p>
                  </div>
                  <div style={styles.featureCard}>
                    <h3 style={styles.featureTitle}>Synthesize</h3>
                    <p style={styles.featureText}>Generate a concise, evidence-based literature review.</p>
                  </div>
                  <div style={styles.featureCard}>
                    <h3 style={styles.featureTitle}>Cite</h3>
                    <p style={styles.featureText}>Every statement links back to the original research.</p>
                  </div>
                </div>
              )}

              {error && <div style={styles.error}>{error}</div>}

              {events.length > 0 && (
                <div style={styles.feed}>
                  {events.map((ev, i) => {
                    if (ev.type === 'tool_call') return <ToolCallCard key={i} event={ev} sourceLabels={sourceLabels} />
                    if (ev.type === 'tool_result') return <ToolResultCard key={i} event={ev} />
                    if (ev.type === 'rag_store') return <RagStoreCard key={i} event={ev} />
                    if (ev.type === 'text') {
                      return (
                        <ReportBlock
                          key={i}
                          text={ev.text}
                          paperMap={paperMap}
                          sourceLabels={sourceLabels}
                          ungroundedIds={ungroundedIds}
                          abstractOnlyIds={abstractOnlyIds}
                        />
                      )
                    }
                    return null
                  })}
                  {running && <div style={styles.cursor}>▍</div>}
                </div>
              )}
            </>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      <footer style={styles.footer}>
        <span>© 2026 Literature Review Agent</span>
        <a
          href="https://github.com/shwe-kandhalu/litreview_agent"
          target="_blank"
          rel="noreferrer"
          style={styles.footerLink}
        >
          GitHub
        </a>
      </footer>
    </div>
  )
}

const SERIF = 'Georgia, "Iowan Old Style", Charter, serif'

const styles = {
  page: {
    minHeight: '100vh',
    background: '#f6f2ea',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    display: 'flex',
    flexDirection: 'column',
  },
  topBar: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '16px 24px',
    borderBottom: '1px solid #e3d9c6',
  },
  topBarBrand: {
    fontFamily: 'Georgia, "Iowan Old Style", Charter, serif',
    fontSize: 15,
    fontWeight: 700,
    color: '#5c5340',
  },
  topBarLinks: {
    display: 'flex',
    alignItems: 'center',
    gap: 20,
  },
  topBarLink: {
    background: 'none',
    border: 'none',
    font: 'inherit',
    fontSize: 13.5,
    fontWeight: 600,
    color: '#6f6656',
    cursor: 'pointer',
    padding: 0,
    textDecoration: 'none',
  },
  main: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    padding: '40px 16px',
  },
  footer: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '16px 24px',
    borderTop: '1px solid #e3d9c6',
    fontSize: 12.5,
    color: '#a39980',
  },
  footerLink: {
    color: '#a39980',
    textDecoration: 'none',
    fontWeight: 600,
  },
  howItWorks: {
    background: '#fffefb',
    border: '1px solid #e3d9c6',
    borderRadius: 8,
    padding: '32px 36px',
  },
  howItWorksH2: {
    fontFamily: SERIF,
    fontSize: 24,
    fontWeight: 700,
    color: '#1a160f',
    margin: '0 0 18px',
  },
  howItWorksH3: {
    fontFamily: SERIF,
    fontSize: 16,
    fontWeight: 700,
    color: '#6b2737',
    margin: '22px 0 8px',
  },
  howItWorksP: {
    fontSize: 14.5,
    lineHeight: 1.7,
    color: '#3a3527',
    margin: '4px 0',
  },
  howItWorksOl: {
    margin: '4px 0',
    paddingLeft: 20,
    fontSize: 14.5,
    lineHeight: 1.8,
    color: '#3a3527',
  },
  container: {
    width: '100%',
    maxWidth: 780,
    margin: '0 auto',
  },
  loginCard: {
    maxWidth: 360,
    margin: '120px auto 0',
    background: '#fffefb',
    border: '1px solid #e3d9c6',
    borderRadius: 6,
    padding: '32px 28px',
    display: 'flex',
    flexDirection: 'column',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 22,
  },
  title: {
    fontFamily: SERIF,
    fontSize: 30,
    fontWeight: 700,
    color: '#1a160f',
    margin: '0 0 6px',
  },
  titleBlock: {
    borderLeft: '4px solid #6b2737',
    paddingLeft: 14,
  },
  subtitle: {
    color: '#726a58',
    margin: 0,
    fontSize: 15,
  },
  poweredBy: {
    fontSize: 12.5,
    color: '#a39980',
    marginTop: 10,
    marginBottom: 0,
  },
  marqueeOuter: {
    overflow: 'hidden',
    marginTop: -8,
    marginBottom: 24,
    maskImage: 'linear-gradient(to right, transparent, black 24px, black calc(100% - 24px), transparent)',
    WebkitMaskImage: 'linear-gradient(to right, transparent, black 24px, black calc(100% - 24px), transparent)',
  },
  marqueeTrack: {
    display: 'flex',
    flexWrap: 'nowrap',
    gap: 8,
    width: 'max-content',
    animation: 'example-marquee 22s linear infinite',
  },
  exampleChip: {
    padding: '6px 14px',
    background: '#fffefb',
    border: '1px solid #e3d9c6',
    borderRadius: 20,
    fontSize: 13,
    color: '#5c5340',
    fontWeight: 500,
    cursor: 'pointer',
    whiteSpace: 'nowrap',
    flexShrink: 0,
  },
  keyNotice: {
    fontSize: 12.5,
    color: '#8a8066',
    background: '#f7e9c8',
    border: '1px solid #e0c078',
    borderRadius: 6,
    padding: '8px 12px',
    marginBottom: 16,
  },
  keyNoticeLink: {
    background: 'none',
    border: 'none',
    padding: 0,
    color: '#6b2737',
    fontWeight: 600,
    fontSize: 12.5,
    cursor: 'pointer',
    textDecoration: 'underline',
  },
  keyInputRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
  },
  keyInput: {
    flex: 1,
    padding: '5px 10px',
    fontSize: 12.5,
    border: '1px solid #e0c078',
    borderRadius: 4,
    outline: 'none',
    background: '#fffefb',
    color: '#26221a',
  },
  featureRow: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 16,
    marginBottom: 8,
  },
  featureCard: {
    flex: '1 1 160px',
    borderTop: '2px solid #e3d9c6',
    padding: '14px 0 0',
  },
  featureTitle: {
    fontFamily: SERIF,
    fontSize: 15,
    fontWeight: 700,
    color: '#6b2737',
    margin: '0 0 6px',
  },
  featureText: {
    fontSize: 13.5,
    lineHeight: 1.6,
    color: '#6f6656',
    margin: 0,
  },
  kbBadge: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '6px 12px',
    background: '#f7e9c8',
    border: '1px solid #e0c078',
    borderRadius: 20,
    fontSize: 13,
    color: '#8a5f10',
    fontWeight: 600,
    whiteSpace: 'nowrap',
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    marginBottom: 24,
  },
  inputRow: {
    display: 'flex',
    gap: 10,
    alignItems: 'stretch',
  },
  inputLabel: {
    fontSize: 12.5,
    fontWeight: 600,
    color: '#8a8066',
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
  },
  input: {
    width: '100%',
    padding: '10px 14px',
    fontSize: 15,
    border: '1.5px solid #ddd0b8',
    borderRadius: 6,
    outline: 'none',
    background: '#fffefb',
    boxSizing: 'border-box',
    color: '#26221a',
  },
  passwordWrap: {
    display: 'flex',
    gap: 8,
    alignItems: 'stretch',
  },
  passwordToggle: {
    background: '#efe8d8',
    border: '1px solid #ddd0b4',
    color: '#5c5340',
    fontSize: 13,
    fontWeight: 600,
    cursor: 'pointer',
    padding: '0 16px',
    borderRadius: 6,
    whiteSpace: 'nowrap',
  },
  button: {
    padding: '11px 26px',
    fontSize: 15,
    fontWeight: 700,
    background: '#6b2737',
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
    whiteSpace: 'nowrap',
    alignSelf: 'flex-start',
  },
  feed: {
    display: 'flex',
    flexDirection: 'column',
    gap: 1,
  },
  logRow: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 9,
    padding: '2px 4px',
  },
  logDot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    flexShrink: 0,
    marginTop: 7,
  },
  logText: {
    flex: 1,
    fontSize: 13.5,
    lineHeight: 1.6,
    color: '#6f6656',
    wordBreak: 'break-word',
  },
  expandBtn: {
    background: 'none',
    border: 'none',
    color: '#5c7a2e',
    cursor: 'pointer',
    fontSize: 12,
    textDecoration: 'underline',
    flexShrink: 0,
    padding: 0,
  },
  report: {
    marginTop: 18,
    background: '#fffefb',
    border: '1px solid #e3d9c6',
    borderRadius: 8,
    padding: '24px 28px',
    boxShadow: '0 2px 10px rgba(38, 34, 26, 0.06)',
  },
  reportLabel: {
    fontSize: 11,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: '#a39980',
    marginBottom: 16,
  },
  reportText: {
    margin: 0,
  },
  reportH2: {
    fontFamily: SERIF,
    fontSize: 19,
    fontWeight: 700,
    color: '#26221a',
    margin: '20px 0 8px',
  },
  reportH3: {
    fontFamily: SERIF,
    fontSize: 17,
    fontWeight: 700,
    color: '#6b2737',
    margin: '16px 0 6px',
    borderBottom: '2px solid #e8d3d8',
    paddingBottom: 4,
  },
  reportP: {
    fontSize: 15,
    lineHeight: 1.7,
    color: '#2e2a20',
    margin: '4px 0',
  },
  citation: {
    fontSize: 12,
  },
  citationLink: {
    color: '#6b2737',
    textDecoration: 'none',
    fontWeight: 700,
  },
  references: {
    marginTop: 20,
    paddingTop: 16,
    borderTop: '1px solid #e3d9c6',
  },
  referenceList: {
    margin: 0,
    paddingLeft: 20,
  },
  referenceItem: {
    fontSize: 13.5,
    lineHeight: 1.6,
    color: '#3a3527',
    marginBottom: 6,
  },
  referenceTitle: {
    color: '#6b2737',
    textDecoration: 'none',
    fontWeight: 700,
  },
  referenceMeta: {
    color: '#8a8066',
  },
  ungroundedNote: {
    color: '#9a5f1f',
    fontSize: 12,
    fontWeight: 500,
  },
  abstractOnlyNote: {
    color: '#8a8066',
    fontSize: 12,
    fontStyle: 'italic',
  },
  tierBadge: {
    display: 'inline-block',
    fontSize: 10.5,
    fontWeight: 600,
    padding: '1px 7px',
    borderRadius: 10,
    marginRight: 7,
    whiteSpace: 'nowrap',
    verticalAlign: 'middle',
  },
  cursor: {
    color: '#c98a1f',
    fontSize: 18,
    paddingLeft: 4,
  },
  error: {
    padding: '12px 16px',
    background: '#f7e6e0',
    border: '1px solid #e0b8a4',
    borderRadius: 6,
    color: '#8a3a24',
    fontSize: 14,
    marginBottom: 16,
  },
}
