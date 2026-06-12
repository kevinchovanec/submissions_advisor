import type {
  ChatMessage,
  FeedbackNote,
  GeneratedCard,
  Journal,
  MatchResult,
  PendingSub,
  Story,
  SubmissionRow,
  Template,
  Conversation,
} from '../types'

export interface ApiClient {
  // Auth
  login(email: string, password: string): Promise<{ user_id: string; access_token: string; refresh_token: string }>
  signup(email: string, password: string): Promise<{ message: string }>
  logout(): Promise<void>
  refresh(refreshToken: string): Promise<{ access_token: string; refresh_token: string; user_id: string }>
  deleteAccount(): Promise<void>
  // Stories
  listStories(): Promise<Story[]>
  getStory(slug: string): Promise<Story>
  createStory(data: { title: string; word_count?: number | null; style?: string; description?: string }): Promise<{ slug: string }>
  updateStory(slug: string, data: { word_count?: number | null; style?: string; description?: string }): Promise<void>
  generateCard(storyText: string): Promise<GeneratedCard>
  // Submissions
  logSubmission(slug: string, data: { journal: string; outcome?: string; notes?: string; sub_date?: string }): Promise<void>
  updateOutcome(slug: string, journal: string, data: { outcome: string; notes?: string }): Promise<void>
  // Tracker
  listAllSubmissions(): Promise<SubmissionRow[]>
  // Pending
  listPending(): Promise<PendingSub[]>
  // Templates
  listTemplates(): Promise<Template[]>
  getTemplate(name: string): Promise<{ name: string; content: string }>
  saveTemplate(name: string, data: { content: string; description?: string }): Promise<void>
  // Feedback
  listFeedback(): Promise<FeedbackNote[]>
  addFeedback(data: { journal: string; story?: string; feedback_date?: string; text: string }): Promise<void>
  // Conversations
  listConversations(slug: string): Promise<Conversation[]>
  saveConversation(slug: string, messages: ChatMessage[]): Promise<void>
  deleteConversation(slug: string, id: string): Promise<void>
  // Match
  matchJournals(text: string, genreMode: string, customRankings?: object[] | null): Promise<MatchResult>
  uploadRankings(file: File): Promise<object[]>
  // Export
  exportXlsx(): Promise<Response>
  exportData(): Promise<Response>
  // Chat SSE
  streamChat(req: {
    message: string
    api_history: object[]
    journals: Journal[]
    story_context?: string
    editor_feedback?: object[]
    pending_context?: string
    genre_mode?: string
  }): Promise<Response>
  // Health
  health(): Promise<{ status: string; cloud_mode: boolean }>
}

