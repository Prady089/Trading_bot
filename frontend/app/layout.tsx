import type { Metadata, Viewport } from "next";
import BottomNav from "@/components/BottomNav";
import SwRegister from "@/components/SwRegister";
import TopBar from "@/components/TopBar";
import "./globals.css";
import "./mobile.css";

export const metadata: Metadata = {
  title: "TradeBot",
  description: "Paper trading bot for NSE: AI stock picks, auto and manual simulated trading",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.svg", apple: "/icon.svg" },
  appleWebApp: { capable: true, title: "TradeBot", statusBarStyle: "black-translucent" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0b0f14" },
    { media: "(prefers-color-scheme: light)", color: "#f6f7f9" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <TopBar />
        <main className="container">{children}</main>
        <BottomNav />
        <SwRegister />
      </body>
    </html>
  );
}
