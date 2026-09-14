import { clerkMiddleware } from "@clerk/nextjs/server";

// Next.js 16 renamed the middleware/proxy file convention to `proxy.ts`
// (middleware.ts still works but is deprecated) -- the exported function
// itself is unaffected. This just needs to run on every request so
// `auth()`/`auth.protect()` are available in Server Components -- the
// actual per-route gating lives in app/(protected)/layout.tsx, not here.
//
// authorizedParties: with a Production instance's Frontend API on our own
// root domain (clerk.iamledger.app), Clerk's FAPI accepts cross-origin
// requests from any subdomain of iamledger.app by default -- an allowlist
// closes that, protecting against subdomain-cookie-leak/CSRF per Clerk's
// production deployment guide. See docs/decisions.md.
export default clerkMiddleware({
  authorizedParties: ["https://app.iamledger.app"],
});

export const config = {
  matcher: [
    "/((?!_next|.*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
