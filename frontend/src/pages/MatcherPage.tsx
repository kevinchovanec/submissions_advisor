import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useAuth } from '../context/AuthContext'
import { useMatch } from '../context/MatchContext'
import { dedupeJournals } from '../api/client'
import type { Journal, SummaryStatus } from '../types'

export default function MatcherPage() {
  const { apiClient, cloudMode } = useAuth()
  const { journals, batches, genreMode, customRankings, setJournals, addBatch, clearBatches, setGenreMode, setCustomRankings } = useMatch()
  const [pasteText, setPasteText] = useState('')
  const [unranked, setUnranked] = useState<Journal[]>([])
  const [uploadError, setUploadError] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Journal summaries (local mode only — data/ is ephemeral on the hosted server)
  const [sumStatus, setSumStatus] = useState<SummaryStatus | null>(null)
  const [sumLog, setSumLog] = useState<string[]>([])
  const [sumRunning, setSumRunning] = useState(false)
  const sumLogRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (cloudMode || journals.length === 0) { setSumStatus(null); return }
    let stale = false
    apiClient.summariesStatus(journals)
      .then((s) => { if (!stale) setSumStatus(s) })
      .catch(() => { if (!stale) setSumStatus(null) })
    return () => { stale = true }
  }, [journals, cloudMode, apiClient])

  useEffect(() => {
    sumLogRef.current?.scrollTo({ top: sumLogRef.current.scrollHeight })
  }, [sumLog])

  async function runSummaries(opts: { scope?: 'paste' | 'all'; dry_run?: boolean }) {
    if (sumRunning) return
    setSumRunning(true)
    setSumLog([])
    try {
      const res = await apiClient.streamSummaries({ journals, scope: opts.scope ?? 'paste', dry_run: opts.dry_run })
      if (!res.ok) {
        let detail = `${res.status}`
        try { detail = (await res.json()).detail ?? detail } catch { /* ignore */ }
        throw new Error(detail)
      }
      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = JSON.parse(line.slice(6))
          if (data.line) setSumLog((prev) => [...prev, data.line])
          if (data.error) setSumLog((prev) => [...prev, `Error: ${data.error}`])
        }
      }
      const fresh = await apiClient.summariesStatus(journals)
      setSumStatus(fresh)
    } catch (err) {
      setSumLog((prev) => [...prev, `Error: ${err instanceof Error ? err.message : 'failed'}`])
    } finally {
      setSumRunning(false)
    }
  }

  const matchMutation = useMutation({
    mutationFn: async () => {
      const combined = batches.join('\n')
      return apiClient.matchJournals(combined, genreMode, customRankings)
    },
    onSuccess: (data) => {
      setJournals(dedupeJournals(data.ranked))
      setUnranked(dedupeJournals(data.unranked))
    },
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => apiClient.uploadRankings(file),
    onSuccess: (data) => {
      setCustomRankings(data)
      setUploadError('')
      if (fileInputRef.current) fileInputRef.current.value = ''
    },
    onError: (err: Error) => {
      setUploadError(err.message)
      if (fileInputRef.current) fileInputRef.current.value = ''
    },
  })

  function handleAddBatch() {
    if (pasteText.trim()) {
      addBatch(pasteText.trim())
      setPasteText('')
    }
  }

  function handleClear() {
    clearBatches()
    setPasteText('')
    setUnranked([])
  }

  async function handleExport() {
    const res = await apiClient.exportXlsx()
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'submissions.xlsx'
    a.click()
    URL.revokeObjectURL(url)
  }

  const REVIEW_THRESHOLD = 95
  const lowConfidence = journals
    .filter((j) => j.rank !== null && (j.match_confidence ?? 100) < REVIEW_THRESHOLD)
    .sort((a, b) => (a.match_confidence ?? 0) - (b.match_confidence ?? 0))

  function handleReject(journal: Journal) {
    setJournals(journals.filter((j) => j.normalized_name !== journal.normalized_name))
    setUnranked([...unranked, journal])
  }

  const totalJournals = batches.reduce((n, b) => {
    const lines = b.split('\n').filter((l) => l.trim() && !['title', 'name', 'journal'].includes(l.trim().toLowerCase()))
    return n + lines.length
  }, 0)

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Journal Matcher</h1>
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-500">Mode:</span>
          {(['Literary', 'Genre'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setGenreMode(m)}
              className={`px-3 py-1 text-sm rounded-full border transition-colors ${
                genreMode === m
                  ? 'bg-indigo-600 text-white border-indigo-600'
                  : 'bg-white text-gray-600 border-gray-300 hover:border-indigo-400'
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      {/* Paste area */}
      <div className="card mb-4">
        <label className="label">Paste open journals (from Duotrope, The Submission Grinder, etc.)</label>
        <textarea
          className="input min-h-[120px] font-mono text-xs mb-3"
          placeholder="Copy and paste a list of open journals here…"
          value={pasteText}
          onChange={(e) => setPasteText(e.target.value)}
        />
        <div className="flex items-center gap-2 flex-wrap">
          <button className="btn-primary" onClick={handleAddBatch} disabled={!pasteText.trim()}>
            Add batch
          </button>
          <button className="btn-secondary" onClick={handleClear} disabled={batches.length === 0 && !pasteText.trim()}>
            Clear all
          </button>
          {batches.length > 0 && (
            <span className="text-sm text-gray-500">
              {batches.length} batch{batches.length !== 1 ? 'es' : ''} loaded (~{totalJournals} journals)
            </span>
          )}
        </div>
      </div>

      {/* Custom rankings */}
      <div className="card mb-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-700">Custom rankings (optional)</span>
          {customRankings && (
            <span className="text-xs text-green-700 bg-green-50 border border-green-200 rounded px-2 py-0.5">
              {customRankings.length} journals loaded
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500 mb-3">
          Upload an Excel or CSV file to override the built-in list. Required columns:{' '}
          <code className="bg-gray-100 px-1 rounded">rank</code>,{' '}
          <code className="bg-gray-100 px-1 rounded">name</code>,{' '}
          <code className="bg-gray-100 px-1 rounded">journal_url</code>{' '}
          (needed for the AI agent to read guidelines).
          Optional: <code className="bg-gray-100 px-1 rounded">score</code>,{' '}
          <code className="bg-gray-100 px-1 rounded">tier</code>.
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            className="text-sm text-gray-600 file:mr-2 file:py-1 file:px-3 file:rounded file:border file:border-gray-300 file:text-sm file:font-medium file:bg-white file:text-gray-700 hover:file:bg-gray-50"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) uploadMutation.mutate(file)
            }}
          />
          {uploadMutation.isPending && <span className="text-xs text-gray-400">Parsing…</span>}
          {customRankings && (
            <button className="btn-secondary text-xs" onClick={() => setCustomRankings(null)}>
              Remove custom rankings
            </button>
          )}
        </div>
        {uploadError && <p className="text-xs text-red-600 mt-2">{uploadError}</p>}
      </div>

      <div className="flex items-center gap-3 mb-6">
        <button
          className="btn-primary"
          onClick={() => matchMutation.mutate()}
          disabled={batches.length === 0 || matchMutation.isPending}
        >
          {matchMutation.isPending ? 'Matching…' : 'Match journals'}
        </button>
        {journals.length > 0 && (
          <button className="btn-secondary" onClick={handleExport}>
            Download submission history XLSX
          </button>
        )}
        {matchMutation.isError && (
          <span className="text-sm text-red-600">{(matchMutation.error as Error).message}</span>
        )}
      </div>

      {/* Results */}
      {journals.length > 0 && (
        <div className="space-y-4">
          <p className="text-sm text-gray-600">
            <strong>{journals.length}</strong> ranked matches · {unranked.length} unranked
          </p>

          {/* Journal summaries — local mode only. data/ is ephemeral on the hosted
              server and the cache is shared, so summaries are generated here and
              committed to the repo to reach cloud users. */}
          {!cloudMode && sumStatus && (
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <span className="text-gray-700">
                  Guideline summaries: <strong>{sumStatus.cached}</strong> cached
                  {sumStatus.missing > 0 && <> · <strong>{sumStatus.missing}</strong> missing</>}
                  {sumStatus.no_url > 0 && <span className="text-gray-400"> · {sumStatus.no_url} no URL</span>}
                </span>
                <span className="flex-1" />
                <button
                  className="btn-secondary text-xs"
                  disabled={sumRunning || sumStatus.missing === 0}
                  onClick={() => runSummaries({ dry_run: true })}
                  title="Check what would change without spending any tokens"
                >
                  Dry run
                </button>
                <button
                  className="btn-secondary text-xs"
                  disabled={sumRunning || sumStatus.missing === 0}
                  onClick={() => runSummaries({})}
                >
                  {sumRunning ? 'Working…' : `Summarize ${sumStatus.missing} missing`}
                </button>
                <button
                  className="btn-secondary text-xs"
                  disabled={sumRunning}
                  onClick={() => {
                    if (!confirm('Summarize every ranked journal with a URL (~519, roughly $6). This produces the artifact cloud users receive. Continue?')) return
                    runSummaries({ scope: 'all' })
                  }}
                  title="Every ranked journal, not just this paste"
                >
                  All ranked
                </button>
              </div>

              {sumLog.length > 0 && (
                <div ref={sumLogRef} className="mt-2 max-h-48 overflow-y-auto rounded bg-white border border-gray-200 p-2">
                  {sumLog.map((line, i) => (
                    <p key={i} className="font-mono text-xs text-gray-600 whitespace-pre-wrap">{line}</p>
                  ))}
                </div>
              )}
            </div>
          )}

          {lowConfidence.length > 0 && (
            <details open className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm">
              <summary className="cursor-pointer font-medium text-amber-800">
                ⚠️ Review {lowConfidence.length} low-confidence match{lowConfidence.length !== 1 ? 'es' : ''}
              </summary>
              <p className="text-xs text-amber-700 mt-1 mb-2">
                These pasted names matched a ranked journal below {REVIEW_THRESHOLD}% confidence.
                Check both names and reject any that are wrong — rejected journals move to the unranked list.
              </p>
              <ul className="divide-y divide-amber-200">
                {lowConfidence.map((j) => (
                  <li key={j.normalized_name} className="flex items-center gap-3 py-1.5">
                    <span className="font-medium flex-1">{j.display_name}</span>
                    <span className="text-amber-800 flex-1">→ <em>{j.matched_name}</em></span>
                    <span className="font-mono text-xs text-amber-700 w-10 text-right">
                      {j.match_confidence?.toFixed(0)}%
                    </span>
                    <button
                      className="text-xs text-red-600 border border-red-300 rounded px-2 py-0.5 hover:bg-red-50"
                      onClick={() => handleReject(j)}
                    >
                      Reject
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          )}

          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  {['Rank', 'Journal', 'Tier', 'Score', 'Deadline', 'Response', 'Submit'].map((h) => (
                    <th key={h} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-100">
                {journals.map((j) => (
                  <tr key={j.display_name} className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-mono text-gray-500">#{j.rank}</td>
                    <td className="px-3 py-2 font-medium">
                      {j.journal_url ? (
                        <a href={j.journal_url} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline">
                          {j.display_name}
                        </a>
                      ) : (
                        j.display_name
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <TierBadge tier={j.tier} />
                    </td>
                    <td className="px-3 py-2 text-gray-500">{j.score?.toFixed(1)}</td>
                    <td className="px-3 py-2 text-gray-500">{j.deadline === 'rolling' ? '—' : j.deadline}</td>
                    <td className="px-3 py-2 text-gray-500">{j.response_days ? `${j.response_days}d` : '—'}</td>
                    <td className="px-3 py-2">
                      {j.submit_url && (
                        <a href={j.submit_url} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline text-xs">
                          Submit →
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {unranked.length > 0 && (
            <details className="text-sm">
              <summary className="cursor-pointer text-gray-500 hover:text-gray-700">
                {unranked.length} journals not in rankings
              </summary>
              <ul className="mt-2 pl-4 space-y-0.5 text-gray-500">
                {unranked.map((j) => <li key={j.display_name}>{j.display_name}</li>)}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  )
}

function TierBadge({ tier }: { tier: string | null }) {
  if (!tier) return <span className="text-gray-400">—</span>
  const colors: Record<string, string> = {
    T1: 'bg-purple-100 text-purple-800',
    T2: 'bg-blue-100 text-blue-800',
    T3: 'bg-green-100 text-green-800',
    T4: 'bg-gray-100 text-gray-600',
  }
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-medium ${colors[tier] ?? 'bg-gray-100 text-gray-600'}`}>
      {tier}
    </span>
  )
}
