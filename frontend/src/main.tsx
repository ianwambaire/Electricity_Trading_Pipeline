import { StrictMode } from 'react'
import { BrowserRouter } from 'react-router-dom'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { ErrorBoundary } from './components/ui/ErrorBoundary'
import { AuthenticationRoot } from './auth/AuthenticationRoot'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary><BrowserRouter><AuthenticationRoot><App /></AuthenticationRoot></BrowserRouter></ErrorBoundary>
  </StrictMode>,
)
