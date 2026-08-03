import React from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { router } from './app/routes'
import { useAuthStore } from '@/features/auth/store/authStore'
import './index.css'

// Bootstrap auth state before first paint so the router can decide whether to
// redirect to /login on the initial navigation.
void useAuthStore.getState().refreshMe()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)
