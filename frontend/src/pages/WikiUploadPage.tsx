import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useWikiStore } from '@/app/wikiStore'

const ALLOWED_EXTS = ['.pdf', '.docx', '.xlsx', '.md', '.txt', '.markdown']

export function WikiUploadPage() {
  const navigate = useNavigate()
  const { uploadFile, uploading } = useWikiStore()
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFile = async (file: File) => {
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!ALLOWED_EXTS.includes(ext)) {
      setError(`不支持的文件类型: ${ext}`)
      return
    }
    setError(null)
    try {
      const { wiki_doc_id } = await uploadFile(file)
      navigate(`/wiki/documents/${wiki_doc_id}`)
    } catch (e: any) {
      setError(e.message || '上传失败')
    }
  }

  return (
    <div style={{ maxWidth: 600, margin: '3rem auto', padding: '1.5rem' }}>
      <h2 style={{ marginBottom: '1rem', fontSize: '1.25rem', fontWeight: 600 }}>上传 Wiki 文档</h2>

      <div
        onDragOver={e => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={e => {
          e.preventDefault()
          setDragOver(false)
          const file = e.dataTransfer.files[0]
          if (file) handleFile(file)
        }}
        onClick={() => fileInputRef.current?.click()}
        style={{
          border: `2px dashed ${dragOver ? '#4f46e5' : '#d0d5dd'}`,
          borderRadius: 12,
          padding: '3rem 2rem',
          textAlign: 'center',
          cursor: 'pointer',
          background: dragOver ? '#eef2ff' : '#f9fafb',
          transition: 'all 0.2s',
        }}
      >
        {uploading ? (
          <p>上传中...</p>
        ) : (
          <>
            <p style={{ fontSize: '1.1rem', fontWeight: 500, marginBottom: '0.5rem' }}>
              拖拽文档到此处，或点击选择文件
            </p>
            <p style={{ color: '#667085', fontSize: '0.85rem' }}>
              支持 PDF / DOCX / XLSX / MD / TXT
            </p>
          </>
        )}
      </div>

      {error && (
        <p style={{ color: '#dc2626', marginTop: '0.75rem', fontSize: '0.9rem' }}>{error}</p>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept={ALLOWED_EXTS.join(',')}
        style={{ display: 'none' }}
        onChange={e => {
          const file = e.target.files?.[0]
          if (file) handleFile(file)
        }}
      />

      <button
        onClick={() => navigate('/wiki')}
        style={{
          marginTop: '1rem', padding: '0.5rem 1rem', cursor: 'pointer',
          border: '1px solid #d0d5dd', borderRadius: 6, background: '#fff',
        }}
      >
        ← 返回列表
      </button>
    </div>
  )
}
