import { createContext, useContext, useState } from 'react'
import type { ChatMessage } from '../types'

/**
 * Conversation state for the Discuss tab, lifted above the router so it
 * survives tab switches (an in-flight stream is still aborted on unmount).
 * apiHistory is the raw Anthropic message history the agent's memory rides
 * on — it must be preserved together with the visible messages.
 */
interface DiscussState {
  selectedSlug: string
  messages: ChatMessage[]
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  apiHistory: any[]
  tokenUsage: { input: number; output: number }
  setSelectedSlug(slug: string): void
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  setApiHistory(history: any[]): void
  setTokenUsage: React.Dispatch<React.SetStateAction<{ input: number; output: number }>>
  resetConversation(): void
}

const DiscussContext = createContext<DiscussState | null>(null)

export function DiscussProvider({ children }: { children: React.ReactNode }) {
  const [selectedSlug, setSelectedSlug] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [apiHistory, setApiHistory] = useState<any[]>([])
  const [tokenUsage, setTokenUsage] = useState({ input: 0, output: 0 })

  function resetConversation() {
    setMessages([])
    setApiHistory([])
    setTokenUsage({ input: 0, output: 0 })
  }

  return (
    <DiscussContext.Provider value={{
      selectedSlug, messages, apiHistory, tokenUsage,
      setSelectedSlug, setMessages, setApiHistory, setTokenUsage, resetConversation,
    }}>
      {children}
    </DiscussContext.Provider>
  )
}

export function useDiscuss() {
  const ctx = useContext(DiscussContext)
  if (!ctx) throw new Error('useDiscuss must be used inside DiscussProvider')
  return ctx
}
