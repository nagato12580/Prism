import { useEffect, useMemo, useState } from 'react'
import {
  BookOpen,
  Boxes,
  FileText,
  GitBranch,
  Loader2,
  Pencil,
  Save,
  Search,
  Sparkles,
  X,
} from 'lucide-react'
import {
  knowledgeGraphApi,
  type KnowledgeGraphEdge,
  type KnowledgeGraphNode,
  type KnowledgeGraphNodeUpdate,
  type KnowledgeGraphWorkbenchGroup,
  type KnowledgeGraphWorkbenchPKU,
  type KnowledgeGraphWorkbenchPayload,
} from '@/app/api'
import { cn } from '@/lib/utils'

type Selection =
  | { kind: 'ckp'; node: KnowledgeGraphNode }
  | { kind: 'pku'; node: KnowledgeGraphNode; edge?: KnowledgeGraphEdge }
  | { kind: 'source'; node: KnowledgeGraphNode; edge?: KnowledgeGraphEdge }
  | { kind: 'relation'; edge: KnowledgeGraphEdge; group: KnowledgeGraphWorkbenchGroup }

const sourceColors: Record<string, string> = {
  document_chunk: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  personal_asset_unit: 'border-rose-200 bg-rose-50 text-rose-800',
  personal_asset_item: 'border-amber-200 bg-amber-50 text-amber-800',
}

function contentForNode(node: KnowledgeGraphNode) {
  return node.statement || node.text || node.summary || ''
}

function truncate(value: string | null | undefined, max = 180) {
  const text = (value || '').trim()
  if (text.length <= max) return text
  return `${text.slice(0, max)}...`
}

