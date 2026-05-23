import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { me } from '../api/auth'

export default function PrivateRoute({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<'loading' | 'ok' | 'unauthorized'>('loading')

  useEffect(() => {
    const token = localStorage.getItem('access_token')
    if (!token) { setStatus('unauthorized'); return }
    me().then(() => setStatus('ok')).catch(() => {
      localStorage.removeItem('access_token')
      setStatus('unauthorized')
    })
  }, [])

  if (status === 'loading') return null
  if (status === 'unauthorized') return <Navigate to="/login" replace />
  return <>{children}</>
}
