import { auth } from "@clerk/nextjs/server";

// Gates every route in this group behind Clerk. auth.protect() redirects an
// unauthenticated request to sign-in server-side, before any client JS for
// the page ships -- replacing the seven copies of a client-side
// "if (!accessToken) return <Please log in>" guard that used to live in
// each of these pages. See docs/decisions.md's Clerk-migration entry.
export default async function ProtectedLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  await auth.protect();
  return children;
}
