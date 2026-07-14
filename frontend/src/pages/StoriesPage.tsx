import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import type { Story } from '../types'

export default function StoriesPage() {
  const { apiClient, cloudMode } = useAuth()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [syncMsg, setSyncMsg] = useState<string | null>(null)

  const { data: stories = [], isLoading } = useQuery({
    queryKey: ['stories'],
    queryFn: () => apiClient.listStories(),
  })

  const syncMutation = useMutation({
    mutationFn: () => apiClient.syncTracker(),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['stories'] })
      qc.invalidateQueries({ queryKey: ['story'] })
      qc.invalidateQueries({ queryKey: ['submissions'] })
      setSyncMsg(
        data.added > 0
          ? `Synced ${data.added} submission${data.added !== 1 ? 's' : ''} from tracker.`
          : 'Already up to date with the tracker.'
      )
    },
    onError: (err: Error) => setSyncMsg(err.message),
  })

  const selectedStory = selectedSlug
    ? stories.find((s) => s.slug === selectedSlug) ?? null
    : null

  return (
    <div className="flex h-full">
      {/* Story list */}
      <aside className="w-64 flex-shrink-0 border-r border-gray-200 bg-white flex flex-col">
        <div className="p-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-sm text-gray-700">Stories</h2>
          <button
            className="btn-primary py-1 px-2 text-xs"
            onClick={() => { setSelectedSlug(null); setShowCreate(true) }}
          >
            + New
          </button>
        </div>
        {!cloudMode && (
          <div className="px-4 py-2 border-b border-gray-100">
            <button
              className="btn-secondary py-1 px-2 text-xs w-full"
              disabled={syncMutation.isPending}
              onClick={() => { setSyncMsg(null); syncMutation.mutate() }}
              title="Merge submission history from your Excel tracker into your story files"
            >
              {syncMutation.isPending ? 'Syncing…' : 'Sync from tracker'}
            </button>
            {syncMsg && <p className="text-xs text-gray-500 mt-1">{syncMsg}</p>}
          </div>
        )}
        {isLoading ? (
          <p className="p-4 text-sm text-gray-400">Loading…</p>
        ) : stories.length === 0 ? (
          <p className="p-4 text-sm text-gray-400">No stories yet.</p>
        ) : (
          <ul className="flex-1 overflow-y-auto divide-y divide-gray-100">
            {stories.map((s) => (
              <li key={s.slug}>
                <button
                  className={`w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors ${selectedSlug === s.slug ? 'bg-indigo-50' : ''}`}
                  onClick={() => { setSelectedSlug(s.slug); setShowCreate(false) }}
                >
                  <p className="text-sm font-medium text-gray-800 truncate">{s.title}</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {s.word_count ? `${s.word_count.toLocaleString()} words · ` : ''}{s.submission_count ?? 0} sub{s.submission_count !== 1 ? 's' : ''}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>

      {/* Detail panel */}
      <div className="flex-1 overflow-y-auto p-6">
        {showCreate && (
          <CreateStoryForm
            onCreated={(slug) => {
              qc.invalidateQueries({ queryKey: ['stories'] })
              setSelectedSlug(slug)
              setShowCreate(false)
            }}
            onCancel={() => setShowCreate(false)}
          />
        )}
        {!showCreate && selectedSlug && (
          <StoryDetail
            slug={selectedSlug}
            onDiscuss={() => navigate('/discuss', { state: { slug: selectedSlug } })}
            onDeleted={() => {
              qc.invalidateQueries({ queryKey: ['stories'] })
              setSelectedSlug(null)
            }}
          />
        )}
        {!showCreate && !selectedSlug && (
          <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
            Select a story or create a new one.
          </div>
        )}
      </div>
    </div>
  )
}

// -------------------------------------------------------------------------

function CreateStoryForm({ onCreated, onCancel }: { onCreated: (slug: string) => void; onCancel: () => void }) {
  const { apiClient, apiKey, serverHasKey } = useAuth()
  const [title, setTitle] = useState('')
  const [wordCount, setWordCount] = useState('')
  const [style, setStyle] = useState('')
  const [description, setDescription] = useState('')
  const [storyText, setStoryText] = useState('')
  const [showAi, setShowAi] = useState(false)
  const [aiError, setAiError] = useState('')

  const createMutation = useMutation({
    mutationFn: () => apiClient.createStory({
      title,
      word_count: wordCount ? parseInt(wordCount) : null,
      style,
      description,
    }),
    onSuccess: (data) => onCreated(data.slug),
  })

  const genMutation = useMutation({
    mutationFn: () => apiClient.generateCard(storyText),
    onSuccess: (data) => {
      if (data.title && !title) setTitle(data.title)
      if (data.style) setStyle(data.style)
      if (data.description) setDescription(data.description)
      if (data.word_count) setWordCount(String(data.word_count))
      setShowAi(false)
      setAiError('')
    },
    onError: (err: Error) => setAiError(err.message),
  })

  return (
    <div className="max-w-xl">
      <h2 className="text-xl font-bold mb-4">New Story</h2>

      {(apiKey || serverHasKey) && (
        <div className="mb-4">
          <button className="text-sm text-indigo-600 hover:underline" onClick={() => setShowAi(!showAi)}>
            {showAi ? 'Hide' : '✨ Generate card with AI'}
          </button>
          {showAi && (
            <div className="mt-2 card">
              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2 mb-2">
                This will send your story text to the Claude API.
              </p>
              <textarea
                className="input min-h-[100px] text-xs font-mono mb-2"
                placeholder="Paste your story or an excerpt here…"
                value={storyText}
                onChange={(e) => setStoryText(e.target.value)}
              />
              {aiError && <p className="text-xs text-red-600 mb-2">{aiError}</p>}
              <button
                className="btn-secondary text-xs"
                disabled={!storyText.trim() || genMutation.isPending}
                onClick={() => genMutation.mutate()}
              >
                {genMutation.isPending ? 'Generating…' : 'Generate'}
              </button>
            </div>
          )}
        </div>
      )}

      <div className="space-y-3">
        <div>
          <label className="label">Title *</label>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} required />
        </div>
        <div>
          <label className="label">Word count</label>
          <input className="input" type="number" value={wordCount} onChange={(e) => setWordCount(e.target.value)} />
        </div>
        <div>
          <label className="label">Style / aesthetic</label>
          <input className="input" placeholder="lyric realism, second person" value={style} onChange={(e) => setStyle(e.target.value)} />
        </div>
        <div>
          <label className="label">Description</label>
          <textarea className="input min-h-[80px]" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        {createMutation.isError && (
          <p className="text-sm text-red-600">{(createMutation.error as Error).message}</p>
        )}
        <div className="flex gap-2">
          <button
            className="btn-primary"
            disabled={!title.trim() || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            {createMutation.isPending ? 'Saving…' : 'Create story'}
          </button>
          <button className="btn-secondary" onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </div>
  )
}

// -------------------------------------------------------------------------

function StoryDetail({ slug, onDiscuss, onDeleted }: { slug: string; onDiscuss: () => void; onDeleted: () => void }) {
  const { apiClient, apiKey, serverHasKey } = useAuth()
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [showLogForm, setShowLogForm] = useState(false)
  const [storyText, setStoryText] = useState('')
  const [showAi, setShowAi] = useState(false)

  const { data: story, isLoading } = useQuery<Story>({
    queryKey: ['story', slug],
    queryFn: () => apiClient.getStory(slug),
  })

  const [draft, setDraft] = useState({ word_count: '', style: '', description: '' })

  function startEdit() {
    if (!story) return
    setDraft({
      word_count: String(story.word_count ?? ''),
      style: story.style ?? '',
      description: story.description ?? '',
    })
    setEditing(true)
  }

  const updateMutation = useMutation({
    mutationFn: () => apiClient.updateStory(slug, {
      word_count: draft.word_count ? parseInt(draft.word_count) : null,
      style: draft.style,
      description: draft.description,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['story', slug] })
      qc.invalidateQueries({ queryKey: ['stories'] })
      setEditing(false)
    },
  })

  const genMutation = useMutation({
    mutationFn: () => apiClient.generateCard(storyText),
    onSuccess: (data) => {
      setDraft({
        word_count: data.word_count ? String(data.word_count) : draft.word_count,
        style: data.style || draft.style,
        description: data.description || draft.description,
      })
      setShowAi(false)
      if (!editing) setEditing(true)
    },
  })

  const deleteStoryMutation = useMutation({
    mutationFn: () => apiClient.deleteStory(slug),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['stories'] })
      qc.invalidateQueries({ queryKey: ['submissions'] })
      onDeleted()
    },
  })

  const logMutation = useMutation({
    mutationFn: (journal: string) => apiClient.logSubmission(slug, { journal }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['story', slug] })
      qc.invalidateQueries({ queryKey: ['stories'] })
      setShowLogForm(false)
    },
  })

  const outcomeMutation = useMutation({
    mutationFn: ({ journal, outcome, notes, sub_date }: { journal: string; outcome: string; notes: string; sub_date?: string }) =>
      apiClient.updateOutcome(slug, journal, { outcome, notes, sub_date }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['story', slug] })
      qc.invalidateQueries({ queryKey: ['submissions'] })
    },
  })

  const deleteSubmissionMutation = useMutation({
    mutationFn: (journal: string) => apiClient.deleteSubmission(slug, journal),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['story', slug] })
      qc.invalidateQueries({ queryKey: ['stories'] })
      qc.invalidateQueries({ queryKey: ['submissions'] })
    },
  })

  if (isLoading || !story) return <p className="text-sm text-gray-400">Loading…</p>

  return (
    <div className="max-w-2xl space-y-6">
      <div className="flex items-start justify-between">
        <h2 className="text-xl font-bold">{story.title}</h2>
        <div className="flex gap-2">
          <button className="btn-secondary text-xs" onClick={onDiscuss}>Open in Discuss →</button>
          {!editing && <button className="btn-secondary text-xs" onClick={startEdit}>Edit</button>}
          <button
            className="text-xs text-red-500 hover:underline px-2 py-1"
            disabled={deleteStoryMutation.isPending}
            onClick={() => { if (window.confirm(`Delete "${story.title}" and all its submissions?`)) deleteStoryMutation.mutate() }}
          >
            {deleteStoryMutation.isPending ? 'Deleting…' : 'Delete story'}
          </button>
        </div>
      </div>

      {!editing ? (
        <div className="card space-y-2 text-sm">
          <Row label="Word count" value={story.word_count?.toLocaleString() ?? '—'} />
          <Row label="Style" value={story.style || '—'} />
          <div>
            <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Description</span>
            <p className="mt-1 text-gray-700 whitespace-pre-wrap">{story.description || '—'}</p>
          </div>
        </div>
      ) : (
        <div className="card space-y-3">
          {(apiKey || serverHasKey) && (
            <div>
              <button className="text-xs text-indigo-600 hover:underline" onClick={() => setShowAi(!showAi)}>
                {showAi ? 'Hide' : '✨ Re-generate with AI'}
              </button>
              {showAi && (
                <div className="mt-2">
                  <textarea
                    className="input min-h-[80px] text-xs font-mono mb-2"
                    placeholder="Paste story text…"
                    value={storyText}
                    onChange={(e) => setStoryText(e.target.value)}
                  />
                  <button
                    className="btn-secondary text-xs"
                    disabled={!storyText.trim() || genMutation.isPending}
                    onClick={() => genMutation.mutate()}
                  >
                    {genMutation.isPending ? 'Generating…' : 'Generate'}
                  </button>
                </div>
              )}
            </div>
          )}
          <div>
            <label className="label">Word count</label>
            <input className="input" type="number" value={draft.word_count} onChange={(e) => setDraft({ ...draft, word_count: e.target.value })} />
          </div>
          <div>
            <label className="label">Style / aesthetic</label>
            <input className="input" value={draft.style} onChange={(e) => setDraft({ ...draft, style: e.target.value })} />
          </div>
          <div>
            <label className="label">Description</label>
            <textarea className="input min-h-[80px]" value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
          </div>
          {updateMutation.isError && (
            <p className="text-sm text-red-600">{(updateMutation.error as Error).message}</p>
          )}
          <div className="flex gap-2">
            <button className="btn-primary text-xs" disabled={updateMutation.isPending} onClick={() => updateMutation.mutate()}>
              {updateMutation.isPending ? 'Saving…' : 'Save changes'}
            </button>
            <button className="btn-secondary text-xs" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* Submissions */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-sm">Submissions</h3>
          <button className="btn-secondary text-xs" onClick={() => setShowLogForm(!showLogForm)}>
            + Log submission
          </button>
        </div>

        {showLogForm && (
          <LogSubmissionForm
            onLog={(j) => logMutation.mutate(j)}
            onCancel={() => setShowLogForm(false)}
            loading={logMutation.isPending}
          />
        )}

        {(story.submitted_to?.length ?? 0) === 0 ? (
          <p className="text-sm text-gray-400">No submissions yet.</p>
        ) : (
          <div className="overflow-x-auto rounded border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  {['Journal', 'Date', 'Outcome', 'Notes', ''].map((h) => (
                    <th key={h} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-100">
                {story.submitted_to!.map((sub) => (
                  <SubmissionRow
                    key={`${sub.journal}-${sub.date}`}
                    sub={sub}
                    onUpdate={(outcome, notes, sub_date) => outcomeMutation.mutate({ journal: sub.journal, outcome, notes, sub_date })}
                    onDelete={() => { if (window.confirm(`Delete submission to ${sub.journal}?`)) deleteSubmissionMutation.mutate(sub.journal) }}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</span>
      <p className="text-gray-800">{value}</p>
    </div>
  )
}

function LogSubmissionForm({ onLog, onCancel, loading }: { onLog: (j: string) => void; onCancel: () => void; loading: boolean }) {
  const [journal, setJournal] = useState('')
  return (
    <div className="card mb-3 flex gap-2 items-end">
      <div className="flex-1">
        <label className="label">Journal name</label>
        <input className="input" value={journal} onChange={(e) => setJournal(e.target.value)} autoFocus />
      </div>
      <button className="btn-primary" disabled={!journal.trim() || loading} onClick={() => onLog(journal.trim())}>
        {loading ? 'Saving…' : 'Log'}
      </button>
      <button className="btn-secondary" onClick={onCancel}>Cancel</button>
    </div>
  )
}

const OUTCOMES = ['pending', 'accepted', 'rejected', 'withdrawn', 'shortlisted']

function SubmissionRow({ sub, onUpdate, onDelete }: {
  sub: { journal: string; date: string; outcome: string; notes: string }
  onUpdate: (outcome: string, notes: string, sub_date: string) => void
  onDelete: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [outcome, setOutcome] = useState(sub.outcome)
  const [notes, setNotes] = useState(sub.notes)
  const [subDate, setSubDate] = useState(sub.date)

  const outcomeColors: Record<string, string> = {
    pending: 'text-yellow-700 bg-yellow-50',
    accepted: 'text-green-700 bg-green-50',
    rejected: 'text-red-700 bg-red-50',
    withdrawn: 'text-gray-500 bg-gray-50',
    shortlisted: 'text-blue-700 bg-blue-50',
  }

  return editing ? (
    <tr className="bg-indigo-50">
      <td className="px-3 py-2 font-medium">{sub.journal}</td>
      <td className="px-3 py-2">
        <input className="input py-0.5 text-xs" type="date" value={subDate} onChange={(e) => setSubDate(e.target.value)} />
      </td>
      <td className="px-3 py-2">
        <select className="input py-0.5 text-xs" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
          {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </td>
      <td className="px-3 py-2">
        <input className="input py-0.5 text-xs" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </td>
      <td className="px-3 py-2 whitespace-nowrap">
        <button className="text-xs text-indigo-600 hover:underline mr-2" onClick={() => { onUpdate(outcome, notes, subDate); setEditing(false) }}>Save</button>
        <button className="text-xs text-gray-400 hover:underline mr-2" onClick={() => setEditing(false)}>Cancel</button>
        <button className="text-xs text-red-500 hover:underline" onClick={onDelete}>Delete</button>
      </td>
    </tr>
  ) : (
    <tr className="hover:bg-gray-50">
      <td className="px-3 py-2 font-medium">{sub.journal}</td>
      <td className="px-3 py-2 text-gray-500">{sub.date}</td>
      <td className="px-3 py-2">
        <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-medium ${outcomeColors[sub.outcome] ?? 'bg-gray-100 text-gray-600'}`}>
          {sub.outcome}
        </span>
      </td>
      <td className="px-3 py-2 text-gray-500 text-xs">{sub.notes}</td>
      <td className="px-3 py-2">
        <button className="text-xs text-gray-400 hover:text-indigo-600" onClick={() => setEditing(true)}>Edit</button>
      </td>
    </tr>
  )
}
