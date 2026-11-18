import { lazy, Suspense, useEffect, useId, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { ArrowRight, Asterisk, BookOpen, ChevronLeft, ChevronRight, Clock, Flame, LogOut, Menu, Target, Upload, X } from 'lucide-react'
import DocumentLibrary from './DocumentLibrary'
import { studyPages } from './studyPages'
const QuizStudio = lazy(() => import('./QuizStudio'))
const RevisionPlanner = lazy(() => import('./RevisionPlanner'))
const LearningAnalytics = lazy(() => import('./LearningAnalytics'))
const Tutor = lazy(() => import('./Tutor'))

const metrics = [['Topics studied', BookOpen], ['Quiz accuracy', Target], ['Study time', Clock], ['Day streak', Flame]]
const demoMetrics = ['24', '84%', '18 hrs', '7']
const ActivityPlot = lazy(() => import('./StudyCharts').then(module => ({ default: module.ProgressChart })))
const MasteryPlot = lazy(() => import('./StudyCharts').then(module => ({ default: module.MasteryChart })))

export function ProgressChart() {
  return <Suspense fallback={<div className="chart" role="status">Loading study activity…</div>}><ActivityPlot /></Suspense>
}

function MasteryChart() {
  return <Suspense fallback={<p role="status">Loading subject mastery…</p>}><MasteryPlot /></Suspense>
}

function Metrics({ demo }) {
  return <div className="metric-grid">{metrics.map(([label, Icon], i) => <div key={label} className="panel metric"><Icon /><div><strong>{demo ? demoMetrics[i] : '—'}</strong><small>{label}</small></div></div>)}</div>
}

export function WorkspacePreview() {
  return <div className="workspace-preview panel">
    <div className="preview-rail"><strong><Asterisk size={20} /> Study Buddy</strong>{studyPages.map(([, label, Icon], index) => <span className={index === 0 ? 'selected' : ''} key={label}><Icon size={14} />{label}</span>)}</div>
    <div className="preview-body"><small className="eyebrow">Illustrative dashboard</small><h3>Good morning.</h3><p className="script">Let’s keep the momentum going.</p><Metrics demo /><div className="data-grid"><div className="panel data-panel"><h4>Learning Progress</h4><ProgressChart /></div><div className="panel data-panel"><h4>Subject Mastery</h4><MasteryChart /></div></div></div>
  </div>
}

const questions = [
  ['What does a database primary key identify?', ['A unique row', 'Every column', 'A database server'], 0, 'A primary key uniquely identifies a row.'],
  ['What helps prevent inconsistent copies of the same fact?', ['Duplicating every row', 'Normalization', 'Removing all keys'], 1, 'Normalization puts each fact where it belongs and reduces unnecessary duplication.'],
  ['Which constraint can require a reference to an existing row?', ['A text format', 'A sort order', 'A foreign key'], 2, 'A foreign key enforces a reference to a valid key in another table or row.'],
]

export function SampleQuiz() {
  const quizId = useId()
  const [step, setStep] = useState(0)
  const [answers, setAnswers] = useState({})
  const [finished, setFinished] = useState(false)
  const [question, options] = questions[step]
  const score = questions.filter(([, , correct], index) => correct === answers[index]).length
  return <div className="example sample-quiz"><small className="eyebrow">Sample quiz · Databases</small>{finished ? <>
    <h3>Score {score}/{questions.length} · {Math.round(100 * score / questions.length)}%</h3>
    <ol>{questions.map(([label, , correct, description], index) => <li key={label}><strong>{answers[index] === correct ? 'Correct' : 'Review'} · {label}</strong><p>{description}</p></li>)}</ol>
    <button className="button outline" onClick={() => { setStep(0); setAnswers({}); setFinished(false) }}>Try again</button>
  </> : <>
    <small>Question {step + 1} of {questions.length}</small>
    <fieldset><legend>{question}</legend>{options.map((option, index) => <label key={option}><input type="radio" name={quizId} checked={answers[step] === index} onChange={() => setAnswers({ ...answers, [step]: index })} />{option}</label>)}</fieldset>
    <div className="quiz-actions"><button className="button outline" disabled={step === 0} onClick={() => setStep(step - 1)}>Previous</button><button className="button" disabled={answers[step] === undefined} onClick={() => step === questions.length - 1 ? setFinished(true) : setStep(step + 1)}>{step === questions.length - 1 ? 'Review answers' : 'Next'}</button></div>
  </>}</div>
}

export function CalendarPreview({ demo = false, sessions = [], timezone, onRange }) {
  const [date, setDate] = useState(() => demo ? new Date(2026, 9, 5) : new Date())
  const [view, setView] = useState(demo ? 'Week' : 'Month')
  const first = view === 'Month' ? new Date(date.getFullYear(), date.getMonth(), 1) : new Date(date.getFullYear(), date.getMonth(), date.getDate() - (date.getDay() + 6) % 7)
  const offset = view === 'Month' ? (first.getDay() + 6) % 7 : 0
  const dates = Array.from({ length: view === 'Month' ? 42 : 7 }, (_, i) => new Date(first.getFullYear(), first.getMonth(), first.getDate() + i - offset))
  const rangeStart = new Date(dates[0].getTime() - 86400000).toISOString()
  const rangeEnd = new Date(dates.at(-1).getTime() + 172800000).toISOString()
  useEffect(() => {
    if (onRange) onRange({ start: rangeStart, end: rangeEnd })
  }, [rangeStart, rangeEnd, onRange])
  const dayFormatter = new Intl.DateTimeFormat('sv-SE', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' })
  const label = value => dayFormatter.format(new Date(value))
  const visible = new Set(dates.map(day => day.toLocaleDateString('sv-SE')))
  const daySessions = day => {
    const start = day.toLocaleDateString('sv-SE')
    return sessions.filter(item => label(item.start_at) <= start && label(new Date(Date.parse(item.end_at) - 1)) >= start)
  }
  function shift(amount) {
    setDate(view === 'Month' ? new Date(date.getFullYear(), date.getMonth() + amount, 1) : new Date(date.getFullYear(), date.getMonth(), date.getDate() + 7 * amount))
  }
  return <div className="example calendar"><div className="calendar-header"><strong>{date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}</strong>{!demo && <div><button className="button outline" onClick={() => setDate(new Date())}>Today</button><button className="icon" aria-label={'Previous ' + view.toLowerCase()} onClick={() => shift(-1)}><ChevronLeft /></button><button className="icon" aria-label={'Next ' + view.toLowerCase()} onClick={() => shift(1)}><ChevronRight /></button></div>}</div>
    {demo ? <small>Example revision schedule</small> : <div className="segments" role="group" aria-label="Calendar view">{['Month', 'Week', 'Agenda'].map(label => <button key={label} onClick={() => setView(label)} aria-pressed={view === label}>{label}</button>)}</div>}
    {view === 'Agenda' ? (sessions.some(item => visible.has(label(item.start_at))) ? <ul className="planner-agenda">{sessions.filter(item => visible.has(label(item.start_at))).map(item => <li key={item.id}><strong>{item.title}</strong> · {label(item.start_at)} · {item.status}</li>)}</ul> : <p>No revision sessions for the week of {first.toLocaleDateString()}.</p>) : <div className="calendar-grid">{['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(day => <strong key={day}>{day}</strong>)}{dates.map((day, index) => <div className={day.getMonth() === date.getMonth() ? '' : 'outside'} key={day.toISOString()}><time dateTime={day.toLocaleDateString('sv-SE')}>{day.getDate()}</time>{demo && (index === 1 || index === 4) && <small>{index === 1 ? 'Databases' : 'Algorithms'}</small>}{!demo && daySessions(day).map(item => <small key={item.id} className={'planner-calendar-label ' + item.status} title={item.title}>{item.title}</small>)}</div>)}</div>}
  </div>
}

function Dashboard({ user }) {
  const [hour] = useState(() => new Date().getHours())
  const greeting = hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening'
  const [range, setRange] = useState('7 days')
  return <><div className="study-heading"><div><h1>Good {greeting}, {user.name.split(/\s+/)[0]}.</h1><p className="script">Let’s keep the momentum going.</p></div><Link className="button" to="/library"><Upload size={17} /> Document Library</Link></div>
    <Metrics />
    <div className="data-grid">
      <section className="panel data-panel"><div className="calendar-header"><h2>Learning Progress</h2><select aria-label="Learning progress period" value={range} onChange={e => setRange(e.target.value)}>{['7 days', '30 days', '90 days'].map(value => <option key={value}>{value}</option>)}</select></div><p>Study activity for the last {range} will appear when progress tracking is connected.</p></section>
      <section className="panel data-panel"><h2>Subject Mastery</h2><p>Subject performance will appear after quiz tracking is connected.</p></section>
      <section className="panel data-panel"><h2>Continue Learning</h2><p>Start with a topic or explore the Library.</p><Link to="/chat">Open the AI Tutor <ArrowRight size={14} /></Link></section>
      <section className="panel data-panel"><h2>Upcoming Revision</h2><p>Review your scheduled study sessions.</p><Link to="/calendar">Open the planner <ArrowRight size={14} /></Link></section>
    </div>
  </>
}

function SettingsPage({ user, signOut }) {
  return <><h1>Settings</h1><p className="script">Make this space yours.</p><div className="settings-grid">
    <section className="panel data-panel"><h2>Profile</h2><span className="avatar">{user.name.charAt(0).toUpperCase()}</span><dl><dt>Name</dt><dd>{user.name}</dd><dt>Email</dt><dd>{user.email}</dd></dl></section>
    <section className="panel data-panel"><h2>Account</h2><p>Password changes will be available when account management is connected.</p><button className="button outline" onClick={signOut}>Sign out</button></section>
    <section className="panel data-panel"><h2>Learning Preferences</h2><p>Preferred subjects, study goals, and custom AI instructions are planned.</p></section>
    <section className="panel data-panel"><h2>Integrations</h2><Link to="/calendar#planner-google">Manage Google Calendar connection</Link></section>
    <section className="panel data-panel"><h2>Data &amp; Privacy</h2><p>Document storage and account data management are planned.</p></section>
  </div></>
}

function StudyContent({ path, user, token, signOut }) {
  switch (path) {
    case '/chat': return <Suspense fallback={<p role="status">Loading AI Tutor…</p>}><Tutor token={token} signOut={signOut} /></Suspense>
    case '/library': return <DocumentLibrary token={token} signOut={signOut} />
    case '/quizzes': return <Suspense fallback={<p role="status">Loading Quiz Studio…</p>}><QuizStudio token={token} signOut={signOut} /></Suspense>
    case '/analytics': return <Suspense fallback={<p role="status">Loading analytics…</p>}><LearningAnalytics token={token} signOut={signOut} /></Suspense>
    case '/calendar': return <Suspense fallback={<p role="status">Loading Revision Planner…</p>}><RevisionPlanner token={token} signOut={signOut} /></Suspense>
    case '/settings': return <SettingsPage user={user} signOut={signOut} />
    default: return <Dashboard user={user} />
  }
}

export function StudyWorkspace({ user, token, logout }) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  function signOut() {
    logout()
    navigate('/login', { replace: true })
  }
  return <div className="study-shell">
    <div className="study-mobile bg-aquamarine"><Link className="brand" to="/"><Asterisk size={22} />AI Study Buddy</Link><button className="icon" onClick={() => setOpen(!open)} aria-label={open ? 'Close workspace navigation' : 'Open workspace navigation'} aria-expanded={open} aria-controls="study-sidebar">{open ? <X /> : <Menu />}</button></div>
    <aside id="study-sidebar" className={'study-sidebar' + (open ? ' open' : '')} onKeyDown={event => { if (event.key === 'Escape') setOpen(false) }}>
      <Link className="brand" to="/"><Asterisk size={22} /> AI Study Buddy</Link>
      <nav aria-label="Workspace">{studyPages.map(([path, label, Icon]) => <NavLink key={path} to={path} onClick={() => setOpen(false)}><Icon size={18} />{label}</NavLink>)}</nav>
      <div className="profile"><Link to="/settings" onClick={() => setOpen(false)}><span className="avatar">{user.name.charAt(0).toUpperCase()}</span><span>{user.name}</span></Link><button className="icon" onClick={signOut} aria-label="Sign out" title="Sign out"><LogOut size={19} /></button></div>
    </aside>
    <main id="main" tabIndex={-1} className="study-content"><StudyContent key={pathname} path={pathname} user={user} token={token} signOut={signOut} /></main>
  </div>
}
