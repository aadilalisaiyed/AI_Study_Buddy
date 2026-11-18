import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, BookOpen, ClipboardList, RotateCcw } from 'lucide-react'
import { api } from './services/api'

const PdfPreview = lazy(() => import('./PdfPreview'))
const QuizProgress = lazy(() => import('./QuizProgress'))
const kinds = { mcq: 'Multiple choice', boolean: 'True / False', short: 'Short answer', mixed: 'Mixed' }
const defaults = { kind: 'mcq', difficulty: 'medium', question_count: 5, focus: '', subject_id: '', minutes: '', document_ids: [] }
const date = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

function answerLabel(item, value) {
  if (value == null) return 'Not answered'
  if (item.kind === 'mcq') return item.options[value]
  if (item.kind === 'boolean') return value ? 'True' : 'False'
  return value
}

function QuizResults({ result, token, back, retake, practice, busy, setError }) {
  const [source, setSource] = useState(null)
  const [opening, setOpening] = useState(false)
  async function preview(citation) {
    setOpening(true)
    try {
      const file = await api.documents.download(token, citation.document_id)
      setSource({ ...citation, file })
    } catch (error) {
      setError(error)
    } finally {
      setOpening(false)
    }
  }
  return <>
    <section className="panel data-panel quiz-section">
      <h2>{result.quiz.title}</h2>
      <p className="quiz-score">{result.percentage}% · {result.earned}/{result.total} marks</p>
      <p>{result.correct} correct · {result.incorrect} incorrect · {result.partial} partial · {result.unanswered} unanswered</p>
      {result.questions.some(question => question.kind === "short") && <p>Short answers earn marks for recognized rubric phrases. Correct paraphrases can be missed.</p>}
      <p className="quiz-capitalize">{result.quiz.difficulty} · {Math.floor(result.duration_seconds / 60)}m {result.duration_seconds % 60}s</p>
      <p>{result.quiz.sources.map(item => item.filename).join(' · ')}</p>
      <div className="document-actions"><button className="button outline" onClick={back}>Return to Quiz Studio</button><button className="button" disabled={busy} onClick={retake}>Retake quiz</button><button className="button outline" disabled={busy} onClick={practice}>Practice weak topics</button>{!!result.topics.length && <Link className="button outline" to={'/calendar?topic=' + encodeURIComponent([...result.topics].sort((a, b) => a.percentage - b.percentage)[0].label)}>Schedule revision</Link>}</div>
    </section>
    <div className="data-grid">
      {[[result.topics, 'Marks by topic'], [result.difficulties, 'Marks by difficulty']].map(([items, label]) => <section key={label} className="panel data-panel">
        <h2>{label}</h2><ul>{items.map(item => <li key={item.label}>{item.label} · {item.earned}/{item.total}</li>)}</ul>
        <Suspense fallback={null}><QuizProgress items={items} label={label} /></Suspense>
      </section>)}
    </div>
    {source && <section className="panel data-panel quiz-section">
      <div className="calendar-header"><h2>{source.filename} · page {source.page_number}</h2><button className="button outline" onClick={() => setSource(null)}>Close preview</button></div>
      <Suspense fallback={<p role="status">Loading source page…</p>}><PdfPreview key={source.chunk_id} file={source.file} filename={source.filename} initialPage={source.page_number} /></Suspense>
    </section>}
    <section className="quiz-section" aria-label="Question review">{result.questions.map(item => <article className="panel data-panel" key={item.id}>
      <h3>{item.position}. {item.prompt}</h3>
      <p>{item.answer == null ? 'Not answered' : item.earned === item.max_marks ? 'Correct' : item.earned > 0 ? 'Partial credit' : 'Incorrect'} · {item.earned}/{item.max_marks} marks</p>
      <p><strong>Your answer</strong> {answerLabel(item, item.answer)}</p>
      <p><strong>{item.kind === 'short' ? 'Expected answer' : 'Correct answer'}</strong> {answerLabel(item, item.correct_answer)}</p>
      <p>{item.explanation}</p>
      {item.kind === 'short' && item.answer != null && <ul>{item.feedback.map(label => <li key={label}>{label}</li>)}</ul>}
      {item.citations.map(citation => citation.available ? <button key={citation.source_id} className="button outline" disabled={opening} onClick={() => preview(citation)}>
        <BookOpen size={16} /> {citation.filename} · page {citation.page_number}
      </button> : <p key={citation.source_id}>{citation.filename} · page {citation.page_number} · source unavailable</p>)}
    </article>)}</section>
  </>
}

