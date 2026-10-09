'use client';

import Link from 'next/link';
import { useActionState, useState } from 'react';
import { PLAYGROUND_KEY } from '@/lib/playground-key';
import { buttonPrimary, buttonSecondary, cardClass, inputClass } from '@/lib/styles';
import { type CreateKeyState, createKey } from './actions';

const initialState: CreateKeyState = { key: null, error: null };

function rememberForPlayground(key: string) {
  try {
    sessionStorage.setItem(PLAYGROUND_KEY, key);
  } catch {
    // storage blocked (private mode): the playground asks for the key instead
  }
}

export function CreateKeyForm({ canCreate }: { canCreate: boolean }) {
  const [state, action, pending] = useActionState(createKey, initialState);
  const [copied, setCopied] = useState(false);
  const newKey = state.key;

  async function copy(key: string) {
    try {
      await navigator.clipboard.writeText(key);
      setCopied(true);
    } catch {
      setCopied(false); // clipboard denied: the key stays visible to copy by hand
    }
  }

  return (
    <section className={`${cardClass} mt-6`}>
      <form action={action} className="flex items-end gap-3">
        <label className="flex-1 text-sm">
          <span className="text-muted">Key name</span>
          <input
            name="name"
            required
            maxLength={40}
            placeholder="laptop"
            className={inputClass}
            disabled={!canCreate || pending}
          />
        </label>
        <button type="submit" className={buttonPrimary} disabled={!canCreate || pending}>
          {pending ? 'Creating…' : 'Create key'}
        </button>
      </form>
      {!canCreate && <p className="mt-2 text-sm text-warn">You have 3 active keys. Revoke one to create another.</p>}
      {state.error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {state.error}
        </p>
      )}
      {newKey && (
        <div className="mt-4 rounded-md border border-ok/40 bg-bg p-3">
          <p className="text-sm">Copy this key now. It will not be shown again.</p>
          <code data-testid="new-key" className="mt-2 block break-all font-mono text-sm">
            {newKey}
          </code>
          <div className="mt-3 flex gap-3">
            <button type="button" className={buttonSecondary} onClick={() => copy(newKey)}>
              {copied ? 'Copied' : 'Copy'}
            </button>
            <Link href="/playground" className={buttonSecondary} onClick={() => rememberForPlayground(newKey)}>
              Try it in the playground
            </Link>
          </div>
        </div>
      )}
    </section>
  );
}
