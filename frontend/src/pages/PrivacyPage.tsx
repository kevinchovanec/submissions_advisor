import { Link } from 'react-router-dom'

export default function PrivacyPage() {
  return (
    <div className="max-w-2xl mx-auto px-6 py-10 space-y-8">
      <div>
        <Link to="/" className="text-sm text-indigo-600 hover:underline">&larr; Back</Link>
        <h1 className="text-2xl font-semibold mt-3">Privacy Policy</h1>
        <p className="text-sm text-gray-500 mt-1">Last updated June 2026</p>
      </div>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">What this app does</h2>
        <p className="text-sm text-gray-700">
          Submissions Advisor is a personal tool for short fiction writers. It helps you track which
          journals you've submitted to, get AI-powered submission recommendations, and draft cover
          letters. There are two modes: <strong>local mode</strong> (runs entirely on your own
          computer — no account, no server) and <strong>cloud mode</strong> (your data stored in
          Supabase so you can access it from any browser).
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">What we store</h2>
        <p className="text-sm text-gray-700">
          In cloud mode, we store:
        </p>
        <ul className="text-sm text-gray-700 list-disc pl-5 space-y-1">
          <li>Story metadata — title, word count, style, and description that you type in. <strong>Your manuscript text is never stored.</strong></li>
          <li>Submission history — which journals you've submitted to, dates, and outcomes you log.</li>
          <li>Cover letter templates you save.</li>
          <li>Editor feedback notes you add.</li>
          <li>Chat history from Discuss sessions (the visible messages only — not the full AI context).</li>
        </ul>
        <p className="text-sm text-gray-700">
          All data is scoped to your account and not visible to other users. We use{' '}
          <a href="https://supabase.com" className="text-indigo-600 hover:underline" target="_blank" rel="noreferrer">Supabase</a>{' '}
          for storage, which is hosted on AWS infrastructure.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">What goes to Anthropic</h2>
        <p className="text-sm text-gray-700">
          When you use the Discuss tab or the AI card generator, your story description and journal
          information are sent to the{' '}
          <a href="https://www.anthropic.com" className="text-indigo-600 hover:underline" target="_blank" rel="noreferrer">Anthropic API</a>{' '}
          (Claude). Anthropic does not use API calls to train their models by default. See{' '}
          <a href="https://www.anthropic.com/privacy" className="text-indigo-600 hover:underline" target="_blank" rel="noreferrer">Anthropic's privacy policy</a>{' '}
          for details on how they handle API data.
        </p>
        <p className="text-sm text-gray-700">
          The AI card generator sends your story text to Anthropic if you use it. This is opt-in
          and requires an explicit consent checkbox. If you prefer to keep your manuscript text
          off the internet, fill in the story card manually instead.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">API keys</h2>
        <p className="text-sm text-gray-700">
          Your Anthropic API key is stored in your browser's{' '}
          <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">sessionStorage</code> only —
          it is cleared automatically when you close the tab and is never written to any database.
          It travels as an HTTP header to the backend during your session and is used solely to
          authenticate API calls to Anthropic on your behalf.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">What we do not do</h2>
        <ul className="text-sm text-gray-700 list-disc pl-5 space-y-1">
          <li>We do not sell your data.</li>
          <li>We do not use your stories or submissions for any purpose other than displaying them to you.</li>
          <li>We do not track behavior across sessions or show advertising.</li>
          <li>We do not share your data with third parties other than Supabase (infrastructure) and Anthropic (AI, only when you actively use AI features).</li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Your rights</h2>
        <p className="text-sm text-gray-700">
          You can download all of your data or delete your account at any time from{' '}
          <Link to="/settings" className="text-indigo-600 hover:underline">Settings</Link>.
          Deleting your account removes all stored stories, submissions, templates, feedback, and
          chat history permanently.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Contact</h2>
        <p className="text-sm text-gray-700">
          Questions? Email{' '}
          <a href="mailto:kevinchovanec@gmail.com" className="text-indigo-600 hover:underline">
            kevinchovanec@gmail.com
          </a>.
        </p>
      </section>
    </div>
  )
}
