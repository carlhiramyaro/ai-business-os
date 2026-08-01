import { InputHTMLAttributes } from "react";

export function Input({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      // text-base (16px), not text-sm (14px): anything under 16px
      // triggers iOS Safari's auto-zoom-on-focus. Fixing the font size is
      // the correct fix -- disabling zoom via a maximumScale/userScalable
      // viewport setting is the lazy alternative and a WCAG 1.4.4
      // failure. See docs/decisions.md [mobile-first polish].
      className={`rounded-md border border-border bg-surface px-3 py-2.5 text-base text-foreground placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-brand/40 ${className}`}
      {...props}
    />
  );
}
