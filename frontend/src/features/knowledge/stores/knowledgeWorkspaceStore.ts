// Transient knowledge workspace UI state.
//
// ONLY transient, client-side selections live here, keyed by kbUid so refresh
// and deep links never depend on stored state. kbUid, active tab, pagination
// cursor, filters and retrieval query are kept in the URL (router), NOT here.
//
// This store is deliberately NOT written to storage: no token, ActorContext,
// evidence text or other sensitive data is ever saved client-side.

import { create } from 'zustand'

export type DrawerView = 'original' | 'markdown' | 'chunks' | 'history'

export interface DrawerState {
  fileUid: string
  view: DrawerView
}

export interface KnowledgeWorkspaceState {
  // Selected file_uids per knowledge base (transient bulk selection).
  selectedFileUids: Record<string, string[]>
  // Open document drawer per knowledge base.
  drawerByKb: Record<string, DrawerState | null>

  setSelectedFiles: (kbUid: string, fileUids: string[]) => void
  toggleSelectedFile: (kbUid: string, fileUid: string) => void
  clearSelectedFiles: (kbUid: string) => void
  openDrawer: (kbUid: string, fileUid: string, view?: DrawerView) => void
  closeDrawer: (kbUid: string) => void
}

export const useKnowledgeWorkspaceStore = create<KnowledgeWorkspaceState>((set) => ({
  selectedFileUids: {},
  drawerByKb: {},

  setSelectedFiles: (kbUid, fileUids) =>
    set((state) => ({ selectedFileUids: { ...state.selectedFileUids, [kbUid]: fileUids } })),

  toggleSelectedFile: (kbUid, fileUid) =>
    set((state) => {
      const current = state.selectedFileUids[kbUid] ?? []
      const next = current.includes(fileUid)
        ? current.filter((id) => id !== fileUid)
        : [...current, fileUid]
      return { selectedFileUids: { ...state.selectedFileUids, [kbUid]: next } }
    }),

  clearSelectedFiles: (kbUid) =>
    set((state) => ({ selectedFileUids: { ...state.selectedFileUids, [kbUid]: [] } })),

  openDrawer: (kbUid, fileUid, view = 'markdown') =>
    set((state) => ({ drawerByKb: { ...state.drawerByKb, [kbUid]: { fileUid, view } } })),

  closeDrawer: (kbUid) =>
    set((state) => ({ drawerByKb: { ...state.drawerByKb, [kbUid]: null } })),
}))
