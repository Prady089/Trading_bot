"use client";

import type { Status } from "@/lib/api";
import { usePoll } from "@/lib/hooks";

export default function TopBar() {
  const { data } = usePoll<Status>("/api/status", 30_000);
  return (
    <header className="topbar">
      <div className="brand">
        <svg viewBox="0 0 512 512" width="22" height="22" aria-hidden>
          <polyline points="96,352 192,256 264,304 416,152" fill="none" stroke="currentColor" strokeWidth="48" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        TradeBot <span className="tag">PAPER</span>
      </div>
      <div className="status-chips">
        {data && (
          <>
            {data.auto_enabled && <span className="chip on">Auto ON</span>}
            {data.futures_auto_enabled && <span className="chip on">Auto FUT</span>}
            <span className={`chip ${data.market_open ? "on" : ""}`}>
              {data.market_open ? "● NSE open" : "NSE closed"}
            </span>
          </>
        )}
      </div>
    </header>
  );
}
