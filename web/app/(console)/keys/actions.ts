'use server';

import { revalidatePath } from 'next/cache';
import { ControlError, control } from '@/lib/control';
import type { CreatedKey } from '@/lib/types';

const MAX_NAME = 40;

export type CreateKeyState = { key: string | null; error: string | null };

export async function createKey(_prev: CreateKeyState, formData: FormData): Promise<CreateKeyState> {
  const name = String(formData.get('name') ?? '').trim();
  if (!name || name.length > MAX_NAME) return { key: null, error: `Give the key a name of 1–${MAX_NAME} characters.` };
  try {
    const created = await control<CreatedKey>('/control/keys', { method: 'POST', body: JSON.stringify({ name }) });
    revalidatePath('/keys');
    return { key: created.key, error: null };
  } catch (error) {
    return { key: null, error: error instanceof ControlError ? error.message : 'Could not create the key. Try again.' };
  }
}

export async function revokeKey(id: string): Promise<{ error: string | null }> {
  try {
    await control<void>(`/control/keys/${encodeURIComponent(id)}`, { method: 'DELETE' });
    revalidatePath('/keys');
    return { error: null };
  } catch (error) {
    return { error: error instanceof ControlError ? error.message : 'Could not revoke the key. Try again.' };
  }
}
