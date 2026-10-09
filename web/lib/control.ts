import 'server-only';
import { auth } from '@/auth';
import { mintControlToken } from './control-token';
import type { PublicStats } from './types';

const PUBLIC_STATS_TIMEOUT_MS = 3000;

export class ControlError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

function apiUrl(): string {
  const url = process.env.API_URL;
  if (!url) throw new Error('API_URL is not set');
  return url;
}

function controlSecret(): string {
  const secret = process.env.CONTROL_JWT_SECRET;
  if (!secret || secret.length < 32) throw new Error('CONTROL_JWT_SECRET must be at least 32 characters');
  return secret;
}

export async function control<T>(path: string, init: RequestInit = {}): Promise<T> {
  const user = (await auth())?.user;
  if (!user?.githubId) throw new ControlError(401, 'signed_out', 'Your session ended. Sign in again.');
  const token = await mintControlToken(
    { githubId: user.githubId, login: user.login, avatarUrl: user.avatarUrl ?? '' },
    controlSecret(),
  );
  const res = await fetch(`${apiUrl()}${path}`, {
    ...init,
    cache: 'no-store',
    headers: { 'content-type': 'application/json', ...init.headers, authorization: `Bearer ${token}` },
  });
  if (res.status === 204) return undefined as T;
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const error = (body as { error?: { code?: string; message?: string } } | null)?.error;
    throw new ControlError(res.status, error?.code ?? 'error', error?.message ?? `The API answered ${res.status}.`);
  }
  return body as T;
}

export async function publicStats(): Promise<PublicStats | null> {
  try {
    const res = await fetch(`${apiUrl()}/control/stats/public`, {
      next: { revalidate: 30 },
      signal: AbortSignal.timeout(PUBLIC_STATS_TIMEOUT_MS),
    });
    return res.ok ? ((await res.json()) as PublicStats) : null;
  } catch {
    return null; // the free-tier API may be asleep; the landing page renders without stats
  }
}
