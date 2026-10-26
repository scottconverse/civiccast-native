export type RecordedCaptionLanguage = 'en' | 'es' | 'zh-Hans' | 'fil' | 'vi' | 'ar'
export type CaptionCompletionRequirement = 'all_selected_languages' | 'english_reviewed'

export interface RecordedCaptionSettings {
  vocabulary?: { terms: string[]; initial_prompt?: string | null }
  enabled: boolean
  languages: RecordedCaptionLanguage[]
  completion_requirement: CaptionCompletionRequirement
}

export const RECORDED_TRANSLATION_LANGUAGES = [
  { id: 'es', label: 'Spanish' },
  { id: 'zh-Hans', label: 'Chinese (Simplified)' },
  { id: 'fil', label: 'Tagalog / Filipino' },
  { id: 'vi', label: 'Vietnamese' },
  { id: 'ar', label: 'Arabic' },
] as const
