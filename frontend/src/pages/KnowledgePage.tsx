import { useEffect, useState, useRef } from 'react'
import { knowledgeApi, type KnowledgeItem } from '@/app/api'
import { Upload, Link as LinkIcon, Trash2, Plus } from 'lucide-react'

export function KnowledgePage() {
  const [items, setItems] = useState<KnowledgeItem[]>([])
  const [loading, setLoading] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [urlInput, setUrlInput] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [newContent, setNewContent] = useState('')
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    setLoading(true)
    try {
      setItems(await knowledgeApi.list())
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    try {
      await knowledgeApi.uploadFile(file)
      await load()
    } catch (e) {
      setError('文件上传失败: ' + (e as Error).message)
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const handleUrl = async () => {
    if (!urlInput.trim()) return
    if (!urlInput.startsWith('http://') && !urlInput.startsWith('https://')) {
      setError('请输入有效的 URL（以 http:// 或 https:// 开头）')
      return
    }
    setError(null)
    try {
      await knowledgeApi.uploadUrl(urlInput)
      setUrlInput('')
      await load()
    } catch (e) {
      setError('URL 导入失败: ' + (e as Error).message)
    }
  }

  const handleCreate = async () => {
    if (!newTitle.trim()) return
    setError(null)
    try {
      await knowledgeApi.create({ title: newTitle, content: newContent, source_type: 'manual' })
      setNewTitle('')
      setNewContent('')
      setShowCreate(false)
      await load()
    } catch (e) {
      setError('创建失败: ' + (e as Error).message)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('确认删除？')) return
    await knowledgeApi.delete(id)
    await load()
  }

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">📚 知识库</h1>
        <div className="flex gap-2">
          <input ref={fileRef} type="file" className="hidden" onChange={handleUpload}
                 accept=".pdf,.docx,.xlsx,.md,.txt" />
          <button onClick={() => fileRef.current?.click()}
                  className="flex items-center gap-1 px-3 py-1.5 bg-primary text-white rounded-lg text-sm hover:opacity-90">
            <Upload size={16} /> 上传文件
          </button>
          <button onClick={() => setShowCreate(!showCreate)}
                  className="flex items-center gap-1 px-3 py-1.5 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">
            <Plus size={16} /> 新建笔记
          </button>
        </div>
      </div>

      {/* URL 导入 */}
      <div className="flex gap-2 mb-4">
        <input
          value={urlInput}
          onChange={(e) => setUrlInput(e.target.value)}
          placeholder="粘贴网页 URL..."
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:border-primary"
        />
        <button onClick={handleUrl}
                className="flex items-center gap-1 px-3 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">
          <LinkIcon size={16} /> 导入
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
          {error}
          <button onClick={() => setError(null)} className="ml-2 text-red-400 hover:text-red-600">✕</button>
        </div>
      )}

      {/* 新建笔记表单 */}
      {showCreate && (
        <div className="mb-4 p-4 border border-gray-200 rounded-[12px] bg-white space-y-2">
          <input value={newTitle} onChange={(e) => setNewTitle(e.target.value)}
                 placeholder="标题" className="w-full px-3 py-2 border rounded-lg text-sm" />
          <textarea value={newContent} onChange={(e) => setNewContent(e.target.value)}
                    placeholder="内容（支持 Markdown）"
                    className="w-full px-3 py-2 border rounded-lg text-sm h-32" />
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowCreate(false)}
                    className="px-3 py-1.5 text-sm text-gray-500">取消</button>
            <button onClick={handleCreate}
                    className="px-3 py-1.5 bg-primary text-white rounded-lg text-sm">保存</button>
          </div>
        </div>
      )}

      {/* 知识列表 */}
      {loading ? (
        <p className="text-gray-400">加载中...</p>
      ) : items.length === 0 ? (
        <p className="text-gray-400 text-center py-12">还没有知识条目，上传文件或新建笔记开始吧</p>
      ) : (
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
          {items.map((item) => (
            <div key={item.id}
                 className="p-4 bg-white border border-gray-200 rounded-[12px] hover:shadow-md transition-shadow">
              <div className="flex items-start justify-between mb-2">
                <h3 className="font-medium text-sm truncate flex-1">{item.title}</h3>
                <button onClick={() => handleDelete(item.id)}
                        className="text-gray-400 hover:text-red-500 ml-2">
                  <Trash2 size={14} />
                </button>
              </div>
              {item.summary && <p className="text-xs text-gray-500 line-clamp-2 mb-2">{item.summary}</p>}
              <div className="flex items-center gap-2 text-xs text-gray-400">
                <span className="px-1.5 py-0.5 bg-gray-100 rounded">{item.source_type}</span>
                {item.tags?.map((t) => (
                  <span key={t} className="text-primary">#{t}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
