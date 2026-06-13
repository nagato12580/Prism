import { createBrowserRouter } from 'react-router-dom'
import { MainLayout } from '@/layouts/MainLayout'

// Placeholder pages until Task 10 and 11 create them
function ChatPage() {
  return <div className="p-4 text-gray-500">对话页面（Task 11 实现）</div>
}

function KnowledgePage() {
  return <div className="p-4 text-gray-500">知识库页面（Task 10 实现）</div>
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <MainLayout />,
    children: [
      { index: true, element: <ChatPage /> },
      { path: 'chat', element: <ChatPage /> },
      { path: 'knowledge', element: <KnowledgePage /> },
    ],
  },
])
