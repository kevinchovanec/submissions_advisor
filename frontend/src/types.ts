export interface Story {
  slug: string;
  title: string;
  word_count: number | null;
  style: string;
  submission_count?: number;
  description?: string;
  submitted_to?: Submission[];
}

export interface Submission {
  journal: string;
  date: string;
  outcome: string;
  notes: string;
}

export interface Journal {
  display_name: string;
  normalized_name: string;
  deadline: string;
  response_days: number | null;
  submit_url: string;
  pay_rate: string;
  rank: number | null;
  score: number | null;
  tier: string | null;
  journal_url: string | null;
  matched_name: string | null;
  match_confidence: number | null;
}

export interface Template {
  name: string;
  description: string;
}

export interface FeedbackNote {
  journal: string;
  story: string;
  date: string | null;
  text: string;
}

export interface PendingSub {
  story_title: string;
  slug: string;
  journal: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface Conversation {
  id: string;
  story_slug: string;
  started_at: string;
  messages: ChatMessage[];
}

export interface MatchResult {
  ranked: Journal[];
  unranked: Journal[];
}

export interface GeneratedCard {
  title: string;
  word_count: number;
  style: string;
  description: string;
}

export type GenreMode = 'Literary' | 'Genre';
