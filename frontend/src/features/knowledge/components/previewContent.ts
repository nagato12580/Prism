export const MAX_PREVIEW_CHARACTERS = 100_000

export interface PreviewContent {
  content: string
  truncated: boolean
  totalCharacters: number
}

export function clampPreviewContent(content: string): PreviewContent {
  return {
    content: content.slice(0, MAX_PREVIEW_CHARACTERS),
    truncated: content.length > MAX_PREVIEW_CHARACTERS,
    totalCharacters: content.length,
  }
}
