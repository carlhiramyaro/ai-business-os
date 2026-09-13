import { clerkMiddleware } from "@clerk/nextjs/server";

// Next.js 16 renamed the middleware/proxy file convention to `proxy.ts`
// (middleware.ts still works but is deprecated) -- the exported function
// itself is unaffected. This just needs to run on every request so
// `auth()`/`auth.protect()` are available in Server Components -- the
// actual per-route gating lives in app/(protected)/layout.tsx, not here.
export default clerkMiddleware();

export const config = {
  matcher: [
    "/((?!_next|.*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
