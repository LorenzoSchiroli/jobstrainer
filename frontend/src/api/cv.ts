import client from './client'

export interface CVResponse {
  cv_text: string | null
  has_cv: boolean
}

export interface CVUploadResponse {
  message: string
  char_count: number
}

export const uploadCV = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return client.post<CVUploadResponse>('/users/cv', form).then(r => r.data)
}

export const getCV = () =>
  client.get<CVResponse>('/users/cv').then(r => r.data)