function TakeQuiz({ attempt, busy, save, submit, back, expired }) {
  const [position, setPosition] = useState(0)
  const [typed, setTyped] = useState(null)
  const [optimistic, setOptimistic] = useState(null)
  const [seconds, setSeconds] = useState(null)
  const item = attempt.questions[position]
  const value = optimistic?.id === item.id ? optimistic.value : attempt.answers[item.id]
  const draft = typed?.id === item.id ? typed.value : value || ''
  const expiredCalled = useRef(false)
  const lastAutoSave = useRef(null)
  useEffect(() => {
    if (!attempt.deadline) return
    const tick = () => setSeconds(Math.max(0, Math.ceil((Date.parse(attempt.deadline) - Date.now()) / 1000)))
    tick()
    const interval = setInterval(tick, 1000)
    return () => clearInterval(interval)
  }, [attempt.deadline])
  useEffect(() => {
    if (seconds === 0 && !busy && !expiredCalled.current) {
      expiredCalled.current = true
      expired()
    }
  }, [seconds, expired, busy])

  useEffect(() => {
    if (!typed || busy || seconds === 0 || lastAutoSave.current === typed) return
    const timer = setTimeout(async () => {
      lastAutoSave.current = typed
      if (await save(typed.id, typed.value)) setTyped(current => current === typed ? null : current)
    }, 650)
    return () => clearTimeout(timer)
  }, [typed, busy, seconds, save])

  async function flush() {
    if (typed?.id !== item.id) return true
    if (!await save(item.id, typed.value)) return false
    setTyped(null)
    return true
  }
  async function choose(answer) {
    setOptimistic({ id: item.id, value: answer })
    await save(item.id, answer)
    setOptimistic(null)
  }
  async function move(next) {
    if (await flush()) setPosition(next)
  }
  return <section className="panel data-panel quiz-section">
    <div className="calendar-header"><h2>{attempt.quiz.title}</h2>{seconds != null && <span aria-label="Time remaining">{Math.floor(seconds/60)}:{String(seconds%60).padStart(2, '0')} remaining</span>}</div>
    <progress value={position + 1} max={attempt.questions.length} aria-label="Quiz progress" />
    <p>Question {position + 1} of {attempt.questions.length} · {item.max_marks} {item.max_marks === 1 ? 'mark' : 'marks'}</p>
    <div className="document-actions" aria-label="Question navigator">
      {attempt.questions.map((question, index) => <button key={question.id} disabled={busy} className={'button ' + (position === index ? '' : 'outline')} aria-current={position === index ? 'step' : undefined} aria-label={'Question ' + (index + 1) + (attempt.answers[question.id] != null ? ', answered' : '')} onClick={() => move(index)}>{index + 1}</button>)}
    </div>
    <fieldset className="quiz-answer-field" disabled={busy || seconds === 0}>
      <legend>{item.prompt}</legend>
      {item.kind === 'short' ? <>
        <label>Your answer<textarea value={draft} rows={5} maxLength={1600} onChange={event => setTyped({ id: item.id, value: event.target.value })} /></label>
        <button className="button outline" disabled={typed?.id !== item.id} onClick={flush}>Save answer</button>
      </> : (item.kind === 'mcq' ? item.options.map((text, index) => [index, text]) : [[true, 'True'], [false, 'False']]).map(([answer, label]) => (
        <label key={label}><input type="radio" name={item.id} checked={value === answer} onChange={() => choose(answer)} />{label}</label>
      ))}
      {item.kind !== 'short' && value != null && <button className="button outline" onClick={() => choose(null)}>Clear answer</button>}
    </fieldset>
    <p role="status">{busy ? 'Saving…' : typed?.id === item.id ? 'Short answer has unsaved changes.' : 'Saved answers can be resumed from quiz history.'}</p>
    <div className="document-actions">
      <button className="button outline" disabled={busy || position === 0} onClick={() => move(position - 1)}><ArrowLeft size={16} /> Previous</button>
      <button className="button outline" disabled={busy || position === attempt.questions.length - 1} onClick={() => move(position + 1)}>Next <ArrowRight size={16} /></button>
      <button className="button outline" disabled={busy} onClick={async () => { if (await flush()) back() }}>Save and exit</button>
      <button className="button" disabled={busy} onClick={async () => { if (await flush()) submit() }}>Submit quiz</button>
    </div>
  </section>
}

