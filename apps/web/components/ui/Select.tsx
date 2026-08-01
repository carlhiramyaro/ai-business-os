import { SelectHTMLAttributes } from "react";

// Mirrors Input.tsx's classes exactly (16px font, same border/focus
// treatment) -- three call sites previously duplicated an identical
// hand-rolled <select> class string; this dedups them so the 16px
// iOS-zoom fix (see Input.tsx's comment) lands once instead of three
// times. See docs/decisions.md [mobile-first polish].
export function Select({ className = "", ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={`rounded-md border border-border bg-surface px-3 py-2.5 text-base text-foreground focus:outline-none focus:ring-2 focus:ring-brand/40 ${className}`}
      {...props}
    />
  );
}
