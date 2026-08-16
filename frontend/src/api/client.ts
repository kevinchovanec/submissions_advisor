import type {
  ChatMessage,
  FeedbackNote,
  GeneratedCard,
  Journal,
  MatchResult,
  PendingSub,
  Story,
  SubmissionRow,
  SummaryStatus,
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
  syncTracker(): Promise<{ created: number; added: number }>
  // Submissions
  logSubmission(slug: string, data: { journal: string; outcome?: string; notes?: string; sub_date?: string }): Promise<void>
  updateOutcome(slug: string, journal: string, data: { outcome: string; notes?: string; sub_date?: string }): Promise<void>
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
  updateFeedback(id: string, data: { journal: string; story?: string; feedback_date?: string; text: string }): Promise<void>
  deleteFeedback(id: string): Promise<void>
  // Stories / submissions deletion
  deleteStory(slug: string): Promise<void>
  deleteSubmission(slug: string, journal: string): Promise<void>
  // Conversations
  listConversations(slug: string): Promise<Conversation[]>
  saveConversation(slug: string, messages: ChatMessage[]): Promise<void>
  deleteConversation(slug: string, id: string): Promise<void>
  // Match
  matchJournals(text: string, genreMode: string, customRankings?: object[] | null): Promise<MatchResult>
  uploadRankings(file: File): Promise<object[]>
  // Journal summaries (generation is local-mode only)
  summariesStatus(journals: Journal[]): Promise<SummaryStatus>
  streamSummaries(req: {
    journals: Journal[]
    scope?: 'paste' | 'all'
    force_refresh?: boolean
    dry_run?: boolean
  }): Promise<Response>
  // Export
  exportXlsx(): Promise<Response>
  exportData(): Promise<Response>
  // Chat SSE — story/pending/feedback context is assembled server-side from these
  // slugs, so no prompt text is built in the browser.
  streamChat(req: {
    message: string
    api_history: object[]
    journals: Journal[]
    genre_mode?: string
    story_slugs: string[]
    primary_slug?: string | null
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
    syncTracker: () => req('POST', '/api/stories/sync-tracker'),

    logSubmission: (slug, data) => req('POST', `/api/stories/${slug}/submissions`, data),
    updateOutcome: (slug, journal, data) => req('PUT', `/api/stories/${slug}/submissions/${encodeURIComponent(journal)}`, data),

    listAllSubmissions: () => req('GET', '/api/submissions'),

    listPending: () => req('GET', '/api/pending'),

    listTemplates: () => req('GET', '/api/templates'),
    getTemplate: (name) => req('GET', `/api/templates/${name}`),
    saveTemplate: (name, data) => req('PUT', `/api/templates/${name}`, data),

    listFeedback: () => req('GET', '/api/feedback'),
    addFeedback: (data) => req('POST', '/api/feedback', data),
    updateFeedback: (id, data) => req('PUT', `/api/feedback/${encodeURIComponent(id)}`, data),
    deleteFeedback: (id) => req('DELETE', `/api/feedback/${encodeURIComponent(id)}`),

    deleteStory: (slug) => req('DELETE', `/api/stories/${slug}`),
    deleteSubmission: (slug, journal) => req('DELETE', `/api/stories/${slug}/submissions/${encodeURIComponent(journal)}`),

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

    summariesStatus: (journals) => req('POST', '/api/summaries/status', { journals }),

    streamSummaries: (sumReq) =>
      fetch('/api/summaries/generate', {
        method: 'POST',
        headers: hdrs(true),
        body: JSON.stringify(sumReq),
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

// formatStoryForAgent / formatPendingContext used to live here as copies of the
// Python formatters in src/storage.py. The server now builds that context from the
// slugs streamChat sends, so there is one copy of the prompt text and it can't go
// stale after the agent logs a submission mid-conversation.
