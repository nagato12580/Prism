import { createBrowserRouter, Navigate } from 'react-router-dom'
import { MainLayout } from '@/layouts/MainLayout'
import { ChatPage } from '@/pages/ChatPage'
import { KnowledgePage } from '@/pages/KnowledgePage'
import { InboxPage } from '@/pages/InboxPage'
import { AssetsPage } from '@/pages/AssetsPage'
import { KnowledgeGraphPage } from '@/pages/KnowledgeGraphPage'
import { WikiPage } from '@/pages/WikiPage'
import { WikiUploadPage } from '@/pages/WikiUploadPage'
import { WikiDocDetail } from '@/pages/WikiDocDetail'
import { WikiPointDetail } from '@/pages/WikiPointDetail'
import { UserProfilePage } from '@/pages/UserProfilePage'
import { MemoryGraphPage } from '@/pages/MemoryGraphPage'
import { MemoryInboxPage } from '@/pages/MemoryInboxPage'
import { KnowledgeIndexPage } from '@/features/knowledge/pages/KnowledgeIndexPage'
import { KnowledgeShell } from '@/features/knowledge/components/KnowledgeShell'
import { KnowledgeFilesPage } from '@/features/knowledge/pages/KnowledgeFilesPage'
import { KnowledgeRetrievalPage } from '@/features/knowledge/pages/KnowledgeRetrievalPage'
import {
  KnowledgeGraphPage as ScopedKnowledgeGraphPage,
} from '@/features/knowledge/pages/KnowledgeGraphPage'
import { KnowledgeGovernancePage } from '@/features/knowledge/pages/KnowledgeGovernancePage'
import { KnowledgeMindmapPage } from '@/features/knowledge/pages/KnowledgeMindmapPage'
import { KnowledgeEvaluationPage } from '@/features/knowledge/pages/KnowledgeEvaluationPage'
import { KnowledgeSettingsPage } from '@/features/knowledge/pages/KnowledgeSettingsPage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <MainLayout />,
    children: [
      { index: true, element: <ChatPage /> },
      { path: 'chat', element: <ChatPage /> },
      { path: 'inbox', element: <InboxPage /> },
      { path: 'assets', element: <AssetsPage /> },
      { path: 'graph', element: <KnowledgeGraphPage /> },
      {
        path: 'knowledge',
        children: [
          { index: true, element: <KnowledgeIndexPage /> },
          {
            path: ':kbUid',
            element: <KnowledgeShell />,
            children: [
              { index: true, element: <Navigate to="files" replace /> },
              { path: 'files', element: <KnowledgeFilesPage /> },
              { path: 'retrieval', element: <KnowledgeRetrievalPage /> },
              { path: 'graph', element: <ScopedKnowledgeGraphPage /> },
              { path: 'governance', element: <KnowledgeGovernancePage /> },
              { path: 'mindmap', element: <KnowledgeMindmapPage /> },
              { path: 'evaluation', element: <KnowledgeEvaluationPage /> },
              { path: 'settings', element: <KnowledgeSettingsPage /> },
            ],
          },
        ],
      },
      { path: 'wiki', element: <WikiPage /> },
      { path: 'memory/inbox', element: <MemoryInboxPage /> },
      { path: 'memory/profile', element: <UserProfilePage /> },
      { path: 'memory/graph', element: <MemoryGraphPage /> },
      { path: 'wiki/upload', element: <WikiUploadPage /> },
      { path: 'wiki/documents/:id', element: <WikiDocDetail /> },
      { path: 'wiki/points/:id', element: <WikiPointDetail /> },
    ],
  },
])
