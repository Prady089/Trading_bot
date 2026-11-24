"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const icon = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  trading: "M3 17l5-5 4 4 8-8M15 8h5v5",
  strategies: "M12 3 4 7l8 4 8-4-8-4zM4 12l8 4 8-4M4 17l8 4 8-4",
  portfolio: "M4 7h16a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1zm4 0V5a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M3 13h18",
  settings:
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm7.4-3a7.4 7.4 0 0 0-.1-1.3l2-1.6-2-3.4-2.4 1a7.6 7.6 0 0 0-2.2-1.3L14.3 3h-4l-.4 2.4a7.6 7.6 0 0 0-2.2 1.3l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.6l-2 1.6 2 3.4 2.4-1a7.6 7.6 0 0 0 2.2 1.3l.4 2.4h4l.4-2.4a7.6 7.6 0 0 0 2.2-1.3l2.4 1 2-3.4-2-1.6c.1-.4.1-.9.1-1.3z",
};

const TABS = [
  { href: "/", label: "Home", d: icon.home, match: (p: string) => p === "/" },
  { href: "/trading", label: "Trading", d: icon.trading, match: (p: string) => p.startsWith("/trading") },
  {
    href: "/strategies", label: "Strategies", d: icon.strategies,
    match: (p: string) => ["/strategies", "/backtest", "/runs"].some((x) => p.startsWith(x)),
  },
  { href: "/portfolio", label: "Portfolio", d: icon.portfolio, match: (p: string) => p.startsWith("/portfolio") },
  {
    href: "/settings", label: "Settings", d: icon.settings,
    match: (p: string) => p.startsWith("/settings"),
  },
];

export default function BottomNav() {
  const path = usePathname();
  return (
    <nav className="tabbar" aria-label="Main">
      <div className="tabbar-inner">
        {TABS.map((t) => {
          const active = t.match(path);
          return (
            <Link key={t.href} href={t.href} className={`tab ${active ? "active" : ""}`} aria-current={active ? "page" : undefined}>
              <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden>
                <path d={t.d} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span>{t.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
