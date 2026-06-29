import client from './client'

export interface PreferenceMemory {
  memory_text: string | null
  user_edited: boolean
}

export const getPreferenceMemory = () =>
  client.get<PreferenceMemory>('/me/preference-memory').then(r => r.data)

export const setPreferenceMemory = (memory_text: string) =>
  client.put<PreferenceMemory>('/me/preference-memory', { memory_text }).then(r => r.data)
