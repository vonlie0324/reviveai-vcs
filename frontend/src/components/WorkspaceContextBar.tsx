import { BarChart3, ChevronDown, FolderKanban, Home, Plus, Settings2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ReviveWorkspace, WorkspaceChannel } from "../workspace";

interface WorkspaceContextBarProps {
  workspace: ReviveWorkspace;
  channel: WorkspaceChannel;
  productionTitle?: string | null;
  onHome: () => void;
  onSwitchChannel: (channel: WorkspaceChannel) => void;
  onAddChannel: () => void;
  onChannelHome: () => void;
  onOpenChannelSettings?: () => void;
}

export function WorkspaceContextBar({ workspace, channel, productionTitle, onHome, onSwitchChannel, onAddChannel, onChannelHome, onOpenChannelSettings }: WorkspaceContextBarProps) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="workspace-context-bar glass-card">
      <button className="context-home" type="button" onClick={onHome} aria-label="Workspace home"><Home size={16} /></button>
      <span className="context-divider">/</span>
      <div className="context-channel-wrap" ref={wrapRef}>
        <button className="context-channel" type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-haspopup="menu">
          {channel.thumbnailUrl ? <img src={channel.thumbnailUrl} alt="" /> : <span className="context-avatar-fallback">{channel.title.slice(0, 1)}</span>}
          <span><strong>{channel.title}</strong><small>{channel.handle || "YouTube channel"}</small></span>
          <ChevronDown size={15} className={open ? "context-chevron open" : "context-chevron"} />
        </button>
        {open && (
          <div className="context-channel-menu" role="menu" aria-label="Switch YouTube channel">
            <small>Switch channel</small>
            {workspace.channels.map((item) => (
              <button key={item.channelId} type="button" role="menuitem" className={item.channelId === channel.channelId ? "active" : ""} onClick={() => { setOpen(false); onSwitchChannel(item); }}>
                {item.thumbnailUrl ? <img src={item.thumbnailUrl} alt="" /> : <span className="context-avatar-fallback">{item.title.slice(0, 1)}</span>}
                <span><strong>{item.title}</strong><small>{item.productions.length} productions</small></span>
              </button>
            ))}
            <button type="button" role="menuitem" className="context-add-channel" onClick={() => { setOpen(false); onAddChannel(); }}><Plus size={15} /> Add YouTube channel</button>
          </div>
        )}
      </div>
      {productionTitle ? (
        <>
          <span className="context-divider">/</span>
          <button className="context-production" type="button" onClick={onChannelHome}><FolderKanban size={15} /><strong>{productionTitle}</strong></button>
        </>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
          <button className="context-intelligence" type="button" onClick={onChannelHome}><BarChart3 size={15} /> Channel workspace</button>
          {onOpenChannelSettings ? (
            <button
              type="button"
              onClick={onOpenChannelSettings}
              aria-label="Open channel autonomy settings"
              title="Channel autonomy settings"
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: 38,
                height: 38,
                borderRadius: 12,
                border: "1px solid rgba(162,171,220,.26)",
                background: "rgba(18,24,45,.88)",
                color: "#e7ecff",
                cursor: "pointer",
                boxShadow: "0 10px 24px rgba(0,0,0,.22)",
              }}
            >
              <Settings2 size={16} />
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
}
