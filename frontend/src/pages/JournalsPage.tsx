import { useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../context/AuthContext'
import type { FeedbackNote, SubmissionRow } from '../types'

interface RankedJournal {
  name: string
  rank: number
  tier?: string | null
  journal_url?: string | null
}

interface JournalProfile {
  key: string
  name: string
  ranked: RankedJournal | null
  submissions: SubmissionRow[]
  notes: FeedbackNote[]
}

/** Mirrors src/ingest.py normalize_name, plus a trailing ", The" — the rankings
 *  spell "Georgia Review, The" where a writer types "The Georgia Review", and
 *  submissions and notes are free text, so both spellings must land together. */
function journalKey(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/^the\s+/, '')
    .replace(/&/g, 'and')
    .replace(/[^\w\s]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\s+the$/, '')
}

const OUTCOME_STYLES: Record<string, string> = {
  pending:     'bg-yellow-100 text-yellow-800',
  accepted:    'bg-green-100 text-green-800',
  rejected:    'bg-gray-100 text-gray-600',
  withdrawn:   'bg-red-50 text-red-700',
  shortlisted: 'bg-blue-100 text-blue-800',
}

export default function JournalsPage() {
  const { apiClient } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [search, setSearch] = useState('')
  const [selectedKey, setSelectedKey] = useState<string | null>(
    location.state?.journal ? journalKey(location.state.journal) : null,
  )

  const { data: rows = [], isLoading: subsLoading } = useQuery<SubmissionRow[]>({
    queryKey: ['submissions'],
    queryFn: () => apiClient.listAllSubmissions(),
  })
  const { data: notes = [], isLoading: notesLoading } = useQuery<FeedbackNote[]>({
    queryKey: ['feedback'],
    queryFn: () => apiClient.listFeedback(),
  })
  const { data: rankings = [] } = useQuery<RankedJournal[]>({
    queryKey: ['rankings'],
    queryFn: () => apiClient.listRankings(),
    staleTime: Infinity,
  })

  const profiles: JournalProfile[] = useMemo(() => {
    const rankedIndex = new Map(rankings.map((r) => [journalKey(r.name), r]))
    const map = new Map<string, JournalProfile & { spellings: Map<string, number> }>()
    const profileFor = (name: string) => {
      const key = journalKey(name)
      if (!map.has(key)) {
        map.set(key, { key, name, ranked: rankedIndex.get(key) ?? null, submissions: [], notes: [], spellings: new Map() })
      }
      const p = map.get(key)!
      p.spellings.set(name, (p.spellings.get(name) ?? 0) + 1)
      return p
    }
    for (const row of rows) if (row.journal.trim()) profileFor(row.journal).submissions.push(row)
    for (const note of notes) if (note.journal.trim()) profileFor(note.journal).notes.push(note)

    return Array.from(map.values())
      .map(({ spellings, ...p }) => ({
        ...p,
        // The ranked spelling if there is one, else whichever the writer used most.
        name: p.ranked?.name ?? [...spellings.entries()].sort((a, b) => b[1] - a[1])[0][0],
      }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [rows, notes, rankings])

  const filtered = search
    ? profiles.filter((p) => p.name.toLowerCase().includes(search.toLowerCase()))
    : profiles
  const selected = profiles.find((p) => p.key === selectedKey) ?? null
  const isLoading = subsLoading || notesLoading

  return (
    <div className="flex h-full">
      <aside className="w-72 flex-shrink-0 border-r border-gray-200 bg-white flex flex-col">
        <div className="p-4 border-b border-gray-100 space-y-2">
          <h2 className="font-semibold text-sm text-gray-700">
            Journals {profiles.length > 0 && <span className="text-gray-400 font-normal">({profiles.length})</span>}
          </h2>
          <input
            className="input py-1 text-sm"
            placeholder="Search journals…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        {isLoading ? (
          <p className="p-4 text-sm text-gray-400">Loading…</p>
        ) : filtered.length === 0 ? (
          <p className="p-4 text-sm text-gray-400">
            {profiles.length === 0 ? 'No submissions or editor notes yet.' : 'No journals match your search.'}
          </p>
        ) : (
          <ul className="flex-1 overflow-y-auto divide-y divide-gray-100">
            {filtered.map((p) => {
              const pending = p.submissions.filter((s) => s.outcome === 'pending').length
              return (
                <li key={p.key}>
                  <button
                    className={`w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors ${selectedKey === p.key ? 'bg-indigo-50' : ''}`}
                    onClick={() => setSelectedKey(p.key)}
                  >
                    <p className="text-sm font-medium text-gray-800 truncate">{p.name}</p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {p.submissions.length} sub{p.submissions.length !== 1 ? 's' : ''}
                      {pending > 0 && <span className="text-yellow-700"> · {pending} pending</span>}
                      {p.notes.length > 0 && (
                        <span className="text-indigo-600"> · {p.notes.length} note{p.notes.length !== 1 ? 's' : ''}</span>
                      )}
                    </p>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </aside>

      <div className="flex-1 overflow-y-auto p-6">
        {selected ? (
          <JournalDetail
            profile={selected}
            onOpenStory={(slug) => navigate('/stories', { state: { slug } })}
          />
        ) : (
          <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
            Select a journal to see its history.
          </div>
        )}
      </div>
    </div>
  )
}

// -------------------------------------------------------------------------

function JournalDetail({ profile, onOpenStory }: { profile: JournalProfile; onOpenStory: (slug: string) => void }) {
  const { ranked, submissions, notes } = profile
  const sorted = [...submissions].sort((a, b) => (b.date || '').localeCompare(a.date || ''))
  const sortedNotes = [...notes].sort((a, b) => (b.date || '').localeCompare(a.date || ''))
  const count = (o: string) => submissions.filter((s) => s.outcome === o).length

  // Story title → slug, so a note naming a story can link to it when it matches one.
  const storySlugs = new Map(submissions.map((s) => [s.story_title.toLowerCase(), s.story_slug]))

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-xl font-bold">{profile.name}</h2>
        <p className="text-sm text-gray-500 mt-0.5 flex flex-wrap gap-x-3">
          {ranked ? (
            <>
              <span>Ranked #{ranked.rank}</span>
              {ranked.tier && <span>{ranked.tier}</span>}
            </>
          ) : (
            <span className="text-gray-400">Not on the ranked list</span>
          )}
          {ranked?.journal_url && (
            <a href={ranked.journal_url} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline">
              Website →
            </a>
          )}
        </p>
      </div>

      <div className="card flex flex-wrap gap-x-6 gap-y-2 text-sm">
        <Stat label="Submissions" value={submissions.length} />
        <Stat label="Pending" value={count('pending')} />
        <Stat label="Shortlisted" value={count('shortlisted')} />
        <Stat label="Accepted" value={count('accepted')} />
        <Stat label="Rejected" value={count('rejected')} />
        <Stat label="Editor notes" value={notes.length} />
      </div>

      {/* Editor notes */}
      <div>
        <h3 className="font-semibold text-sm mb-1">Editor notes</h3>
        {notes.length === 0 ? (
          <p className="text-sm text-gray-400">No notes from this journal's editors yet.</p>
        ) : (
          <>
            <p className="text-sm text-gray-600 mb-3">{notesSummary(notes)}</p>
            <div className="space-y-2">
              {sortedNotes.map((n, i) => {
                const slug = n.story ? storySlugs.get(n.story.toLowerCase()) : undefined
                return (
                  <div key={n.id ?? i} className="card py-3">
                    <p className="text-xs text-gray-500 mb-1">
                      {n.story && (slug ? (
                        <button className="text-indigo-600 hover:underline mr-2" onClick={() => onOpenStory(slug)}>
                          {n.story}
                        </button>
                      ) : (
                        <span className="mr-2">{n.story}</span>
                      ))}
                      {n.date}
                    </p>
                    <p className="text-sm text-gray-700 whitespace-pre-wrap">{n.text}</p>
                  </div>
                )
              })}
            </div>
          </>
        )}
      </div>

      {/* Submissions */}
      <div>
        <h3 className="font-semibold text-sm mb-3">Submissions</h3>
        {sorted.length === 0 ? (
          <p className="text-sm text-gray-400">Nothing submitted here yet.</p>
        ) : (
          <div className="overflow-x-auto rounded border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  {['Story', 'Date', 'Outcome', 'Notes'].map((h) => (
                    <th key={h} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-100">
                {sorted.map((s) => (
                  <tr key={`${s.story_slug}-${s.journal}-${s.date}`} className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-medium">
                      <button className="text-indigo-600 hover:underline text-left" onClick={() => onOpenStory(s.story_slug)}>
                        {s.story_title}
                      </button>
                    </td>
                    <td className="px-3 py-2 text-gray-500 whitespace-nowrap">{s.date}</td>
                    <td className="px-3 py-2">
                      <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-medium capitalize ${OUTCOME_STYLES[s.outcome] ?? 'bg-gray-100 text-gray-600'}`}>
                        {s.outcome}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-gray-500 text-xs">{s.notes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

/** "2 notes from the editors, on "Story X" and "Story Y"." */
function notesSummary(notes: FeedbackNote[]): string {
  const stories = [...new Set(notes.map((n) => n.story?.trim()).filter(Boolean))] as string[]
  const head = `${notes.length} note${notes.length !== 1 ? 's' : ''} from the editors`
  if (stories.length === 0) return `${head}.`
  const quoted = stories.map((s) => `“${s}”`)
  const list = quoted.length === 1
    ? quoted[0]
    : `${quoted.slice(0, -1).join(', ')} and ${quoted[quoted.length - 1]}`
  return `${head}, on ${list}.`
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
      <p className={`text-lg font-semibold ${value === 0 ? 'text-gray-300' : 'text-gray-800'}`}>{value}</p>
    </div>
  )
}
