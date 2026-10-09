'use client';

import dynamic from 'next/dynamic';

// The playground reads the key from sessionStorage, which only exists in the browser.
export const PlaygroundClient = dynamic(() => import('./Playground').then((m) => m.Playground), {
  ssr: false,
  loading: () => <p className="mt-6 text-sm text-muted">Loading playground…</p>,
});
