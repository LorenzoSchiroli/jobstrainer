import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { uploadCV, getCV } from '../api/cv'

export default function CV() {
  const [hasCV, setHasCV] = useState(false)
  const [charCount, setCharCount] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    getCV().then(({ has_cv, cv_text }) => {
      setHasCV(has_cv)
      if (cv_text) setCharCount(cv_text.length)
    }).catch(() => {})
  }, [])

  async function handleFile(file: File) {
    setError('')
    setUploading(true)
    try {
      const res = await uploadCV(file)
      setHasCV(true)
      setCharCount(res.char_count)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div style={{ maxWidth: 480, margin: '10vh auto', padding: '2rem' }}>
      <h2>Your CV</h2>

      {hasCV && (
        <p style={{ opacity: 0.6, fontSize: '0.875rem' }}>
          CV loaded ({charCount?.toLocaleString()} characters). Upload a new file to replace it.
        </p>
      )}

      <div
        onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handleFile(f) }}
        onDragOver={e => e.preventDefault()}
        onClick={() => inputRef.current?.click()}
        style={{
          border: '2px dashed #444',
          borderRadius: 8,
          padding: '3rem',
          textAlign: 'center',
          cursor: 'pointer',
          marginBottom: '1rem',
        }}
      >
        {uploading ? 'Uploading...' : 'Drop PDF / DOCX / TXT here or click to browse'}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,.txt"
        style={{ display: 'none' }}
        onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
      />

      {error && <p style={{ color: '#f87171', fontSize: '0.875rem' }}>{error}</p>}

      <div style={{ display: 'flex', gap: '1rem', marginTop: '1rem' }}>
        <button onClick={() => navigate('/search')} disabled={!hasCV} style={{ flex: 1 }}>
          Go to Search →
        </button>
        <button
          onClick={() => { localStorage.removeItem('access_token'); navigate('/login') }}
          style={{ opacity: 0.5 }}
        >
          Logout
        </button>
      </div>
    </div>
  )
}
