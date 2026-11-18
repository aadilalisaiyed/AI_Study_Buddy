import { useEffect, useRef, useState } from 'react'
import { BrowserRouter, Link, NavLink, Navigate, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Asterisk, Menu, X, Eye, EyeOff } from 'lucide-react'
import { Home, Features, Tour, Pricing, Resources, Resource } from './PublicPages'
import { StudyWorkspace } from './StudyWorkspace'
import { studyPages } from './studyPages'
import { api } from './services/api'
import './App.css'

const links = [['/', 'Home'], ['/features', 'Features'], ['/workspace', 'Workspace'], ['/pricing', 'Pricing'], ['/resources', 'Resources']]

export function Brand() {
  return <Link className="brand" to="/"><Asterisk aria-hidden="true" strokeWidth={2} />AI Study Buddy</Link>
}

function PublicLayout() {
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  return <>
    <header className={'public-header' + (pathname === '/' ? ' over-hero' : '')}>
      <div className="nav-row wrap">
        <Brand />
        <button className="menu-button icon" type="button" aria-label={open ? 'Close navigation' : 'Open navigation'} aria-expanded={open} aria-controls="public-nav" onClick={() => setOpen(!open)}>{open ? <X /> : <Menu />}</button>
        <div id="public-nav" className={'public-nav' + (open ? ' open' : '')} onKeyDown={event => { if (event.key === 'Escape') setOpen(false) }}>
          <nav aria-label="Main navigation">{links.map(([path, label]) => <NavLink key={path} to={path} end onClick={() => setOpen(false)}>{label}</NavLink>)}</nav>
          <div className="nav-actions"><Link className="button outline" to="/login" onClick={() => setOpen(false)}>Log In</Link><Link className="button" to="/signup" onClick={() => setOpen(false)}>Get Started</Link></div>
        </div>
      </div>
    </header>
    <Outlet />
    <footer className="footer"><div className="wrap footer-inner"><Brand /><nav aria-label="Footer">{links.slice(1).map(([path, label]) => <Link key={path} to={path}>{label}</Link>)}<Link to="/login">Log In</Link><Link to="/signup">Get Started</Link></nav></div></footer>
  </>
}

