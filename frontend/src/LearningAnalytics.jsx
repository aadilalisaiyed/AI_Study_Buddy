import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from './services/api'
import './learning-analytics.css'

const percent = value => value == null ? '—' : value + '%'
const minutes = value => Math.round(value / 60) + ' min'
const kind = { mcq: 'Multiple choice', boolean: 'True/false', short: 'Short answer' }
const colors = ['#7F0508', '#0F3F49']

function Panel({ title, children }) {
  return <section className="panel data-panel analytics-panel"><h2>{title}</h2>{children}</section>
}

function Plot({ title, data, axis, series, horizontal = false, bounded = true, points = false, lines = false }) {
  if (!data.length || !data.some(row => series.some(([key]) => row[key] != null))) return <p>No recorded data for this period.</p>
  const Chart = lines ? LineChart : BarChart
  const numberProps = bounded ? { domain: [0, 100], unit: '%' } : { allowDecimals: false }
  return <div className="analytics-chart" role="img" aria-label={title}>
    <ResponsiveContainer width="100%" height={245} minWidth={0}>
      <Chart data={data} layout={horizontal ? 'vertical' : 'horizontal'} accessibilityLayer>
        <CartesianGrid strokeDasharray="3 3" />
        {horizontal ? <><XAxis type="number" {...numberProps} /><YAxis type="category" dataKey={axis} width={104} /></>
          : <><XAxis dataKey={axis} minTickGap={18} /><YAxis width={45} {...numberProps} /></>}
        <Tooltip labelFormatter={(_, entries) => entries?.[0]?.payload?.date || entries?.[0]?.payload?.[axis]}
          formatter={value => bounded ? percent(value) : value} />
        <Legend />
        {series.map(([key, label], i) => lines
          ? <Line key={key} dataKey={key} name={label} stroke={colors[i]} dot={points && data.length <= 30} isAnimationActive={false} />
          : <Bar key={key} dataKey={key} name={label} fill={colors[i]} isAnimationActive={false} />)}
      </Chart>
    </ResponsiveContainer>
  </div>
}

