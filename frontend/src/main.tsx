import React from 'react'
import { createRoot } from 'react-dom/client'
import { ChatScene } from './features/chat/ChatScene'
import './styles/tokens.css'
import './styles/chat.css'

createRoot(document.getElementById('app')!).render(
  <React.StrictMode><ChatScene /></React.StrictMode>,
)
