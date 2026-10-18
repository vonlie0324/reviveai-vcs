import {
  ArrowRight,
  Check,
  FolderKanban,
  Plus,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { API_BASE_URL, apiFetch } from "../http";
import type { ReviveWorkspace, WorkspaceChannel, WorkspaceProduction } from "../workspace";
import { formatRelativeWorkspaceTime } from "../workspace";

interface WorkspaceDashboardProps {
  displayName?: string | null; // Retained for App.tsx compatibility; not shown in compact header.
  workspace: ReviveWorkspace;
  onAddChannel: () => void;
  onOpenChannel: (channel: WorkspaceChannel) => void;
  onOpenProduction: (channel: WorkspaceChannel, production: WorkspaceProduction) => void;
  onManageChannels: () => void;
}

type Publication = {
  publication_id: string;
  production_job_id?: string | null;
  media_job_id?: string | null;
  assembly_job_id?: string | null;
  audio_job_id?: string | null;
  status: string;
  youtube_video_id?: string | null;
  privacy_status?: string | null;
  public_confirmed_at?: string | null;
  published_at?: string | null;
};

function matchesLineage(item: WorkspaceProduction, publication: Publication) {
  const checkpoint = item.checkpoint;
  return Boolean(
    (checkpoint.productionBriefJobId && checkpoint.productionBriefJobId === publication.production_job_id) ||
    (checkpoint.mediaStudioJobId && checkpoint.mediaStudioJobId === publication.media_job_id) ||
    (checkpoint.finalAssemblyJobId && checkpoint.finalAssemblyJobId === publication.assembly_job_id) ||
    (checkpoint.audioFinishingJobId && checkpoint.audioFinishingJobId === publication.audio_job_id)
  );
}

function isVerifiedPublic(publication: Publication) {
  return publication.status === "PUBLISHED" &&
    publication.privacy_status === "public" &&
    Boolean(publication.youtube_video_id);
}

function ChannelAvatar({ channel }: { channel: WorkspaceChannel }) {
  if (channel.thumbnailUrl) {
    return <img className="workspace-channel-avatar" src={channel.thumbnailUrl} alt="" />;
  }
  return <span className="workspace-channel-avatar fallback">{channel.title.slice(0, 1).toUpperCase()}</span>;
}

function isFinalApproved(production: WorkspaceProduction) {
  return production.status === "READY" && /^(final video approved|production complete|production completed)$/i.test(production.stageLabel.trim());
}

function needsFinalReview(production: WorkspaceProduction) {
  return /ready for (your |final |human )?approval|awaiting (your |final |human )?approval|needs (your |final |human )?approval/i.test(production.stageLabel);
}

function isPublishedCheckpoint(production: WorkspaceProduction) {
  return /published|public release/i.test(production.stageLabel);
}

function channelCount(value?: number | null) {
  if (value == null) return "—";
  return new Intl.NumberFormat(undefined, { notation: value >= 10000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(value);
}

export function WorkspaceDashboard({ workspace, onAddChannel, onOpenChannel, onOpenProduction, onManageChannels }: WorkspaceDashboardProps) {
  const [publications, setPublications] = useState<Publication[]>([]);
  const [publicationState, setPublicationState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    const abort = new AbortController();
    setPublicationState("loading");
    apiFetch(`${API_BASE_URL}/api/v1/youtube/publications`, { signal: abort.signal })
      .then(async response => {
        if (!response.ok) throw new Error(`Publication verification failed (${response.status})`);
        const payload: unknown = await response.json();
        if (!Array.isArray(payload)) throw new Error("Invalid publication response");
        if (!abort.signal.aborted) {
          setPublications(payload as Publication[]);
          setPublicationState("ready");
        }
      })
      .catch(() => {
        if (!abort.signal.aborted) {
          setPublications([]);
          setPublicationState("error");
        }
      });
    return () => abort.abort();
  }, []);

  const allProductions = useMemo(() => workspace.channels
    .flatMap((channel) => channel.productions.map((production) => ({ channel, production })))
    .sort((a, b) => b.production.updatedAt.localeCompare(a.production.updatedAt))
    .filter((item, index, all) => {
      const key = `${item.channel.channelId}:${item.production.title.trim().toLowerCase()}`;
      return all.findIndex((candidate) => `${candidate.channel.channelId}:${candidate.production.title.trim().toLowerCase()}` === key) === index;
    }), [workspace.channels]);

  // Final approvals are terminal for work-queue purposes, regardless of historical QC findings.
  // Cached checkpoints are only a navigation aid, not proof of live backend state.
  // Approved and public items are excluded from the attention queue.
  const actionableProductions = useMemo(() => allProductions
     .filter(({ production }) => {
      if (publicationState === "ready" && publications.some(publication =>
        matchesLineage(production, publication) && isVerifiedPublic(publication)
      )) return false;
      return !isFinalApproved(production) && !isPublishedCheckpoint(production) &&
        (needsFinalReview(production) || production.status !== "READY");
    })
    .sort((a, b) => {
      const priority = (p: WorkspaceProduction) => p.status === "BLOCKED" ? 0 : (p.status === "REVIEW" || needsFinalReview(p)) ? 1 : 2;
      return priority(a.production) - priority(b.production) || b.production.updatedAt.localeCompare(a.production.updatedAt);
    }), [allProductions, publications, publicationState]);

  return (
    <section className="workspace-dashboard" aria-label="ReviveAI workspace">
      <div className="workspace-section-heading channels-heading" style={{ marginTop: 0, alignItems: "center" }}>
        <div>
          <span className="eyebrow">ReviveAI workspace</span>
          <h1 style={{ margin: "4px 0", fontSize: "clamp(23px, 2.5vw, 30px)" }}>Your channels</h1>
          <p style={{ margin: 0, opacity: .72 }}>Choose a channel to view its content and performance.</p>
        </div>
        <button className="secondary-button" type="button" onClick={onManageChannels}>
          Manage channels
        </button>
      </div>

      <div className="workspace-channel-grid">
        {workspace.channels
          .slice()
          .sort((a, b) => b.lastOpenedAt.localeCompare(a.lastOpenedAt))
          .map((channel, index) => (
            <button
              key={channel.channelId}
              className={`workspace-channel-card glass-card entry-surface entry-card-${Math.min(index + 2, 7)}`}
              type="button"
              onClick={() => onOpenChannel(channel)}
              aria-label={`Open ${channel.title} workspace`}
              style={{ display: "block", width: "100%", textAlign: "left", color: "inherit", cursor: "pointer", padding: 0 }}
            >
              <div className="workspace-channel-main">
                <ChannelAvatar channel={channel} />
                <span className="workspace-channel-copy">
                  <small>Channel</small>
                  <strong>{channel.title}</strong>
                  <span>{channel.handle || "YouTube channel"}</span>
                </span>
              </div>
              <div className="workspace-channel-stats" aria-label="Saved channel evidence">
                <span><b>{channelCount(channel.subscriberCount)}</b><small>Subscribers</small></span>
                <span><b>{channelCount(channel.publicVideoCount)}</b><small>Public videos</small></span>
                <span><b>{channel.productions.length}</b><small>Productions</small></span>
              </div>
              <div style={{ padding: "1px 14px 10px", fontSize: 12, opacity: .68 }}>
                Updated {formatRelativeWorkspaceTime(channel.updatedAt)}
              </div>
              <div className="workspace-channel-intelligence" style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 5 }}>
                Open workspace <ArrowRight size={14} aria-hidden="true" />
              </div>
            </button>
          ))}
        <button className="workspace-channel-card add-card entry-surface" type="button" onClick={onAddChannel}>
          <span><Plus size={18} aria-hidden="true" /></span>
          <strong>Add channel</strong>
          <small>Analyze another YouTube channel and keep its productions separate.</small>
        </button>
      </div>

      <div className="workspace-section-heading" style={{ marginTop: 22 }}>
        <div>
          <span className="eyebrow">Action required</span>
          <h2>Continue working</h2>
          <p style={{ marginTop: 4, opacity: .72 }}>Unfinished saved productions, checked against known YouTube publication records.</p>
        </div>
        <span>{Math.min(3, actionableProductions.length)} priority items shown · {actionableProductions.length} saved candidates</span>
      </div>

      {publicationState !== "ready" && (
        <p role="status" style={{ margin: "0 0 10px", fontSize: 12, color: publicationState === "error" ? "#f4c58c" : "#b4bce2" }}>
          {publicationState === "loading"
            ? "Verifying existing publication records…"
            : "Publication verification unavailable. Showing saved checkpoints; published items may still appear."}
        </p>
      )}

      {actionableProductions.length > 0 ? (
        <div className="glass-card" style={{ padding: "6px 16px", borderRadius: 15 }}>
          {actionableProductions.slice(0, 3).map(({ channel, production }, index) => {
            const label = production.status === "BLOCKED" ? "Needs attention" : (production.status === "REVIEW" || needsFinalReview(production)) ? "Needs review" : "In progress";
            const action = production.status === "BLOCKED" ? "Resolve issue" : (production.status === "REVIEW" || needsFinalReview(production)) ? "Review" : "Continue";
            return (
              <button
                key={`${channel.channelId}:${production.id}`}
                type="button"
                onClick={() => onOpenProduction(channel, production)}
                style={{ display: "flex", alignItems: "center", gap: 12, width: "100%", padding: "14px 2px", background: "transparent", border: "none", color: "inherit", textAlign: "left", borderBottom: index < Math.min(actionableProductions.length, 3) - 1 ? "1px solid rgba(142,151,192,.18)" : "none", cursor: "pointer" }}
              >
                <span style={{ width: 34, height: 34, display: "grid", placeItems: "center", borderRadius: 9, background: "rgba(138,121,246,.12)", flexShrink: 0 }}><FolderKanban size={17} aria-hidden="true" /></span>
                <span style={{ flex: 1, minWidth: 0, display: "grid", gap: 3 }}>
                  <strong style={{ fontSize: 14 }}>{production.title}</strong>
                  <small style={{ opacity: .72 }}>{channel.title} · {label} · Saved checkpoint: {production.stageLabel}</small>
                </span>
                <span style={{ fontSize: 12, fontWeight: 700, whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: 5 }}>{action} <ArrowRight size={15} aria-hidden="true" /></span>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="glass-card" style={{ padding: "18px 20px", display: "flex", alignItems: "center", gap: 10 }}>
          <Check size={19} aria-hidden="true" />
          <span>No unfinished productions in saved checkpoints. Open a channel to create or inspect content.</span>
        </div>
      )}
      <p style={{ textAlign: "right", margin: "10px 0 0", fontSize: 12, opacity: .75 }}>
        To browse completed work and full history, open a channel and select <strong>Productions</strong>.
      </p>

    </section>
  );
}
