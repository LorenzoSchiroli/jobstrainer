import client from './client'

export interface Company {
  name: string
  country: string | null
  is_consulting: boolean | null
  is_startup: boolean | null
  financial_health_score: number | null
  industry: string | null
}

export interface Job {
  id: string
  title: string
  url: string
  location: string | null
  employment_type: string | null
  location_type: string | null
  seniority: string | null
  languages_required: string[]
  company: Company
}

export const searchJobs = (query: string, strict: boolean) =>
  client.post<Job[]>('/jobs/search', { query, strict }).then(r => r.data)