function Values({ entries }) {
  return <dl className="analytics-values">{entries.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
}

function Heatmap({ days, timezone }) {
  const firstDay = new Date(days[0].date + 'T00:00:00Z').getUTCDay()
  return <div className="analytics-heatmap" aria-label={'Study activity in ' + timezone}>
    {Array.from({ length: (firstDay + 6) % 7 }, (_, i) => <span key={'empty' + i} aria-hidden="true" />)}
    {days.map(day => {
      const count = day.quizzes + day.tutor + day.revisions
      const label = day.date + ' · ' + day.quizzes + ' quizzes, ' + day.tutor + ' Tutor questions, ' + day.revisions + ' completed revisions'
      return <time key={day.date} dateTime={day.date} title={label} aria-label={label}
        className={'analytics-day activity-' + Math.min(4, count)}>{Number(day.date.slice(-2))}</time>
    })}
  </div>
}

export default function LearningAnalytics({ token, signOut }) {
  const [preset, setPreset] = useState('30')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [query, setQuery] = useState('days=30')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    api.analytics(token, query, controller.signal).then(data => {
      if (!controller.signal.aborted) setResult({ query, token, retry, data })
    }).catch(err => {
      if (controller.signal.aborted) return
      if (err.status === 401) signOut()
      else setError(err.message)
    })
    return () => controller.abort()
  }, [query, retry, signOut, token])
  const apply = newQuery => {
    setError('')
    if (query === newQuery) setRetry(value => value + 1)
    else setQuery(newQuery)
  }
  const data = result?.query === query && result?.token === token && result?.retry === retry ? result.data : null
  const trend = data?.trend.map(row => ({ ...row, plotted: row.day.slice(5) })) || []
  return <div className="analytics-layout">
    <header><h1>Your Learning Intelligence</h1><p className="script">Progress is a story worth understanding.</p>
      <p>Explore your learning habits, quiz performance, strengths and revision activity.</p></header>
    <form className="panel data-panel analytics-filters" onSubmit={event => {
      event.preventDefault()
      apply(new URLSearchParams({ start_date: start, end_date: end }).toString())
    }}>
      <label>Date range<select value={preset} onChange={event => {
        const value = event.target.value
        setPreset(value)
        if (value !== 'custom') apply('days=' + value)
      }}><option value="7">Last 7 days</option><option value="30">Last 30 days</option>
        <option value="90">Last 90 days</option><option value="custom">Custom range</option></select></label>
      {preset === 'custom' && <><label>Start date<input type="date" required value={start} onChange={event => setStart(event.target.value)} /></label>
        <label>End date<input type="date" required min={start} value={end} onChange={event => setEnd(event.target.value)} /></label>
        <button className="button">Apply dates</button></>}
      {data && <small>{data.range.start} to {data.range.end} · {data.range.timezone}</small>}
    </form>
    {error ? <div className="panel data-panel"><p role="alert">{error}</p><button className="button outline" onClick={() => apply(query)}>Retry</button></div>
      : !data ? <p className="panel data-panel" role="status">Loading your learning activity…</p> : <>
        <Panel title="Overview"><Values entries={[
          ['Quizzes completed', data.overview.quizzes], ['Graded attempts', data.overview.attempts],
          ['Questions answered', data.overview.questions], ['Objective accuracy', percent(data.overview.accuracy)],
          ['Learning streak', data.consistency.current + ' days'], ['Average attempt score', percent(data.overview.average_score)],
          ['Measured quiz elapsed time', minutes(data.overview.quiz_seconds)],
          ['Revision completion', percent(data.revision.rate)],
        ]} /></Panel>
        {!data.consistency.active_days && <Panel title="Your learning story starts here."><p>No study activity was recorded in this period.</p>
          <div className="document-actions"><Link to="/quizzes">Open Quiz Studio</Link><Link to="/library">Open Library</Link><Link to="/chat">Explore AI Tutor</Link></div></Panel>}
        <div className="data-grid">
          <Panel title="Quiz score over time"><Plot title="Quiz score by attempt" data={trend} axis="plotted" lines points series={[[ 'score', 'Marks score' ]]} /></Panel>
          <Panel title="Objective accuracy over time"><Plot title="Objective questions correct by attempt" data={trend} axis="plotted" lines points series={[[ 'accuracy', 'Objective accuracy' ]]} /></Panel>
        </div>
        {!!trend.length && <details className="panel data-panel analytics-panel"><summary>Quiz trend values</summary>
          <ol>{trend.map(row => <li key={row.id}>{new Date(row.date).toLocaleString(undefined, { timeZone: data.range.timezone })}
            {' · Score '}{percent(row.score)}{' · Objective accuracy '}{percent(row.accuracy)}</li>)}</ol>
        </details>}
        <Panel title="Subject performance">
          <p>Quizzes without a selected subject are grouped as Uncategorized.</p>
          <Plot title="Average quiz score by subject" data={data.subjects} axis="label" horizontal series={[[ 'average_score', 'Average attempt score' ]]} />
        </Panel>
        <Panel title="Topics to revisit">
          {!data.weak_topics.length && <p>No topics met the weakness criteria in this range.</p>}
          {data.weak_topics.map(topic => <details key={topic.key}><summary>{topic.label} · {percent(topic.percentage)} · {topic.priority}</summary>
            <p>{topic.questions} evaluated · {topic.earned} / {topic.available} marks · Last practiced {new Date(topic.last_practiced).toLocaleDateString(undefined, { timeZone: data.range.timezone })}</p>
            <div className="document-actions"><Link to={'/quizzes?topic=' + encodeURIComponent(topic.label)}>Practice topic</Link>
              <Link to={'/calendar?topic=' + encodeURIComponent(topic.label)}>Schedule revision</Link></div>
          </details>)}
          {!!data.topics.length && <details><summary>Topic performance</summary><ul>{data.topics.map(topic =>
            <li key={topic.key}>{topic.label} · {topic.correct}/{topic.questions} fully correct · {percent(topic.percentage)} of answered marks</li>)}</ul></details>}
        </Panel>
        <Panel title="Study consistency">
          <Values entries={[[ 'Active days', data.consistency.active_days ], [ 'Current streak', data.consistency.current ],
            [ 'Longest streak in range', data.consistency.longest ]]} />
          <p>Mon · Tue · Wed · Thu · Fri · Sat · Sun</p><Heatmap days={data.activity} timezone={data.range.timezone} />
          <p>Shading reflects graded quizzes, Tutor questions, and completed revisions recorded by AI Study Buddy.</p>
        </Panel>
        <Panel title="Revision activity"><Values entries={[
          ['Scheduled or completed', data.revision.scheduled], ['Completed', data.revision.completed],
          ['Cancelled', data.revision.cancelled], ['Past sessions pending', data.revision.overdue],
          ['Planned revision time', data.revision.planned_minutes + ' min'],
          ['Planned time for completed sessions', data.revision.completed_planned_minutes + ' min'],
        ]} />
          <Plot title="Weekly planned and completed revisions" data={data.revision.weekly} axis="week" bounded={false}
            series={[[ 'planned', 'Planned' ], [ 'completed', 'Completed' ]]} />
          <Plot title="Planned revisions by subject" data={data.revision.subjects} axis="label" bounded={false} horizontal series={[[ 'sessions', 'Sessions' ]]} />
          <h3>Upcoming sessions</h3>{data.revision.upcoming.length ? <ul>{data.revision.upcoming.map(session =>
            <li key={session.id}><Link to={'/calendar?session=' + session.id}>{session.title}</Link> · {new Date(session.start_at).toLocaleString(undefined, { timeZone: data.range.timezone })}</li>)}</ul> : <p>No upcoming sessions.</p>}
        </Panel>
        <div className="data-grid">
          <Panel title="Marks by difficulty"><Plot title="Marks by difficulty" data={data.difficulties} axis="label" series={[[ 'percentage', 'Answered marks' ]]} /></Panel>
          <Panel title="Marks by question type"><Plot title="Marks by question type" data={data.types.map(row => ({ ...row, label: kind[row.label] || row.label }))} axis="label" series={[[ 'percentage', 'Answered marks' ]]} /><p>Short-answer partial credit contributes to marks.</p></Panel>
          <Panel title="Tutor activity"><Values entries={[[ 'New conversations', data.tutor.conversations ], [ 'Questions submitted', data.tutor.questions ], [ 'Active Tutor days', data.tutor.active_days ]]} /></Panel>
          <Panel title="Library activity"><Values entries={[[ 'Currently ready', data.library.ready ], [ 'Uploads in range', data.library.uploaded ],
            [ 'Processed in range', data.library.processed ], [ 'Failed uploads from range', data.library.failed ]]} /></Panel>
        </div>
        <Panel title="Next steps">
          {data.insights.topic_change && <p>{data.insights.topic_change.label} improved from {percent(data.insights.topic_change.earlier)}
            {' '}to {percent(data.insights.topic_change.later)} of answered marks, comparing the dates before and from {data.insights.topic_change.later_start}.</p>}
          {data.insights.score_change != null && <p>The latest three attempts averaged {Math.abs(data.insights.score_change)} percentage points {data.insights.score_change < 0 ? 'below' : 'above'} the previous three in this period.</p>}
          <div className="document-actions"><Link to="/quizzes">View Quiz Studio</Link><Link to="/chat">Continue with AI Tutor</Link><Link to="/library">Open Library</Link></div>
        </Panel>
      </>}
  </div>
}
