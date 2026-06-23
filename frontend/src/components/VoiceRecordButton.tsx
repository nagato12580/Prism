import { type AssetDraft } from '@/app/api'

interface Props {
  onResult: (item: AssetDraft) => void
  onError: (message: string) => void
}

export default function VoiceRecordButton({ onResult: _onResult, onError: _onError }: Props) {
  return null
}
