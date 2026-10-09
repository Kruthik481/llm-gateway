import { redirect } from 'next/navigation';
import { auth } from '@/auth';

export default async function ConsoleLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  if (!session?.user?.githubId) redirect('/');
  return children;
}
