export type RecordedCaptionLanguage = 'en' | 'es'
export type CaptionCompletionRequirement = 'all_selected_languages' | 'english_reviewed'

export interface RecordedCaptionSettings {
  enabled: boolean
  languages: RecordedCaptionLanguage[]
  completion_requirement: CaptionCompletionRequirement
}
