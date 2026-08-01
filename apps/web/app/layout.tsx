import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";
import { NavBar } from "@/components/NavBar";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Ledger — AI Business Analyst",
  description: "Upload your business data and get an AI-generated Business Health Report you can chat with.",
};

// Deliberately NOT set: maximumScale/userScalable (the lazy fix for iOS
// auto-zoom is a WCAG 1.4.4 failure -- Input/Select's 16px font size is
// the real fix, see components/ui/Input.tsx) or viewportFit: "cover"
// (nothing is pinned to a screen edge, so opting into the notch-safe-area
// layout would only risk content sliding under it for no benefit). See
// docs/decisions.md [mobile-first polish].
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0f766e", // matches --brand in app/globals.css
  colorScheme: "light", // no dark-mode CSS exists yet; stops Android's forced dark mode from auto-inverting the palette
  interactiveWidget: "resizes-content", // keeps the chat composer above the on-screen keyboard on Android
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <AuthProvider>
          <NavBar />
          <main className="flex flex-1 flex-col">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
