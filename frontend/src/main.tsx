import React from 'react'
import { createRoot } from 'react-dom/client'
import { Platform } from './features/platform/Platform'
import './styles/fonts.css'
import './styles/tokens.css'
import './styles/chat.css'
import './features/platform/platform.css'
import './features/platform/puruma-refinements.css'
import './styles/storybook.css'

createRoot(document.getElementById('app')!).render(
  <React.StrictMode><Platform /></React.StrictMode>,
)
