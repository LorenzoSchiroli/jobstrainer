import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, register } from '../api/auth'

export default function Login() {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const fn = mode === 'login' ? login : register
      const { access_token } = await fn(username, password)
      localStorage.setItem('access_token', access_token)
      navigate('/search')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 360, margin: '10vh auto', padding: '2rem' }}>
      <h1 style={{ textAlign: 'center', marginBottom: '2rem', fontSize: '1.5rem' }}>jobstrainer</h1>
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        <input
          value={username}
          onChange={e => setUsername(e.target.value)}
          placeholder="Username"
          autoComplete="username"
          required
        />
        <input
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          placeholder="Password"
          autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          required
        />
        {error && <p style={{ color: '#f87171', margin: 0, fontSize: '0.875rem' }}>{error}</p>}
        <button type="submit" disabled={loading}>
          {loading ? 'Loading...' : mode === 'login' ? 'Login' : 'Register'}
        </button>
        <button
          type="button"
          onClick={() => { setMode(m => m === 'login' ? 'register' : 'login'); setError('') }}
          style={{ background: 'none', border: 'none', cursor: 'pointer', opacity: 0.5, fontSize: '0.875rem' }}
        >
          {mode === 'login' ? 'No account? Register' : 'Have an account? Login'}
        </button>
      </form>
    </div>
  )
}
