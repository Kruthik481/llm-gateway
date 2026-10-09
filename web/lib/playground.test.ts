import { afterEach, describe, expect, it, vi } from 'vitest';
import { GatewayRequestError, runChat } from './playground';

const INPUT = {
  apiUrl: 'https://gw.test',
  apiKey: ' lgw_abc ',
  model: 'llama-3.3-70b',
  temperature: 0.7,
  stream: true,
  prompt: 'hi',
  simulateOutage: true,
};

function sseResponse(events: unknown[], headers: Record<string, string> = {}): Response {
  const body = events.map((e) => `data: ${typeof e === 'string' ? e : JSON.stringify(e)}\n\n`).join('');
  return new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream', ...headers } });
}

afterEach(() => vi.unstubAllGlobals());

describe('runChat', () => {
  it('streams text, returns the gateway meta and sends the right request', async () => {
    const meta = { provider: 'openrouter', cache: 'bypass', attempts: 2, cost_usd: '0.0001', saved_usd: '0', ttft_ms: 120 };
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse(
        [
          { choices: [{ delta: { role: 'assistant', content: '' } }] },
          { choices: [{ delta: { content: 'Hel' } }] },
          { choices: [{ delta: { content: 'lo' } }] },
          { choices: [{ delta: {}, finish_reason: 'stop' }], x_gateway: meta },
          '[DONE]',
        ],
        { 'x-request-id': 'req-1' },
      ),
    );
    vi.stubGlobal('fetch', fetchMock);
    const seen: string[] = [];
    const result = await runChat(INPUT, (text) => seen.push(text));
    expect(result).toEqual({ text: 'Hello', meta, requestId: 'req-1' });
    expect(seen).toEqual(['Hel', 'Hello']);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('https://gw.test/v1/chat/completions');
    expect(init.headers).toMatchObject({ authorization: 'Bearer lgw_abc', 'x-gateway-debug-fail': 'cerebras' });
    expect(JSON.parse(init.body)).toMatchObject({ stream: true, stream_options: { include_usage: true } });
  });

  it('throws the gateway error for a failed request', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: { code: 'rate_limited', message: 'Slow down' } }), { status: 429 }),
      ),
    );
    await expect(runChat(INPUT, () => {})).rejects.toEqual(new GatewayRequestError(429, 'rate_limited', 'Slow down'));
  });

  it('throws when the stream carries an error event, after keeping the partial text', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        sseResponse([{ choices: [{ delta: { content: 'Par' } }] }, { error: { code: 'upstream_error', message: 'cut off' } }]),
      ),
    );
    const seen: string[] = [];
    await expect(runChat(INPUT, (t) => seen.push(t))).rejects.toMatchObject({ code: 'upstream_error' });
    expect(seen).toEqual(['Par']);
  });

  it('handles non-streaming answers', async () => {
    const body = { choices: [{ message: { content: 'Hi!' } }], x_gateway: { provider: 'cerebras' } };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200 })));
    const result = await runChat({ ...INPUT, stream: false }, () => {});
    expect(result.text).toBe('Hi!');
    expect(result.meta).toEqual({ provider: 'cerebras' });
  });
});
