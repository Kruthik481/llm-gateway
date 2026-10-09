import { control } from '@/lib/control';
import { formatDateTime } from '@/lib/format';
import type { KeyRow } from '@/lib/types';
import { CreateKeyForm } from './CreateKeyForm';
import { RevokeButton } from './RevokeButton';

const MAX_KEYS = 3;

export const metadata = { title: 'API keys · LLM Gateway' };

export default async function KeysPage() {
  const keys = await control<KeyRow[]>('/control/keys');
  return (
    <main className="mx-auto max-w-5xl px-4 py-10">
      <h1 className="text-2xl font-semibold">API keys</h1>
      <p className="mt-1 text-sm text-muted">Up to {MAX_KEYS} active keys. A key is shown once, when you create it.</p>
      <CreateKeyForm canCreate={keys.length < MAX_KEYS} />
      {keys.length === 0 ? (
        <p className="mt-8 text-sm text-muted">No active keys yet.</p>
      ) : (
        <table aria-label="API keys" className="mt-8 w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="py-2">Name</th>
              <th>Key</th>
              <th>Created</th>
              <th>Last used</th>
              <th className="text-right">Requests (24h)</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {keys.map((key) => (
              <tr key={key.id} className="border-t border-line">
                <td className="py-3">{key.name}</td>
                <td className="font-mono text-muted">{key.prefix}…</td>
                <td>{formatDateTime(key.created_at)}</td>
                <td>{key.last_used_at ? formatDateTime(key.last_used_at) : 'Never'}</td>
                <td className="text-right tabular-nums">{key.requests_24h}</td>
                <td className="text-right">
                  <RevokeButton id={key.id} name={key.name} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
