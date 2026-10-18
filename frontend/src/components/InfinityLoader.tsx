import type { CSSProperties } from "react";

const animation = `@keyframes revive-infinity-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`;
export function InfinityLoader({ label = "Loading", inline = false }: { label?: string; inline?: boolean }) {
  const layout: CSSProperties = { display: "inline-flex", alignItems: "center", gap: 8, verticalAlign: "middle" };
  return <span role="status" aria-label={label} style={layout}>
    <style>{animation}</style>
    <svg width={inline ? 17 : 24} height={inline ? 17 : 24} viewBox="0 0 36 36" aria-hidden="true" style={{ display: "block", animation: "revive-infinity-spin 2.4s linear infinite", flexShrink: 0 }}>
      <path d="M18 18 C12 7 3 9 3 18 C3 27 12 29 18 18 C24 7 33 9 33 18 C33 27 24 29 18 18" stroke="#a78bfa" strokeWidth="3.2" fill="none" strokeLinecap="round" />
    </svg>
    <span>{label}</span>
  </span>;
}