function Auth({ signup, onLogin }) {
  const { state } = useLocation()
  const navigate = useNavigate()
  const [visible, setVisible] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(event) {
    event.preventDefault()
    const fields = new FormData(event.currentTarget)
    const email = fields.get('email').trim()
    const password = fields.get('password')
    const name = fields.get('name')?.trim()
    setError('')
    if (signup && (name.length < 2 || password !== fields.get('confirm'))) {
      setError(name.length < 2 ? 'Enter a name with at least two characters.' : 'The passwords do not match.')
      return
    }
    setBusy(true)
    try {
      if (signup) {
        await api.register({ name, email, password })
        navigate('/login', { replace: true, state: { ...state, registered: true } })
      } else {
        const { access_token, expires_in } = await api.login(email, password)
        const profile = await api.me(access_token)
        onLogin({ profile, token: access_token, expiresAt: Date.now() + expires_in * 1000 })
      }
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  return <main id="main" tabIndex={-1} className="auth">
    <aside className="auth-art"><Brand /><div><h2>AI Study Buddy</h2><p className="script">Learn Deeper. Remember Longer.</p></div></aside>
    <section className="auth-content"><div>
      <Link className="back-link" to="/">← Back to home</Link>
      <h1>{signup ? 'Create your account' : 'Welcome back.'}</h1>
      <p className="script">{signup ? 'Your journey starts here.' : 'Pick up where you left off.'}</p>
      {state?.registered && <p role="status">Account created. Log in to continue.</p>}
      {state?.prompt && <p role="status">Your study prompt is ready to continue after login.</p>}
      <form onSubmit={submit} className="auth-form">
        {signup && <label>Full name<input name="name" autoComplete="name" minLength={2} maxLength={100} required /></label>}
        <label>Email<input type="email" name="email" autoComplete="email" required /></label>
        <label>Password <span className="password-field"><input type={visible ? 'text' : 'password'} name="password" autoComplete={signup ? 'new-password' : 'current-password'} minLength={signup ? 12 : undefined} maxLength={signup ? 128 : undefined} required /><button type="button" className="icon" aria-label={visible ? 'Hide password' : 'Show password'} onClick={() => setVisible(!visible)}>{visible ? <EyeOff /> : <Eye />}</button></span></label>
        {signup && <><small>Use 12–128 characters.</small><label>Confirm password<input type={visible ? 'text' : 'password'} name="confirm" autoComplete="new-password" required /></label></>}
        {error && <p className="error" role="alert">{error}</p>}
        <button className="button" disabled={busy}>{busy ? 'Please wait…' : signup ? 'Create account' : 'Log In'}</button>
      </form>
      <p>{signup ? 'Already have an account? ' : 'New to AI Study Buddy? '}<Link to={signup ? '/login' : '/signup'} state={state}>{signup ? 'Log In' : 'Get Started'}</Link></p>
    </div></section>
  </main>
}

const sessionKey = 'ai-study-buddy.session'

function readSession() {
  try {
    const cached = JSON.parse(window.sessionStorage.getItem(sessionKey))
    if (typeof cached?.token === 'string' && cached.profile?.name
      && Number.isFinite(cached.expiresAt) && cached.expiresAt > Date.now() + 15000) return cached
  } catch {
    // The cookie can still restore sign-in if browser storage is unavailable.
  }
  return null
}

function cacheSession(session) {
  try {
    if (session) window.sessionStorage.setItem(sessionKey, JSON.stringify(session))
    else window.sessionStorage.removeItem(sessionKey)
  } catch {
    // Keep the current session usable when browser storage is unavailable.
  }
}

function Router() {
  const [session, setSession] = useState(readSession)
  const [restoring, setRestoring] = useState(!session)
  const startup = useRef(null)

  useEffect(() => {
    if (!restoring) return
    let active = true
    startup.current ??= api.refresh().then(async ({ access_token, expires_in }) => {
      const profile = await api.me(access_token)
      return { profile, token: access_token, expiresAt: Date.now() + expires_in * 1000 }
    })
    startup.current.then(next => {
      if (active) setSession(next)
    }).catch(() => {}).finally(() => {
      if (active) setRestoring(false)
    })
    return () => { active = false }
  }, [restoring])

  useEffect(() => {
    if (!restoring) cacheSession(session)
  }, [session, restoring])

  useEffect(() => {
    if (!session) return
    const controller = new AbortController()
    const timer = setTimeout(() => {
      api.refresh(controller.signal).then(({ access_token, expires_in }) => {
        if (!controller.signal.aborted) setSession(current => current && { ...current, token: access_token, expiresAt: Date.now() + expires_in * 1000 })
      }).catch(() => { if (!controller.signal.aborted) setSession(null) })
    }, Math.max(1000, session.expiresAt - Date.now() - 15000))
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [session])

  function logout() {
    cacheSession(null)
    setSession(null)
    return api.logout().catch(() => {})
  }

  const location = useLocation()
  const resume = <Navigate to={location.state?.destination || '/dashboard'} replace state={{ prompt: location.state?.prompt }} />
  useEffect(() => { if (!location.hash) window.scrollTo(0, 0) }, [location.pathname, location.hash])
  return <>
    <a className="skip" href="#main">Skip to content</a>
    <Routes>
      <Route element={<PublicLayout />}>
        <Route index element={<Home authenticated={Boolean(session)} />} />
        <Route path="features" element={<Features />} />
        <Route path="workspace" element={<Tour />} />
        <Route path="pricing" element={<Pricing />} />
        <Route path="resources" element={<Resources />} />
        <Route path="resources/:slug" element={<Resource />} />
        <Route path="*" element={<main id="main" tabIndex={-1} className="wrap page"><h1>Page unavailable</h1><Link to="/">Back to home</Link></main>} />
      </Route>
      <Route path="login" element={session ? resume : restoring ? <main role="status">Restoring session…</main> : <Auth key="login" onLogin={setSession} />} />
      <Route path="signup" element={session ? resume : restoring ? <main role="status">Restoring session…</main> : <Auth key="signup" signup onLogin={setSession} />} />
      {studyPages.map(([path]) => <Route key={path} path={path} element={session ? <StudyWorkspace user={session.profile} token={session.token} logout={logout} /> : restoring ? <main role="status">Restoring session…</main> : <Navigate to="/login" replace state={{ destination: path + location.search, prompt: location.state?.prompt }} />} />)}
    </Routes>
  </>
}

export default function App() {
  return <BrowserRouter><Router /></BrowserRouter>
}
