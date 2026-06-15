import { createBrowserRouter } from 'react-router-dom'
import { MainLayout } from '@/layouts/MainLayout'
import { ChatPage } from '@/pages/ChatPage'
import { KnowledgePage } from '@/pages/KnowledgePage'
import { WikiPage } from '@/pages/WikiPage'
import { WikiUploadPage } from '@/pages/WikiUploadPage'
import { WikiDocDetail } from '@/pages/WikiDocDetail'
import { WikiPointDetail } from '@/pages/WikiPointDetail'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <MainLayout />,
    children: [
      { index: true, element: <ChatPage /> },
      { path: 'chat', element: <ChatPage /> },
      { path: 'knowledge', element: <KnowledgePage /> },
      { path: 'wiki', element: <WikiPage /> },
      { path: 'wiki/upload', element: <WikiUploadPage /> },
      { path: 'wiki/documents/:id', element: <WikiDocDetail /> },
      { path: 'wiki/points/:id', element: <WikiPointDetail /> },
    ],
  },
])
