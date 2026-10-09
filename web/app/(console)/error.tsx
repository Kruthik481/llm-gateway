'use client';

import { buttonSecondary } from '@/lib/styles';

export default function ConsoleError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="mx-auto max-w-xl px-4 py-16 text-center">
      <h1 className="text-xl font-semibold">The gateway API did not answer</h1>
      <p className="mt-2 text-sm text-muted">
        On the free tier it sleeps when idle and takes about 50 seconds to wake.{' '}
        {error.digest && `(ref ${error.digest})`}
      </p>
      <button type="button" onClick={reset} className={`${buttonSecondary} mt-6`}>
        Try again
      </button>
    </main>
  );
}
