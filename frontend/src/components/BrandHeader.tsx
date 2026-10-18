import { ChevronDown, LogOut, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "../auth";

export function BrandHeader() {
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const demoBadge = String(import.meta.env.VITE_DEMO_BADGE_LABEL || "").trim();

  useEffect(() => {
    const close = (event: MouseEvent) => { if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", escape); };
  }, []);

  const initial = (user?.name || user?.email || "R").trim().charAt(0).toUpperCase();
  return (
    <header className="topbar">
      <div className="brand" aria-label="ReviveAI">
        <div className="brand-mark" aria-hidden="true"><Sparkles size={19} strokeWidth={2.2} /></div>
        <div><div className="brand-name">ReviveAI</div><div className="brand-subtitle">Creator Workspace</div></div>
      </div>
      <div className="topbar-actions">
        {demoBadge && <div className="milestone-pill">{demoBadge}</div>}
        {user && (
          <div className="account-menu" ref={rootRef}>
            <button className="account-chip" type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
              {user.picture ? <img src={user.picture} alt="" referrerPolicy="no-referrer" /> : <span>{initial}</span>}
              <div><strong>{user.name || "Creator"}</strong><small>{user.email || "Signed in"}</small></div>
              <ChevronDown size={15} className={open ? "open" : ""} />
            </button>
            {open && (
              <div className="account-popover glass-card" role="menu">
                <div className="account-popover-user">
                  <ShieldCheck size={17} />
                  <div><strong>Private creator workspace</strong><small>{user.email || user.name}</small></div>
                </div>
                <div className="account-popover-meta"><span>Sign-in method</span><strong>{user.provider === "google.com" ? "Google" : user.provider === "password" ? "Email & password" : user.provider || "Firebase"}</strong></div>
                <button type="button" role="menuitem" onClick={() => { setOpen(false); void signOut(); }}><LogOut size={16} /> Sign out</button>
              </div>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
