"use client";

import { useCallback, useEffect, useState } from "react";

export function useToast() {
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(id);
  }, [toast]);
  const show = useCallback((msg: string, ok = true) => setToast({ msg, ok }), []);
  const node = toast ? (
    <div className={`toast ${toast.ok ? "ok" : "bad"}`} role="status" onClick={() => setToast(null)}>{toast.msg}</div>
  ) : null;
  return { show, node };
}
