import NextAuth from 'next-auth';
import Credentials from 'next-auth/providers/credentials';
import GitHub from 'next-auth/providers/github';

const isE2E = process.env.E2E === '1';

// Test-only sign-in: E2E runs cannot log in to real GitHub. Never enabled unless E2E=1.
const e2eProvider = Credentials({
  id: 'e2e',
  name: 'E2E',
  credentials: { login: { label: 'Login' } },
  authorize: async (credentials) => ({ id: '424242', name: String(credentials?.login || 'e2e-user'), image: '' }),
});

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [GitHub, ...(isE2E ? [e2eProvider] : [])],
  callbacks: {
    jwt({ token, account, profile, user }) {
      if (account?.provider === 'github' && profile) {
        token.githubId = Number(profile.id);
        token.login = String(profile.login);
        token.avatarUrl = String(profile.avatar_url ?? '');
      }
      if (account?.provider === 'e2e' && user) {
        token.githubId = Number(user.id);
        token.login = user.name ?? 'e2e-user';
        token.avatarUrl = '';
      }
      return token;
    },
    session({ session, token }) {
      session.user.githubId = token.githubId ?? 0;
      session.user.login = token.login ?? '';
      session.user.avatarUrl = token.avatarUrl ?? '';
      return session;
    },
  },
});
