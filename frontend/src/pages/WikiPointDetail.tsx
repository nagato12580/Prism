import { useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useWikiStore } from '@/app/wikiStore'

export function WikiPointDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { selectedPoint, selectedPointLoading, selectedPointRelations, loadPoint } = useWikiStore()

  useEffect(() => {
    if (!id) return
    loadPoint(id)
  }, [id, loadPoint])

  if (selectedPointLoading || !selectedPoint) {
    return <p style={{ padding: '2rem', color: '#667085' }}>加载中...</p>
  }

  const tags = selectedPoint.tags ? selectedPoint.tags.split(',').filter(Boolean) : []

  return (
    <div style={{ maxWidth: 800, margin: '1.5rem auto', padding: '1.5rem' }}>
      <button
        onClick={() => navigate(-1)}
        style={{ padding: '0.4rem 0.8rem', cursor: 'pointer', border: '1px solid #d0d5dd', borderRadius: 6, background: '#fff', marginBottom: '1rem' }}
      >
        ← 返回
      </button>

      <article>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.75rem' }}>{selectedPoint.title}</h1>

        {/* Meta */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '1.5rem', fontSize: '0.85rem', color: '#667085' }}>
          {selectedPoint.category && <span style={{ background: '#f3f4f6', padding: '0.2rem 0.6rem', borderRadius: 4 }}>📁 {selectedPoint.category}</span>}
          {tags.map(tag => (
            <span key={tag} style={{ background: '#eef2ff', color: '#4f46e5', padding: '0.2rem 0.6rem', borderRadius: 4 }}>{tag}</span>
          ))}
          <span style={{ background: '#f3f4f6', padding: '0.2rem 0.6rem', borderRadius: 4 }}>{selectedPoint.status}</span>
        </div>

        {/* Content: render Markdown as plain text with basic formatting */}
        {selectedPoint.content ? (
          <div
            style={{ lineHeight: 1.8, fontSize: '0.95rem' }}
            dangerouslySetInnerHTML={{
              __html: selectedPoint.content
                .replace(/^### (.+)$/gm, '<h3 style="font-size:1.1rem;font-weight:600;margin:1rem 0 0.5rem">$1</h3>')
                .replace(/^## (.+)$/gm, '<h2 style="font-size:1.2rem;font-weight:600;margin:1.25rem 0 0.5rem">$1</h2>')
                .replace(/^# (.+)$/gm, '<h1 style="font-size:1.4rem;font-weight:700;margin:1.5rem 0 0.5rem">$1</h1>')
                .replace(/^- (.+)$/gm, '<li style="margin-left:1.5rem">$1</li>')
                .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                .replace(/\n\n/g, '<br/><br/>')
            }}
          />
        ) : (
          <p style={{ color: '#667085' }}>{selectedPoint.description || '暂无内容'}</p>
        )}

        {/* Relations */}
        {selectedPointRelations.length > 0 && (
          <div style={{ marginTop: '2rem', paddingTop: '1.5rem', borderTop: '1px solid #e5e7eb' }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '0.75rem' }}>
              关联知识点 ({selectedPointRelations.length})
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
              {selectedPointRelations.map(rel => {
                const isFrom = rel.from_point_id === selectedPoint.id
                const otherTitle = isFrom ? rel.to_title : rel.from_title
                const otherId = isFrom ? rel.to_point_id : rel.from_point_id
                const dirLabel = isFrom ? `→ ${rel.type}` : `${rel.type} →`
                return (
                  <div
                    key={rel.id}
                    onClick={() => navigate(`/wiki/points/${otherId}`)}
                    style={{
                      padding: '0.5rem 0.75rem', border: '1px solid #e5e7eb', borderRadius: 6, cursor: 'pointer',
                      fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '0.5rem',
                    }}
                  >
                    <span style={{ color: '#667085', fontSize: '0.8rem' }}>{dirLabel}</span>
                    <span style={{ fontWeight: 500 }}>{otherTitle || otherId}</span>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </article>
    </div>
  )
}
