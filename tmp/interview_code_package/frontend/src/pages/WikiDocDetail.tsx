import { useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useWikiStore } from '@/app/wikiStore'

export function WikiDocDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { selectedDoc, selectedDocLoading, loadDocument, points, pointsLoading, loadPoints, deleteDocument } = useWikiStore()
  const pollRef = useRef<ReturnType<typeof setInterval>>()

  useEffect(() => {
    if (!id) return
    loadDocument(id)
    loadPoints(id)

    // Poll for progress if processing
    pollRef.current = setInterval(() => {
      loadDocument(id)
      loadPoints(id)
    }, 3000)

    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [id, loadDocument, loadPoints])

  // Stop polling when done
  useEffect(() => {
    if (selectedDoc && (selectedDoc.status === 'completed' || selectedDoc.status === 'failed')) {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = undefined
      }
    }
  }, [selectedDoc])

  const handleDelete = async () => {
    if (!id || !confirm('确定删除该文档及所有提取的知识点？')) return
    await deleteDocument(id)
    navigate('/wiki')
  }

  if (selectedDocLoading || !selectedDoc) {
    return <p style={{ padding: '2rem', color: '#667085' }}>加载中...</p>
  }

  const progressPct = selectedDoc.progress_total > 0
    ? Math.round((selectedDoc.progress_current / selectedDoc.progress_total) * 100)
    : 0

  return (
    <div style={{ maxWidth: 800, margin: '1.5rem auto', padding: '1.5rem' }}>
      <button
        onClick={() => navigate('/wiki')}
        style={{ padding: '0.4rem 0.8rem', cursor: 'pointer', border: '1px solid #d0d5dd', borderRadius: 6, background: '#fff', marginBottom: '1rem' }}
      >
        ← 返回
      </button>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 600 }}>
            📄 {selectedDoc.original_filename || '文档详情'}
          </h2>
          <p style={{ color: '#667085', fontSize: '0.85rem', marginTop: '0.25rem' }}>
            状态：{selectedDoc.status} · 阶段：{selectedDoc.extract_stage || '—'}
          </p>
        </div>
        <button
          onClick={handleDelete}
          style={{ padding: '0.4rem 0.8rem', cursor: 'pointer', border: '1px solid #fca5a5', borderRadius: 6, background: '#fef2f2', color: '#dc2626' }}
        >
          删除
        </button>
      </div>

      {/* Progress bar */}
      {selectedDoc.status === 'processing' && selectedDoc.progress_total > 0 && (
        <div style={{ marginBottom: '1.5rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#667085', marginBottom: '0.25rem' }}>
            <span>{selectedDoc.extract_stage}</span>
            <span>{progressPct}%</span>
          </div>
          <div style={{ height: 6, background: '#e5e7eb', borderRadius: 3 }}>
            <div style={{
              height: '100%', width: `${progressPct}%`,
              background: '#4f46e5', borderRadius: 3, transition: 'width 0.5s',
            }} />
          </div>
        </div>
      )}

      {/* Logs */}
      {selectedDoc.logs && selectedDoc.logs.length > 0 && (
        <details style={{ marginBottom: '1.5rem' }}>
          <summary style={{ cursor: 'pointer', fontWeight: 500, fontSize: '0.95rem' }}>
            管线日志 ({selectedDoc.logs.length})
          </summary>
          <div style={{ maxHeight: 200, overflow: 'auto', marginTop: '0.5rem', background: '#f9fafb', borderRadius: 6, padding: '0.5rem 0.75rem', fontSize: '0.8rem' }}>
            {selectedDoc.logs.map(log => (
              <div key={log.id} style={{ padding: '0.2rem 0', color: log.status === 'error' ? '#dc2626' : log.status === 'warning' ? '#d97706' : '#374151' }}>
                [{log.stage}] {log.message}
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Knowledge points */}
      <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '0.75rem' }}>
        知识点 {points.length > 0 && `(${points.length})`}
      </h3>

      {pointsLoading ? (
        <p style={{ color: '#667085' }}>加载中...</p>
      ) : points.length === 0 ? (
        <p style={{ color: '#667085' }}>暂无知识点</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {points.map(point => (
            <div
              key={point.id}
              onClick={() => navigate(`/wiki/points/${point.id}`)}
              style={{
                padding: '0.75rem 1rem', border: '1px solid #e5e7eb', borderRadius: 8, cursor: 'pointer',
                transition: 'box-shadow 0.15s',
              }}
              onMouseEnter={e => (e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.08)')}
              onMouseLeave={e => (e.currentTarget.style.boxShadow = 'none')}
            >
              <div style={{ fontWeight: 500 }}>{point.title}</div>
              {point.description && (
                <div style={{ fontSize: '0.85rem', color: '#667085', marginTop: '0.25rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {point.description}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
