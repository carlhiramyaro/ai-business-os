"use client";

import { AuthenticateWithRedirectCallback } from "@clerk/nextjs";

// Google OAuth's redirect target (see app/login/page.tsx's signIn.sso()/
// signUp.sso() calls). This component reads Clerk's callback params and
// completes the sign-in/sign-up -- but its own redirect afterward is
// controlled ONLY by these props, not by the redirectUrl passed to sso()
// (that's a separate Future-hooks API this classic component doesn't read
// from). Without them it falls back to Clerk's own default ("/"), landing
// signed-in users on the marketing page instead of the app.
export default function SsoCallbackPage() {
  return <AuthenticateWithRedirectCallback signInForceRedirectUrl="/entry" signUpForceRedirectUrl="/entry" />;
}