export function createApiClient(accessToken: string | null, apiKey: string | null): ApiClient {
  function hdrs(includeKey = false): Record<string, string> {
    const h: Record<string, string> = { 'Content-Type': 'application/json' }
    if (accessToken) h['Authorization'] = `Bearer ${accessToken}`
    // Only send the header if the user provided a key; omitting it lets the
    // server fall back to ANTHROPIC_API_KEY in .env (local mode convenience)
    if (includeKey && apiKey) h['X-Anthropic-Key'] = apiKey
    return h
  }

  async function req<T>(method: string, path: string, body?: unknown, includeKey = false): Promise<T> {
    const res = await fetch(path, {
      method,
      headers: hdrs(includeKey),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
    if (!res.ok) {
      let msg = `${res.status}`
      try { msg = (await res.json()).detail ?? msg } catch { /* ignore */ }
      throw new Error(msg)
    }
    if (res.status === 204) return undefined as T
    return res.json()
  }

  return {
    login: (email, password) => req('POST', '/api/auth/login', { email, password }),
    signup: (email, password) => req('POST', '/api/auth/signup', { email, password }),
    logout: () => req('POST', '/api/auth/logout'),
    refresh: (refreshToken) => req('POST', '/api/auth/refresh', { refresh_token: refreshToken }),
    deleteAccount: () => req('DELETE', '/api/auth/account'),

    listStories: () => req('GET', '/api/stories'),
    getStory: (slug) => req('GET', `/api/stories/${slug}`),
    createStory: (data) => req('POST', '/api/stories', data),
    updateStory: (slug, data) => req('PUT', `/api/stories/${slug}`, data),
    generateCard: (storyText) => req('POST', '/api/stories/generate-card', { story_text: storyText }, true),

    logSubmission: (slug, data) => req('POST', `/api/stories/${slug}/submissions`, data),
    updateOutcome: (slug, journal, data) => req('PUT', `/api/stories/${slug}/submissions/${encodeURIComponent(journal)}`, data),

    listAllSubmissions: () => req('GET', '/api/submissions'),

    listPending: () => req('GET', '/api/pending'),

    listTemplates: () => req('GET', '/api/templates'),
    getTemplate: (name) => req('GET', `/api/templates/${name}`),
    saveTemplate: (name, data) => req('PUT', `/api/templates/${name}`, data),

    listFeedback: () => req('GET', '/api/feedback'),
    addFeedback: (data) => req('POST', '/api/feedback', data),

    listConversations: (slug) => req('GET', `/api/conversations/${slug}`),
    saveConversation: (slug, messages) => req('POST', `/api/conversations/${slug}`, { messages }),
    deleteConversation: (slug, id) => req('DELETE', `/api/conversations/${slug}/${id}`),

    matchJournals: (text, genreMode, customRankings) =>
      req('POST', '/api/match', {
        text,
        genre_mode: genreMode,
        ...(customRankings ? { custom_rankings: customRankings } : {}),
      }),

    uploadRankings: async (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      const headers: Record<string, string> = {}
      if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`
      const res = await fetch('/api/rankings/upload', { method: 'POST', headers, body: fd })
      if (!res.ok) {
        let msg = `${res.status}`
        try { msg = (await res.json()).detail ?? msg } catch { /* ignore */ }
        throw new Error(msg)
      }
      return res.json()
    },

    exportXlsx: () => fetch('/api/export', { headers: hdrs() }),
    exportData: () => fetch('/api/export/data', { headers: hdrs() }),

    streamChat: (chatReq) =>
      fetch('/api/chat', {
        method: 'POST',
        headers: hdrs(true),
        body: JSON.stringify(chatReq),
      }),

    health: () => req('GET', '/api/health'),
  }
}

/** Duplicate journals by display_name — keep first occurrence. */
export function dedupeJournals<T extends { display_name: string }>(journals: T[]): T[] {
  const seen = new Set<string>()
  return journals.filter((j) => {
    if (seen.has(j.display_name)) return false
    seen.add(j.display_name)
    return true
  })
}

/** Format story dict as the agent's opening context block (mirrors storage.format_story_for_agent). */
export function formatStoryForAgent(story: Story): string {
  const lines = [
    `## Active story: ${story.title}`,
    `Story slug (use this when calling log_submission): ${story.slug}`,
    `Word count: ${story.word_count ?? 'unknown'}`,
    `Style: ${story.style || 'not specified'}`,
    '',
    'Description:',
    story.description?.trim() || '(no description)',
  ]
  if (story.submitted_to?.length) {
    lines.push('', 'Previous submissions (do not suggest these journals):')
    for (const s of story.submitted_to) {
      const note = s.notes ? ` — ${s.notes}` : ''
      lines.push(`  - ${s.journal} (${s.date}, ${s.outcome})${note}`)
    }
  }
  return lines.join('\n')
}

/** Format pending list as agent cross-story context block (mirrors storage.format_pending_for_context). */
export function formatPendingContext(pending: PendingSub[]): string {
  if (!pending.length) return ''
  const lines = [
    'Journals with a submission currently under review (any story — do not suggest these unless the writer explicitly asks about them):',
  ]
  for (const p of pending) {
    lines.push(`  - ${p.journal} (${p.story_title})`)
  }
  return lines.join('\n')
}
