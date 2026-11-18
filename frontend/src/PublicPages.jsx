import { useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowDown, ArrowRight, BarChart3, BookOpen, CalendarDays, Check, ClipboardList, FileText, Paperclip, Plus, Search, Send, Workflow, MessagesSquare } from 'lucide-react'
import textbook from './assets/textbook.webp'
import desk from './assets/desk.webp'
import revision from './assets/revision.webp'
import { CalendarPreview, ProgressChart, SampleQuiz, WorkspacePreview } from './StudyWorkspace'

const features = [
  ['AI Tutor', 'Ask questions about your notes and trace explanations back to their source.', MessagesSquare],
  ['Document Library', 'Organize source material by subject and find the right document when you need it.', BookOpen],
  ['Quiz Studio', 'Turn important concepts into practice questions and review the reasoning behind each answer.', ClipboardList],
  ['Learning Analytics', 'Follow study activity, compare subject mastery, and find topics that need attention.', BarChart3],
  ['Revision Planner', 'Set aside time to revisit material before it fades from memory.', CalendarDays],
  ['Connected Learning Tools', 'Planned MCP integrations will bring approved external tools into your study workflow.', Workflow],
]

const prompts = [
  ['Explain a concept', 'Explain this concept in simple terms: ', FileText],
  ['Create a quiz', 'Create a practice quiz on: ', ClipboardList],
  ['Plan my revision', 'Help me plan revision for: ', CalendarDays],
  ['Summarize a PDF', 'Summarize the key ideas in: ', FileText],
]

function TutorPreview() {
  return <div className="example tutor-example"><span className="eyebrow">ILLUSTRATIVE CONVERSATION</span><p className="example-question">Why does database normalization matter?</p><p>Normalization gives each fact a clear place to live. For example, keeping a course title in one course table means a title change only needs one update.</p><small><FileText size={14} /> Database Systems Notes · Section 3</small></div>
}

function FeaturePreview({ index }) {
  if (index === 0) return <TutorPreview />
  if (index === 1) return <div className="example"><small>Example documents</small>{['Operating Systems', 'Database Systems Notes', 'Data Structures'].map(name => <p key={name} className="file-row"><FileText size={17} />{name}<small>PDF</small></p>)}</div>
  if (index === 2) return <SampleQuiz />
  if (index === 3) return <div className="example"><small>Illustrative study activity</small><ProgressChart /></div>
  if (index === 4) return <CalendarPreview demo />
  return <div className="example file-row"><CalendarDays /><div><strong>Google Calendar</strong><p>Planned connection</p></div></div>
}

export function PageTitle({ eyebrow, title, tagline }) {
  return <div className="page-title"><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="script">{tagline}</p></div>
}

const stages = [
  ['Bring your material', 'Collect PDFs, notes, and the topics you want to study.'],
  ['Ask better questions', 'Explore unfamiliar ideas using the context from your notes.'],
  ['Practice what matters', 'Recall important concepts and review the reasoning behind each answer.'],
  ['Keep progressing', 'Use study activity and past mistakes to guide your next revision.'],
]

const homeHighlights = [
  [0, 'Answers grounded in what you’re learning.'],
  [2, 'Understanding grows through practice.'],
  [3, 'See the progress behind your effort.'],
  [4, 'Make room for what matters next.'],
]

