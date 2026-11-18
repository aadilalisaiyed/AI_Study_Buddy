import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { BookOpen, Download, Eye, FileText, RefreshCw, Search, Trash2, Upload } from 'lucide-react'
import { api } from './services/api'

const PdfPreview = lazy(() => import('./PdfPreview'))

const labels = {
  PENDING: 'Upload pending', UPLOADING: 'Awaiting upload confirmation', UPLOADED: 'Queued for processing',
  PROCESSING: 'Processing', READY: 'Ready', FAILED: 'Processing failed', DELETING: 'Deleting',
}
const pageSize = 12
const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })

function fileSize(bytes) {
  return bytes < 1024 * 1024 ? Math.max(1, Math.round(bytes / 1024)) + ' KB' : (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function useDocumentList(token, search, status, sort, page, revision, subjectFilter) {
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    const controller = new AbortController()
    let timer
    async function load(quiet = false) {
      if (!quiet) setLoading(true)
      try {
        const data = await api.documents.list(token, {
          search, sort, page, page_size: pageSize, ...(status && { status }), ...(subjectFilter && { subject_id: subjectFilter }),
        }, controller.signal)
        if (!controller.signal.aborted) {
          setResult(data)
          setError(null)
        }
      } catch (failure) {
        if (!controller.signal.aborted) {
          setError(failure)
          if (failure.status === 401) return
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
      if (!controller.signal.aborted) timer = setTimeout(() => load(true), 3500)
    }
    timer = setTimeout(load, 150)
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [token, search, status, sort, page, revision, subjectFilter])
  return { result, error, loading }
}

function RemoveDialog({ target, confirm, close }) {
  const dialog = useRef(null)
  useEffect(() => {
    const element = dialog.current
    element.showModal()
    return () => element.close()
  }, [])
  return <dialog ref={dialog} className="panel library-dialog" onCancel={close} aria-labelledby="delete-title">
    <h2 id="delete-title">Delete this document?</h2>
    <p>{target.filename} and its indexed text will be removed from your library.</p>
    <div className="document-actions"><button className="button outline" autoFocus onClick={close}>Cancel</button><button className="button" onClick={confirm}>Delete PDF</button></div>
  </dialog>
}

export default function DocumentLibrary({ token, signOut }) {
  const input = useRef(null)
  const active = useRef(null)
  const resumeTarget = useRef(null)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [subjects, setSubjects] = useState([])
  const [subjectName, setSubjectName] = useState('')
  const [subjectFilter, setSubjectFilter] = useState('')
  const [subjectError, setSubjectError] = useState('')
  useEffect(() => {
    let active = true
    api.subjects.list(token).then(items => { if (active) setSubjects(items) })
      .catch(failure => { if (active) setSubjectError(failure.message) })
    return () => { active = false }
  }, [token])

  async function addSubject(event) {
    event.preventDefault()
    setSubjectError('')
    try {
      const subject = await api.subjects.create(token, subjectName)
      setSubjects(items => [...items, subject])
      setSubjectName('')
    } catch (failure) { setSubjectError(failure.message) }
  }

  async function assignSubject(document, value) {
    setSubjectError('')
    try {
      await api.subjects.assign(token, document.id, value || null)
      refresh()
    } catch (failure) { setSubjectError(failure.message) }
  }
  const [sort, setSort] = useState('newest')
  const [page, setPage] = useState(1)
  const [revision, setRevision] = useState(0)
  const [target, setTarget] = useState(null)
  const [busy, setBusy] = useState('')
  const [progress, setProgress] = useState(null)
  const [notice, setNotice] = useState('')
  const [actionError, setActionError] = useState(null)
  const [preview, setPreview] = useState(null)
  const { result, error, loading } = useDocumentList(token, search, status, sort, page, revision, subjectFilter)
  const items = result?.items || []
  const maxPage = Math.max(1, Math.ceil((result?.total || 0) / pageSize))
  const failure = actionError || error

  useEffect(() => () => active.current?.abort(), [])
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview.url) }, [preview])

  function refresh() {
    setRevision(value => value + 1)
  }

  async function perform(key, action) {
    if (active.current) return
    const controller = new AbortController()
    active.current = controller
    setBusy(key)
    setActionError(null)
    setNotice('')
    try {
      await action(controller.signal)
    } catch (failure) {
      if (!controller.signal.aborted) setActionError(failure)
    } finally {
      if (!controller.signal.aborted) {
        active.current = null
        setBusy('')
        setProgress(null)
        refresh()
      }
    }
  }

  function choose(document = null) {
    resumeTarget.current = document
    input.current.click()
  }

  async function selectFile(event) {
    const [file] = event.target.files
    event.target.value = ''
    if (!file) return
    const previous = resumeTarget.current
    resumeTarget.current = null
    if (!/\.pdf$/i.test(file.name) || (file.type && file.type !== 'application/pdf') || !file.size) {
      setActionError(new Error('Choose a nonempty PDF file.'))
      return
    }
    if (previous && previous.file_size !== file.size) {
      setActionError(new Error('Select the original PDF to resume this upload.'))
      return
    }
    await perform('upload', async signal => {
      const document = previous || (await api.documents.initialize(token, file, signal)).document
      setProgress(0)
      await api.documents.upload(token, document.id, file, setProgress, signal)
      await api.documents.complete(token, document.id, signal)
      setSearch('')
      setStatus('')
      setPage(1)
      setNotice('Upload verified. The PDF is queued for processing.')
    })
  }

  function fetchPdf(document, showPreview) {
    return perform(document.id, async signal => {
      const data = await api.documents.download(token, document.id, signal)
      const url = URL.createObjectURL(data)
      if (showPreview) {
        setPreview({ url, file: data, name: document.filename, id: document.id })
        return
      }
      const link = window.document.createElement('a')
      link.href = url
      link.download = document.filename
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 30000)
    })
  }

  function complete(document) {
    return perform(document.id, async signal => {
      await api.documents.complete(token, document.id, signal)
      setNotice('Upload verified. The PDF is queued for processing.')
    })
  }

  function remove(document) {
    setTarget(null)
    return perform(document.id, async signal => {
      await api.documents.remove(token, document.id, signal)
      if (preview?.id === document.id) setPreview(null)
      setNotice('Deletion requested. The worker will remove the original and any index entries.')
    })
  }

  return <>
    <div className="study-heading">
      <div><h1>Your Knowledge Library</h1><p className="script">Everything worth remembering, in one place.</p></div>
      <button className="button" disabled={Boolean(busy) || failure?.status === 401} onClick={() => choose()}><Upload size={16} /> Upload PDF</button>
      <input ref={input} type="file" accept=".pdf,application/pdf" hidden onChange={selectFile} />
    </div>
    <div className="panel library-toolbar">
      <label className="search"><Search size={18} /><input type="search" placeholder="Search documents…" value={search} onChange={event => { setSearch(event.target.value); setPage(1) }} aria-label="Search documents" /></label>
      <label><span id="library-filter-label">Status</span><select aria-labelledby="library-filter-label" value={status} onChange={event => { setStatus(event.target.value); setPage(1) }}><option value="">All statuses</option>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label><span id="library-sort-label">Sort by</span><select aria-labelledby="library-sort-label" value={sort} onChange={event => { setSort(event.target.value); setPage(1) }}><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></label>
    </div>
    <form className="document-actions" onSubmit={addSubject}>
      <label>New subject<input required maxLength={80} value={subjectName} onChange={event => setSubjectName(event.target.value)} /></label>
      <button className="button outline">Create subject</button>
    </form>
    <label>Filter by subject<select value={subjectFilter} onChange={event => { setSubjectFilter(event.target.value); setPage(1) }}>
      <option value="">All subjects</option>{subjects.map(subject => <option key={subject.id} value={subject.id}>{subject.name}</option>)}
    </select></label>
    {subjectError && <p role="alert">{subjectError}</p>}
    {busy === 'upload' && <div className="panel data-panel library-feedback" role="status">
      <p>{progress == null ? 'Preparing upload…' : progress === 100 ? 'PDF transferred. Waiting for storage verification…' : 'Sending PDF to document storage…'}</p>
      {progress != null && <progress aria-label="PDF transfer progress" max={100} value={progress}>{progress}%</progress>}
      <button className="button outline" onClick={() => {
        active.current?.abort()
        active.current = null
        setBusy('')
        setProgress(null)
        setNotice('Upload interrupted. Resume it from the library if a record was created.')
        refresh()
      }}>Cancel upload</button>
    </div>}
    {failure && <div className="panel data-panel library-feedback error" role="alert">
      <p>{failure.message}</p>
      {failure.status === 401 ? <button className="button outline" onClick={signOut}>Sign in again</button> : error && <button className="button outline" onClick={refresh}>Reload library</button>}
    </div>}
    {notice && <p className="panel data-panel library-feedback" role="status">{notice}</p>}
    {preview && <section className="panel data-panel library-feedback">
      <div className="calendar-header"><h2>{preview.name}</h2><button className="button outline" onClick={() => setPreview(null)}>Close preview</button></div>
      <Suspense fallback={<p role="status">Loading PDF preview…</p>}>
        <PdfPreview key={preview.url} file={preview.file} filename={preview.name} />
      </Suspense>
      <a href={preview.url} download={preview.name}>Download the PDF to view it with your own reader</a>
    </section>}
    {loading && !result && <p className="panel data-panel library-feedback" role="status">Loading your documents…</p>}
    {result && !items.length && <div className="panel empty"><BookOpen className="accent" /><h3>{search || status ? 'No matching documents.' : page > 1 ? 'No documents on this page.' : 'Your library is waiting.'}</h3><p>{search || status ? 'Try a different filename or status.' : 'Upload a PDF with selectable text to make it available for study.'}</p></div>}
    {items.length > 0 && <ul className="document-list" aria-label="Your documents">{items.map(document => {
      const disabled = Boolean(busy) || failure?.status === 401
      const pending = document.status === 'PENDING' || document.status === 'UPLOADING'
      const deleting = document.status === 'DELETING'
      return <li key={document.id} className="panel data-panel document-item">
        <FileText className="accent" size={23} />
        <div className="document-info">
          <h2>{document.filename}</h2><p>{fileSize(document.file_size)} · {dateFormat.format(new Date(document.created_at))}{document.page_count > 0 && ' · ' + document.page_count + ' pages'}</p>
          <span className={'document-status status-' + document.status.toLowerCase()}>{labels[document.status]}</span>
          <label>Subject for {document.filename}<select value={document.subject_id || ''} disabled={disabled || deleting}
            onChange={event => assignSubject(document, event.target.value)}>
            <option value="">Uncategorized</option>{subjects.map(subject => <option key={subject.id} value={subject.id}>{subject.name}</option>)}
          </select></label>
          {document.error_message && <p className="document-error">{document.error_message}{document.status === 'UPLOADED' && ' The worker will retry automatically.'}</p>}
        </div>
        <div className="document-actions">
          {document.status === 'PENDING' && <button className="button outline" disabled={disabled} onClick={() => choose(document)}>Resume upload</button>}
          {pending && <button className="button outline" disabled={disabled} onClick={() => complete(document)}>Verify upload</button>}
          {!pending && !deleting && <>
            <button className="button outline" disabled={disabled} onClick={() => fetchPdf(document, true)}><Eye size={16} /> Preview</button>
            <button className="button outline" disabled={disabled} onClick={() => fetchPdf(document, false)}><Download size={16} /> Download</button>
          </>}
          {document.status === 'FAILED' && document.retryable && <button className="button outline" disabled={disabled} onClick={() => perform(document.id, async signal => {
            await api.documents.retry(token, document.id, signal)
            setNotice('Processing retry queued.')
          })}><RefreshCw size={16} /> Retry processing</button>}
          {(!deleting || document.retryable) && <button className="button outline" disabled={disabled} onClick={() => setTarget(document)}><Trash2 size={16} />{deleting ? 'Retry deletion' : 'Delete'}</button>}
        </div>
      </li>
    })}</ul>}
    {(maxPage > 1 || page > 1) && <nav className="document-actions" aria-label="Document pages"><button className="button outline" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page} of {maxPage}</span><button className="button outline" disabled={page >= maxPage} onClick={() => setPage(page + 1)}>Next</button></nav>}
    {target && <RemoveDialog target={target} confirm={() => remove(target)} close={() => setTarget(null)} />}
  </>
}
