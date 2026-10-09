import { describe, expect, it } from 'vitest';
import { readSSE } from './sse';

function streamOf(...parts: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(encoder.encode(part));
      controller.close();
    },
  });
}

describe('readSSE', () => {
  it('yields each data payload, even when events are split across chunks', async () => {
    const out: string[] = [];
    for await (const data of readSSE(streamOf('data: {"a":1}\n\nda', 'ta: {"b":2}\n', '\ndata: [DONE]\n\n'))) {
      out.push(data);
    }
    expect(out).toEqual(['{"a":1}', '{"b":2}', '[DONE]']);
  });

  it('ignores comments and blank events', async () => {
    const out: string[] = [];
    for await (const data of readSSE(streamOf(': keep-alive\n\n\n\ndata: x\n\n'))) out.push(data);
    expect(out).toEqual(['x']);
  });
});
