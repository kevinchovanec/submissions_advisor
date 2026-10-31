import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../context/AuthContext'
import type { SubmissionRow } from '../types'

const OUTCOMES = ['pending', 'accepted', 'rejected', 'withdrawn', 'shortlisted'] as const

const OUTCOME_STYLES: Record<string, string> = {
  pending:     'bg-yellow-100 text-yellow-800',
  accepted:    'bg-green-100 text-green-800',
  rejected:    'bg-gray-100 text-gray-600',
  withdrawn:   'bg-red-50 text-red-700',
  shortlisted: 'bg-blue-100 text-blue-800',
}

interface StoryGroup {
  slug: string
  title: string
  pending: SubmissionRow[]
  closed: SubmissionRow[]
}

export default function TrackerPage() {
  const { apiClient } = useAuth()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')

  const { data: rows = [], isLoading, isError } = useQuery<SubmissionRow[]>({
    queryKey: ['submissions'],
    queryFn: () => apiClient.listAllSubmissions(),
  })

  const outcomeMutation = useMutation({
    mutationFn: ({ story_slug, journal, outcome, notes, sub_date }: {
      story_slug: string; journal: string; outcome: string; notes: string; sub_date?: string
    }) => apiClient.updateOutcome(story_slug, journal, { outcome, notes, sub_date }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['submissions'] })
      qc.invalidateQueries({ queryKey: ['story', vars.story_slug] })
      qc.invalidateQueries({ queryKey: ['stories'] })
    },
  })

  const deleteSubmissionMutation = useMutation({
    mutationFn: ({ story_slug, journal }: { story_slug: string; journal: string }) =>
      apiClient.deleteSubmission(story_slug, journal),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['submissions'] })
      qc.invalidateQueries({ queryKey: ['story', vars.story_slug] })
      qc.invalidateQueries({ queryKey: ['stories'] })
    },
  })

  const groups: StoryGroup[] = useMemo(() => {
    const map = new Map<string, StoryGroup>()
    for (const row of rows) {
      if (!map.has(row.story_slug)) {
        map.set(row.story_slug, { slug: row.story_slug, title: row.story_title, pending: [], closed: [] })
      }
      const g = map.get(row.story_slug)!
      if (row.outcome === 'pending') g.pending.push(row)
      else g.closed.push(row)
    }
    return Array.from(map.values())
      .filter((g) => {
        if (!search) return true
        const q = search.toLowerCase()
        return (
          g.title.toLowerCase().includes(q) ||
          [...g.pending, ...g.closed].some((r) => r.journal.toLowerCase().includes(q))
        )
      })
      .sort((a, b) => {
        if (b.pending.length !== a.pending.length) return b.pending.length - a.pending.length
        return (b.pending.length + b.closed.length) - (a.pending.length + a.closed.length)
      })
  }, [rows, search])

  const totalPending = rows.filter((r) => r.outcome === 'pending').length

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Submission Tracker</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {rows.length} submissions across {groups.length} stories · {totalPending} pending
          </p>
        </div>
        <input
          className="input max-w-xs"
          placeholder="Search…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {isLoading && <p className="text-sm text-gray-400">Loading…</p>}
      {isError && <p className="text-sm text-red-600">Failed to load submissions.</p>}

      {!isLoading && groups.length === 0 && (
        <p className="text-sm text-gray-400 mt-8 text-center">
          {rows.length === 0 ? 'No submissions logged yet.' : 'No stories match your search.'}
        </p>
      )}

      <div className="space-y-4">
        {groups.map((g) => (
          <StoryCard
            key={g.slug}
            group={g}
            onNavigate={() => navigate('/stories', { state: { slug: g.slug } })}
            onSave={(journal, outcome, notes, sub_date) =>
              outcomeMutation.mutate({ story_slug: g.slug, journal, outcome, notes, sub_date })
            }
            onDelete={(journal) => deleteSubmissionMutation.mutate({ story_slug: g.slug, journal })}
            saving={outcomeMutation.isPending || deleteSubmissionMutation.isPending}
          />
        ))}
      </div>
    </div>
  )
}

