"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

const LINKS = [
  { href: "/entry", label: "Add entry" },
  { href: "/upload", label: "Upload" },
  { href: "/reports", label: "Reports" },
  { href: "/chat", label: "Chat" },
];

export function NavBar() {
  const { user, logout, loading } = useAuth();
  const pathname = usePathname();

  return (
    <header className="border-b border-border bg-surface">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <Link href="/" className="text-lg font-semibold tracking-tight text-foreground">
          Ledger
        </Link>

        <nav className="flex items-center gap-6 text-sm">
          {user &&
            LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={
                  pathname === link.href
                    ? "font-medium text-foreground"
                    : "text-muted transition-colors hover:text-foreground"
                }
              >
                {link.label}
              </Link>
            ))}

          {!loading &&
            (user ? (
              <div className="flex items-center gap-3">
                <span className="text-muted">{user.email}</span>
                <button onClick={logout} className="text-muted underline hover:text-foreground">
                  Log out
                </button>
              </div>
            ) : (
              <Link href="/login" className="rounded-md bg-brand px-3 py-1.5 font-medium text-brand-foreground hover:bg-brand-hover">
                Log in
              </Link>
            ))}
        </nav>
      </div>
    </header>
  );
}
