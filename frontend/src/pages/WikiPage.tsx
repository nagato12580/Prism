import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useWikiStore } from '@/app/wikiStore'
import type { WikiDocument } from '@/app/api'

export function WikiPage() {
  const navigate = useNavigate()
  const { documents, documentsLoading, loadDocuments, points, pointsLoading, loadPoints } = useWikiStore()
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)

  useEffect(() => {
    loadDocuments()
  }, [loadDocuments])

  useEffect(() => {
    if (selectedDocId) {
      loadPoints(selectedDocId)
    }
  }, [selectedDocId, loadPoints])

  const selectedDoc = documents.find(d => d.id === selectedDocId)

  const statusLabel = (status: string) => {
    switch (status) {
      case 'pending': return '⏳ 待处理'
      case 'processing': return '🔄 处理中'
      case 'completed': return '✅ 已完成'
      case 'failed': return '❌ 失败'
      default: return status
    }
  }

  return (
    <div style={{ display: 'flex', height: '100%', padding: '1.5rem', gap: '1.5rem' }}>
      {/* 左侧：文档列表 */}
      <div style={{ width: '320px', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
          <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 600 }}>Wiki 知识库</h2>
          <button
            onClick={() => navigate('/wiki/upload')}
            style={{ padding: '0.4rem 0.8rem', cursor: 'pointer', borderRadius: 6, border: '1px solid #d0d5dd', background: '#fff' }}
          >
            + 上传文档
          </button>
        </div>

        {documentsLoading ? (
          <p style={{ color: '#667085' }}>加载中...</p>
        ) : documents.length === 0 ? (
          <p style={{ color: '#667085' }}>暂无文档，点击上传开始</p>
        ) : (
          documents.map(doc => (
            <div
              key={doc.id}
              onClick={() => setSelectedDocId(doc.id)}
              style={{
                padding: '0.75rem 1rem',
                border: selectedDocId === doc.id ? '2px solid #4f46e5' : '1px solid #e5e7eb',
                borderRadius: 8,
                cursor: 'pointer',
                background: selectedDocId === doc.id ? '#eef2ff' : '#fff',
              }}
            >
              <div style={{ fontWeight: 500, marginBottom: '0.25rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                📄 {doc.original_filename || doc.id}
              </div>
              <div style={{ fontSize: '0.8rem', color: '#667085' }}>{statusLabel(doc.status)}</div>
              {doc.status === 'processing' && doc.progress_total > 0 && (
                <div style={{ marginTop: '0.25rem', height: 4, background: '#e5e7eb', borderRadius: 2 }}>
                  <div style={{
                    height: '100%', width: `${Math.round((doc.progress_current / doc.progress_total) * 100)}%`,
                    background: '#4f46e5', borderRadius: 2, transition: 'width 0.3s',
                  }} />
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* 右侧：知识点列表 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        {selectedDoc ? (
          <>
            <h2 style={{ margin: '0 0 0.5rem 0', fontSize: '1.25rem', fontWeight: 600 }}>
              {selectedDoc.original_filename || '文档详情'}
              <span style={{ fontSize: '0.85rem', fontWeight: 400, color: '#667085', marginLeft: '0.75rem' }}>
                {statusLabel(selectedDoc.status)}
              </span>
            </h2>

            {pointsLoading ? (
              <p style={{ color: '#667085' }}>加载知识点...</p>
            ) : points.length === 0 ? (
              <p style={{ color: '#667085' }}>
                {selectedDoc.status === 'completed' ? '该文档未提取到知识点' : '文档处理中，完成后将显示知识点'}
              </p>
            ) : (
              points.map(point => (
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
                  <div style={{ fontWeight: 500 }}>🔗 {point.title}</div>
                  <div style={{ fontSize: '0.8rem', color: '#667085', marginTop: '0.25rem' }}>
                    {point.category && `${point.category} · `}{point.status}
                  </div>
                </div>
              ))
            )}
          </>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#9ca3af' }}>
            选择左侧文档查看知识点
          </div>
        )}
      </div>
    </div>
  )
}
