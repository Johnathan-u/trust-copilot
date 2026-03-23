'use client'

import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'

export type ResponseStyle = 'precise' | 'balanced' | 'natural'

/** Map workspace ai_temperature to UI style. Must align with backend: Precise 0.2, Balanced 0.35, Natural 0.5. */
function temperatureToResponseStyle(temp: number | null): ResponseStyle {
  if (temp == null || Number.isNaN(temp)) return 'balanced'
  if (temp <= 0.25) return 'precise'
  if (temp <= 0.45) return 'balanced'
  return 'natural'
}

type AISettingsState = {
  model: string
  responseStyle: ResponseStyle
  setModel: (m: string) => void
  setResponseStyle: (s: ResponseStyle) => void
  loadFromWorkspace: () => Promise<void>
}

const defaultModel = 'gpt-4o-mini'
const defaultStyle: ResponseStyle = 'balanced'

const AISettingsContext = createContext<AISettingsState>({
  model: defaultModel,
  responseStyle: defaultStyle,
  setModel: () => {},
  setResponseStyle: () => {},
  loadFromWorkspace: async () => {},
})

export function useAISettings() {
  const ctx = useContext(AISettingsContext)
  if (!ctx) throw new Error('useAISettings must be used within AISettingsProvider')
  return ctx
}

export function AISettingsProvider({ children }: { children: React.ReactNode }) {
  const [model, setModel] = useState<string>(defaultModel)
  const [responseStyle, setResponseStyle] = useState<ResponseStyle>(defaultStyle)

  const loadFromWorkspace = useCallback(async () => {
    try {
      const r = await fetch('/api/workspaces/current', { credentials: 'include' })
      if (!r.ok) return
      const d = await r.json() as { ai_completion_model?: string | null; ai_temperature?: number | null }
      if (d.ai_completion_model) setModel(d.ai_completion_model)
      if (d.ai_temperature != null && !Number.isNaN(d.ai_temperature)) {
        setResponseStyle(temperatureToResponseStyle(d.ai_temperature))
      }
    } catch {
      // keep current state
    }
  }, [])

  return (
    <AISettingsContext.Provider
      value={{
        model,
        responseStyle,
        setModel,
        setResponseStyle,
        loadFromWorkspace,
      }}
    >
      {children}
    </AISettingsContext.Provider>
  )
}
