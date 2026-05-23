import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { searchJobs, Job } from '../api/search'
import JobCard from '../components/JobCard'

export default function Search() {
  const [query, setQuery] = useState('')
  const [strict, setStrict] = useState(false)
  const [results, setResults] = useState<Job[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [searched, setSearched] = useState(false)
  const navigate = useNavigate()

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    setSearched(true)
    try {
      setResults(await searchJobs(query, strict))
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Search failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: '4vh auto', padding: '2rem' }}>
      <h2 style={{ marginBottom: '1rem' }}>Search Jobs</h2>

      <form onSubmit={handleSearch} style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="e.g. machine learning engineer remote"
          required
        />
        <button type="submit" disabled={loading} style={{ whiteSpace: 'nowrap' }}>
          {loading ? '...' : 'Search'}
        </button>
      </form>

      <label style={{ fontSize: '0.875rem', opacity: 0.6, display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '1.5rem' }}>
        <input type="checkbox" checked={strict} onChange={e => setStrict(e.target.checked)} />
        Strict mode
      </label>

      {error && <p style={{ color: '#f87171' }}>{error}</p>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {results.map(job => <JobCard key={job.id} job={job} />)}
        {searched && results.length === 0 && !loading && !error && (
          <p style={{ opacity: 0.4 }}>No results found.</p>
        )}
      </div>

      <div style={{ marginTop: '2rem', fontSize: '0.8rem', opacity: 0.4, display: 'flex', gap: '1.5rem' }}>
        <span style={{ cursor: 'pointer' }} onClick={() => navigate('/cv')}>Update CV</span>
        <span style={{ cursor: 'pointer' }} onClick={() => { localStorage.removeItem('access_token'); navigate('/login') }}>Logout</span>
      </div>
    </div>
  )
}
