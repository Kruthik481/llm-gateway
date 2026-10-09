import { createServer } from 'node:http';

const PORT = 4900;
const WORDS = ['Hello', ' from', ' the', ' fake', ' model.'];
const usage = { prompt_tokens: 9, completion_tokens: WORDS.length, total_tokens: 9 + WORDS.length };

createServer(async (req, res) => {
  if (req.method === 'GET') {
    res.end('ok');
    return;
  }
  let raw = '';
  for await (const chunk of req) raw += chunk;
  const body = JSON.parse(raw || '{}');
  if (!body.stream) {
    res.setHeader('content-type', 'application/json');
    res.end(
      JSON.stringify({
        choices: [{ index: 0, message: { role: 'assistant', content: WORDS.join('') }, finish_reason: 'stop' }],
        usage,
      }),
    );
    return;
  }
  res.writeHead(200, { 'content-type': 'text/event-stream' });
  const send = (payload) => res.write(`data: ${JSON.stringify(payload)}\n\n`);
  for (const word of WORDS) {
    send({ choices: [{ index: 0, delta: { content: word }, finish_reason: null }] });
    await new Promise((resolve) => setTimeout(resolve, 30));
  }
  send({ choices: [{ index: 0, delta: {}, finish_reason: 'stop' }] });
  send({ choices: [], usage });
  res.end('data: [DONE]\n\n');
}).listen(PORT);
