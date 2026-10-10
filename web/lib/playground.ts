import { readSSE } from './sse';
import type { GatewayMeta } from './types';

export type ChatInput = {
  apiUrl: string;
  apiKey: string;
  model: string;
  temperature: number;
  stream: boolean;
  prompt: string;
  simulateOutage: boolean;
};

export type ChatResult = { text: string; meta: GatewayMeta | null; requestId: string | null };

export class GatewayRequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

type ErrorBody = { error?: { code?: string; message?: string } } | null;

export async function runChat(
  input: ChatInput,
  onText: (text: string) => void,
  signal?: AbortSignal,
): Promise<ChatResult> {
  const headers: Record<string, string> = {
    authorization: `Bearer ${input.apiKey.trim()}`,
    'content-type': 'application/json',
  };
  if (input.simulateOutage) headers['x-gateway-debug-fail'] = 'groq';
  const res = await fetch(`${input.apiUrl}/v1/chat/completions`, {
    method: 'POST',
    headers,
    signal,
    body: JSON.stringify({
      model: input.model,
      temperature: input.temperature,
      stream: input.stream,
      ...(input.stream ? { stream_options: { include_usage: true } } : {}),
      messages: [{ role: 'user', content: input.prompt }],
    }),
  });
  const requestId = res.headers.get('x-request-id');
  if (!res.ok) {
    const error = ((await res.json().catch(() => null)) as ErrorBody)?.error;
    throw new GatewayRequestError(res.status, error?.code ?? 'error', error?.message ?? `Request failed (${res.status})`);
  }
  if (!input.stream) {
    const body = await res.json();
    const text: string = body.choices?.[0]?.message?.content ?? '';
    onText(text);
    return { text, meta: body.x_gateway ?? null, requestId };
  }
  if (!res.body) throw new GatewayRequestError(502, 'no_body', 'The gateway sent an empty stream.');
  let text = '';
  let meta: GatewayMeta | null = null;
  for await (const data of readSSE(res.body)) {
    if (data === '[DONE]') break;
    const chunk = JSON.parse(data);
    if (chunk.error) throw new GatewayRequestError(502, chunk.error.code ?? 'upstream_error', chunk.error.message);
    const piece: string | undefined = chunk.choices?.[0]?.delta?.content;
    if (piece) {
      text += piece;
      onText(text);
    }
    if (chunk.x_gateway) meta = chunk.x_gateway;
  }
  return { text, meta, requestId };
}
