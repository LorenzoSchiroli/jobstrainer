import { useEffect, useRef, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { me, UserResponse } from '../api/auth'
import { getPreferenceMemory, setPreferenceMemory } from '../api/preferences'
import { getCV, uploadCV } from '../api/cv'
import { useSearchMode } from '../hooks/useSearchMode'

export default function Sidebar({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  const navigate = useNavigate()
  const location = useLocation()
  const { mode, setMode } = useSearchMode()
  const [user, setUser] = useState<UserResponse | null>(null)
  const [memory, setMemory] = useState('')
  const [savedNote, setSavedNote] = useState('')
  const [cvChars, setCvChars] = useState<number | null>(null)
  const [cvText, setCvText] = useState('')
  const [showCv, setShowCv] = useState(false)
  const [cvError, setCvError] = useState('')
  const [cvBusy, setCvBusy] = useState(false)
  const cvInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    me().then(setUser).catch(() => {})
    getPreferenceMemory().then(p => setMemory(p.memory_text || '')).catch(() => {})
    getCV().then(({ cv_text }) => {
      setCvText(cv_text || '')
      setCvChars(cv_text ? cv_text.length : null)
    }).catch(() => {})
  }, [])

  const logout = () => {
    localStorage.removeItem('access_token')
    navigate('/login')
  }

  const handleCvFile = async (file: File) => {
    setCvError('')
    setCvBusy(true)
    try {
      const res = await uploadCV(file)
      setCvChars(res.char_count)
      const { cv_text } = await getCV()
      setCvText(cv_text || '')
    } catch (err: any) {
      setCvError(err.response?.data?.detail || 'Upload failed')
    } finally {
      setCvBusy(false)
      if (cvInputRef.current) cvInputRef.current.value = ''
    }
  }

  const saveMemory = async () => {
    await setPreferenceMemory(memory)
    setSavedNote('Saved')
    setTimeout(() => setSavedNote(''), 1500)
  }

  const navLink = (path: string, label: string) => (
    <div
      onClick={() => navigate(path)}
      style={{
        cursor: 'pointer', padding: '0.4rem 0.6rem', borderRadius: 6,
        background: location.pathname === path ? '#2a2a2a' : 'transparent',
      }}
    >
      {label}
    </div>
  )

  return (
    <aside style={{
      position: 'fixed', top: 0, left: 0, zIndex: 30,
      width: 240, minWidth: 240, height: '100vh', borderRight: '1px solid #2a2a2a',
      padding: '1rem', display: 'flex', flexDirection: 'column', gap: '1rem', background: '#0f0f0f',
      overflowY: 'auto',
      transform: open ? 'translateX(0)' : 'translateX(-100%)',
      transition: 'transform 200ms ease',
    }}>
      <button onClick={onToggle} aria-label="Collapse sidebar"
              style={{ alignSelf: 'flex-end', background: 'transparent', color: '#aaa', border: 'none', cursor: 'pointer', fontSize: '1.1rem' }}>
        ☰
      </button>

      <div style={{ fontWeight: 600 }}>{user?.username || '...'}</div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
        {navLink('/search', 'Search')}
      </div>

      <div>
        <div style={{ fontSize: '0.8rem', opacity: 0.6, marginBottom: '0.4rem' }}>Search mode</div>
        <div style={{ display: 'flex', gap: '0.4rem' }}>
          {(['basic', 'advanced'] as const).map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              style={{
                flex: 1, padding: '0.35rem', borderRadius: 6,
                background: mode === m ? '#3b82f6' : '#1f1f1f', color: '#fff', border: 'none',
                cursor: 'pointer', textTransform: 'capitalize',
              }}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
        <div style={{ fontSize: '0.8rem', opacity: 0.6 }}>
          CV {cvChars != null ? `(${cvChars.toLocaleString()} chars)` : '(none)'}
        </div>
        <button onClick={() => cvInputRef.current?.click()} disabled={cvBusy}
                style={{ padding: '0.35rem', borderRadius: 6, cursor: 'pointer' }}>
          {cvBusy ? 'Uploading...' : cvChars != null ? 'Replace CV' : 'Upload CV'}
        </button>
        <input ref={cvInputRef} type="file" accept=".pdf,.docx,.txt" style={{ display: 'none' }}
               onChange={e => { const f = e.target.files?.[0]; if (f) handleCvFile(f) }} />
        {cvChars != null && (
          <button onClick={() => setShowCv(s => !s)}
                  style={{ padding: '0.25rem', borderRadius: 6, cursor: 'pointer', fontSize: '0.75rem', background: 'transparent', color: '#aaa', border: '1px solid #2a2a2a' }}>
            {showCv ? 'Hide CV' : 'View CV'}
          </button>
        )}
        {showCv && (
          <textarea value={cvText} readOnly rows={8}
                    style={{ resize: 'vertical', fontSize: '0.75rem', background: '#141414', color: '#ccc', border: '1px solid #2a2a2a', borderRadius: 6, padding: '0.4rem' }} />
        )}
        {cvError && <span style={{ fontSize: '0.75rem', color: '#f87171' }}>{cvError}</span>}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
        <div style={{ fontSize: '0.8rem', opacity: 0.6 }}>Preferences (learned)</div>
        <textarea
          value={memory}
          onChange={e => setMemory(e.target.value)}
          rows={6}
          style={{ resize: 'vertical', fontSize: '0.8rem', background: '#141414', color: '#eee', border: '1px solid #2a2a2a', borderRadius: 6, padding: '0.4rem' }}
        />
        <button onClick={saveMemory} style={{ padding: '0.35rem', borderRadius: 6, cursor: 'pointer' }}>
          Save preferences
        </button>
        {savedNote && <span style={{ fontSize: '0.75rem', opacity: 0.6 }}>{savedNote}</span>}
      </div>

      <div style={{ marginTop: 'auto', fontSize: '0.85rem', opacity: 0.6, cursor: 'pointer' }} onClick={logout}>
        Logout
      </div>
    </aside>
  )
}
