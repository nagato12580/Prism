import { useEffect, useRef, useState, type DragEvent } from 'react'
import { Loader2, Mic, MicOff, Upload } from 'lucide-react'
import { assetApi, type AssetDraft } from '@/app/api'

const MAX_RECORD_SECONDS = 60

interface Props {
  onResult: (item: AssetDraft) => void
  onError: (message: string) => void
}

type Status = 'idle' | 'recording' | 'processing'

export default function VoiceRecordButton({ onResult, onError }: Props) {
  const [status, setStatus] = useState<Status>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [isDragOver, setIsDragOver] = useState(false)

  const mediaRecorder = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<number | null>(null)

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
      streamRef.current?.getTracks().forEach((t) => t.stop())
      if (mediaRecorder.current?.state === 'recording') {
        mediaRecorder.current.stop()
      }
    }
  }, [])

  const cleanup = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    mediaRecorder.current = null
  }

  const startRecording = async () => {
    setElapsed(0)
    chunksRef.current = []

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      const recorder = new MediaRecorder(stream, {
        mimeType: MediaRecorder.isTypeSupported('audio/webm')
          ? 'audio/webm'
          : 'audio/mp4',
      })
      mediaRecorder.current = recorder

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      recorder.onstop = async () => {
        setStatus('processing')
        cleanup()

        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || 'audio/webm',
        })
        if (blob.size < 1000) {
          setStatus('idle')
          onError('录音太短，请重新录制。')
          return
        }

        const ext = recorder.mimeType?.includes('webm') ? 'webm' : 'm4a'
        try {
          const item = await assetApi.createVoice(
            blob,
            `recording.${ext}`,
            'recording',
          )
          setStatus('idle')
          onResult(item)
        } catch (err) {
          setStatus('idle')
          const msg =
            err instanceof Error ? err.message : '语音转写失败，请重试。'
          if (msg.includes('ASR') || msg.includes('模型') || msg.includes('Key')) {
            onError('ASR 服务未配置或不可用，请检查 .env 中的 ASR_API_KEY。')
          } else {
            onError(msg)
          }
        }
      }

      recorder.start()
      setStatus('recording')

      timerRef.current = window.setInterval(() => {
        setElapsed((prev) => {
          if (prev >= MAX_RECORD_SECONDS - 1) {
            stopRecording()
            return MAX_RECORD_SECONDS
          }
          return prev + 1
        })
      }, 1000)

      // Auto-stop at max duration
      setTimeout(() => {
        if (mediaRecorder.current?.state === 'recording') {
          stopRecording()
        }
      }, MAX_RECORD_SECONDS * 1000)
    } catch {
      onError('无法访问麦克风，请检查浏览器权限设置或使用文件上传。')
    }
  }

  const stopRecording = () => {
    if (mediaRecorder.current?.state === 'recording') {
      mediaRecorder.current.stop()
    }
  }

  const handleClick = () => {
    if (status === 'processing') return
    if (status === 'recording') {
      stopRecording()
    } else {
      startRecording()
    }
  }

  const handleFile = async (file: File) => {
    if (!file.type.startsWith('audio/') && !file.name.match(/\.(mp3|wav|webm|m4a|aac)$/i)) {
      onError('不支持的音频格式，请选择 mp3/wav/webm/m4a/aac 文件。')
      return
    }
    setStatus('processing')
    try {
      const item = await assetApi.createVoice(file, file.name, 'upload')
      setStatus('idle')
      onResult(item)
    } catch (err) {
      setStatus('idle')
      onError(err instanceof Error ? err.message : '文件上传转写失败。')
    }
  }

  const handleDrop = (e: DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  const handleDragOver = (e: DragEvent) => {
    e.preventDefault()
    setIsDragOver(true)
  }

  const handleDragLeave = () => setIsDragOver(false)

  const formatTime = (s: number) => {
    const min = Math.floor(s / 60)
    const sec = s % 60
    return `${min.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`
  }

  const progressPct = (elapsed / MAX_RECORD_SECONDS) * 100

  return (
    <div
      className={`rounded-lg border-2 p-4 transition ${
        isDragOver
          ? 'border-[var(--prism-blue)] bg-blue-50'
          : status === 'recording'
            ? 'border-red-300 bg-red-50'
            : 'border-dashed border-slate-200 bg-gradient-to-br from-blue-50 to-purple-50'
      }`}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      <div className="flex items-center gap-4">
        {/* Record/Stop button */}
        <button
          type="button"
          disabled={status === 'processing'}
          onClick={handleClick}
          className={`flex h-11 w-11 items-center justify-center rounded-full border-2 transition ${
            status === 'recording'
              ? 'animate-pulse border-red-400 bg-red-100 text-red-600'
              : 'border-slate-200 bg-white text-[var(--prism-blue)] hover:border-blue-300 hover:shadow-sm'
          } disabled:opacity-50`}
        >
          {status === 'processing' ? (
            <Loader2 size={20} className="animate-spin" />
          ) : status === 'recording' ? (
            <MicOff size={20} />
          ) : (
            <Mic size={20} />
          )}
        </button>

        {/* Status text */}
        <div className="flex-1 min-w-0">
          {status === 'idle' && (
            <>
              <div className="text-[13px] font-semibold text-slate-900">语音录入</div>
              <div className="text-[11px] text-slate-500">
                点击录音或拖拽音频文件到此处
              </div>
            </>
          )}
          {status === 'recording' && (
            <>
              <div className="text-[13px] font-semibold text-red-700">正在录音...</div>
              <div className="flex items-center gap-2">
                <div className="h-1.5 flex-1 rounded-full bg-red-200">
                  <div
                    className="h-full rounded-full bg-red-500 transition-all duration-1000"
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
                <span className="text-[11px] font-mono tabular-nums text-red-600">
                  {formatTime(elapsed)}
                </span>
              </div>
            </>
          )}
          {status === 'processing' && (
            <>
              <div className="text-[13px] font-semibold text-[var(--prism-blue)]">
                智能处理中...
              </div>
              <div className="text-[11px] text-slate-500">
                语音转写 → AI 解析 → 放入收件箱
              </div>
            </>
          )}
        </div>

        {/* File upload button */}
        {status === 'idle' && (
          <label className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[10px] text-slate-500 transition hover:border-blue-200 hover:text-[var(--prism-blue)]">
            <Upload size={13} />
            <span>上传</span>
            <input
              type="file"
              accept="audio/*"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) handleFile(file)
                e.target.value = ''
              }}
            />
          </label>
        )}
      </div>
    </div>
  )
}