export default function QuizStudio({ token, signOut }) {
  const [params, setParams] = useSearchParams()
  const attemptId = params.get('attempt')
  const quizId = params.get('quiz')
  const [form, setForm] = useState(() => ({ ...defaults, focus: (params.get('topic') || '').slice(0, 160) }))
  const [files, setFiles] = useState(null)
  const [subjects, setSubjects] = useState([])
  useEffect(() => {
    let active = true
    api.subjects.list(token).then(items => { if (active) setSubjects(items) }).catch(() => {})
    return () => { active = false }
  }, [token])
  const [config, setConfig] = useState({ max_questions: 20, max_documents: 5 })
  const [quizzes, setQuizzes] = useState([])
  const [hasMore, setHasMore] = useState(false)
  const [summary, setSummary] = useState(null)
  const [quiz, setQuiz] = useState(null)
  const [history, setHistory] = useState([])
  const [hasMoreAttempts, setHasMoreAttempts] = useState(false)
  const [attempt, setAttempt] = useState(null)
  const [results, setResults] = useState(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState(null)
  const [confirm, setConfirm] = useState(false)
  const request = useRef(null)
  const locked = useRef(false)

  useEffect(() => {
    let live = true
    async function load() {
      try {
        const [documents, preferences, listing, performance] = await Promise.all([
          api.documents.list(token, { status: 'READY', page_size: 50, page: 1 }),
          api.quizzes.config(token), api.quizzes.list(token), api.quizzes.summary(token),
        ])
        if (documents.total > 50) documents.items.push(...(await api.documents.list(token, { status: 'READY', page_size: 50, page: 2 })).items)
        if (!live) return
        setFiles(documents.items); setConfig(preferences); setQuizzes(listing.items); setHasMore(listing.has_more); setSummary(performance)
      } catch (failure) { if (live) setError(failure) }
    }
    load()
    return () => { live = false }
  }, [token, quizId, attemptId])

  useEffect(() => {
    if (!attemptId && !quizId) return
    let live = true
    let timer
    async function load() {
      try {
        if (attemptId) {
          const current = await api.quizzes.attempt(token, attemptId)
          const result = current.status === 'graded' ? await api.quizzes.results(token, attemptId) : null
          if (live) { setAttempt(current); setResults(result) }
        } else {
          const [current, attempts] = await Promise.all([api.quizzes.get(token, quizId), api.quizzes.attempts(token, quizId)])
          if (live) {
            setQuiz(current); setHistory(attempts.items); setHasMoreAttempts(attempts.has_more)
            if (current.status === 'generating') timer = setTimeout(load, 3000)
          }
        }
      } catch (failure) { if (live) setError(failure) }
    }
    load()
    return () => { live = false; clearTimeout(timer) }
  }, [token, quizId, attemptId])

  function go(values) {
    setError(null); setConfirm(false); setQuiz(null); setAttempt(null); setResults(null); setHistory([])
    setParams(values)
  }

  async function run(label, action) {
    if (locked.current) return false
    locked.current = true
    setBusy(label); setError(null)
    try { await action(); return true } catch (failure) { setError(failure); return false } finally { locked.current = false; setBusy('') }
  }

  function generate(weak = false) {
    return run('Generating and validating questions…', async () => {
      const payload = { ...form, subject_id: form.subject_id || null, minutes: form.minutes ? Number(form.minutes) : null, weak_practice: weak }
      const fingerprint = JSON.stringify(payload)
      const id = request.current?.fingerprint === fingerprint ? request.current.id : crypto.randomUUID()
      request.current = { id, fingerprint }
      const generated = await api.quizzes.generate(token, { ...payload, request_id: id })
      request.current = null
      go({ quiz: generated.id })
    })
  }

  function start(id, retake = false) {
    return run('Starting attempt…', async () => {
      const current = await api.quizzes.start(token, id, { request_id: crypto.randomUUID() }, retake)
      go({ attempt: current.id })
    })
  }

  function submit(id) {
    return run('Grading quiz…', async () => setResults(await api.quizzes.submit(token, id)))
  }

  const field = (key, value) => setForm(current => ({ ...current, [key]: value }))
  return <>
    <h1>Quiz Studio</h1><p className="script">Practice makes progress.</p>
    {error && <div className="panel data-panel error" role="alert">{error.message} {error.status === 401 && <button className="button outline" onClick={signOut}>Sign in again</button>}</div>}
    {busy && <p role="status">{busy}</p>}
    {results && attemptId === results.attempt.id ? <QuizResults result={results} token={token} back={() => go({})}
      retake={() => start(results.quiz.id, true)} practice={() => generate(true)} busy={busy} setError={setError} />
      : attemptId ? (attempt?.id === attemptId ? <TakeQuiz key={attemptId} attempt={attempt} busy={busy}
        save={(id, value) => run('Saving answer…', async () => setAttempt(await api.quizzes.save(token, attemptId, { answers: { [id]: value } })))}
        expired={() => submit(attemptId)} submit={() => submit(attemptId)} back={() => go({ quiz: attempt.quiz_id })} />
        : <><p role="status">Opening attempt…</p><button className="button outline" onClick={() => go({})}>Back to Quiz Studio</button></>)
      : quizId ? <section className="panel data-panel quiz-section">
        <button className="button outline" onClick={() => go({})}>Back to Quiz Studio</button>
        {quiz?.id === quizId && <>
          <h2>{quiz.title}</h2><p className="quiz-capitalize">{quiz.question_count} questions · {quiz.difficulty} · {kinds[quiz.kind]} · {quiz.minutes ? quiz.minutes + ' minutes' : 'Untimed'}</p>
          <p>{quiz.sources.map(item => item.filename).join(' · ')}</p><p>Questions cover sampled passages from the selected PDFs.</p>
          {quiz.status === 'ready' ? <button className="button" disabled={Boolean(busy)} onClick={() => start(quiz.id)}>Start quiz</button>
            : <p role="status">{quiz.error_message || 'Generation is in progress.'}</p>}
          <h3>Attempt history</h3>
          {!history.length && <p>No attempts yet.</p>}
          {history.map(item => <button key={item.id} className="button outline" disabled={Boolean(busy)} onClick={() => go({ attempt: item.id })}>
            {item.status === 'graded' ? 'View results' : 'Resume attempt'} · {date.format(new Date(item.started_at))}
          </button>)}
          {hasMoreAttempts && <button className="button outline" disabled={Boolean(busy)} onClick={() => run('Loading attempts…', async () => {
            const page = await api.quizzes.attempts(token, quizId, history.length); setHistory([...history, ...page.items]); setHasMoreAttempts(page.has_more)
          })}>More attempts</button>}
          {confirm ? <div className="document-actions"><p>Delete this quiz and its attempts?</p><button className="button" disabled={Boolean(busy)} onClick={() => run('Deleting quiz…', async () => {
            await api.quizzes.remove(token, quizId); go({})
          })}>Confirm deletion</button><button className="button outline" onClick={() => setConfirm(false)}>Cancel</button></div>
            : <button className="button outline" disabled={Boolean(busy) || quiz.status === 'generating'} onClick={() => setConfirm(true)}>Delete quiz</button>}
        </>}
      </section> : <>
        {summary && <section className="panel data-panel quiz-section">
          <h2>Practice history</h2><p>{summary.attempts_completed} completed attempts · {summary.questions_answered} answered · {summary.attempts_completed ? summary.average_score_percent + '% average score' : 'No scores yet'}</p>
          {!!summary.trend.length && <div className="document-actions" aria-label="Recent attempts">{summary.trend.slice(-3).reverse().map(item => (
            <button key={item.id} className="button outline" onClick={() => go({ attempt: item.id })}>{item.percentage}% · {date.format(new Date(item.date))}</button>
          ))}</div>}
          {!!summary.weak_topics.length && <><p>Topics to revisit</p><ul>{summary.weak_topics.map(item => <li key={item.key}>{item.label} · {item.percentage}% of available marks</li>)}</ul>
            <button className="button outline" disabled={Boolean(busy)} onClick={() => generate(true)}><RotateCcw size={16} /> Practice weak topics</button></>}
        </section>}
        <div className="data-grid">
          <form className="panel data-panel quiz-section" onSubmit={event => { event.preventDefault(); generate() }}>
            <h2><ClipboardList size={21} /> Create quiz</h2>
            {!files && <p role="status">Loading ready PDFs…</p>}
            {files?.length === 0 && <p>Upload a PDF and wait for it to become ready. <Link to="/library">Open Library</Link></p>}
            {!!files?.length && <fieldset className="quiz-answer-field"><legend>Select up to {config.max_documents} ready PDFs</legend>
              {files.map(file => <label key={file.id}><input type="checkbox" checked={form.document_ids.includes(file.id)}
                disabled={Boolean(busy) || (!form.document_ids.includes(file.id) && form.document_ids.length >= config.max_documents)}
                onChange={event => field('document_ids', event.target.checked ? [...form.document_ids, file.id] : form.document_ids.filter(id => id !== file.id))} />{file.filename}</label>)}
            </fieldset>}
            <div className="quiz-form-grid">
              <label>Quiz type<select value={form.kind} onChange={event => field('kind', event.target.value)}>{Object.entries(kinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              <label>Difficulty<select value={form.difficulty} onChange={event => field('difficulty', event.target.value)}>{['easy','medium','hard','mixed'].map(value => <option key={value} value={value}>{value}</option>)}</select></label>
              <label>Question count<select value={form.question_count} onChange={event => field('question_count', Number(event.target.value))}>{[5,10,15,20].filter(n => n <= config.max_questions).map(n => <option key={n}>{n}</option>)}</select></label>
              <label>Time limit in minutes<input type="number" min={1} max={90} placeholder="Untimed" value={form.minutes} onChange={event => field('minutes', event.target.value)} /></label>
              <label>Subject<select value={form.subject_id} onChange={event => field('subject_id', event.target.value)}>
                <option value="">Uncategorized</option>{subjects.map(subject => <option key={subject.id} value={subject.id}>{subject.name}</option>)}
              </select></label>
              <label>Topic focus<input maxLength={160} value={form.focus} placeholder="Optional" onChange={event => field('focus', event.target.value)} /></label>
            </div>
            <p>Selected passages are sent to Gemini for generation.</p>
            <button className="button" disabled={Boolean(busy) || !form.document_ids.length}>Generate quiz</button>
          </form>
          <section className="panel data-panel quiz-section">
            <h2>Recent quizzes</h2>
            {!quizzes.length && <p>Your generated quizzes will appear here.</p>}
            {quizzes.map(item => <button key={item.id} className="button outline" disabled={Boolean(busy)} onClick={() => go({ quiz: item.id })}>
              {item.title} · {item.difficulty} · {item.status}
            </button>)}
            {hasMore && <button className="button outline" disabled={Boolean(busy)} onClick={() => run('Loading quizzes…', async () => {
              const page = await api.quizzes.list(token, quizzes.length); setQuizzes([...quizzes, ...page.items]); setHasMore(page.has_more)
            })}>More quizzes</button>}
          </section>
        </div>
      </>}
  </>
}
