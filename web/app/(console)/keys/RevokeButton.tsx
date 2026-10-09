'use client';

import { useState, useTransition } from 'react';
import { buttonDanger, buttonGhost } from '@/lib/styles';
import { revokeKey } from './actions';

export function RevokeButton({ id, name }: { id: string; name: string }) {
  const [isArmed, setArmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  if (!isArmed) {
    return (
      <button type="button" className={buttonGhost} onClick={() => setArmed(true)}>
        Revoke
      </button>
    );
  }
  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        className={buttonDanger}
        disabled={pending}
        aria-label={`Confirm revoking ${name}`}
        onClick={() =>
          startTransition(async () => {
            const result = await revokeKey(id);
            setError(result.error);
            if (!result.error) setArmed(false);
          })
        }
      >
        {pending ? 'Revoking…' : 'Confirm revoke'}
      </button>
      <button type="button" className={buttonGhost} onClick={() => setArmed(false)}>
        Cancel
      </button>
      {error && (
        <span role="alert" className="text-xs text-danger">
          {error}
        </span>
      )}
    </span>
  );
}
