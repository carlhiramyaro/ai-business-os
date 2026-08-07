"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";

const LINKS = [
  { href: "/entry", label: "Add entry" },
  { href: "/upload", label: "Upload" },
  { href: "/reports", label: "Reports" },
  { href: "/insights", label: "Insights" },
  { href: "/memory", label: "Memory" },
  { href: "/chat", label: "Chat" },
  { href: "/settings", label: "Settings" },
];

export function NavBar() {
  const { user, logout, loading } = useAuth();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [prevPathname, setPrevPathname] = useState(pathname);

  // Close the disclosure panel on navigation -- adjusting state during
  // render (React's recommended pattern for "reset on prop change")
  // rather than in a useEffect, which would call setState synchronously
  // and trigger a cascading re-render. See docs/decisions.md
  // [mobile-first polish].
  if (pathname !== prevPathname) {
    setPrevPathname(pathname);
    setOpen(false);
  }

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-surface">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3 sm:px-6 sm:py-4">
        <Link href="/" className="text-lg font-semibold tracking-tight text-foreground">
          Ledger
        </Link>

        <nav className="hidden items-center gap-6 text-sm md:flex">
          {user &&
            LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                aria-current={pathname === link.href ? "page" : undefined}
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
              <Link
                href="/login"
                className="inline-flex min-h-11 items-center justify-center rounded-md bg-brand px-3 font-medium text-brand-foreground hover:bg-brand-hover"
              >
                Log in
              </Link>
            ))}
        </nav>

        {/* Logged-out mobile view has no hamburger -- just the same Log in
            link the desktop nav shows, kept inline. */}
        {!loading && !user && (
          <Link
            href="/login"
            className="inline-flex min-h-11 items-center justify-center rounded-md bg-brand px-3 font-medium text-brand-foreground hover:bg-brand-hover md:hidden"
          >
            Log in
          </Link>
        )}

        {user && (
          <button
            type="button"
            onClick={() => setOpen((prev) => !prev)}
            aria-expanded={open}
            aria-controls="mobile-nav-panel"
            aria-label={open ? "Close menu" : "Open menu"}
            className="flex min-h-11 min-w-11 items-center justify-center rounded-md text-foreground md:hidden"
          >
            {open ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-6 w-6">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-6 w-6">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            )}
          </button>
        )}
      </div>

      {open && user && (
        <nav id="mobile-nav-panel" className="border-t border-border md:hidden">
          <div className="flex flex-col">
            {LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                aria-current={pathname === link.href ? "page" : undefined}
                className={`block px-4 py-3 text-base ${
                  pathname === link.href ? "font-medium text-foreground" : "text-muted"
                }`}
              >
                {link.label}
              </Link>
            ))}
            <div className="border-t border-border px-4 py-3 text-sm text-muted">{user.email}</div>
            <button
              onClick={logout}
              className="block w-full px-4 py-3 text-left text-base text-muted hover:text-foreground"
            >
              Log out
            </button>
          </div>
        </nav>
      )}
    </header>
  );
}
