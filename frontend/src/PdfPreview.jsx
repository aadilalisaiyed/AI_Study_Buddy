import { useEffect, useRef, useState } from 'react'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

GlobalWorkerOptions.workerSrc = workerUrl

export default function PdfPreview({ file, filename, initialPage = 1 }) {
  const canvas = useRef(null)
  const [pdf, setPdf] = useState(null)
  const [number, setNumber] = useState(initialPage)
  const [error, setError] = useState(false)
  const [rendered, setRendered] = useState(0)

  useEffect(() => {
    let closed = false
    let loading
    async function open() {
      try {
        const bytes = await file.arrayBuffer()
        if (closed) return
        loading = getDocument({
          data: new Uint8Array(bytes),
          isEvalSupported: false,
          maxImageSize: 16_000_000,
          canvasMaxAreaInBytes: 32_000_000,
          stopAtErrors: true,
        })
        const document = await loading.promise
        if (!closed) {
          setNumber(Math.max(1, Math.min(initialPage, document.numPages)))
          setPdf(document)
        }
      } catch {
        if (!closed) setError(true)
      }
    }
    open()
    return () => {
      closed = true
      loading?.destroy().catch(() => {})
    }
  }, [file, initialPage])

  useEffect(() => {
    if (!pdf) return
    let stopped = false
    let render
    async function paint() {
      try {
        const page = await pdf.getPage(number)
        if (stopped) return
        const base = page.getViewport({ scale: 1 })
        const viewport = page.getViewport({ scale: Math.min(2, 1200 / Math.max(base.width, base.height)) })
        const element = canvas.current
        element.width = Math.ceil(viewport.width)
        element.height = Math.ceil(viewport.height)
        render = page.render({ canvas: element, viewport })
        await render.promise
        if (!stopped) setRendered(number)
      } catch {
        if (!stopped) setError(true)
      }
    }
    paint()
    return () => {
      stopped = true
      render?.cancel()
    }
  }, [pdf, number])

  if (error) return <p role="status">This PDF could not be previewed. Download it to open it in your PDF reader.</p>
  return <div className="pdf-preview">
    {pdf && <nav className="document-actions" aria-label="PDF pages">
      <button className="button outline" disabled={number <= 1} onClick={() => setNumber(number - 1)}>Previous page</button>
      <span>Page {number} of {pdf.numPages}</span>
      <button className="button outline" disabled={number >= pdf.numPages} onClick={() => setNumber(number + 1)}>Next page</button>
    </nav>}
    {rendered !== number && <p role="status">Rendering PDF preview…</p>}
    <canvas ref={canvas} hidden={rendered !== number} aria-label={filename + ', page ' + number} />
  </div>
}
