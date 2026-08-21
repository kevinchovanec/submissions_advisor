import { createContext, useContext, useState } from 'react'
import type { ChatMessage } from '../types'

/**
 * Conversation state for the Discuss tab, lifted above the router so it
 * survives tab switches (an in-flight stream is still aborted on unmount).
 * apiHistory is the raw Anthropic message history the agent's memory rides
 * on — it must be preserved together with the visible messages.
 *
 * Several stories can be loaded at once. primarySlug is one of selectedSlugs:
 * it keys saved conversations (so the cloud schema needs no story_slugs column)
 * and is the default target when the agent logs a submission.
 */
interface DiscussState {
  selectedSlugs: string[]
  primarySlug: string
  messages: ChatMessage[]
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  apiHistory: any[]
  tokenUsage: { input: number; cached: number; output: number }
  setSelection(slugs: string[], primary?: string): void
  toggleSlug(slug: string): void
  setPrimarySlug(slug: string): void
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  setApiHistory(history: any[]): void
  setTokenUsage: React.Dispatch<React.SetStateAction<{ input: number; cached: number; output: number }>>
  resetConversation(): void
}

const DiscussContext = createContext<DiscussState | null>(null)

export function DiscussProvider({ children }: { children: React.ReactNode }) {
  const [selectedSlugs, setSelectedSlugs] = useState<string[]>([])
  const [primarySlug, setPrimary] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [apiHistory, setApiHistory] = useState<any[]>([])
  const [tokenUsage, setTokenUsage] = useState({ input: 0, cached: 0, output: 0 })

  function setSelection(slugs: string[], primary?: string) {
    setSelectedSlugs(slugs)
    // Keep primary valid at all times: prefer the caller's choice, else the
    // existing primary if it survived, else the first remaining story.
    const next = primary && slugs.includes(primary)
      ? primary
      : slugs.includes(primarySlug) ? primarySlug : (slugs[0] ?? '')
    setPrimary(next)
  }

  function toggleSlug(slug: string) {
    const next = selectedSlugs.includes(slug)
      ? selectedSlugs.filter((s) => s !== slug)
      : [...selectedSlugs, slug]
    setSelection(next)
  }

  function setPrimarySlug(slug: string) {
    if (selectedSlugs.includes(slug)) setPrimary(slug)
  }

  function resetConversation() {
    setMessages([])
    setApiHistory([])
    setTokenUsage({ input: 0, cached: 0, output: 0 })
  }

  return (
    <DiscussContext.Provider value={{
      selectedSlugs, primarySlug, messages, apiHistory, tokenUsage,
      setSelection, toggleSlug, setPrimarySlug,
      setMessages, setApiHistory, setTokenUsage, resetConversation,
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