function splitList(value: string) {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function joinList(values?: string[]) {
  return (values ?? []).join(', ')
}

function nodeKindLabel(node: KnowledgeGraphNode) {
  if (node.type === 'canonical') return 'CKP'
  if (node.type === 'pku') return 'PKU'
  if (node.type === 'document_chunk') return '文档块'
  if (node.type === 'personal_asset_unit') return '知识单元'
  if (node.type === 'asset') return '碎片'
  return node.type
}

function secondaryType(node: KnowledgeGraphNode) {
  return node.canonical_type || node.unit_type || node.asset_kind || node.media_type || node.source_kind || node.type
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

export function KnowledgeGraphWorkbench({
  onSaveNode,
}: {
  onSaveNode: (nodeId: string, data: KnowledgeGraphNodeUpdate) => Promise<KnowledgeGraphNode>
}) {
  const [query, setQuery] = useState('')
  const [payload, setPayload] = useState<KnowledgeGraphWorkbenchPayload | null>(null)
  const [selectedParentId, setSelectedParentId] = useState<string | null>(null)
  const [selectedCkpId, setSelectedCkpId] = useState<string | null>(null)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [subMode, setSubMode] = useState<'evidence' | 'relations'>('evidence')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const selectedParentGroup = selectedParentId && payload?.parent_groups ? payload.parent_groups[selectedParentId] : null
  const parentList = payload?.parents?.length ? payload.parents : payload?.ckps ?? []
  const selectedChildGroup =
    selectedCkpId && selectedParentGroup
      ? selectedParentGroup.children.find((child) => child.ckp.id === selectedCkpId) ?? null
      : null
  const selectedGroup = selectedCkpId && payload ? payload.groups[selectedCkpId] ?? selectedChildGroup : null

  const loadWorkbench = async (nextQuery = query) => {
    setLoading(true)
    setError(null)
    try {
      const data = await knowledgeGraphApi.getWorkbench({ q: nextQuery.trim() || undefined, limit: 60 })
      setPayload(data)
      const parents = data.parents?.length ? data.parents : data.ckps
      const nextParentId = parents.some((parent) => parent.id === selectedParentId)
        ? selectedParentId
        : parents[0]?.id ?? null
      const nextParentGroup = nextParentId && data.parent_groups ? data.parent_groups[nextParentId] : null
      const firstChild = nextParentGroup?.children[0] ?? null
      const preservedChild = nextParentGroup?.children.find((child) => child.ckp.id === selectedCkpId) ?? null
      const nextChildId = nextParentGroup
        ? preservedChild?.ckp.id ?? firstChild?.ckp.id ?? null
        : nextParentId
      const visibleChildId = nextParentGroup && !firstChild ? null : nextChildId
      setSelectedParentId(nextParentId)
      setSelectedCkpId(visibleChildId)
      setSelection(
        visibleChildId
          ? { kind: 'ckp', node: data.groups[visibleChildId]?.ckp ?? preservedChild?.ckp ?? firstChild?.ckp ?? parents[0] }
          : nextParentId
            ? { kind: 'ckp', node: nextParentGroup?.parent ?? parents.find((parent) => parent.id === nextParentId)! }
            : null,
      )
    } catch (err) {
      setError(`加载 CKP Workbench 失败：${getErrorMessage(err)}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadWorkbench('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const sourceCount = useMemo(() => {
    const ids = new Set<string>()
    selectedGroup?.pkus.forEach((entry) => entry.sources.forEach((source) => ids.add(source.node.id)))
    return ids.size
  }, [selectedGroup])

  const handleSaveNode = async (nodeId: string, data: KnowledgeGraphNodeUpdate) => {
    setError(null)
    try {
      const updated = await onSaveNode(nodeId, data)
      setPayload((current) => updateWorkbenchNode(current, updated))
      setSelection((current) => updateSelectionNode(current, updated))
      return updated
    } catch (err) {
      setError(`保存节点失败：${getErrorMessage(err)}`)
      throw err
    }
  }

  return (
    <div className="grid h-full min-h-0 gap-4 overflow-hidden xl:grid-cols-[18rem_minmax(0,1fr)_23rem]">
      <aside className="prism-panel flex min-h-0 flex-col rounded-lg p-4">
        <div className="relative">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void loadWorkbench()
            }}
            placeholder="搜索 CKP"
            className="h-10 w-full rounded-lg border border-[var(--prism-line)] bg-white pl-9 pr-3 text-sm outline-none transition focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100"
          />
        </div>
        <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
          <span>{parentList.length} 个父 CKP</span>
          {loading ? <Loader2 size={14} className="animate-spin" /> : null}
        </div>
        <div className="mt-3 min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
          {parentList.map((parent) => {
            const parentGroup = payload?.parent_groups?.[parent.id]
            const childCount = parent.child_count ?? parentGroup?.stats.child_count ?? 1
            const pkuCount = parent.pku_count ?? parentGroup?.stats.pku_count ?? 0
            const sourceCount = parent.source_count ?? parentGroup?.stats.source_count ?? 0
            return (
            <button
              key={parent.id}
              type="button"
              onClick={() => {
                const currentParentGroup = payload?.parent_groups?.[parent.id]
                const firstChild = currentParentGroup?.children[0]
                setSelectedParentId(parent.id)
                setSelectedCkpId(currentParentGroup && !firstChild ? null : firstChild?.ckp.id ?? parent.id)
                setSelection({ kind: 'ckp', node: firstChild?.ckp ?? parent })
              }}
              className={cn(
                'w-full rounded-lg border px-3 py-2 text-left transition',
                selectedParentId === parent.id
                  ? 'border-blue-300 bg-blue-50 shadow-sm'
                  : 'border-[var(--prism-line)] bg-white hover:bg-slate-50',
              )}
            >
              <div className="line-clamp-2 break-words text-sm font-semibold text-slate-950">{parent.label}</div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                <span>{parent.canonical_type || 'canonical'}</span>
                <span>{childCount} 子 CKP</span>
                <span>{pkuCount} PKU</span>
                <span>{sourceCount} 来源</span>
                {typeof parent.confidence === 'number' ? <span>{parent.confidence.toFixed(2)}</span> : null}
                {parent.status ? <span>{parent.status}</span> : null}
              </div>
            </button>
            )
          })}
          {!loading && payload && parentList.length === 0 ? (
            <p className="rounded-lg border border-dashed border-[var(--prism-line)] bg-white px-3 py-6 text-center text-sm leading-6 text-slate-500">
              没有匹配的 CKP。
            </p>
          ) : null}
        </div>
      </aside>

      <main className="prism-panel flex min-h-0 flex-col overflow-hidden rounded-lg p-4">
        {error ? (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm leading-6 text-red-700">
            {error}
          </div>
        ) : null}
        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        {selectedParentGroup && selectedParentGroup.children.length > 0 ? (
          <section className="mb-4 rounded-lg border border-[var(--prism-line)] bg-white px-4 py-3">
            <div className="mb-2 text-xs font-semibold uppercase text-slate-500">子 CKP</div>
            <div className="flex flex-wrap gap-2">
              {selectedParentGroup.children.map((child) => (
                <button
                  key={child.ckp.id}
                  type="button"
                  onClick={() => {
                    setSelectedCkpId(child.ckp.id)
                    setSelection({ kind: 'ckp', node: child.ckp })
                  }}
                  className={cn(
                    'max-w-full rounded-lg border px-3 py-2 text-left text-sm transition',
                    selectedCkpId === child.ckp.id
                      ? 'border-blue-300 bg-blue-50 text-blue-900 shadow-sm'
                      : 'border-[var(--prism-line)] bg-slate-50 text-slate-700 hover:bg-white',
                  )}
                >
                  <span className="line-clamp-1 break-words font-medium">{child.ckp.label}</span>
                  <span className="mt-1 block text-[11px] text-slate-500">
                    {child.ckp.pku_count ?? child.pkus.length} PKU · {child.ckp.source_count ?? 0} 来源
                  </span>
                </button>
              ))}
            </div>
          </section>
        ) : null}
        {selectedParentGroup && selectedParentGroup.children.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--prism-line)] bg-white px-4 py-6 text-center text-sm leading-6 text-slate-500">
            当前筛选下，这个父 CKP 没有可见的子 CKP。
          </div>
        ) : !selectedGroup ? (
          <div className="flex min-h-full items-center justify-center px-6 text-center text-sm leading-6 text-slate-500">
            暂无可展示的 CKP。确认碎片或完成文档向量化后，会生成 PKU 和 CKP。
          </div>
        ) : (
          <>
            <section className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3">
              <div className="flex items-start gap-3">
                <span className="mt-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-white">
                  <Sparkles size={16} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-semibold uppercase text-blue-700">当前 CKP</div>
                  <h2 className="mt-1 break-words text-lg font-semibold text-slate-950">{selectedGroup.ckp.label}</h2>
                  <p className="mt-2 break-words text-sm leading-6 text-slate-700">
                    {truncate(contentForNode(selectedGroup.ckp), 260)}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    <span className="rounded-md bg-white px-2 py-1 text-blue-700">{selectedGroup.pkus.length} 个 PKU</span>
                    <span className="rounded-md bg-white px-2 py-1 text-blue-700">{sourceCount} 个来源</span>
                    {typeof selectedGroup.ckp.confidence === 'number' ? (
                      <span className="rounded-md bg-white px-2 py-1 text-blue-700">
                        置信度 {selectedGroup.ckp.confidence.toFixed(2)}
                      </span>
                    ) : null}
                    <span className="rounded-md bg-white px-2 py-1 text-blue-700">
                      {selectedGroup.ckp.canonical_type || 'canonical'}
                    </span>
                  </div>
                  {selectedGroup.ckp.keywords?.length ? (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {selectedGroup.ckp.keywords.slice(0, 8).map((keyword) => (
                        <span key={keyword} className="rounded-md bg-blue-100 px-2 py-1 text-[11px] text-blue-700">
                          {keyword}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            </section>

            <div className="mt-4 inline-flex rounded-lg border border-[var(--prism-line)] bg-white p-1">
              <button
                type="button"
                onClick={() => setSubMode('evidence')}
                className={cn(
                  'rounded-md px-3 py-1.5 text-sm font-medium',
                  subMode === 'evidence' ? 'bg-slate-950 text-white' : 'text-slate-600',
                )}
              >
                证据链
              </button>
              <button
                type="button"
                onClick={() => setSubMode('relations')}
                className={cn(
                  'rounded-md px-3 py-1.5 text-sm font-medium',
                  subMode === 'relations' ? 'bg-slate-950 text-white' : 'text-slate-600',
                )}
              >
                PKU 关系
              </button>
            </div>

            {subMode === 'evidence' ? (
              <div className="mt-4 space-y-3">
                {selectedGroup.pkus.length === 0 ? (
                  <p className="rounded-lg border border-[var(--prism-line)] bg-white px-3 py-4 text-sm text-slate-500">
                    这个 CKP 暂时没有可见 PKU。
                  </p>
                ) : (
                  selectedGroup.pkus.map((entry) => (
                    <PKUCard
                      key={entry.pku.id}
                      entry={entry}
                      active={selection?.kind === 'pku' && selection.node.id === entry.pku.id}
                      activeSourceId={selection?.kind === 'source' ? selection.node.id : null}
                      onSelect={setSelection}
                    />
                  ))
                )}
              </div>
            ) : (
              <PKURelationList group={selectedGroup} onSelect={setSelection} />
            )}
          </>
        )}
        </div>
      </main>

      <WorkbenchInspector selection={selection} onSaveNode={handleSaveNode} />
    </div>
  )
}

function updateWorkbenchNode(payload: KnowledgeGraphWorkbenchPayload | null, updated: KnowledgeGraphNode) {
  if (!payload) return payload
  const ckps = payload.ckps.map((ckp) => (ckp.id === updated.id ? { ...ckp, ...updated } : ckp))
  const parents = payload.parents?.map((parent) => (parent.id === updated.id ? { ...parent, ...updated } : parent))
  const groups = Object.fromEntries(
    Object.entries(payload.groups).map(([id, group]) => [
      id,
      {
        ...group,
        ckp: group.ckp.id === updated.id ? { ...group.ckp, ...updated } : group.ckp,
        pkus: group.pkus.map((entry) => ({
          ...entry,
          pku: entry.pku.id === updated.id ? { ...entry.pku, ...updated } : entry.pku,
          sources: entry.sources.map((source) => ({
            ...source,
            node: source.node.id === updated.id ? { ...source.node, ...updated } : source.node,
          })),
        })),
      },
    ]),
  )
  const parentGroups = payload.parent_groups
    ? Object.fromEntries(
        Object.entries(payload.parent_groups).map(([id, parentGroup]) => [
          id,
          {
            ...parentGroup,
            parent:
              parentGroup.parent.id === updated.id ? { ...parentGroup.parent, ...updated } : parentGroup.parent,
            children: parentGroup.children.map((child) => ({
              ...child,
              ckp: child.ckp.id === updated.id ? { ...child.ckp, ...updated } : child.ckp,
              pkus: child.pkus.map((entry) => ({
                ...entry,
                pku: entry.pku.id === updated.id ? { ...entry.pku, ...updated } : entry.pku,
                sources: entry.sources.map((source) => ({
                  ...source,
                  node: source.node.id === updated.id ? { ...source.node, ...updated } : source.node,
                })),
              })),
            })),
          },
        ]),
      )
    : undefined
  return { ...payload, ckps, groups, parents, parent_groups: parentGroups }
}

function updateSelectionNode(selection: Selection | null, updated: KnowledgeGraphNode) {
  if (!selection || selection.kind === 'relation') return selection
  return selection.node.id === updated.id ? { ...selection, node: { ...selection.node, ...updated } } : selection
}

function PKUCard({
  entry,
  active,
  activeSourceId,
  onSelect,
}: {
  entry: KnowledgeGraphWorkbenchPKU
  active: boolean
  activeSourceId: string | null
  onSelect: (selection: Selection) => void
}) {
  return (
    <article
      className={cn(
        'rounded-lg border bg-white px-4 py-3 transition',
        active ? 'border-violet-400 shadow-sm ring-2 ring-violet-100' : 'border-violet-200',
      )}
    >
      <button
        type="button"
        className="block w-full text-left"
        onClick={() => onSelect({ kind: 'pku', node: entry.pku, edge: entry.link })}
      >
        <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs font-semibold text-violet-700">
          <Boxes size={14} />
          <span className="shrink-0">PKU</span>
          <span className="max-w-full truncate rounded-md bg-violet-50 px-1.5 py-0.5 text-[11px]">
            {entry.pku.unit_type || 'unit'}
          </span>
          <span className="max-w-full truncate rounded-md bg-violet-50 px-1.5 py-0.5 text-[11px]">
            {entry.link.label}
          </span>
          {entry.link.role ? (
            <span className="max-w-full truncate rounded-md bg-violet-50 px-1.5 py-0.5 text-[11px]">
              {entry.link.role}
            </span>
          ) : null}
          {typeof entry.pku.confidence === 'number' ? (
            <span className="shrink-0 sm:ml-auto">{entry.pku.confidence.toFixed(2)}</span>
          ) : null}
        </div>
        <p className="mt-2 break-words text-sm font-medium leading-6 text-slate-950">
          {entry.pku.statement || entry.pku.label}
        </p>
        {entry.link.reason ? <p className="mt-1 text-xs leading-5 text-slate-500">{entry.link.reason}</p> : null}
      </button>
      <div className="mt-3 grid gap-2 md:grid-cols-2">
        {entry.sources.map(({ node, edge }) => (
          <button
            key={node.id}
            type="button"
            onClick={() => onSelect({ kind: 'source', node, edge })}
            className={cn(
              'rounded-lg border px-3 py-2 text-left text-xs transition hover:brightness-[0.98]',
              sourceColors[node.source_kind || node.type] ?? 'border-slate-200 bg-slate-50 text-slate-700',
              active || activeSourceId === node.id ? 'ring-2 ring-violet-100' : '',
            )}
          >
            <div className="flex items-center gap-2 font-semibold">
              {node.type === 'document_chunk' ? <FileText size={13} /> : <BookOpen size={13} />}
              {nodeKindLabel(node)}
            </div>
            <div className="mt-1 line-clamp-1 break-words font-semibold">{node.label}</div>
            <div className="mt-1 line-clamp-2 break-words leading-5">{truncate(contentForNode(node), 120)}</div>
          </button>
        ))}
      </div>
    </article>
  )
}

function PKURelationList({
  group,
  onSelect,
}: {
  group: KnowledgeGraphWorkbenchGroup
  onSelect: (selection: Selection) => void
}) {
  const pkuById = new Map(group.pkus.map((entry) => [entry.pku.id, entry.pku]))
  return (
    <div className="mt-4 space-y-2">
      {group.relations.length === 0 ? (
        <p className="rounded-lg border border-[var(--prism-line)] bg-white px-3 py-4 text-sm text-slate-500">
          这个 CKP 暂时没有 PKU 间关系。
        </p>
      ) : (
        group.relations.map((edge) => (
          <button
            key={edge.id}
            type="button"
            onClick={() => onSelect({ kind: 'relation', edge, group })}
            className="w-full rounded-lg border border-pink-200 bg-white px-4 py-3 text-left transition hover:bg-pink-50"
          >
            <div className="flex items-center gap-2 text-xs font-semibold text-pink-700">
              <GitBranch size={14} />
              {edge.label}
              {typeof edge.confidence === 'number' ? <span className="ml-auto">{edge.confidence.toFixed(2)}</span> : null}
            </div>
            <div className="mt-2 grid gap-2 text-sm text-slate-700 md:grid-cols-[1fr_auto_1fr]">
              <span className="break-words">{pkuById.get(edge.source)?.label ?? edge.source}</span>
              <span className="text-slate-400">-&gt;</span>
              <span className="break-words">{pkuById.get(edge.target)?.label ?? edge.target}</span>
            </div>
            {edge.reason ? <p className="mt-2 text-xs leading-5 text-slate-500">{edge.reason}</p> : null}
          </button>
        ))
      )}
    </div>
  )
}

function WorkbenchInspector({
  selection,
  onSaveNode,
}: {
  selection: Selection | null
  onSaveNode: (nodeId: string, data: KnowledgeGraphNodeUpdate) => Promise<KnowledgeGraphNode>
}) {
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [draft, setDraft] = useState({
    label: '',
    content: '',
    summary: '',
    category: '',
    tags: '',
    keywords: '',
    typeValue: '',
    modality: '',
    status: '',
    confidence: '',
    sourcePlatform: '',
    sourceUrl: '',
  })

  const node = selection?.kind === 'relation' ? null : selection?.node ?? null

  useEffect(() => {
    setEditing(false)
    if (!node) return
    setDraft({
      label: node.label ?? '',
      content: contentForNode(node),
      summary: node.summary ?? '',
      category: node.category ?? '',
      tags: joinList(node.tags),
      keywords: joinList(node.keywords),
      typeValue: secondaryType(node) ?? '',
      modality: node.modality ?? '',
      status: node.status ?? '',
      confidence: typeof node.confidence === 'number' ? node.confidence.toFixed(2) : '',
      sourcePlatform: node.source_platform ?? '',
      sourceUrl: node.source_url ?? '',
    })
  }, [node])

  if (!selection) {
    return (
      <aside className="prism-panel flex min-h-[24rem] items-center justify-center rounded-lg p-5 text-center text-sm text-slate-500">
        选择 CKP、PKU 或来源查看详情。
      </aside>
    )
  }

  if (selection.kind === 'relation') {
    const source = selection.group.pkus.find((entry) => entry.pku.id === selection.edge.source)?.pku
    const target = selection.group.pkus.find((entry) => entry.pku.id === selection.edge.target)?.pku
    return (
      <aside className="prism-panel rounded-lg p-5">
        <div className="text-xs font-semibold text-pink-700">PKU 关系</div>
        <h2 className="mt-1 text-base font-semibold text-slate-950">{selection.edge.label}</h2>
        <div className="mt-4 space-y-2 text-sm leading-6 text-slate-700">
          <p className="break-words">{source?.label ?? selection.edge.source}</p>
          <p className="text-xs font-semibold text-pink-600">-&gt;</p>
          <p className="break-words">{target?.label ?? selection.edge.target}</p>
        </div>
        <p className="mt-4 rounded-lg border border-[var(--prism-line)] bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-600">
          {selection.edge.reason || '暂无关系原因。'}
        </p>
        <div className="mt-4 grid grid-cols-2 gap-2">
          <MiniStat label="置信度" value={typeof selection.edge.confidence === 'number' ? selection.edge.confidence.toFixed(2) : '-'} />
          <MiniStat label="模型" value={selection.edge.llm_model || '-'} />
        </div>
      </aside>
    )
  }

  const save = async () => {
    if (!node) return
    const confidence = draft.confidence.trim()
    if (confidence && Number.isNaN(Number(confidence))) {
      return
    }
    const update: KnowledgeGraphNodeUpdate = {
      label: draft.label.trim(),
      summary: draft.summary,
      category: draft.category,
      tags: splitList(draft.tags),
      keywords: splitList(draft.keywords),
      status: draft.status || undefined,
    }
    if (confidence) update.confidence = Number(confidence)
    if (node.type === 'canonical') {
      update.statement = draft.content
      update.canonical_type = draft.typeValue
    } else if (node.type === 'pku') {
      update.statement = draft.content
      update.normalized_statement = draft.label
      update.unit_type = draft.typeValue
      update.modality = draft.modality
    } else if (node.type === 'asset') {
      update.text = draft.content
      update.asset_kind = draft.typeValue
      update.source_platform = draft.sourcePlatform
      update.source_url = draft.sourceUrl
    } else if (node.type === 'personal_asset_unit') {
      update.text = draft.content
    } else {
      update.text = draft.content
    }
    setSaving(true)
    try {
      await onSaveNode(node.id, update)
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }

  return (
    <aside className="prism-panel flex min-h-0 flex-col rounded-lg p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-semibold text-slate-500">{nodeKindLabel(selection.node)}</div>
          <h2 className="mt-1 break-words text-base font-semibold leading-6 text-slate-950">{selection.node.label}</h2>
        </div>
        <button
          type="button"
          onClick={() => setEditing((value) => !value)}
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-[var(--prism-line)] bg-white text-slate-600 transition hover:bg-slate-50"
          title={editing ? '退出编辑' : '编辑节点'}
        >
          {editing ? <X size={15} /> : <Pencil size={15} />}
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
        {editing ? (
          <div className="space-y-3">
            <EditInput label="标题" value={draft.label} onChange={(value) => setDraft({ ...draft, label: value })} />
            <EditTextarea
              label={selection.node.type === 'canonical' || selection.node.type === 'pku' ? '表述' : '内容'}
              value={draft.content}
              onChange={(value) => setDraft({ ...draft, content: value })}
              rows={5}
            />
            <EditTextarea label="摘要" value={draft.summary} onChange={(value) => setDraft({ ...draft, summary: value })} />
            <div className="grid grid-cols-2 gap-2">
              <EditInput label="类型" value={draft.typeValue} onChange={(value) => setDraft({ ...draft, typeValue: value })} />
              <EditInput label="状态" value={draft.status} onChange={(value) => setDraft({ ...draft, status: value })} />
            </div>
            {selection.node.type === 'pku' ? (
              <EditInput label="模态" value={draft.modality} onChange={(value) => setDraft({ ...draft, modality: value })} />
            ) : null}
            {selection.node.type === 'asset' ? (
              <div className="grid grid-cols-2 gap-2">
                <EditInput
                  label="平台"
                  value={draft.sourcePlatform}
                  onChange={(value) => setDraft({ ...draft, sourcePlatform: value })}
                />
                <EditInput
                  label="来源链接"
                  value={draft.sourceUrl}
                  onChange={(value) => setDraft({ ...draft, sourceUrl: value })}
                />
              </div>
            ) : null}
            <EditInput label="标签" value={draft.tags} onChange={(value) => setDraft({ ...draft, tags: value })} />
            <EditInput label="关键词" value={draft.keywords} onChange={(value) => setDraft({ ...draft, keywords: value })} />
            <div className="grid grid-cols-2 gap-2">
              <EditInput label="分类" value={draft.category} onChange={(value) => setDraft({ ...draft, category: value })} />
              <EditInput label="置信度" value={draft.confidence} onChange={(value) => setDraft({ ...draft, confidence: value })} />
            </div>
            <div className="flex gap-2 pt-1">
              <button
                type="button"
                onClick={save}
                disabled={saving}
                className="inline-flex h-9 flex-1 items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
                保存
              </button>
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-[var(--prism-line)] bg-white px-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
              >
                <X size={15} />
                取消
              </button>
            </div>
          </div>
        ) : (
          <>
            <DetailBlock label="内容" value={contentForNode(selection.node)} />
            {selection.kind !== 'ckp' && selection.edge?.reason ? (
              <DetailBlock label="关系原因" value={selection.edge.reason} />
            ) : null}
            {selection.kind !== 'ckp' && selection.edge ? (
              <div className="grid grid-cols-2 gap-2">
                <MiniStat label="关系" value={selection.edge.label} />
                <MiniStat label="角色" value={selection.edge.role || '-'} />
              </div>
            ) : null}
            <div className="grid grid-cols-2 gap-2">
              <MiniStat label="类型" value={secondaryType(selection.node)} />
              <MiniStat label="置信度" value={typeof selection.node.confidence === 'number' ? selection.node.confidence.toFixed(2) : '-'} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <MiniStat label="来源类型" value={selection.node.source_kind || '-'} />
              <MiniStat label="来源 ID" value={selection.node.source_id || selection.node.ref_id || '-'} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <MiniStat label="分类" value={selection.node.category || '-'} />
              <MiniStat label="状态" value={selection.node.status || '-'} />
            </div>
            {selection.node.source_platform || selection.node.source_url ? (
              <div className="grid grid-cols-2 gap-2">
                <MiniStat label="平台" value={selection.node.source_platform || '-'} />
                <MiniStat label="链接" value={selection.node.source_url || '-'} />
              </div>
            ) : null}
            {selection.node.tags?.length ? <ChipBlock label="标签" values={selection.node.tags} /> : null}
            {selection.node.keywords?.length ? <ChipBlock label="关键词" values={selection.node.keywords.slice(0, 10)} /> : null}
          </>
        )}
      </div>
    </aside>
  )
}

function DetailBlock({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-slate-500">{label}</div>
      <p className="whitespace-pre-wrap break-words rounded-lg border border-[var(--prism-line)] bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-700">
        {value || '无'}
      </p>
    </div>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-950">{value || '-'}</div>
    </div>
  )
}

function ChipBlock({ label, values }: { label: string; values: string[] }) {
  return (
    <div>
      <div className="mb-2 text-xs font-medium text-slate-500">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        {values.map((value) => (
          <span key={value} className="rounded-md bg-slate-100 px-2 py-1 text-[11px] text-slate-600">
            {value}
          </span>
        ))}
      </div>
    </div>
  )
}

function EditInput({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-500">{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-lg border border-[var(--prism-line)] bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100"
      />
    </label>
  )
}

function EditTextarea({
  label,
  value,
  rows = 3,
  onChange,
}: {
  label: string
  value: string
  rows?: number
  onChange: (value: string) => void
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-500">{label}</span>
      <textarea
        value={value}
        rows={rows}
        onChange={(event) => onChange(event.target.value)}
        className="w-full resize-y rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none transition focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100"
      />
    </label>
  )
}
