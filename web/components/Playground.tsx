'use client';

import { useRef, useState } from 'react';
import { formatMs, formatUsd } from '@/lib/format';
import { MODELS } from '@/lib/models';
import { GatewayRequestError, runChat } from '@/lib/playground';
import { PLAYGROUND_KEY } from '@/lib/playground-key';
import { buttonPrimary, buttonSecondary, cardClass, inputClass } from '@/lib/styles';
import type { GatewayMeta } from '@/lib/types';

function readStoredKey(): string {
  try {
    return sessionStorage.getItem(PLAYGROUND_KEY) ?? '';
  } catch {
    return ''; // storage blocked: the user pastes the key
  }
}

function storeKey(key: string) {
  try {
    sessionStorage.setItem(PLAYGROUND_KEY, key);
  } catch {
    // storage blocked: the key lives only in this page's state
  }
}

function MetaStrip({ meta }: { meta: GatewayMeta }) {
  const parts = [
    meta.provider,
    `cache ${meta.cache}`,
    `${meta.attempts} attempt${meta.attempts === 1 ? '' : 's'}`,
    meta.cache === 'hit' ? `saved ${formatUsd(meta.saved_usd)}` : `${formatUsd(meta.cost_usd)} list price`,
    `TTFT ${formatMs(meta.ttft_ms)}`,
  ];
  return (
    <p data-testid="meta" className="mt-3 font-mono text-xs text-muted">
      {parts.join(' · ')}
    </p>
  );
}

export function Playground({ apiUrl }: { apiUrl: string }) {
  // Rendered client-only (see PlaygroundClient), so sessionStorage is safe to read here.
  const [apiKey, setApiKey] = useState(readStoredKey);
  const [model, setModel] = useState<string>(MODELS[0]);
  const [temperature, setTemperature] = useState(0.7);
  const [stream, setStream] = useState(true);
  const [simulateOutage, setSimulateOutage] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [output, setOutput] = useState('');
  const [meta, setMeta] = useState<GatewayMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setOutput('');
    setMeta(null);
    setError(null);
    try {
      const result = await runChat(
        { apiUrl, apiKey, model, temperature, stream, prompt, simulateOutage },
        setOutput,
        controller.signal,
      );
      setMeta(result.meta);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof GatewayRequestError ? `${err.code}: ${err.message}` : 'Could not reach the gateway.');
    } finally {
      setRunning(false);
    }
  }

  return (
    <form onSubmit={send} className="mt-6 grid gap-4">
      <label className="text-sm">
        <span className="text-muted">API key</span>
        <input
          value={apiKey}
          onChange={(e) => {
            setApiKey(e.target.value);
            storeKey(e.target.value);
          }}
          placeholder="lgw_…"
          autoComplete="off"
          className={`${inputClass} font-mono`}
          required
        />
      </label>
      <div className="grid gap-4 sm:grid-cols-3">
        <label className="text-sm">
          <span className="text-muted">Model</span>
          <select value={model} onChange={(e) => setModel(e.target.value)} className={inputClass}>
            {MODELS.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="text-muted">
            Temperature {temperature.toFixed(1)} {temperature === 0 && '(cached)'}
          </span>
          <input
            type="range"
            min={0}
            max={2}
            step={0.1}
            value={temperature}
            onChange={(e) => setTemperature(Number(e.target.value))}
            className="mt-3 w-full accent-[var(--accent)]"
          />
        </label>
        <div className="flex flex-col justify-end gap-2 text-sm">
          <label className="inline-flex items-center gap-2">
            <input type="checkbox" checked={stream} onChange={(e) => setStream(e.target.checked)} /> Stream
          </label>
          <label className="inline-flex items-center gap-2">
            <input type="checkbox" checked={simulateOutage} onChange={(e) => setSimulateOutage(e.target.checked)} />
            Simulate Cerebras outage
          </label>
        </div>
      </div>
      <label className="text-sm">
        <span className="text-muted">Prompt</span>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={4}
          required
          className={inputClass}
        />
      </label>
      <div className="flex gap-3">
        <button type="submit" className={buttonPrimary} disabled={isRunning}>
          {isRunning ? 'Running…' : 'Send'}
        </button>
        {isRunning && (
          <button type="button" className={buttonSecondary} onClick={() => abortRef.current?.abort()}>
            Stop
          </button>
        )}
      </div>
      <section aria-label="Answer" className={cardClass}>
        <pre data-testid="output" className="min-h-24 whitespace-pre-wrap font-sans text-sm">
          {output}
        </pre>
        {error && (
          <p role="alert" className="mt-3 text-sm text-danger">
            {error}
          </p>
        )}
        {meta && <MetaStrip meta={meta} />}
      </section>
    </form>
  );
}
