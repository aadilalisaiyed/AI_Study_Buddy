import { Fragment, Suspense, lazy, useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { BookOpen, FileText, PanelRight, Plus, Send, Trash2 } from 'lucide-react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from './services/api'

const PdfPreview = lazy(() => import('./PdfPreview'))
const date = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })
const markdownPlugins = [remarkGfm]
const markdownElements = ['p', 'h1', 'h2', 'h3', 'h4', 'ul', 'ol', 'li', 'blockquote', 'strong', 'em', 'del', 'hr', 'pre', 'code', 'br', 'table', 'thead', 'tbody', 'tr', 'th', 'td']
const errors = {
  provider_quota: "Gemini's Free-tier quota is temporarily exhausted.",
  provider_configuration: 'Gemini needs to be configured by the workspace administrator.',
  generation_timeout: 'The answer did not finish in time.',
  retrieval_unavailable: 'The study index was temporarily unavailable.',
  document_unavailable: 'A selected document is no longer available for study.',
}

const processingStatuses = new Set(['UPLOADED', 'PROCESSING'])
const sourceStatus = {
  PENDING: 'Upload incomplete', UPLOADING: 'Upload not confirmed', UPLOADED: 'Waiting to be indexed',
  PROCESSING: 'Indexing PDF', READY: 'Ready', FAILED: 'Indexing failed', DELETING: 'Deleting',
}

async function loadSources(token, signal) {
  const filters = { sort: 'newest', page_size: 50 }
  const first = await api.documents.list(token, filters, signal)
  if (first.total <= first.items.length) return first.items
  const second = await api.documents.list(token, { ...filters, page: 2 }, signal)
  return [...first.items, ...second.items]
}

function Answer({ message, onSource }) {
  if (message.role === 'user') return <p className="tutor-question">{message.content}</p>
  if (message.status === 'pending') return <p role="status">Looking for evidence in your notes…</p>
  if (message.status === 'failed') return <p className="error">{errors[message.error_code] || 'This answer could not be completed.'} You can send the question again.</p>
  const sources = new Map(message.citations.map(source => [source.source_id, source]))
  const annotate = child => typeof child !== 'string' ? child : child.split(/(\[S\d+\])/g).map((part, i) => {
    const source = sources.get(part.slice(1, -1))
    return source ? <button key={i} className="tutor-citation" onClick={() => onSource(source)} aria-label={source.filename + ', page ' + source.page_number}>{part}</button> : <Fragment key={i}>{part}</Fragment>
  })
  const annotated = Tag => ({ children }) => <Tag>{Array.isArray(children) ? children.map(annotate) : annotate(children)}</Tag>
  return <div className="tutor-markdown">
    <Markdown skipHtml unwrapDisallowed allowedElements={markdownElements} remarkPlugins={markdownPlugins}
      components={{ p: annotated('p'), li: annotated('li'), td: annotated('td') }}>{message.content}</Markdown>
    {message.citations.length > 0 && <div className="document-actions" aria-label="Answer sources">
      {message.citations.map(source => <button key={source.source_id} className="tutor-citation" onClick={() => onSource(source)}>
        {source.filename} · p. {source.page_number}
      </button>)}
    </div>}
  </div>
}