export function Home({ authenticated }) {
  const [prompt, setPrompt] = useState('')
  const [actions, setActions] = useState(false)
  const field = useRef(null)
  const navigate = useNavigate()
  function pick(value) {
    setPrompt(value)
    setActions(false)
    field.current?.focus()
  }
  function submit(event) {
    event.preventDefault()
    if (prompt.trim()) navigate(authenticated ? '/chat' : '/login', { state: { prompt: prompt.trim(), destination: '/chat' } })
  }
  return <main id="main" tabIndex={-1}>
    <section className="hero">
      <div className="hero-content">
        <p className="hero-kicker">Your AI learning companion</p>
        <h1>AI Study Buddy</h1>
        <p className="script hero-tagline">Learn Deeper. Remember Longer.</p>
        <form className="composer" onSubmit={submit} onKeyDown={event => { if (event.key === 'Escape' && actions) { setActions(false); field.current?.focus() } }}>
          <button type="button" className="icon composer-add" aria-expanded={actions} aria-controls="composer-actions" aria-label="Choose a study action" onClick={() => setActions(!actions)}><Plus /></button>
          {actions && <div id="composer-actions" className="composer-menu">{prompts.map(([label, value]) => <button type="button" key={label} onClick={() => pick(value)}>{label}</button>)}</div>}
          <input ref={field} value={prompt} onChange={event => setPrompt(event.target.value)} aria-label="Study prompt" placeholder="Ask anything about your studies..." />
          <button type="button" className="icon attachment" disabled aria-label="Attachments coming soon" title="Attachments coming soon"><Paperclip /></button>
          <Link className="icon" to="/library" aria-label="Open document library" title="Open document library"><BookOpen /></Link>
          <button className="icon send" aria-label="Send study prompt"><Send /></button>
        </form>
        <div className="quick-prompts">{prompts.map(([label, value, Icon]) => <button type="button" key={label} onClick={() => pick(value)}><Icon size={18} />{label}</button>)}</div>
      </div>
      <a className="scroll-cue icon" href="#overview" aria-label="Explore AI Study Buddy"><ArrowDown /></a>
    </section>
    <section id="overview" className="wrap split page">
      <div><h2>Turn your study material into real understanding.</h2><p>Upload your notes, ask questions, practice with quizzes, and track your learning — all in one intelligent workspace.</p><Link className="button" to="/features">Explore Features <ArrowRight size={16} /></Link></div>
      <WorkspacePreview />
    </section>
    <section className="warm-band"><div className="wrap page"><h2>From information to understanding.</h2><p className="script">A simpler way to learn.</p><ol className="steps">{stages.map(([title, description]) => <li key={title}><h3>{title}</h3><p>{description}</p></li>)}</ol></div></section>
    {homeHighlights.map(([index, title], position) => <section key={title} className={'wrap page split highlight' + (position % 2 ? ' reverse' : '')}><div><h2>{title}</h2><p>{features[index][1]}</p>{index === 2 && <p className="script">Practice makes progress.</p>}{index === 4 && <p>Google Calendar connectivity is planned.</p>}</div><FeaturePreview index={index} /></section>)}
    <section className="final-cta"><h2>Your next chapter starts here.</h2><p className="script">Let's make learning meaningful.</p><Link className="button" to={authenticated ? '/dashboard' : '/signup'}>Get Started <ArrowRight size={16} /></Link></section>
  </main>
}

export function Features() {
  return <main id="main" tabIndex={-1} className="wrap page"><PageTitle eyebrow="Features" title="Everything you need to study smarter." tagline="A focused workspace for serious learning." />
    <div className="feature-grid">{features.map(([name, description, Icon], index) => <article className="feature-card panel" key={name}><Icon className="accent" /><h2>{name}</h2><p>{description}</p><FeaturePreview index={index} /></article>)}</div>
  </main>
}

export function Tour() {
  return <main id="main" tabIndex={-1} className="wrap page"><PageTitle eyebrow="Workspace" title="A clearer space for every kind of learning." tagline="Made for curious minds." />
    <div className="split"><div><h2>Start with your dashboard.</h2><p>Get an overview of your study progress, pick up previous sessions, and check what’s coming up for revision.</p><Link className="button" to="/signup">Create Your Workspace <ArrowRight size={16} /></Link></div><WorkspacePreview /></div>
    {features.slice(0, 5).map(([name, description], index) => <section key={name} className={'page split highlight' + (index % 2 ? ' reverse' : '')}><div><h2>{name}</h2><p>{description}</p></div><FeaturePreview index={index} /></section>)}
  </main>
}

export function Pricing() {
  const [yearly, setYearly] = useState(false)
  const plans = [
    ['Free', 0, ['Personal study space', 'Document-based learning', 'Study and revision tools']],
    ['Pro', 299, ['Expanded personal workspace', 'Deeper progress insights', 'More room for study materials']],
    ['Team', 699, ['Shared study workspace', 'Group learning materials', 'Team progress overview']],
  ]
  return <main id="main" tabIndex={-1} className="wrap page"><PageTitle eyebrow="Pricing" title="Choose the plan that fits your learning." tagline="Flexible plans for every kind of learner." />
    <div className="price-controls"><div className="segments" role="group" aria-label="Billing period">{['Monthly', 'Yearly'].map((label, i) => <button key={label} aria-pressed={yearly === Boolean(i)} onClick={() => setYearly(Boolean(i))}>{label}</button>)}</div><p>Illustrative plans and prices. Billing is planned.</p></div>
    <div className="pricing-grid">{plans.map(([name, price, ideas]) => <article key={name} className={'panel price-card ' + (name === 'Pro' ? 'featured-price' : '')}><h2>{name}</h2><p className="price">₹{(yearly ? price * 12 : price).toLocaleString('en-IN')} <small>/ {yearly ? 'year' : 'month'}</small></p><ul>{ideas.map(idea => <li key={idea}><Check size={16} />{idea}</li>)}</ul><Link className="button outline" to="/workspace">Explore the Workspace</Link></article>)}</div>
  </main>
}

