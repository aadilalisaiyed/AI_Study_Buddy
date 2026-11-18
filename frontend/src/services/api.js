const base = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
const documentPath = id => '/documents/' + encodeURIComponent(id)
const chatPath = id => '/chat/conversations' + (id ? '/' + encodeURIComponent(id) : '')
const quizPath = id => '/quizzes' + (id ? '/' + encodeURIComponent(id) : '')
const attemptPath = id => quizPath() + '/attempts/' + encodeURIComponent(id)
const jsonBody = data => ({ headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
const PDF_TYPE = 'application/pdf'

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

function responseError(data, status) {
  const detail = data?.detail
  return new ApiError(typeof detail === 'string' ? detail : detail?.message || detail?.[0]?.msg || 'The request failed. Try again.', status)
}

async function request(path, { token, signal, timeout = 10000, asFile = false, ...options } = {}) {
  let response
  try {
    const deadline = AbortSignal.timeout(timeout)
    response = await fetch(base + '/api/v1' + path, {
      ...options,
      signal: signal ? AbortSignal.any([signal, deadline]) : deadline,
      headers: {
        Accept: asFile ? PDF_TYPE : 'application/json',
        ...(token && { Authorization: 'Bearer ' + token }),
        ...options.headers,
      },
    })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new Error(error.name === 'TimeoutError' ? 'The request timed out. Try again.' : 'Could not connect to the study service. Try again.')
  }
  if (response.ok && asFile) return response.blob()
  const data = await response.json().catch(() => null)
  if (!response.ok) throw responseError(data, response.status)
  return data
}

function uploadPdf(token, id, file, onProgress, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(signal.reason)
      return
    }
    const xhr = new XMLHttpRequest()
    const abort = () => xhr.abort()
    xhr.open('PUT', base + '/api/v1' + documentPath(id) + '/uploads/content')
    xhr.timeout = 120000
    xhr.responseType = 'json'
    xhr.setRequestHeader('Authorization', 'Bearer ' + token)
    xhr.setRequestHeader('Content-Type', PDF_TYPE)
    xhr.upload.addEventListener('progress', event => {
      if (event.lengthComputable) onProgress(Math.round(event.loaded * 100 / event.total))
    })
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response)
      else reject(responseError(xhr.response, xhr.status))
    }
    xhr.onerror = () => reject(new Error('The PDF transfer was interrupted. Try again.'))
    xhr.ontimeout = () => reject(new Error('Storage did not confirm the upload in time. You can resume it.'))
    xhr.onabort = () => reject(signal.reason)
    xhr.onloadend = () => signal.removeEventListener('abort', abort)
    signal.addEventListener('abort', abort, { once: true })
    xhr.send(file)
  })
}

