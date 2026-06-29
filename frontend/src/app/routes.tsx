import { createBrowserRouter } from 'react-router-dom'
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
import { GraphExplorePage } from '@/pages/GraphExplorePage'

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
      { path: 'graph/explore', element: <GraphExplorePage /> },
      { path: 'knowledge', element: <KnowledgePage /> },
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
