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
  /** The ranked spelling when the stored name resolves to a ranked journal; display only. */
  journal_display?: string;
  date: string;
  outcome: string;
  notes: string;
}

export interface Journal {
  display_name: string;
  normalized_name: string;
  /** The pasted name's normalization; set on matched journals, whose normalized_name is the ranked one. */
  pasted_normalized_name?: string | null;
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
  id?: string;
  journal: string;
  /** The ranked spelling when the stored name resolves to a ranked journal; display only. */
  journal_display?: string;
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

export interface SubmissionRow {
  story_slug: string;
  story_title: string;
  journal: string;
  /** The ranked spelling when the stored name resolves to a ranked journal; display only. */
  journal_display?: string;
  date: string;
  outcome: string;
  notes: string;
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

/** Summary coverage for a set of journals. The three buckets are disjoint. */
export interface SummaryStatus {
  total: number;
  cached: number;
  missing: number;
  no_url: number;
}
