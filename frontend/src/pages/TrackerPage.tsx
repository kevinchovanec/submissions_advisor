import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../context/AuthContext'
import type { SubmissionRow } from '../types'

const OUTCOMES = ['All', 'pending', 'accepted', 'rejected', 'withdrawn'] as const
type Filter = typeof OUTCOMES[number]

const OUTCOME_STYLES: Record<string, string> = {
  pending:   'bg-yellow-100 text-yellow-800',
  accepted:  'bg-green-100 text-green-800',
  rejected:  'bg-gray-100 text-gray-600',
  withdrawn: 'bg-red-50 text-red-700',
}

export default function TrackerPage() {
  const { apiClient } = useAuth()
  const navigate = useNavigate()
  const [filter, setFilter] = useState<Filter>('All')
  const [search, setSearch] = useState('')

  const { data: rows = [], isLoading, isError } = useQuery<SubmissionRow[]>({
    queryKey: ['submissions'],
    queryFn: () => apiClient.listAllSubmissions(),
  })

  const filtered = rows.filter((r) => {
    if (filter !== 'All' && r.outcome !== filter) return false
    if (search) {
      const q = search.toLowerCase()
      return r.story_title.toLowerCase().includes(q) || r.journal.toLowerCase().includes(q)
    }
    return true
  })

  const counts: Record<string, number> = {}
  for (const r of rows) counts[r.outcome] = (counts[r.outcome] ?? 0) + 1

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Submission Tracker</h1>
        <span className="text-sm text-gray-500">{rows.length} total submissions</span>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="flex gap-1">
          {OUTCOMES.map((o) => (
            <button
              key={o}
              onClick={() => setFilter(o)}
              className={`px-3 py-1 text-sm rounded-full border transition-colors capitalize ${
                filter === o
                  ? 'bg-indigo-600 text-white border-indigo-600'
                  : 'bg-white text-gray-600 border-gray-300 hover:border-indigo-400'
              }`}
            >
              {o === 'All' ? `All (${rows.length})` : `${o} (${counts[o] ?? 0})`}
            </button>
          ))}
        </div>
        <input
          className="input max-w-xs"
          placeholder="Search story or journal…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {isLoading && <p className="text-sm text-gray-400">Loading…</p>}
      {isError && <p className="text-sm text-red-600">Failed to load submissions.</p>}

      {!isLoading && filtered.length === 0 && (
        <p className="text-sm text-gray-400 mt-8 text-center">
          {rows.length === 0 ? 'No submissions logged yet.' : 'No submissions match this filter.'}
        </p>
      )}

      {filtered.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                {['Story', 'Journal', 'Date', 'Outcome', 'Notes'].map((h) => (
                  <th key={h} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-100">
              {filtered.map((r, i) => (
                <tr key={i} className="hover:bg-gray-50">
                  <td className="px-3 py-2 font-medium">
                    <button
                      className="text-indigo-600 hover:underline text-left"
                      onClick={() => navigate('/stories', { state: { slug: r.story_slug } })}
                    >
                      {r.story_title}
                    </button>
                  </td>
                  <td className="px-3 py-2">{r.journal}</td>
                  <td className="px-3 py-2 text-gray-500 whitespace-nowrap">{r.date}</td>
                  <td className="px-3 py-2">
                    <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-medium capitalize ${OUTCOME_STYLES[r.outcome] ?? 'bg-gray-100 text-gray-600'}`}>
                      {r.outcome}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-gray-500 max-w-xs truncate">{r.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
