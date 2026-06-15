import { create } from 'zustand'
import type {
  WikiDocument, WikiDocumentDetail, WikiKnowledgePoint,
  WikiKnowledgePointListItem, WikiKnowledgeRelation,
} from './api'
import * as api from './api'

interface WikiState {
  // Document list
  documents: WikiDocument[]
  documentsLoading: boolean
  loadDocuments: () => Promise<void>

  // Selected document detail
  selectedDoc: WikiDocumentDetail | null
  selectedDocLoading: boolean
  loadDocument: (id: string) => Promise<void>

  // Knowledge points
  points: WikiKnowledgePointListItem[]
  pointsLoading: boolean
  loadPoints: (docId?: string) => Promise<void>

  // Selected point detail
  selectedPoint: WikiKnowledgePoint | null
  selectedPointLoading: boolean
  selectedPointRelations: WikiKnowledgeRelation[]
  loadPoint: (id: string) => Promise<void>

  // Upload
  uploading: boolean
  uploadFile: (file: File) => Promise<{ wiki_doc_id: string }>

  // Delete
  deleteDocument: (id: string) => Promise<void>

  // Trigger extraction
  triggerExtraction: (id: string) => Promise<void>
}

export const useWikiStore = create<WikiState>((set, get) => ({
  documents: [],
  documentsLoading: false,
  async loadDocuments() {
    set({ documentsLoading: true })
    try {
      const documents = await api.fetchWikiDocuments()
      set({ documents })
    } finally {
      set({ documentsLoading: false })
    }
  },

  selectedDoc: null,
  selectedDocLoading: false,
  async loadDocument(id: string) {
    set({ selectedDocLoading: true })
    try {
      const selectedDoc = await api.fetchWikiDocument(id)
      set({ selectedDoc })
    } finally {
      set({ selectedDocLoading: false })
    }
  },

  points: [],
  pointsLoading: false,
  async loadPoints(docId?: string) {
    set({ pointsLoading: true })
    try {
      const points = await api.fetchWikiPoints(docId)
      set({ points })
    } finally {
      set({ pointsLoading: false })
    }
  },

  selectedPoint: null,
  selectedPointLoading: false,
  selectedPointRelations: [],
  async loadPoint(id: string) {
    set({ selectedPointLoading: true })
    try {
      const [selectedPoint, selectedPointRelations] = await Promise.all([
        api.fetchWikiPoint(id),
        api.fetchWikiPointRelations(id),
      ])
      set({ selectedPoint, selectedPointRelations })
    } finally {
      set({ selectedPointLoading: false })
    }
  },

  uploading: false,
  async uploadFile(file: File) {
    set({ uploading: true })
    try {
      const result = await api.uploadWikiFile(file)
      return { wiki_doc_id: result.wiki_doc_id }
    } finally {
      set({ uploading: false })
    }
  },

  async deleteDocument(id: string) {
    await api.deleteWikiDocument(id)
    set({ documents: get().documents.filter(d => d.id !== id) })
  },

  async triggerExtraction(id: string) {
    await api.triggerWikiExtraction(id)
    // Refresh the list to show updated status
    const docs = get().documents.map(d =>
      d.id === id ? { ...d, status: 'processing' } : d
    )
    set({ documents: docs })
  },
}))
