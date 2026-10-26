export type RecordedCaptionLanguage = 'en' | 'es'
export type CaptionCompletionRequirement = 'all_selected_languages' | 'english_reviewed'

export interface RecordedCaptionSettings {
  vocabulary?: { terms: string[]; initial_prompt?: string | null }
  enabled: boolean
  languages: RecordedCaptionLanguage[]
  completion_requirement: CaptionCompletionRequirement
}
