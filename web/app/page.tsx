import Link from 'next/link';
import { auth, signIn } from '@/auth';
import { CodeSnippet } from '@/components/CodeSnippet';
import { Stat } from '@/components/Stat';
import { publicStats } from '@/lib/control';
import { formatPercent } from '@/lib/format';
import { buttonPrimary } from '@/lib/styles';

export default async function Home() {
  const [session, stats] = await Promise.all([auth(), publicStats()]);
  return (
    <main className="mx-auto max-w-4xl px-4 py-16">
      <p className="text-sm font-medium text-accent">LLM Gateway</p>
      <h1 className="mt-2 text-4xl font-semibold tracking-tight">
        One OpenAI-compatible endpoint in front of several LLM providers.
      </h1>
      <p className="mt-4 max-w-2xl text-muted">
        Issued API keys, per-key rate limits, daily token budgets, a response cache and automatic fallback from
        Groq to OpenRouter, with usage and list-price cost tracked for every request.
      </p>
      <div className="mt-8 flex gap-3">
        {session?.user ? (
          <Link href="/keys" className={buttonPrimary}>
            Open the console
          </Link>
        ) : (
          <form
            action={async () => {
              'use server';
              await signIn('github', { redirectTo: '/keys' });
            }}
          >
            <button type="submit" className={buttonPrimary}>
              Sign in with GitHub
            </button>
          </form>
        )}
      </div>
      <CodeSnippet apiUrl={process.env.NEXT_PUBLIC_API_URL ?? ''} />
      <section aria-label="Live stats" className="mt-10 grid gap-4 sm:grid-cols-3">
        <Stat label="Requests today" value={stats ? String(stats.requests_today) : '—'} />
        <Stat label="Cache hit rate" value={stats ? formatPercent(stats.cache_hit_rate) : '—'} />
        <Stat label="Fallbacks served" value={stats ? String(stats.fallbacks_today) : '—'} />
      </section>
      <p className="mt-10 text-sm text-muted">Prompts and answers are never stored; cached answers expire in 24h.</p>
    </main>
  );
}
