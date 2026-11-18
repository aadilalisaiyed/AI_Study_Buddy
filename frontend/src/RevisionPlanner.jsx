import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CalendarDays, Clock, Link2, Plus } from 'lucide-react'
import { CalendarPreview } from './StudyWorkspace'
import { api } from './services/api'

const weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const statusText = {
  local_only: 'Local only', pending: 'Google sync pending', synced: 'Synced with Google',
  sync_failed: 'Google sync failed', reconnect_required: 'Reconnect Google Calendar',
  out_of_sync: 'Local changes differ from Google', deleted: 'Google event removed',
}
const local = (instant, timezone) => {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(instant))
  const value = Object.fromEntries(parts.map(({ type, value }) => [type, value]))
  return { date: value.year + '-' + value.month + '-' + value.day, time: value.hour + ':' + value.minute }
}

function dateLabel(value, timezone) {
  return new Intl.DateTimeFormat(undefined, { timeZone: timezone, dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function newPlan(pref) {
  const start = local(Date.now() + 86400000, pref.timezone)
  return {
    title: '', subject: '', topic: '', description: '', local_date: start.date, local_time: pref.window_start.slice(0, 5),
    timezone: pref.timezone, fold: '', duration: pref.duration, reminder_minutes: pref.reminder_minutes ?? '',
    source_quiz_id: null, document_ids: [],
  }
}

function SettingsForm({ preferences, save, busy }) {
  const [value, setValue] = useState({ ...preferences, reminder_minutes: preferences.reminder_minutes ?? '' })
  const change = (key, property) => setValue(current => ({ ...current, [key]: property }))
  return <details className="panel data-panel planned-details">
    <summary>Scheduling preferences</summary>
    <form onSubmit={event => {
      event.preventDefault()
      save({ ...value, reminder_minutes: value.reminder_minutes === '' ? null : Number(value.reminder_minutes) })
    }}>
      <div className="planner-fields">
        <label>Preferred timezone<input required maxLength={100} value={value.timezone} onChange={event => change('timezone', event.target.value)} /></label>
        <label>Preferred duration<input required type="number" min={15} max={180} value={value.duration} onChange={event => change('duration', Number(event.target.value))} /></label>
        <label>Window begins<input required type="time" value={value.window_start.slice(0, 5)} onChange={event => change('window_start', event.target.value)} /></label>
        <label>Window ends<input required type="time" value={value.window_end.slice(0, 5)} onChange={event => change('window_end', event.target.value)} /></label>
        <label>Minimum break in minutes<input required type="number" min={0} max={120} value={value.break_minutes} onChange={event => change('break_minutes', Number(event.target.value))} /></label>
        <label>Maximum study minutes per day<input required type="number" min={15} max={720} value={value.daily_minutes} onChange={event => change('daily_minutes', Number(event.target.value))} /></label>
        <label>Default reminder in minutes<input type="number" min={0} max={1440} value={value.reminder_minutes} onChange={event => change('reminder_minutes', event.target.value)} /></label>
      </div>
      <fieldset className="planner-weekdays"><legend>Study days</legend>{weekdays.map((label, index) => <label key={label}>
        <input type="checkbox" checked={value.days.includes(index)} onChange={event => change('days', event.target.checked ? [...value.days, index] : value.days.filter(day => day !== index))} />{label}
      </label>)}</fieldset>
      <button className="button outline" disabled={busy || !value.days.length}>Save preferences</button>
    </form>
  </details>
}

function GooglePanel({ state, busy, calendars, authorize, loadCalendars, choose, disconnect }) {
  const [choice, setChoice] = useState('')
  const [confirm, setConfirm] = useState(false)
  const connected = state?.status === 'connected'
  return <section className="panel data-panel planner-stack" id="planner-google">
    <h2><Link2 size={19} /> Google Calendar</h2>
    <p>{!state ? 'Checking connection…' : connected ? 'Connected' : state.status === 'reconnect_required' ? 'Connection expired' : 'Not connected'}</p>
    {state?.email && <p>{state.email}</p>}
    {state?.selected_calendar && <p>Selected calendar · {state.selected_calendar.name}</p>}
    {state?.last_synced_at && <p>Last successful sync · {new Date(state.last_synced_at).toLocaleString()}</p>}
    {!connected && state && <>
      <p>{state.configured ? 'Google will ask for your account identity, calendar list, and event access. Event changes need separate approval in the Planner.' : 'Calendar OAuth needs backend configuration. Local revision planning is available.'}</p>
      <button className="button outline" disabled={busy || !state.configured} onClick={authorize}>{state.status === 'reconnect_required' ? 'Reconnect Google Calendar' : 'Connect Google Calendar'}</button>
    </>}
    {connected && <>
      <div className="document-actions"><button className="button outline" disabled={busy} onClick={loadCalendars}>Load calendars</button>
        <button className="button outline" disabled={busy} onClick={() => setConfirm(true)}>Disconnect Google Calendar</button></div>
      {calendars?.length === 0 && <p>No writable Google calendars were returned.</p>}
      {!!calendars?.length && <form className="planner-stack" onSubmit={event => { event.preventDefault(); choose(choice) }}>
        <label className="planner-field"><span id="google-calendar-label">Destination calendar</span><select aria-labelledby="google-calendar-label" value={choice} onChange={event => setChoice(event.target.value)} required>
          <option value="">Choose a calendar</option>{calendars.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label><button className="button" disabled={busy || !choice}>Save calendar</button>
      </form>}
      {confirm && <><p>Disconnecting keeps your local sessions and existing Google events.</p><div className="document-actions">
        <button className="button" disabled={busy} onClick={() => { setConfirm(false); disconnect() }}>Confirm disconnect</button>
        <button className="button outline" onClick={() => setConfirm(false)}>Keep connected</button>
      </div></>}
    </>}
  </section>
}

export default function RevisionPlanner({ token, signOut }) {
  const [params] = useSearchParams()
  const sessionId = params.get('session')
  const [deepLink, setDeepLink] = useState(null)
  const [prefs, setPrefs] = useState(null)
  const [draft, setDraft] = useState(null)
  const [editing, setEditing] = useState(null)
  const [google, setGoogle] = useState(null)
  const [calendars, setCalendars] = useState(null)
  const [sync, setSync] = useState(false)
  const [recommendations, setRecommendations] = useState([])
  const [sessions, setSessions] = useState([])
  const [history, setHistory] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [range, setRange] = useState(null)
  const [proposal, setProposal] = useState(null)
  const [slots, setSlots] = useState(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState('')
  const [revision, setRevision] = useState(0)
  const request = useRef(null)
  const locked = useRef(false)
  const form = useRef(null)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([api.planner.preferences(token), api.planner.recommendations(token), api.googleCalendar.status(token)])
      .then(([preferences, tips, state]) => {
        if (controller.signal.aborted) return
        setPrefs(preferences); setRecommendations(tips); setGoogle(state)
        setDraft(current => {
          if (current) return current
          const requestedTopic = params.get('topic')
          const tip = tips.find(item => item.topic === requestedTopic)
          const initial = newPlan(preferences)
          if (!requestedTopic) return initial
          return { ...initial, title: ('Revise ' + requestedTopic).slice(0, 140), topic: requestedTopic.slice(0, 100),
            ...(tip && { subject: tip.subject, duration: tip.duration, source_quiz_id: tip.source_quiz_id, document_ids: tip.document_ids }) }
        })
      }).catch(failure => { if (!controller.signal.aborted) setError(failure) })
    return () => controller.abort()
  }, [token, revision, params])

  useEffect(() => {
    if (!range && !history) return
    let active = true
    api.planner.sessions(token, history ? {} : range).then(page => {
      if (active) { setSessions(page.items); setHasMore(page.has_more) }
    }).catch(failure => { if (active) setError(failure) })
    return () => { active = false }
  }, [token, range, history, revision])

  useEffect(() => {
    if (!sessionId) return
    let active = true
    api.planner.session(token, sessionId).then(item => {
      if (active) setDeepLink({ sessionId, token, item })
    }).catch(failure => { if (active) setError(failure) })
    return () => { active = false }
  }, [token, sessionId, revision])

  const linked = deepLink?.sessionId === sessionId && deepLink?.token === token ? deepLink.item : null
  const listed = linked && !sessions.some(item => item.id === linked.id) ? [linked, ...sessions] : sessions

  async function run(label, work) {
    if (locked.current) return
    locked.current = true
    setBusy(label); setError(null); setNotice('')
    try { await work() } catch (failure) {
      setError(failure)
      if (failure.status === 409 || failure.status === 503) {
        api.googleCalendar.status(token).then(setGoogle).catch(() => {})
      }
    } finally {
      setBusy('')
      locked.current = false
    }
  }

  function reload() { setRevision(value => value + 1) }
  function change(key, value) { setDraft(current => ({ ...current, [key]: value })) }
  function edit(item) {
    const start = local(item.start_at, item.timezone)
    setEditing(item.id); setSync(false); setSlots(null); setProposal(null)
    setDraft({ ...newPlan(prefs), title: item.title, description: item.description, subject: item.subject, topic: item.topic,
      local_date: start.date, local_time: start.time, duration: Math.round((Date.parse(item.end_at)-Date.parse(item.start_at))/60000),
      timezone: item.timezone, reminder_minutes: item.reminder_minutes ?? '', source_quiz_id: item.source_quiz_id, document_ids: item.document_ids })
    requestAnimationFrame(() => form.current?.scrollIntoView({ block: 'nearest' }))
  }
  function recommend(item) {
    setEditing(null); setSlots(null); setProposal(null); setSync(false)
    setDraft({ ...newPlan(prefs), title: ('Revise ' + item.topic).slice(0, 140), topic: item.topic, subject: item.subject,
      description: item.activity, duration: item.duration, source_quiz_id: item.source_quiz_id, document_ids: item.document_ids })
    requestAnimationFrame(() => form.current?.scrollIntoView({ block: 'nearest' }))
  }
  function review(action, item = null, remote = sync) {
    return run('Preparing review…', async () => {
      const payload = { action, session_id: item?.id || editing, google: remote }
      if (action === 'create') payload.session_id = null
      if (action === 'create' || action === 'update') payload.plan = {
        ...draft, fold: draft.fold === '' ? null : Number(draft.fold), duration: Number(draft.duration),
        reminder_minutes: draft.reminder_minutes === '' ? null : Number(draft.reminder_minutes),
      }
      const fingerprint = JSON.stringify(payload)
      const id = request.current?.fingerprint === fingerprint ? request.current.id : crypto.randomUUID()
      request.current = { fingerprint, id }
      const saved = await api.planner.propose(token, { ...payload, request_id: id })
      request.current = null
      setProposal(saved)
    })
  }
  function confirmed(result) {
    setProposal(result)
    if (result.status === 'failed') setNotice('The local change was saved. Google synchronization needs attention.')
    else {
      setNotice(result.calendar_name ? 'Local session and Google Calendar updated.' : 'Local revision plan updated.')
      setEditing(null); setDraft(newPlan(prefs)); setSync(false); setSlots(null)
    }
    reload()
  }

  const liveGoogle = google?.status === 'connected' && !!google.selected_calendar
  const callback = params.get('google')
  const callbackText = { connected: 'Google Calendar connected. Select a calendar to synchronize.', denied: 'Google authorization was cancelled.',
    calendar_scope: 'Google did not grant all required scopes. Review consent and reconnect.', oauth_refresh: 'Google did not grant offline access. Reconnect.',
    oauth_state: 'This Google authorization expired or did not match this browser. Start again.',
    calendar_config: 'Google Calendar is not fully configured.', failed: 'Google Calendar could not connect.' }
  return <>
    <h1>Revision Planner</h1><p className="script">Make space for revision.</p>
    {callbackText[callback] && <p className="panel data-panel" role="status">{callbackText[callback]}</p>}
    {error && <div role="alert" className="panel data-panel error">{error.message} {error.status === 401 && <button className="button outline" onClick={signOut}>Sign in again</button>}</div>}
    {notice && <p role="status" className="panel data-panel">{notice}</p>}
    {busy && <p role="status">{busy}</p>}
    {prefs && <CalendarPreview sessions={history ? [] : sessions} timezone={prefs.timezone} onRange={setRange} />}
    <section className="panel data-panel planner-stack">
      <div className="calendar-header"><h2>{history ? 'Session history' : 'Sessions in view'}</h2><button className="button outline" onClick={() => setHistory(!history)}>{history ? 'Show visible dates' : 'View session history'}</button></div>
      {!listed.length && <p>No sessions to show.</p>}
      {listed.map(item => <article key={item.id} className="panel data-panel">
        <h3>{item.title}</h3><p>{item.subject || 'Revision'}{item.topic && ' · ' + item.topic}</p>
        <p>{dateLabel(item.start_at, prefs?.timezone || item.timezone)} – {dateLabel(item.end_at, prefs?.timezone || item.timezone)}</p>
        <p className="quiz-capitalize">{item.status} · {statusText[item.sync_status] || item.sync_status}</p>
        {item.sync_error && <p className="error">{item.sync_error}</p>}
        <div className="document-actions">
          {item.status === 'scheduled' && <>
            <button className="button outline" disabled={!!busy} onClick={() => edit(item)}>Edit session</button>
            <button className="button outline" disabled={!!busy} onClick={() => run('Saving completion…', async () => {
              await api.planner.complete(token, item.id); reload()
            })}>Mark completed</button>
            <button className="button outline" disabled={!!busy} onClick={() => review('cancel', item, false)}>Cancel local session</button>
            {liveGoogle && <button className="button outline" disabled={!!busy} onClick={() => review('sync', item, true)}>Review Google sync</button>}
            {liveGoogle && item.calendar_id && item.sync_status !== 'deleted' && <button className="button outline" disabled={!!busy} onClick={() => review('cancel', item, true)}>Review Google cancellation</button>}
          </>}
          {item.sync_retry_id && liveGoogle && <button className="button outline" disabled={!!busy} onClick={() => run('Retrying approved synchronization…', async () => {
            confirmed(await api.planner.retry(token, item.id, item.sync_retry_id))
          })}>Retry approved sync</button>}
        </div>
      </article>)}
      {hasMore && <button className="button outline" disabled={!!busy} onClick={() => run('Loading more sessions…', async () => {
        const page = await api.planner.sessions(token, history ? {} : range, sessions.length)
        setSessions(items => [...items, ...page.items]); setHasMore(page.has_more)
      })}>More sessions</button>}
    </section>
    <div className="data-grid">
      <section className="panel data-panel planner-stack"><h2>Recommended for Revision</h2>
        {!recommendations.length && <p>When graded quizzes show a topic needs more practice, it will appear here.</p>}
        {recommendations.map(item => <article key={item.topic} className="panel data-panel"><h3>{item.topic}</h3><p>{item.subject} · {item.duration} minutes</p>
          <p>{item.reason}</p><button className="button outline" disabled={!!busy || !prefs} onClick={() => recommend(item)}>Schedule revision</button></article>)}
      </section>
      <GooglePanel state={google} calendars={calendars} busy={!!busy}
        authorize={() => run('Opening Google authorization…', async () => { window.location.assign((await api.googleCalendar.authorize(token)).url) })}
        loadCalendars={() => run('Loading writable calendars…', async () => setCalendars((await api.googleCalendar.calendars(token)).items))}
        choose={id => run('Saving calendar…', async () => { setGoogle(await api.googleCalendar.select(token, id)); setNotice('Destination calendar saved.') })}
        disconnect={() => run('Disconnecting…', async () => {
          const result = await api.googleCalendar.disconnect(token); setCalendars(null); setSync(false); reload()
          setNotice(result.revoked ? 'Google Calendar disconnected.' : 'Local access removed. Remove the grant in your Google account to finish revocation.')
        })} />
    </div>
    {prefs && draft && <section ref={form} className="panel data-panel planner-stack">
      <h2><Plus size={20} /> {editing ? 'Edit revision session' : 'Plan a revision session'}</h2>
      <form onSubmit={event => { event.preventDefault(); review(editing ? 'update' : 'create') }} className="planner-stack">
        <div className="planner-fields">
          <label>Session title<input required maxLength={140} value={draft.title} onChange={event => change('title', event.target.value)} /></label>
          <label>Subject<input maxLength={100} value={draft.subject} onChange={event => change('subject', event.target.value)} /></label>
          <label>Topic<input maxLength={100} value={draft.topic} onChange={event => change('topic', event.target.value)} /></label>
          <label>Session date<input required type="date" value={draft.local_date} onChange={event => change('local_date', event.target.value)} /></label>
          <label>Start time<input required type="time" value={draft.local_time} onChange={event => change('local_time', event.target.value)} /></label>
          <label>Session timezone<input required maxLength={100} value={draft.timezone} onChange={event => change('timezone', event.target.value)} /></label>
          <label>Duration in minutes<input required type="number" min={15} max={180} value={draft.duration} onChange={event => change('duration', Number(event.target.value))} /></label>
          <label>Reminder minutes<input type="number" min={0} max={1440} value={draft.reminder_minutes} onChange={event => change('reminder_minutes', event.target.value)} /></label>
          <label>Repeated clock time<select value={draft.fold} onChange={event => change('fold', event.target.value)}><option value="">Ask if ambiguous</option><option value="0">First occurrence</option><option value="1">Second occurrence</option></select></label>
        </div>
        <label className="planner-field">Description<textarea rows={3} maxLength={1500} value={draft.description} onChange={event => change('description', event.target.value)} /></label>
        {liveGoogle && <label><input type="checkbox" checked={sync} onChange={event => setSync(event.target.checked)} /> Include Google Calendar in this review</label>}
        <div className="document-actions">
          <button className="button" disabled={!!busy}>Review session</button>
          <button type="button" className="button outline" disabled={!!busy || !draft.local_date} onClick={() => run('Checking suitable slots…', async () => {
            const end = new Date(draft.local_date + 'T00:00:00Z')
            end.setUTCDate(end.getUTCDate() + 6)
            setSlots(await api.planner.availability(token, draft.local_date, end.toISOString().slice(0, 10), draft.duration, sync && liveGoogle))
          })}><Clock size={16} /> Find available times</button>
          {editing && <button type="button" className="button outline" onClick={() => { setDraft(newPlan(prefs)); setEditing(null); setSync(false) }}>New session</button>}
        </div>
      </form>
      {slots && <div className="planner-stack"><p>{slots.scope === 'google' ? 'Checked local sessions and ' + slots.calendar_name + '.' : 'Checked local sessions only. External commitments were not checked.'}</p>
        {!slots.slots.length && <p>No suitable slots. Try different dates or preferences.</p>}
        {slots.slots.map(slot => <button key={slot.start_at} className="button outline" onClick={() => setDraft(current => ({
          ...current, local_date: slot.local_date, local_time: slot.local_time.slice(0, 5), timezone: slot.timezone, fold: String(slot.fold),
        }))}>{dateLabel(slot.start_at, slot.timezone)}</button>)}
      </div>}
    </section>}
    {proposal && <section className="panel data-panel planner-stack" role="region" aria-label="Review revision proposal">
      <h2><CalendarDays size={20} /> {proposal.status === 'pending' ? 'Review revision proposal' : 'Revision operation'}</h2>
      <p><strong>{proposal.details.title}</strong>{proposal.details.subject && ' · ' + proposal.details.subject}{proposal.details.topic && ' · ' + proposal.details.topic}</p>
      <p>{dateLabel(proposal.details.start_at, proposal.details.timezone)} – {dateLabel(proposal.details.end_at, proposal.details.timezone)} · {Math.round((Date.parse(proposal.details.end_at)-Date.parse(proposal.details.start_at))/60000)} minutes</p>
      {proposal.action === 'update' && <p>Previous time · {dateLabel(proposal.details.previous_start_at, proposal.details.timezone)}</p>}
      <p>{proposal.calendar_name ? 'Google destination · ' + proposal.calendar_name : 'Local revision planner only'}</p>
      {proposal.details.leaves_remote_unchanged && <p>The linked Google event stays as it is.</p>}
      {proposal.error && <p className="error">{proposal.error}</p>}
      <div className="document-actions">
        {proposal.status === 'pending' && <button className="button" disabled={!!busy} onClick={() => run('Applying approved proposal…', async () => confirmed(await api.planner.confirm(token, proposal.id)))}>
          {proposal.action === 'cancel' ? 'Confirm cancellation' : proposal.action === 'update' ? 'Confirm reschedule' : proposal.calendar_name ? 'Confirm & add to Calendar' : 'Confirm local session'}
        </button>}
        {proposal.status === 'failed' && proposal.session_id && liveGoogle && <button className="button outline" disabled={!!busy} onClick={() => run('Retrying approved synchronization…', async () => confirmed(await api.planner.retry(token, proposal.session_id, proposal.id)))}>Retry this approval</button>}
        <button className="button outline" disabled={!!busy} onClick={() => setProposal(null)}>{proposal.status === 'pending' ? 'Dismiss proposal' : 'Close review'}</button>
      </div>
    </section>}
    {prefs && <SettingsForm key={JSON.stringify(prefs)} preferences={prefs} busy={!!busy} save={value => run('Saving preferences…', async () => {
      const saved = await api.planner.savePreferences(token, value)
      setPrefs(saved); setNotice('Scheduling preferences saved.'); if (!editing) change('timezone', saved.timezone); reload()
    })} />}
  </>
}