const resourcePhotos = { setup: textbook, tutor: desk, revision, library: textbook, 'quiz-results': desk, account: revision }

const resources = [
  ['setup', 'Guides', 'Set up your workspace', 'Create an account and find your way around the dashboard.', ['Create an account with your name, email, and a password of at least 12 characters.', 'Log in and use the sidebar to explore the dashboard, AI Tutor, library, quizzes, analytics, and planner.']],
  ['tutor', 'Tutorials', 'Use the AI Tutor', 'Write a focused study prompt and understand what a source citation tells you.', ['Name the topic and what you are trying to understand. Ask for an example if the idea still feels abstract.', 'The AI Tutor screen keeps your prompt ready while the answer service is being built. The Features page shows how source references could appear.']],
  ['revision', 'Guides', 'Build a revision plan', 'Space out reviews and make time for weaker topics.', ['Start with a short review one day after studying. Revisit the same material a few days later and again the following week.', 'Use a short recall exercise to plan your next session. Spend more time on the questions you struggled to answer.']],
  ['library', 'Updates', 'Organize your document library', 'Prepare notes and PDFs for the upcoming library.', ['Use descriptive filenames that include the subject and topic. Collect the original PDFs so you can trace quotations back to their source.', 'Document uploads and indexing are planned. The library will show processing status when storage is connected.']],
  ['quiz-results', 'Tutorials', 'Understand quiz results', 'Review missed questions and turn them into study priorities.', ['Read the explanation for each missed question, then answer it again without looking at the options.', 'Use the sample quiz to see how score, accuracy, and explanations appear after an attempt.']],
  ['account', 'FAQs', 'Manage your account', 'Find your profile and sign out on a shared device.', ['Open Settings to see the name and email associated with your account.', 'Use the Sign out action when you finish. If you refresh the app, log in again to reopen the workspace.']],
]

export function Resources() {
  const [category, setCategory] = useState('All')
  const [query, setQuery] = useState('')
  const filtered = resources.filter(([, kind, title, summary]) => (category === 'All' || category === kind) && (title + ' ' + summary).toLowerCase().includes(query.trim().toLowerCase()))
  return <main id="main" tabIndex={-1} className="wrap page"><PageTitle eyebrow="Resources" title="Guides, tutorials and answers at one place." tagline="Learn. Set up. Get the most out of AI Study Buddy." />
    <div className="resource-controls"><label className="search"><Search size={19} /><input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search resources…" aria-label="Search resources" /></label><div className="segments" role="group" aria-label="Resource categories">{['All', 'Guides', 'Tutorials', 'FAQs', 'Updates'].map(kind => <button key={kind} aria-pressed={kind === category} onClick={() => setCategory(kind)}>{kind}</button>)}</div></div>
    <div className="resource-grid">{filtered.map(([id, kind, title, summary]) => <Link className="panel resource-card" key={id} to={'/resources/' + id}><img className="resource-image" src={resourcePhotos[id]} alt="" loading="lazy" /><div><p className="eyebrow">{kind}</p><h2>{title}</h2><p>{summary}</p><ArrowRight size={18} /></div></Link>)}</div>
    {!filtered.length && <p className="empty panel" role="status">No resources match your search.</p>}
  </main>
}

export function Resource() {
  const { slug } = useParams()
  const entry = resources.find(([id]) => id === slug)
  return <main id="main" tabIndex={-1} className="wrap page reading"><Link className="back-link" to="/resources">← All resources</Link>{entry ? <article><PageTitle eyebrow={entry[1]} title={entry[2]} tagline={entry[3]} />{entry[4].map(paragraph => <p key={paragraph}>{paragraph}</p>)}</article> : <h1>Resource unavailable</h1>}</main>
}
