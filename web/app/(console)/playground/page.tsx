import { PlaygroundClient } from '@/components/PlaygroundClient';

export const metadata = { title: 'Playground · LLM Gateway' };

export default function PlaygroundPage() {
  return (
    <main className="mx-auto max-w-4xl px-4 py-10">
      <h1 className="text-2xl font-semibold">Playground</h1>
      <p className="mt-1 text-sm text-muted">
        Calls the real gateway from your browser with your key. Temperature 0 answers are cached for 24h.
      </p>
      <PlaygroundClient apiUrl={process.env.NEXT_PUBLIC_API_URL ?? ''} />
    </main>
  );
}
