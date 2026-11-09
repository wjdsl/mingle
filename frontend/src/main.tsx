import React from 'react'
import { createRoot } from 'react-dom/client'
import { Platform } from './features/platform/Platform'
import './styles/tokens.css'
import './styles/chat.css'
import './features/platform/platform.css'
import './features/platform/puruma-refinements.css'

createRoot(document.getElementById('app')!).render(
  <React.StrictMode><Platform /></React.StrictMode>,
)
