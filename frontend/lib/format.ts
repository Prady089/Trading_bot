const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });

export const money = (v: number | null | undefined, decimals = false) =>
  v == null ? "–" : (decimals ? inr2 : inr).format(v);

export const signedMoney = (v: number | null | undefined) =>
  v == null ? "–" : `${v > 0 ? "+" : ""}${inr.format(v)}`;

export const pct = (v: number | null | undefined) => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`);

export const num = (v: number | null | undefined, d = 2) => (v == null ? "–" : v.toFixed(d));

export const tone = (v: number | null | undefined) => (v == null || v === 0 ? "" : v > 0 ? "up" : "down");

export const istTime = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