export const api = {
  subjects: {
    list: token => request('/subjects', { token }),
    create: (token, name) => request('/subjects', { token, method: 'POST', ...jsonBody({ name }) }),
    assign: (token, document, subject_id) => request('/subjects/documents/' + encodeURIComponent(document),
      { token, method: 'PUT', ...jsonBody({ subject_id }) }),
  },
  analytics: (token, query, signal) => request('/analytics/overview?' + query, { token, signal }),
  checkHealth: () => request('/health'),
  checkDatabase: () => request('/health/db'),
  login: (email, password) => request('/auth/login', {
    method: 'POST',
    credentials: 'include',
    body: new URLSearchParams({ username: email, password }),
  }),
  refresh: signal => {
    const send = () => request('/auth/refresh', { method: 'POST', credentials: 'include', signal })
    return navigator.locks ? navigator.locks.request('study-buddy-session', { signal }, send) : send()
  },
  logout: () => {
    const send = () => request('/auth/logout', { method: 'POST', credentials: 'include', keepalive: true })
    return navigator.locks ? navigator.locks.request('study-buddy-session', send) : send()
  },
  register: (user) => request('/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(user),
  }),
  me: token => request('/auth/me', { token }),
  chat: {
    list: (token, offset = 0, signal) => request(chatPath() + '?offset=' + offset, { token, signal }),
    get: (token, id) => request(chatPath(id), { token }),
    create: token => request(chatPath(), { token, method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }),
    update: (token, id, data) => request(chatPath(id), {
      token, method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    }),
    remove: (token, id) => request(chatPath(id), { token, method: 'DELETE' }),
    messages: (token, id, before, signal) => request(chatPath(id) + '/messages' + (before ? '?before=' + before : ''), { token, signal }),
    submit: (token, id, data, signal) => request(chatPath(id) + '/messages', {
      token, signal, method: 'POST', timeout: 230000, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    }),
  },
  googleCalendar: {
    authorize: token => request('/integrations/google/authorize', { token, method: 'POST' }),
    status: token => request('/integrations/google/status', { token }),
    calendars: token => request('/integrations/google/calendars', { token, timeout: 55000 }),
    select: (token, calendar_id) => request('/integrations/google/calendar', { token, method: 'PUT', timeout: 55000, ...jsonBody({ calendar_id }) }),
    disconnect: token => request('/integrations/google/disconnect', { token, method: 'POST' }),
  },
  planner: {
    preferences: token => request('/planner/preferences', { token }),
    savePreferences: (token, data) => request('/planner/preferences', { token, method: 'PUT', ...jsonBody(data) }),
    recommendations: token => request('/planner/recommendations', { token }),
    sessions: (token, range, offset = 0) => request('/planner/sessions?' + new URLSearchParams({ ...range, offset }), { token }),
    availability: (token, first, last, duration, google) => request('/planner/availability?' + new URLSearchParams({ first, last, duration, google }), { token, timeout: 100000 }),
    propose: (token, data) => request('/planner/proposals', { token, method: 'POST', ...jsonBody(data) }),
    confirm: (token, id) => request('/planner/proposals/' + encodeURIComponent(id) + '/confirm',
      { token, method: 'POST', timeout: 100000, ...jsonBody({ approved: true }) }),
    session: (token, id) => request('/planner/sessions/' + encodeURIComponent(id), { token }),
    complete: (token, id) => request('/planner/sessions/' + encodeURIComponent(id) + '/complete', { token, method: 'POST' }),
    retry: (token, id, proposal_id) => request('/planner/sessions/' + encodeURIComponent(id) + '/sync?' + new URLSearchParams({ proposal_id }),
      { token, method: 'POST', timeout: 100000, ...jsonBody({ approved: true }) }),
  },
  quizzes: {
    config: token => request(quizPath() + '/config', { token }),
    list: (token, offset = 0) => request(quizPath() + '?offset=' + offset, { token }),
    get: (token, id) => request(quizPath(id), { token }),
    summary: token => request(quizPath() + '/performance/summary', { token }),
    generate: (token, data) => request(quizPath() + '/generate', { token, method: 'POST', timeout: 195000, ...jsonBody(data) }),
    remove: (token, id) => request(quizPath(id), { token, method: 'DELETE' }),
    start: (token, id, data, retake) => request(quizPath(id) + (retake ? '/retake' : '/attempts'), { token, method: 'POST', ...jsonBody(data) }),
    attempts: (token, id, offset = 0) => request(quizPath(id) + '/attempts?offset=' + offset, { token }),
    attempt: (token, id) => request(attemptPath(id), { token }),
    save: (token, id, data) => request(attemptPath(id) + '/answers', { token, method: 'PATCH', ...jsonBody(data) }),
    submit: (token, id) => request(attemptPath(id) + '/submit', { token, method: 'POST' }),
    results: (token, id) => request(attemptPath(id) + '/results', { token }),
  },
  documents: {
    list: (token, query, signal) => request('/documents?' + new URLSearchParams(query), { token, signal }),
    initialize: (token, file, signal) => request('/documents/uploads/init', {
      token, signal, method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: file.name, content_type: PDF_TYPE, file_size: file.size }),
    }),
    upload: uploadPdf,
    complete: (token, id, signal) => request(documentPath(id) + '/uploads/complete', { token, signal, method: 'POST', timeout: 35000 }),
    download: (token, id, signal) => request(documentPath(id) + '/download', { token, signal, asFile: true, timeout: 45000 }),
    retry: (token, id, signal) => request(documentPath(id) + '/retry', { token, signal, method: 'POST' }),
    remove: (token, id, signal) => request(documentPath(id), { token, signal, method: 'DELETE' }),
  },
}
