import { StrictMode } from 'react'
import { BrowserRouter } from 'react-router-dom'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { AuthenticationRoot } from './auth/AuthenticationRoot'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter><AuthenticationRoot><App /></AuthenticationRoot></BrowserRouter>
  </StrictMode>,
)
