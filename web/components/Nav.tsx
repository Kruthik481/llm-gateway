import Link from 'next/link';
import { auth, signOut } from '@/auth';
import { buttonGhost } from '@/lib/styles';

const LINKS = [
  { href: '/keys', label: 'Keys' },
  { href: '/usage', label: 'Usage' },
  { href: '/playground', label: 'Playground' },
];

export async function Nav() {
  const session = await auth();
  return (
    <header className="border-b border-line">
      <nav aria-label="Main" className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-3 text-sm">
        <Link href="/" className="font-semibold">
          LLM Gateway
        </Link>
        {session?.user && (
          <>
            {LINKS.map((link) => (
              <Link key={link.href} href={link.href} className="text-muted hover:text-fg">
                {link.label}
              </Link>
            ))}
            <span className="ml-auto text-muted">{session.user.login}</span>
            <form
              action={async () => {
                'use server';
                await signOut({ redirectTo: '/' });
              }}
            >
              <button type="submit" className={buttonGhost}>
                Sign out
              </button>
            </form>
          </>
        )}
      </nav>
    </header>
  );
}
