import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../context/AuthContext'
import type { FeedbackNote } from '../types'

export default function NotesPage() {
  const { apiClient } = useAuth()
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)

  const { data: notes = [], isLoading } = useQuery<FeedbackNote[]>({
    queryKey: ['feedback'],
    queryFn: () => apiClient.listFeedback(),
  })

  const addMutation = useMutation({
    mutationFn: (data: { journal: string; story: string; feedback_date: string; text: string }) =>
      apiClient.addFeedback(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['feedback'] })
      setShowForm(false)
    },
  })

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Editor Notes</h1>
        <button className="btn-primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : '+ Add note'}
        </button>
      </div>

      {showForm && (
        <AddNoteForm
          onSubmit={(data) => addMutation.mutate(data)}
          loading={addMutation.isPending}
          error={addMutation.isError ? (addMutation.error as Error).message : ''}
        />
      )}

      {isLoading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : notes.length === 0 ? (
        <p className="text-sm text-gray-400">No editor notes yet. Add encouraging feedback or personal rejections here.</p>
      ) : (
        <div className="space-y-3">
          {notes.map((note, i) => (
            <NoteCard key={i} note={note} />
          ))}
        </div>
      )}
    </div>
  )
}

function AddNoteForm({
  onSubmit,
  loading,
  error,
}: {
  onSubmit: (data: { journal: string; story: string; feedback_date: string; text: string }) => void
  loading: boolean
  error: string
}) {
  const [journal, setJournal] = useState('')
  const [story, setStory] = useState('')
  const [date, setDate] = useState('')
  const [text, setText] = useState('')

  return (
    <div className="card mb-6 space-y-3">
      <h3 className="font-semibold text-sm">New editor note</h3>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label">Journal *</label>
          <input className="input" value={journal} onChange={(e) => setJournal(e.target.value)} />
        </div>
        <div>
          <label className="label">Story</label>
          <input className="input" placeholder="(optional)" value={story} onChange={(e) => setStory(e.target.value)} />
        </div>
      </div>
      <div>
        <label className="label">Date</label>
        <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </div>
      <div>
        <label className="label">Feedback text *</label>
        <textarea
          className="input min-h-[80px]"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="What did the editor say?"
        />
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <button
        className="btn-primary"
        disabled={!journal.trim() || !text.trim() || loading}
        onClick={() => onSubmit({ journal, story, feedback_date: date, text })}
      >
        {loading ? 'Saving…' : 'Save note'}
      </button>
    </div>
  )
}

function NoteCard({ note }: { note: FeedbackNote }) {
  const [expanded, setExpanded] = useState(false)
  const preview = note.text.length > 200 ? note.text.slice(0, 200) + '…' : note.text

  return (
    <div className="card">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium text-sm">{note.journal}</p>
          <p className="text-xs text-gray-500 mt-0.5">
            {note.story && <span className="mr-2">{note.story}</span>}
            {note.date && <span>{note.date}</span>}
          </p>
        </div>
      </div>
      <div className="mt-2 text-sm text-gray-700 whitespace-pre-wrap">
        {expanded ? note.text : preview}
      </div>
      {note.text.length > 200 && (
        <button
          className="text-xs text-indigo-600 hover:underline mt-1"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  )
}
