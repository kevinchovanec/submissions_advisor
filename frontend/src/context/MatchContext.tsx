import { createContext, useContext, useState } from 'react'
import type { Journal, GenreMode } from '../types'

interface MatchState {
  journals: Journal[]
  batches: string[]
  genreMode: GenreMode
  customRankings: object[] | null
  setJournals(journals: Journal[]): void
  addBatch(text: string): void
  clearBatches(): void
  setGenreMode(mode: GenreMode): void
  setCustomRankings(rankings: object[] | null): void
}

const MatchContext = createContext<MatchState | null>(null)

export function MatchProvider({ children }: { children: React.ReactNode }) {
  const [journals, setJournals] = useState<Journal[]>([])
  const [batches, setBatches] = useState<string[]>([])
  const [genreMode, setGenreMode] = useState<GenreMode>('Literary')
  const [customRankings, setCustomRankings] = useState<object[] | null>(null)

  function addBatch(text: string) {
    setBatches((prev) => [...prev, text])
  }

  function clearBatches() {
    setBatches([])
    setJournals([])
  }

  return (
    <MatchContext.Provider value={{
      journals, batches, genreMode, customRankings,
      setJournals, addBatch, clearBatches, setGenreMode, setCustomRankings,
    }}>
      {children}
    </MatchContext.Provider>
  )
}

export function useMatch() {
  const ctx = useContext(MatchContext)
  if (!ctx) throw new Error('useMatch must be used inside MatchProvider')
  return ctx
}