function StoryCard({ group, onNavigate, onSave, onDelete, saving }: {
  group: StoryGroup
  onNavigate: () => void
  onSave: (journal: string, outcome: string, notes: string, sub_date?: string) => void
  onDelete: (journal: string) => void
  saving: boolean
}) {
  const total = group.pending.length + group.closed.length
  return (
    <div className="card">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <button className="text-base font-semibold text-indigo-600 hover:underline text-left" onClick={onNavigate}>
          {group.title}
        </button>
        <div className="flex items-center gap-2 text-xs text-gray-500">
          {group.pending.length > 0 && (
            <span className="bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded-full font-medium">
              {group.pending.length} pending
            </span>
          )}
          <span>{total} total</span>
        </div>
      </div>

      {/* Pending submissions */}
      {group.pending.length > 0 && (
        <div className="space-y-1 mb-3">
          {group.pending.map((row) => (
            <SubRow key={`${row.journal}-${row.date}`} row={row} onSave={onSave} onDelete={onDelete} saving={saving} />
          ))}
        </div>
      )}

      {/* Closed submissions */}
      {group.closed.length > 0 && (
        <>
          {group.pending.length > 0 && <div className="border-t border-gray-100 my-2" />}
          <div className="space-y-1">
            {group.pending.length > 0 && (
              <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">Past</p>
            )}
            {group.closed.map((row) => (
              <SubRow key={`${row.journal}-${row.date}`} row={row} onSave={onSave} onDelete={onDelete} saving={saving} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function SubRow({ row, onSave, onDelete, saving }: {
  row: SubmissionRow
  onSave: (journal: string, outcome: string, notes: string, sub_date?: string) => void
  onDelete: (journal: string) => void
  saving: boolean
}) {
  const navigate = useNavigate()
  const [editing, setEditing] = useState(false)
  const [outcome, setOutcome] = useState(row.outcome)
  const [notes, setNotes] = useState(row.notes)
  const [subDate, setSubDate] = useState(row.date)

  if (!editing && outcome !== row.outcome) setOutcome(row.outcome)
  if (!editing && notes !== row.notes) setNotes(row.notes)
  if (!editing && subDate !== row.date) setSubDate(row.date)

  function handleSave() {
    onSave(row.journal, outcome, notes, subDate !== row.date ? subDate : undefined)
    setEditing(false)
  }

  if (editing) {
    return (
      <div className="bg-indigo-50 rounded p-2 space-y-2">
        <p className="text-sm font-medium">{row.journal}</p>
        <div className="flex gap-2 flex-wrap">
          <div>
            <label className="text-xs text-gray-500 block mb-0.5">Date</label>
            <input className="input py-0.5 text-xs w-36" type="date" value={subDate} onChange={(e) => setSubDate(e.target.value)} />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-0.5">Outcome</label>
            <select className="input py-0.5 text-xs" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>
          <div className="flex-1 min-w-32">
            <label className="text-xs text-gray-500 block mb-0.5">Notes</label>
            <input className="input py-0.5 text-xs w-full" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
        </div>
        <div className="flex gap-2">
          <button className="text-xs text-indigo-600 hover:underline" onClick={handleSave} disabled={saving}>Save</button>
          <button className="text-xs text-gray-400 hover:underline" onClick={() => setEditing(false)}>Cancel</button>
          <button
            className="text-xs text-red-500 hover:underline"
            disabled={saving}
            onClick={() => { if (window.confirm(`Delete submission to ${row.journal}?`)) onDelete(row.journal) }}
          >
            Delete
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-between gap-2 py-1 px-1 rounded hover:bg-gray-50 group">
      <div className="flex items-center gap-2 min-w-0">
        <span className={`flex-shrink-0 inline-block px-1.5 py-0.5 rounded text-xs font-medium capitalize ${OUTCOME_STYLES[row.outcome] ?? 'bg-gray-100 text-gray-600'}`}>
          {row.outcome}
        </span>
        <button
          className="text-sm truncate hover:text-indigo-600 hover:underline text-left"
          onClick={() => navigate('/journals', { state: { journal: row.journal } })}
        >
          {row.journal}
        </button>
        {row.notes && <span className="text-xs text-gray-400 truncate hidden sm:block">— {row.notes}</span>}
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        <span className="text-xs text-gray-400">{row.date}</span>
        <button
          className="text-xs text-gray-300 hover:text-indigo-600 opacity-0 group-hover:opacity-100 transition-opacity"
          onClick={() => setEditing(true)}
        >
          Edit
        </button>
      </div>
    </div>
  )
}
