import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useMatch } from '../context/MatchContext'
import { useDiscuss } from '../context/DiscussContext'
import type { ChatMessage, Conversation } from '../types'

export default function DiscussPage() {
  const { apiClient, cloudMode } = useAuth()
  const { journals, genreMode } = useMatch()
  const location = useLocation()
  const qc = useQueryClient()

  const {
    selectedSlugs, primarySlug, messages, apiHistory, tokenUsage,
    setSelection, toggleSlug, setPrimarySlug,
    setMessages, setApiHistory, setTokenUsage, resetConversation,
  } = useDiscuss()
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [streamingText, setStreamingText] = useState('')
  const [streamError, setStreamError] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)

  // "Open in Discuss →" navigation: adopt the requested story. Switching to a
  // different story starts a fresh conversation; re-opening the same story
  // keeps the one in progress.
  const navSlug = location.state?.slug
  useEffect(() => {
    if (navSlug && !selectedSlugs.includes(navSlug)) {
      setSelection([navSlug], navSlug)
      resetConversation()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navSlug])

  const { data: stories = [] } = useQuery({
    queryKey: ['stories'],
    queryFn: () => apiClient.listStories(),
  })

  const { data: pending = [] } = useQuery({
    queryKey: ['pending'],
    queryFn: () => apiClient.listPending(),
  })

  const { data: conversations = [] } = useQuery<Conversation[]>({
    queryKey: ['conversations', primarySlug],
    queryFn: () => apiClient.listConversations(primarySlug),
    enabled: !!primarySlug && cloudMode,
  })

  const saveMutation = useMutation({
    mutationFn: () => apiClient.saveConversation(primarySlug, messages),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['conversations', primarySlug] })
      resetConversation()
      setStreamError('')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteConversation(primarySlug, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations', primarySlug] }),
  })

  const selectedStories = stories.filter((s) => selectedSlugs.includes(s.slug))
  const primaryStory = stories.find((s) => s.slug === primarySlug)

  /** Confirm before discarding an in-progress conversation, then apply the change. */
  function changeSelection(apply: () => void) {
    if (messages.length > 0 && !confirm('Changing the story selection ends the current conversation. Continue?')) return
    apply()
    resetConversation()
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingText])

  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || streaming) return
    setStreamError('')
    const userMsg: ChatMessage = { role: 'user', content: text }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setStreaming(true)
    setStreamingText('')

    abortRef.current = new AbortController()

    try {
      const res = await apiClient.streamChat({
        message: text,
        api_history: apiHistory,
        journals,
        genre_mode: genreMode,
        story_slugs: selectedSlugs,
        primary_slug: primarySlug || null,
      })

      if (!res.ok) {
        const err = await res.text()
        throw new Error(err)
      }

      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let accumulated = ''
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
          if (data.text) {
            accumulated += data.text
            setStreamingText(accumulated)
          }
          if (data.done) {
            setApiHistory(data.history ?? [])
            setMessages((prev) => [...prev, { role: 'assistant', content: accumulated }])
            setStreamingText('')
            if (data.usage) {
              const u = data.usage
              // Kept separate rather than summed: a cached token costs a tenth of a
              // fresh one, so a single total makes a cheap turn look as expensive as
              // the first one. Almost all of a long conversation is cache reads.
              setTokenUsage((prev) => ({
                input: prev.input + (u.input_tokens ?? 0) + (u.cache_creation_input_tokens ?? 0),
                cached: prev.cached + (u.cache_read_input_tokens ?? 0),
                output: prev.output + (u.output_tokens ?? 0),
              }))
            }
            // The agent wrote through a tool (e.g. logged a submission), so the
            // cached story/pending data is stale. Refetch rather than making the
            // user reload to see the new ⛔ exclusion.
            for (const key of (data.invalidate ?? []) as string[]) {
              qc.invalidateQueries({ queryKey: [key] })
            }
            break
          }
          if (data.error) throw new Error(data.error)
        }
      }
    } catch (err: unknown) {
      if ((err as Error).name !== 'AbortError') {
        setStreamError(err instanceof Error ? err.message : 'Stream failed')
        setStreamingText('')
      }
    } finally {
      setStreaming(false)
    }
  }, [streaming, apiHistory, journals, genreMode, apiClient, selectedSlugs, primarySlug, qc])

  function handleEndConversation() {
    if (messages.length === 0) return
    if (cloudMode) {
      saveMutation.mutate()
    } else {
      resetConversation()
    }
  }

  return (
    <div className="flex h-full">
      {/* Left sidebar */}
      <aside className="w-56 flex-shrink-0 border-r border-gray-200 bg-white flex flex-col overflow-hidden">
        <div className="p-4 border-b border-gray-100">
          <div className="flex items-baseline justify-between">
            <label className="label mb-0">Stories</label>
            {selectedSlugs.length > 0 && (
              <button
                className="text-xs text-gray-400 hover:text-gray-600"
                onClick={() => changeSelection(() => setSelection([]))}
              >
                clear
              </button>
            )}
          </div>
          <p className="text-xs text-gray-400 mb-2">
            Pick any number. The rest stay visible to the agent as one-line summaries.
          </p>

          <ul className="max-h-56 overflow-y-auto -mx-1 pr-1">
            {stories.map((s) => {
              const checked = selectedSlugs.includes(s.slug)
              return (
                <li key={s.slug} className="flex items-center gap-1.5 px-1 py-0.5 rounded hover:bg-gray-50">
                  <input
                    type="checkbox"
                    id={`story-${s.slug}`}
                    className="flex-shrink-0"
                    checked={checked}
                    onChange={() => changeSelection(() => toggleSlug(s.slug))}
                  />
                  <label
                    htmlFor={`story-${s.slug}`}
                    className="text-xs text-gray-700 truncate cursor-pointer flex-1"
                    title={s.title}
                  >
                    {s.title}
                  </label>
                  {/* Primary keys saved conversations and is the default log target. */}
                  {checked && selectedSlugs.length > 1 && (
                    <button
                      className={`text-xs flex-shrink-0 ${s.slug === primarySlug ? 'text-amber-500' : 'text-gray-300 hover:text-amber-400'}`}
                      title={s.slug === primarySlug ? 'Primary story' : 'Make primary'}
                      onClick={() => setPrimarySlug(s.slug)}
                    >
                      ★
                    </button>
                  )}
                </li>
              )
            })}
          </ul>

          {journals.length > 0 ? (
            <p className="text-xs text-green-600 mt-2">✓ {journals.length} journals loaded</p>
          ) : (
            <p className="text-xs text-amber-600 mt-2">⚠ No journals — paste in Matcher first</p>
          )}
        </div>

        {/* Past conversations (cloud only) */}
        {cloudMode && conversations.length > 0 && (
          <div className="flex-1 overflow-y-auto p-3">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Past conversations</p>
            <ul className="space-y-1">
              {conversations.map((c) => (
                <li key={c.id} className="group flex items-start justify-between gap-1">
                  <button
                    className="text-xs text-gray-600 hover:text-indigo-600 text-left"
                    onClick={() => {
                      setMessages(c.messages)
                      setApiHistory([])
                      setTokenUsage({ input: 0, cached: 0, output: 0 })
                    }}
                  >
                    {new Date(c.started_at).toLocaleDateString()}
                    <span className="text-gray-400 ml-1">({c.messages.length} msgs)</span>
                  </button>
                  <button
                    className="text-gray-300 hover:text-red-500 text-xs opacity-0 group-hover:opacity-100"
                    onClick={() => deleteMutation.mutate(c.id)}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </aside>

      {/* Chat area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-white flex-shrink-0">
          <h1 className="font-semibold text-sm text-gray-700">
            {selectedStories.length === 0 && 'Discuss'}
            {selectedStories.length === 1 && selectedStories[0].title}
            {selectedStories.length > 1 && (
              <>
                {primaryStory?.title ?? selectedStories[0].title}
                <span className="font-normal text-gray-400 ml-1.5">
                  + {selectedStories.length - 1} more
                </span>
              </>
            )}
          </h1>
          <div className="flex items-center gap-3">
            {(tokenUsage.input > 0 || tokenUsage.output > 0) && (
              <span
                className="text-xs text-gray-400 whitespace-nowrap"
                title={
                  'Anthropic API tokens this conversation.\n' +
                  'New input is billed in full; cached input costs about a tenth as much, ' +
                  'which is why later turns cost less than the first.\n' +
                  'Output includes the model’s thinking, which is not shown.'
                }
              >
                {tokenUsage.input.toLocaleString()} new
                {tokenUsage.cached > 0 && (
                  <span className="text-gray-300"> · {tokenUsage.cached.toLocaleString()} cached</span>
                )}
                {' · '}{tokenUsage.output.toLocaleString()} out
              </span>
            )}
            {messages.length > 0 && (
              <button
                className="btn-secondary text-xs"
                onClick={handleEndConversation}
                disabled={saveMutation.isPending}
              >
                {cloudMode ? (saveMutation.isPending ? 'Saving…' : 'End & save') : 'Clear conversation'}
              </button>
            )}
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && !streaming && (
            <p className="text-sm text-gray-400 text-center mt-12">
              {selectedSlugs.length === 0
                ? 'Select one or more stories to begin.'
                : selectedSlugs.length === 1
                  ? 'Start the conversation — ask about journals, cover letters, or submission strategy.'
                  : `${selectedSlugs.length} stories loaded — ask where each should go, and I'll keep them off the same journals.`}
            </p>
          )}

          {messages.map((msg, i) => (
            <ChatBubble key={i} message={msg} />
          ))}

          {(streaming || streamingText) && (
            <ChatBubble message={{ role: 'assistant', content: streamingText || '…' }} streaming />
          )}

          {streamError && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded p-3">
              {streamError}
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="flex-shrink-0 border-t border-gray-200 bg-white p-3">
          <form
            className="flex gap-2"
            onSubmit={(e) => { e.preventDefault(); sendMessage(input) }}
          >
            <textarea
              className="input flex-1 resize-none min-h-[40px] max-h-[120px]"
              placeholder={selectedSlugs.length ? 'Ask about your stories…' : 'Select a story first'}
              value={input}
              disabled={selectedSlugs.length === 0 || streaming}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(input) }
              }}
              rows={1}
            />
            <button
              type="submit"
              className="btn-primary self-end"
              disabled={selectedSlugs.length === 0 || !input.trim() || streaming}
            >
              {streaming ? '…' : 'Send'}
            </button>
          </form>
          <p className="text-xs text-gray-400 mt-1">Shift+Enter for new line</p>
        </div>
      </div>
    </div>
  )
}

function ChatBubble({ message, streaming }: { message: ChatMessage; streaming?: boolean }) {
  const isUser = message.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-lg px-4 py-3 text-sm ${
          isUser
            ? 'bg-indigo-600 text-white'
            : 'bg-white border border-gray-200 text-gray-800'
        }`}
      >
        <div className="chat-content">
          <MessageContent content={message.content} isUser={isUser} />
          {streaming && <span className="inline-block w-0.5 h-[1em] bg-current ml-0.5 align-middle animate-pulse" />}
        </div>
      </div>
    </div>
  )
}

function MessageContent({ content, isUser }: { content: string; isUser: boolean }) {
  if (isUser) return <p className="whitespace-pre-wrap">{content}</p>

  // Simple markdown-ish rendering for assistant messages
  const lines = content.split('\n')
  const elements: React.ReactNode[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    if (line.startsWith('```')) {
      // Code block
      const lang = line.slice(3).trim()
      const codeLines: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i])
        i++
      }
      elements.push(
        <pre key={i} className={lang ? `language-${lang}` : ''}>
          <code>{codeLines.join('\n')}</code>
        </pre>
      )
    } else if (line.startsWith('## ')) {
      elements.push(<h2 key={i} className="font-bold text-base mt-2 mb-1">{line.slice(3)}</h2>)
    } else if (line.startsWith('### ')) {
      elements.push(<h3 key={i} className="font-semibold mt-2 mb-0.5">{line.slice(4)}</h3>)
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      elements.push(<li key={i} className="ml-4">{renderInline(line.slice(2))}</li>)
    } else if (/^\d+\. /.test(line)) {
      elements.push(<li key={i} className="ml-4 list-decimal">{renderInline(line.replace(/^\d+\. /, ''))}</li>)
    } else if (line.trim() === '') {
      elements.push(<br key={i} />)
    } else {
      elements.push(<p key={i}>{renderInline(line)}</p>)
    }
    i++
  }

  return <>{elements}</>
}

function renderInline(text: string): React.ReactNode {
  // Bold: **text**
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={i}>{part.slice(2, -2)}</strong>
    if (part.startsWith('*') && part.endsWith('*')) return <em key={i}>{part.slice(1, -1)}</em>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={i}>{part.slice(1, -1)}</code>
    return part
  })
}
