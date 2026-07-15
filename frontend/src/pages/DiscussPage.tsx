import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useMatch } from '../context/MatchContext'
import { useDiscuss } from '../context/DiscussContext'
import { formatStoryForAgent, formatPendingContext } from '../api/client'
import type { ChatMessage, Conversation, Story } from '../types'

export default function DiscussPage() {
  const { apiClient, cloudMode } = useAuth()
  const { journals, genreMode } = useMatch()
  const location = useLocation()
  const qc = useQueryClient()

  const {
    selectedSlug, messages, apiHistory, tokenUsage,
    setSelectedSlug, setMessages, setApiHistory, setTokenUsage, resetConversation,
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
    if (navSlug && navSlug !== selectedSlug) {
      setSelectedSlug(navSlug)
      resetConversation()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navSlug])

  const { data: stories = [] } = useQuery({
    queryKey: ['stories'],
    queryFn: () => apiClient.listStories(),
  })

  const { data: story } = useQuery<Story>({
    queryKey: ['story', selectedSlug],
    queryFn: () => apiClient.getStory(selectedSlug),
    enabled: !!selectedSlug,
  })

  const { data: pending = [] } = useQuery({
    queryKey: ['pending'],
    queryFn: () => apiClient.listPending(),
  })

  const { data: feedback = [] } = useQuery({
    queryKey: ['feedback'],
    queryFn: () => apiClient.listFeedback(),
  })

  const { data: conversations = [] } = useQuery<Conversation[]>({
    queryKey: ['conversations', selectedSlug],
    queryFn: () => apiClient.listConversations(selectedSlug),
    enabled: !!selectedSlug && cloudMode,
  })

  const saveMutation = useMutation({
    mutationFn: () => apiClient.saveConversation(selectedSlug, messages),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['conversations', selectedSlug] })
      resetConversation()
      setStreamError('')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteConversation(selectedSlug, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations', selectedSlug] }),
  })

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

    const storyContext = story ? formatStoryForAgent(story) : undefined
    const pendingContext = formatPendingContext(pending)

    abortRef.current = new AbortController()

    try {
      const res = await apiClient.streamChat({
        message: text,
        api_history: apiHistory,
        journals,
        story_context: storyContext,
        editor_feedback: feedback,
        pending_context: pendingContext,
        genre_mode: genreMode,
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
              const inTokens = (u.input_tokens ?? 0) + (u.cache_read_input_tokens ?? 0) + (u.cache_creation_input_tokens ?? 0)
              setTokenUsage((prev) => ({ input: prev.input + inTokens, output: prev.output + (u.output_tokens ?? 0) }))
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
  }, [streaming, story, pending, feedback, apiHistory, journals, genreMode, apiClient])

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
          <label className="label">Story</label>
          <select
            className="input text-sm"
            value={selectedSlug}
            onChange={(e) => {
              if (messages.length > 0 && !confirm('Starting a new story — end the current conversation?')) return
              setSelectedSlug(e.target.value)
              resetConversation()
            }}
          >
            <option value="">— select —</option>
            {stories.map((s) => (
              <option key={s.slug} value={s.slug}>{s.title}</option>
            ))}
          </select>

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
                      setTokenUsage({ input: 0, output: 0 })
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
            {story ? story.title : 'Discuss'}
          </h1>
          <div className="flex items-center gap-3">
            {(tokenUsage.input > 0 || tokenUsage.output > 0) && (
              <span
                className="text-xs text-gray-400 whitespace-nowrap"
                title="Anthropic API tokens used in this conversation (input includes cached tokens · output)"
              >
                {tokenUsage.input.toLocaleString()} in · {tokenUsage.output.toLocaleString()} out tokens
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
              {selectedSlug
                ? 'Start the conversation — ask about journals, cover letters, or submission strategy.'
                : 'Select a story to begin.'}
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
              placeholder={selectedSlug ? 'Ask about your story…' : 'Select a story first'}
              value={input}
              disabled={!selectedSlug || streaming}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(input) }
              }}
              rows={1}
            />
            <button
              type="submit"
              className="btn-primary self-end"
              disabled={!selectedSlug || !input.trim() || streaming}
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
