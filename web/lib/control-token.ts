import { SignJWT } from 'jose';

export type ControlUser = { githubId: number; login: string; avatarUrl: string };

export const CONTROL_TOKEN_TTL_S = 300;

export async function mintControlToken(
  user: ControlUser,
  secret: string,
  nowS: number = Math.floor(Date.now() / 1000),
): Promise<string> {
  return new SignJWT({ github_id: user.githubId, login: user.login, avatar_url: user.avatarUrl })
    .setProtectedHeader({ alg: 'HS256' })
    .setIssuedAt(nowS)
    .setExpirationTime(nowS + CONTROL_TOKEN_TTL_S)
    .sign(new TextEncoder().encode(secret));
}