export default function Tutor({ token, signOut }) {
  const { state } = useLocation()
  const [draft, setDraft] = useState(state?.prompt || '')
  const [current, setCurrent] = useState(null)
  const [conversations, setConversations] = useState([])
  const [hasMore, setHasMore] = useState(false)
  const [messages, setMessages] = useState([])
  const [before, setBefore] = useState(null)
  const [files, setFiles] = useState(null)
  const [maxDocuments, setMaxDocuments] = useState(5)
  const [selected, setSelected] = useState([])
  const [sourcesOpen, setSourcesOpen] = useState(true)
  const [source, setSource] = useState(null)
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [watch, setWatch] = useState(false)
  const [rename, setRename] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const active = useRef(null)
  const messageEnd = useRef(null)

  const pending = messages.some(message => message.status === 'pending')
  async function list(offset = 0, signal) {
    const result = await api.chat.list(token, offset, signal)
    setConversations(items => offset ? [...items, ...result.items.filter(item => !items.some(entry => item.id === entry.id))] : result.items)
    setHasMore(result.has_more)
    setMaxDocuments(result.max_documents)
  }

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      api.chat.list(token, 0, controller.signal),
      loadSources(token, controller.signal),
    ]).then(([history, documents]) => {
      if (controller.signal.aborted) return
      setConversations(history.items)
      setHasMore(history.has_more)
      setMaxDocuments(history.max_documents)
      setFiles(documents)
    }).catch(failure => { if (!controller.signal.aborted) setError(failure) })
    return () => {
      controller.abort()
      active.current?.abort()
    }
  }, [token])

  useEffect(() => {
    if (!current || (!watch && !pending)) return
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      try {
        const result = await api.chat.messages(token, current.id, undefined, controller.signal)
        if (controller.signal.aborted) return
        setMessages(previous => [...previous.filter(message => message.ordinal < (result.items[0]?.ordinal || 0)), ...result.items])
        setWatch(result.items.some(message => message.status === 'pending'))
      } catch (failure) {
        if (!controller.signal.aborted) {
          setError(failure)
          setWatch(false)
        }
      }
    }, 2500)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [current, watch, pending, messages, token])

  async function show(identifier) {
    setLoading(true)
    setError(null)
    try {
      const [conversation, history] = await Promise.all([api.chat.get(token, identifier), api.chat.messages(token, identifier)])
      setCurrent(conversation)
      setSelected(conversation.document_ids)
      setMessages(history.items)
      setBefore(history.next_before)
      setSource(null)
      setPreview(null)
      setConfirmDelete(false)
      setRename(null)
      setWatch(false)
    } catch (failure) {
      setError(failure)
    } finally {
      setLoading(false)
    }
  }

  async function create() {
    const next = await api.chat.create(token)
    setCurrent(next)
    setMessages([])
    setBefore(null)
    setSource(null)
    setPreview(null)
    setConfirmDelete(false)
    setRename(null)
    setWatch(false)
    return next
  }

  async function newChat() {
    setLoading(true)
    setError(null)
    try {
      await create()
      setSelected([])
      await list()
    } catch (failure) {
      setError(failure)
    } finally {
      setLoading(false)
    }
  }

  const processing = Boolean(files?.some(file => processingStatuses.has(file.status)))

  useEffect(() => {
    if (!processing) return
    const controller = new AbortController()
    const timer = setTimeout(() => {
      loadSources(token, controller.signal).then(documents => {
        if (!controller.signal.aborted) setFiles(documents)
      }).catch(failure => {
        if (!controller.signal.aborted) setError(failure)
      })
    }, 4000)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [files, processing, token])

  const readyIds = selected.filter(id => files?.some(file => file.id === id && file.status === 'READY'))
  async function send(event) {
    event.preventDefault()
    const question = draft.trim()
    if (!question || !readyIds.length || busy || pending || loading || active.current) return
    const controller = new AbortController()
    active.current = controller
    setBusy(true)
    setError(null)
    try {
      const conversation = current || await create()
      const result = await api.chat.submit(token, conversation.id, {
        request_id: crypto.randomUUID(), content: question, document_ids: readyIds,
      }, controller.signal)
      setMessages(items => [...items, ...result])
      setDraft('')
      await list()
      requestAnimationFrame(() => messageEnd.current?.scrollIntoView({ block: 'nearest' }))
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure)
      setWatch(true)
    } finally {
      active.current = null
      setBusy(false)
    }
  }

  async function manage(action) {
    setLoading(true)
    setError(null)
    try {
      await action()
    } catch (failure) {
      setError(failure)
    } finally {
      setLoading(false)
    }
  }

  function openSource(item) {
    setSource(item)
    setPreview(null)
    setSourcesOpen(true)
  }

  return <>
    <h1>AI Tutor</h1><p className="script">A better way to understand.</p>
    {error && <div className="panel data-panel error tutor-alert" role="alert">{error.message} {error.status === 401 && <button className="button outline" onClick={signOut}>Sign in again</button>}</div>}
    <div className="tutor-layout">
      <aside className="panel data-panel tutor-history">
        <h2>Conversations</h2>
        <button className="button outline" disabled={busy || loading} onClick={newChat}><Plus size={15} /> New chat</button>
        {!conversations.length && <p>Saved conversations will appear here.</p>}
        <ul>{conversations.map(item => <li key={item.id}><button disabled={loading || busy} aria-current={item.id === current?.id ? 'true' : undefined} onClick={() => show(item.id)}>
          <strong>{item.title}</strong><time dateTime={item.updated_at}>{date.format(new Date(item.updated_at))}</time>
        </button></li>)}</ul>
        {hasMore && <button className="button outline" disabled={busy || loading} onClick={() => manage(() => list(conversations.length))}>More conversations</button>}
      </aside>
      <section className="panel data-panel tutor-main">
        <div className="calendar-header">
          <h2>{current?.title || 'Study my documents'}</h2>
          <button className="icon" aria-label={sourcesOpen ? 'Hide sources' : 'Show sources'} aria-expanded={sourcesOpen} onClick={() => setSourcesOpen(!sourcesOpen)}><PanelRight /></button>
        </div>
        {current && <div className="document-actions">
          <button className="button outline" disabled={busy || loading} onClick={() => setRename(current.title)}>Rename</button>
          <button className="button outline" disabled={busy || pending || loading} onClick={() => setConfirmDelete(true)}><Trash2 size={14} /> Delete chat</button>
        </div>}
        {rename !== null && <form className="tutor-inline" onSubmit={event => {
          event.preventDefault()
          manage(async () => {
            setCurrent(await api.chat.update(token, current.id, { title: rename }))
            setRename(null)
            await list()
          })
        }}><input aria-label="Conversation title" maxLength={120} value={rename} onChange={event => setRename(event.target.value)} required /><button className="button" disabled={loading}>Save name</button><button className="button outline" type="button" onClick={() => setRename(null)}>Cancel</button></form>}
        {confirmDelete && <div className="tutor-inline" role="alert"><p>Delete this conversation and its messages?</p><button className="button" disabled={loading} onClick={() => manage(async () => {
          await api.chat.remove(token, current.id)
          setCurrent(null)
          setMessages([])
          setBefore(null)
          setSelected([])
          setSource(null)
          setPreview(null)
          setConfirmDelete(false)
          await list()
        })}>Confirm deletion</button><button className="button outline" onClick={() => setConfirmDelete(false)}>Cancel</button></div>}
        {before && <button className="button outline" disabled={loading || busy} onClick={() => manage(async () => {
          const history = await api.chat.messages(token, current.id, before)
          setMessages(items => [...history.items, ...items])
          setBefore(history.next_before)
        })}>Load earlier messages</button>}
        {loading && <p role="status">Loading conversation…</p>}
        {files && !files.length && <div className="tutor-empty"><BookOpen size={21} /><h3>Your study materials are waiting.</h3><p>Upload a PDF to start asking questions grounded in your notes.</p><Link className="button" to="/library">Open Library</Link></div>}
        {files?.length > 0 && !readyIds.length && !messages.length && <p>Choose ready PDFs in the sources panel to ask a question.</p>}
        <div className="tutor-messages" aria-label="Conversation messages">{messages.map(message => <article className={'tutor-message ' + message.role} key={message.id}>
          <small>{message.role === 'user' ? 'You' : 'AI Study Buddy'}</small>
          <Answer message={message} onSource={openSource} />
        </article>)}<div ref={messageEnd} /></div>
        {busy && <p role="status">Finding relevant passages and preparing your answer…</p>}
        <form onSubmit={send} className="tutor-compose">
          <label className="draft-label">Your study prompt<textarea value={draft} maxLength={1200} rows={3} onChange={event => setDraft(event.target.value)}
            placeholder="Ask something about your study materials…" onKeyDown={event => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault()
                event.currentTarget.form.requestSubmit()
              }
            }} /></label>
          <div className="document-actions"><button className="button" disabled={!draft.trim() || !readyIds.length || busy || pending || loading}><Send size={16} /> Send prompt</button>
            {busy && <button type="button" className="button outline" onClick={() => active.current?.abort()}>Stop waiting</button>}</div>
        </form>
      </section>
      <aside hidden={!sourcesOpen} className="panel data-panel tutor-sources">
        <h2>Sources</h2>
        <p>Selected excerpts are sent to Gemini to answer your question.</p>
        {processing && <p role="status">PDFs become selectable as soon as indexing finishes.</p>}
        {files?.some(file => file.status === 'FAILED') && <p>Open the Library for indexing errors and retry options.</p>}
        {readyIds.length >= maxDocuments && <p>Remove a selected PDF to choose another.</p>}
        <fieldset disabled={busy || loading}><legend>Select ready PDFs</legend>
          {!files && <p>Loading documents…</p>}
          {files?.map(file => <label className="tutor-file" key={file.id}>
            <input type="checkbox" disabled={file.status !== 'READY' || (!readyIds.includes(file.id) && readyIds.length >= maxDocuments)} checked={readyIds.includes(file.id)} onChange={event => {
              const checked = event.currentTarget.checked
              setSelected(items => checked ? [...new Set([...items, file.id])] : items.filter(id => id !== file.id))
            }} /><span>{file.filename}<small>{sourceStatus[file.status] || file.status}</small></span>
          </label>)}
        </fieldset>
        <Link to="/library">Open Library</Link>
        {source && <section className="tutor-source-detail" aria-label="Citation details">
          <h3><FileText size={17} /> {source.filename}</h3><p>Page {source.page_number}</p>
          {source.available ? <><blockquote>{source.excerpt}</blockquote><button className="button outline" disabled={loading} onClick={() => manage(async () => {
            setPreview(await api.documents.download(token, source.document_id))
          })}>Open page {source.page_number}</button></> : <p>The original source is unavailable.</p>}
          {preview && <Suspense fallback={<p role="status">Loading PDF preview…</p>}><PdfPreview key={source.chunk_id} file={preview} filename={source.filename} initialPage={source.page_number} /></Suspense>}
        </section>}
      </aside>
    </div>
  </>
}
