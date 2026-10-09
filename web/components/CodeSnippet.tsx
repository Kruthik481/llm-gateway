import { cardClass } from '@/lib/styles';

export function CodeSnippet({ apiUrl }: { apiUrl: string }) {
  const code = `from openai import OpenAI

client = OpenAI(base_url="${apiUrl}/v1", api_key="lgw_...")
stream = client.chat.completions.create(
    model="llama-3.3-70b",
    messages=[{"role": "user", "content": "Explain rate limiting in one line."}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")`;
  return (
    <pre className={`${cardClass} mt-8 overflow-x-auto font-mono text-xs leading-relaxed`}>
      <code>{code}</code>
    </pre>
  );
}
