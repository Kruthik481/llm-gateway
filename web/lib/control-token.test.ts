import { jwtVerify } from 'jose';
import { describe, expect, it } from 'vitest';
import { CONTROL_TOKEN_TTL_S, mintControlToken } from './control-token';

const SECRET = 'test-control-secret-0123456789abcdef';

describe('mintControlToken', () => {
  it('signs the claims the API requires with a five minute lifetime', async () => {
    const token = await mintControlToken({ githubId: 7, login: 'ana', avatarUrl: 'https://a/7.png' }, SECRET, 1_000);
    const { payload, protectedHeader } = await jwtVerify(token, new TextEncoder().encode(SECRET), {
      currentDate: new Date(1_000_000),
    });
    expect(protectedHeader.alg).toBe('HS256');
    expect(payload).toMatchObject({ github_id: 7, login: 'ana', avatar_url: 'https://a/7.png', iat: 1_000 });
    expect(payload.exp! - payload.iat!).toBe(CONTROL_TOKEN_TTL_S);
  });
});
