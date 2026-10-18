import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, BarChart3, CalendarClock, CheckCircle2, CircleAlert, ExternalLink, FolderKanban, RefreshCw, Youtube, Activity, Clock3, ShieldAlert, Clapperboard, ImageIcon, PlayCircle } from "lucide-react";
import { getProductionBriefJob, getMediaStudioJob, mediaAssetUrl, getYouTubeAutonomySnapshot, getYouTubePublication, listYouTubePublications } from "../api";
import type { AutonomousActivityEvent, MediaStudioJob, YouTubeAutonomySnapshot, YouTubePerformanceSnapshot, YouTubePublication } from "../types";
import type { WorkspaceChannel, WorkspaceProduction } from "../workspace";
import { getUniqueWorkspaceProductions } from "../workspace";

type Tab = "autonomy" | "productions" | "intelligence" | "directions";
interface Props {
  channel: WorkspaceChannel;
  programId?: string | null;
  autopilotStatus: string;
  autopilotMessage: string;
  currentProductionTitle?: string | null;
  currentProductionJobId?: string | null;
  currentMediaJobId?: string | null;
  currentPublicationId?: string | null;
  learningCheckpointRequired?: string | null;
  learningWaitStartedAt?: string | null;
  supervisorHeartbeatAt?: string | null;
  executionOwner?: string | null;
  onOpenTab: (tab: Tab) => void;
  onOpenProduction: (production: WorkspaceProduction) => void;
}
type Ranked = { publication: YouTubePublication; snapshot: YouTubePerformanceSnapshot };
type Verification = "published" | "uploaded" | "no_match" | "unverified";
/** Only server identifiers establish publication lineage; a similar title is never proof. */
function publicationState(publication: YouTubePublication): "published" | "uploaded" | null {
  if (publication.superseded_by_publication_id) return null;
  if (publication.status === "PUBLISHED" || !!publication.public_confirmed_at) return "published";
  if (publication.youtube_video_id) return "uploaded";
  return null;
}

const panel: React.CSSProperties = { background: "#151d33", border: "1px solid #2c3655", borderRadius: 14, padding: 15, minWidth: 0 };
const muted: React.CSSProperties = { color: "#aab7d5", fontSize: 13, margin: 0 };
const smallHeading: React.CSSProperties = { color: "#a79bff", fontSize: 11, letterSpacing: 1.1, textTransform: "uppercase", fontWeight: 800 };
const metric: React.CSSProperties = { color: "#f4f6ff", fontSize: 26, fontWeight: 800, margin: "7px 0 2px" };
const action: React.CSSProperties = { border: "1px solid #4b5482", background: "#252b4d", color: "#edf0ff", borderRadius: 10, padding: "10px 13px", cursor: "pointer", display: "inline-flex", gap: 8, alignItems: "center", justifyContent: "center", fontWeight: 700 };
function titleOf(p: YouTubePublication) { return p.video_title?.trim() || `Video ${p.youtube_video_id || p.publication_id.slice(-8)}`; }
function when(value?: string | null) { if (!value) return "Not scheduled"; const ms = Date.parse(value); return Number.isFinite(ms) ? new Date(ms).toLocaleString() : "Not scheduled"; }
function thumbnail(p: YouTubePublication): string | null { return p.youtube_video_id ? `https://i.ytimg.com/vi/${encodeURIComponent(p.youtube_video_id)}/mqdefault.jpg` : null; }
function YouTubeThumbnail({ publication, style }: { publication: YouTubePublication; style: React.CSSProperties }) {
  const src = thumbnail(publication);
  const [failed, setFailed] = useState(false);
  useEffect(() => { setFailed(false); }, [src]);
  if (!src || failed) {
    return <span aria-label="YouTube thumbnail unavailable" role="img" style={{ ...style, display: "inline-flex", alignItems: "center", justifyContent: "center", background: "#272d49", color: "#aab7d5", flexShrink: 0 }}><ImageIcon size={23} aria-hidden="true" /></span>;
  }
  return <img src={src} alt="YouTube video thumbnail" loading="lazy" onError={() => setFailed(true)} style={style} />;
}
function compact(value: number) { return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value); }

export function ChannelCommandCenter({ channel, programId, autopilotStatus, autopilotMessage, currentProductionTitle, currentProductionJobId, currentMediaJobId, currentPublicationId, learningCheckpointRequired, learningWaitStartedAt, supervisorHeartbeatAt, executionOwner, onOpenTab, onOpenProduction }: Props) {
  const [snapshot, setSnapshot] = useState<YouTubeAutonomySnapshot | null>(null);
  const [ranking, setRanking] = useState<Ranked[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [loadToken, setLoadToken] = useState(0);
  const [publicationVerification, setPublicationVerification] = useState<Record<string, Verification>>({});
  const [verifying, setVerifying] = useState(true);
  const [linkedPublications, setLinkedPublications] = useState<Record<string, YouTubePublication>>({});
  // The supervisor's media job is the only source for a live character preview.
  // Never substitute the latest saved/published production's thumbnail.
  const [activeMedia, setActiveMedia] = useState<MediaStudioJob | null>(null);
  const [mediaLoading, setMediaLoading] = useState(false);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [previewBroken, setPreviewBroken] = useState(false);
  const runningProduction = autopilotStatus === "RUNNING" && Boolean(currentProductionJobId || currentMediaJobId);
  useEffect(() => {
    let cancelled = false;
    let busy = false;
    setActiveMedia(null);
    setPreviewBroken(false);
    setMediaError(null);
    if (!runningProduction || !currentMediaJobId) { setMediaLoading(false); return; }
    setMediaLoading(true);
    const load = async () => {
      if (busy || cancelled || document.hidden) return;
      busy = true;
      try {
        const job = await getMediaStudioJob(currentMediaJobId);
        if (cancelled) return;
        if (currentProductionJobId && job.production_brief_job_id !== currentProductionJobId) {
          setActiveMedia(null);
          setMediaError("The media asset does not belong to the active production.");
        } else if (job.channel_id !== channel.channelId) {
          setActiveMedia(null);
          setMediaError("The media job belongs to another channel.");
        } else {
          setActiveMedia(job);
          setMediaError(null);
        }
      } catch (error) {
        if (!cancelled) setMediaError(error instanceof Error ? error.message : "Character preview unavailable.");
      } finally {
        busy = false;
        if (!cancelled) setMediaLoading(false);
      }
    };
    void load();
    const timer = window.setInterval(() => { void load(); }, 12000);
    const onVisible = () => { if (!document.hidden) void load(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { cancelled = true; window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [runningProduction, currentMediaJobId, currentProductionJobId, channel.channelId]);
  const characterAsset = activeMedia?.result?.reference_asset ?? null;
  const latestKeyframe = activeMedia?.result?.keyframes?.length
    ? [...activeMedia.result.keyframes].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0]
    : null;
  const characterImageUrl = characterAsset?.asset_url ? mediaAssetUrl(characterAsset.asset_url) : null;
  const keyframeImageUrl = latestKeyframe?.asset_url ? mediaAssetUrl(latestKeyframe.asset_url) : null;
  const activeSavedProduction = useMemo(() => currentProductionJobId
    ? getUniqueWorkspaceProductions(channel.productions).find(p =>
        p.checkpoint?.productionBriefJobId === currentProductionJobId || p.id === currentProductionJobId) ?? null
    : null, [channel.productions, currentProductionJobId]);
  const saved = useMemo(() => getUniqueWorkspaceProductions(channel.productions), [channel.productions]);
  const sortedProductions = useMemo(() => [...saved].sort((a, b) => {
    const left = Date.parse(a.updatedAt) || 0;
    const right = Date.parse(b.updatedAt) || 0;
    return right - left;
  }), [saved]);
  // A verified, non-uploaded production takes priority. Otherwise show the latest
  // saved record with its actual verified status (never a fabricated approval request).
  const recentProduction = useMemo(() =>
    sortedProductions.find(p => publicationVerification[p.id] === "no_match" &&
      (p.status === "READY" || p.stage === "DELIVERY" || p.stage === "PUBLISHING")) ??
    sortedProductions[0] ?? null,
    [sortedProductions, publicationVerification]);
  const recentVerification = recentProduction ? publicationVerification[recentProduction.id] : undefined;
  const recentPublication = recentProduction ? linkedPublications[recentProduction.id] : undefined;
  const recentStatus = verifying || !recentVerification || recentVerification === "unverified"
    ? "Publication status not verified"
    : recentVerification === "published" ? "Published on YouTube"
    : recentVerification === "uploaded" ? "Uploaded to YouTube — public status pending"
    : "Not linked to a YouTube upload";
  // Resolve each saved production to its immutable brief/recommendation ID before
  // using any YouTube publication to determine the production's effective status.
  // Do not use titles: published copy can differ from a production's working title.
  useEffect(() => {
    let cancelled = false;
    setVerifying(true);
    setPublicationVerification({});
    setLinkedPublications({});
    const run = async () => {
      const [publicationResult, briefResults] = await Promise.all([
        listYouTubePublications().then(value => ({ value, ok: true as const }), () => ({ value: null, ok: false as const })),
        Promise.allSettled(saved.map(production => {
          const jobId = production.checkpoint?.productionBriefJobId || production.id;
          return getProductionBriefJob(jobId);
        })),
      ]);
      if (cancelled) return;
      const records = publicationResult.value;
      const next: Record<string, Verification> = {};
      const links: Record<string, YouTubePublication> = {};
      saved.forEach((production, index) => {
        const brief = briefResults[index];
        if (!records || brief.status !== "fulfilled" || brief.value.channel_id !== channel.channelId) {
          next[production.id] = "unverified";
          return;
        }
        const recommendationId = brief.value.recommendation_id;
        // Match immutable job lineage first. Production working titles can change
        // before YouTube upload, and a recommendation can be used more than once.
        const cp = production.checkpoint;
        const lineage = [
          ["production_job_id", cp?.productionBriefJobId || production.id],
          ["media_job_id", cp?.mediaStudioJobId],
          ["assembly_job_id", cp?.finalAssemblyJobId],
          ["audio_job_id", cp?.audioFinishingJobId],
        ] as const;
        const idMatches = records.filter(pub => lineage.some(([key, id]) =>
          Boolean(id && pub[key] && pub[key] === id)));
        const strongMatches = idMatches.filter(pub => publicationState(pub) !== null);
        const recommendationMatches = records.filter(pub => pub.recommendation_id === recommendationId);
        const duplicateBrief = briefResults.some((other, otherIndex) => otherIndex !== index &&
          other.status === "fulfilled" && other.value.channel_id === channel.channelId &&
          other.value.recommendation_id === recommendationId &&
          saved[otherIndex].checkpoint?.productionBriefJobId !== cp?.productionBriefJobId);
        // Recommendation-only linkage is safe only if there is one saved brief
        // and precisely one published/uploaded record for that recommendation.
        // Never claim a video is NOT uploaded when linkage evidence is ambiguous.
        const fallback = !duplicateBrief && recommendationMatches.length === 1
          ? recommendationMatches.filter(pub => publicationState(pub) !== null)
          : [];
        const candidates = strongMatches.length ? strongMatches : fallback;
        const matchedPublication = [...candidates].sort((a, b) =>
          (publicationState(a) === "published" ? 1 : 0) -
          (publicationState(b) === "published" ? 1 : 0) ||
          (Date.parse(a.updated_at) || 0) - (Date.parse(b.updated_at) || 0)).slice(-1)[0];
        if (matchedPublication) {
          links[production.id] = matchedPublication;
          next[production.id] = publicationState(matchedPublication)!;
        } else {
          // An unmatched record is not proof of non-upload: historical uploads
          // can lack lineage or the current endpoint can omit older records.
          next[production.id] = "unverified";
        }
      });
      setPublicationVerification(next);
      setLinkedPublications(links);
      setVerifying(false);
    };
    void run().catch(() => { if (!cancelled) setVerifying(false); });
    return () => { cancelled = true; };
  }, [saved, channel.channelId, loadToken]);
  const visiblePublications = useMemo(() => (snapshot?.publications ?? []).filter(p => !p.superseded_by_publication_id && (!programId || !p.program_id || p.program_id === programId)), [snapshot, programId]);
  const published = useMemo(() => visiblePublications.filter(p => p.status === "PUBLISHED" || !!p.public_confirmed_at), [visiblePublications]);
  const latest = useMemo(() => [...visiblePublications].sort((a,b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))[0], [visiblePublications]);
  const pending = useMemo(() => visiblePublications.filter(p => p.status !== "PUBLISHED" && !p.public_confirmed_at && !!p.youtube_video_id).length, [visiblePublications]);
  const top = ranking[0];
  const rankedCount = ranking.length;
  const currentEvent = useMemo<AutonomousActivityEvent | null>(() => [...(snapshot?.activity ?? [])].sort((a,b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at))[0] ?? null, [snapshot]);
  const refresh = useCallback(async (signal?: { cancelled: boolean }) => {
    setRefreshing(true); setError(null);
    try {
      const next = await getYouTubeAutonomySnapshot(30);
      if (signal?.cancelled) return;
      setSnapshot(next);
      const scope = next.publications.filter(p => !p.superseded_by_publication_id && (!programId || !p.program_id || p.program_id === programId) && (p.status === "PUBLISHED" || !!p.public_confirmed_at));
      const details = await Promise.allSettled(scope.sort((a,b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).slice(0, 20).map(p => getYouTubePublication(p.publication_id)));
      if (signal?.cancelled) return;
      const scored: Ranked[] = [];
      details.forEach((item, i) => {
        if (item.status !== "fulfilled") return;
        const observations = item.value.snapshots ?? [];
        const v24 = observations.filter(s => s.checkpoint.toUpperCase() === "24H" && s.views !== null).sort((a,b) => Date.parse(b.observed_at) - Date.parse(a.observed_at))[0];
        if (v24) scored.push({ publication: scope[i], snapshot: v24 });
      });
      scored.sort((a,b) => (b.snapshot.views ?? 0) - (a.snapshot.views ?? 0));
      setRanking(scored);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (e) { if (!signal?.cancelled) setError(e instanceof Error ? e.message : "Unable to load channel activity."); }
    finally { if (!signal?.cancelled) { setLoading(false); setRefreshing(false); } }
  }, [programId]);
  useEffect(() => { const state = { cancelled: false }; void refresh(state); return () => { state.cancelled = true; }; }, [refresh, loadToken]);
  const actionable = useMemo(() => saved.filter(p => {
    const verified = publicationVerification[p.id];
    if (verified === "published" || verified === "uploaded") return false;
    const stage = (p.stageLabel || "").toLowerCase();
    const status = (p.status || "").toLowerCase();
    if (/published|final video approved|completed|closed|delivered/.test(stage)) return false;
    // A stale approval checkpoint is not proof that an upload still needs approval.
    // Do not show approval requests unless a future authoritative status source
    // can demonstrate that approval remains outstanding.
    if (/review|approval/.test(stage) || status === "review") return false;
    if (!verified || verified === "unverified") return false;
    return /blocked|error|failed|attention|in progress|visual|audio|production|brief|draft|create/.test(stage + " " + status);
  }).sort((a,b) => {
    const priority = (p: WorkspaceProduction) => /blocked|failed|error|attention/i.test(`${p.stageLabel} ${p.status}`) ? 0 : 1;
    return priority(a) - priority(b);
  }).slice(0,3), [saved, publicationVerification]);
  const currentStatus = pending ? "Release awaiting action" : autopilotStatus === "RUNNING" ? "Autopilot running" : autopilotStatus === "NEEDS_ATTENTION" ? "Needs attention" : autopilotStatus === "PAUSED" ? "Autopilot paused" : "Autopilot idle";
  const lifecycle = useMemo(() => {
    const status = autopilotStatus.toUpperCase();
    const message = (autopilotMessage || "").trim();
    const messageLower = message.toLowerCase();
    const lastPhase = (currentEvent?.phase || "").toLowerCase();
    const learning = Boolean(learningCheckpointRequired || learningWaitStartedAt) || /checkpoint|learning|analytics|performance/.test(messageLower) && status === "RUNNING";
    const matchedPublication = visiblePublications.find(p => p.publication_id === currentPublicationId);
    const scheduledTime = matchedPublication?.publish_at || snapshot?.autonomy.next_scheduled_public_at || null;
    let label: string;
    let phase = 0;
    let detail = message || "No active autonomous session reported.";
    let next = "No next action scheduled";
    if (status === "NEEDS_ATTENTION" || status === "ERROR" || status === "FAILED") {
      label = "Needs attention";
      next = "Inspect the exception in Autonomy";
    } else if (status === "PAUSED") {
      label = "Autopilot paused";
      next = "Resume autonomy when ready";
    } else if (status === "WAITING_FOR_FINAL_APPROVAL") {
      label = "Waiting for final approval";
      next = "Inspect legacy approval state in Autonomy";
    } else if (status === "RUNNING") {
      if (learning) { label = "Learning from performance"; phase = 4; next = `Evaluate ${learningCheckpointRequired || "the next"} checkpoint and choose a new concept`; }
      else if (currentPublicationId || /publish|upload|release|schedule/.test(messageLower) || /publish/.test(lastPhase)) { label = scheduledTime ? "Publishing scheduled" : "Publishing workflow active"; phase = 3; next = scheduledTime ? `Next scheduled release: ${when(scheduledTime)}` : "Continue YouTube publishing workflow"; }
      else if (/review|quality|qc|approval|delivery/.test(messageLower) || /review|quality|delivery/.test(lastPhase)) { label = "AI review and delivery checks"; phase = 2; next = "Complete quality gates and deliver the master"; }
      else if (currentMediaJobId || currentProductionJobId || /render|generat|creat|production|video|audio|visual/.test(messageLower)) { label = "Producing video"; phase = 1; next = "Complete production and AI review"; }
      else { label = "Planning next production"; phase = 0; next = "Start the next production task"; }
    } else if (status === "COMPLETED") { label = "Autonomous run completed"; phase = 4; next = "Start or resume another autonomous campaign"; }
    else { label = "Autopilot not running"; next = "Open Autonomy to start or review the campaign"; }
    if (!detail || (status === "IDLE" && /ready to produce/.test(messageLower))) detail = status === "IDLE" ? "No autonomous execution is currently reported." : detail;
    const heartbeatMs = supervisorHeartbeatAt ? Date.parse(supervisorHeartbeatAt) : NaN;
    const heartbeatAgeMin = Number.isFinite(heartbeatMs) ? (Date.now() - heartbeatMs) / 60000 : NaN;
    const health = status !== "RUNNING" ? null : executionOwner === "BACKEND" && Number.isFinite(heartbeatAgeMin) && heartbeatAgeMin > 20
      ? "Supervisor heartbeat may be stale" : !supervisorHeartbeatAt ? "Heartbeat not available" : "Supervisor heartbeat recorded";
    return { label, phase, detail, next, scheduledTime, health, status };
  }, [autopilotStatus, autopilotMessage, currentEvent, currentPublicationId, currentProductionJobId, currentMediaJobId, learningCheckpointRequired, learningWaitStartedAt, snapshot, visiblePublications, supervisorHeartbeatAt, executionOwner]);
  const nav = (label: string, tab: Tab) => <button style={{ ...action, border: "none", background: "transparent", color: "#c3b8ff", padding: "6px 4px", boxShadow: "none", fontSize: 13 }} type="button" onClick={() => onOpenTab(tab)}>{label}<ArrowRight size={14}/></button>;
  return <div style={{ display: "grid", gap: 11, minWidth: 0 }}>
    <style>{`@media(min-width:850px){.revai-performance-columns{grid-template-columns:minmax(0, 0.95fr) minmax(0, 1.8fr)!important}}@media(max-width:849px){.revai-performance-columns{grid-template-columns:minmax(0,1fr)!important}}@keyframes revai-live-pulse{0%,100%{opacity:.45;transform:scale(.95)}50%{opacity:1;transform:scale(1.05)}}@keyframes revai-live-sweep{0%{transform:translateX(-100%)}100%{transform:translateX(300%)}}@keyframes revai-live-scan{0%{top:4%}50%{top:94%}100%{top:4%}}@media(prefers-reduced-motion:reduce){.revai-motion{animation:none!important}}`}</style>
    <section style={{ ...panel, background: "linear-gradient(115deg,#1f2145,#142437 85%)" }} aria-label="Autonomous production status">
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "start", justifyContent: "space-between" }}>
        <div><div style={smallHeading}>AUTONOMOUS PRODUCTION</div><h2 style={{ fontSize: 21, margin: "5px 0" }}>ReviveAI Autopilot</h2></div>
        <span style={{ border: `1px solid ${lifecycle.status === "NEEDS_ATTENTION" ? "#e3a679" : lifecycle.status === "RUNNING" ? "#66c5af" : "#687096"}`, padding: "6px 10px", borderRadius: 30, fontSize: 12, fontWeight: 700 }}>
          <Activity size={13} style={{ verticalAlign: "middle", marginRight: 5 }}/>{lifecycle.label}
        </span>
      </div>
      {runningProduction && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,270px),1fr))", gap: 14, marginTop: 12, padding: 12, background: "#19263e", border: "1px solid #46547c", borderRadius: 12 }}>
          <div style={{ position: "relative", borderRadius: 11, overflow: "hidden", background: "radial-gradient(circle at 50% 35%,#343663,#111a30 70%)", aspectRatio: "16/10", minHeight: 155, display: "grid", placeItems: "center", border: "1px solid #4a537b" }}>
            {characterImageUrl && !previewBroken ? (
              <img key={characterImageUrl} src={characterImageUrl} alt={`Character reference for ${currentProductionTitle || "current production"}`} style={{ width: "100%", height: "100%", position: "absolute", inset: 0, objectFit: "contain" }} onError={() => setPreviewBroken(true)}/>
            ) : (
              <div style={{ display: "grid", placeItems: "center", gap: 10, textAlign: "center", padding: 15 }}>
                <Clapperboard className="revai-motion" size={36} color="#b2a5ff" style={{ animation: "revai-live-pulse 2.4s ease-in-out infinite" }}/>
                <span style={{ ...muted, fontSize: 12 }}>{currentMediaJobId ? (mediaLoading ? "Loading character reference…" : "Character reference not available yet") : "Preparing character generation"}</span>
              </div>
            )}
            <div className="revai-motion" aria-hidden="true" style={{ position: "absolute", top: 0, bottom: 0, width: "40%", background: "linear-gradient(90deg,transparent,rgba(169,147,255,.11),transparent)", pointerEvents: "none", animation: "revai-live-sweep 4s linear infinite" }}/>
            {characterImageUrl && !previewBroken && <div className="revai-motion" aria-hidden="true" style={{ position: "absolute", left: 0, right: 0, height: 2, background: "rgba(138,236,218,.55)", boxShadow: "0 0 14px #9bffef", pointerEvents: "none", animation: "revai-live-scan 5s ease-in-out infinite" }}/ >}
            <span style={{ position: "absolute", top: 9, left: 9, borderRadius: 30, background: "rgba(11,16,31,.85)", padding: "5px 9px", color: "#b6ffe6", fontSize: 11, fontWeight: 800 }}><span className="revai-motion" style={{ display: "inline-block", marginRight: 6, width: 7, height: 7, borderRadius: "50%", background: "#72e5bc", animation: "revai-live-pulse 1.4s ease-in-out infinite" }}/>PRODUCTION ACTIVE</span>
            <span style={{ position: "absolute", bottom: 8, left: 8, background: "rgba(11,16,31,.85)", borderRadius: 6, padding: "4px 8px", fontSize: 11 }}>{characterImageUrl && !previewBroken ? "Generated character reference · static image" : "Visual preview pending"}</span>
          </div>
          <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 9, justifyContent: "center" }}>
            <div style={smallHeading}>CURRENT AUTONOMOUS VIDEO</div>
            <strong style={{ fontSize: 18, overflowWrap: "anywhere" }}>{currentProductionTitle?.trim() || "Resolving active production title…"}</strong>
            <span style={muted}>{lifecycle.label}</span>
            {activeMedia && <div style={{ ...muted, fontSize: 12 }}>Media stage: {activeMedia.stage.replace(/_/g, " ")} · {activeMedia.progress_total > 0 ? `${activeMedia.progress_current}/${activeMedia.progress_total} steps reported` : "Progress not reported"}</div>}
            {activeMedia && activeMedia.progress_total > 0 && <div role="progressbar" aria-label="Media generation steps" aria-valuenow={Math.min(activeMedia.progress_current,activeMedia.progress_total)} aria-valuemin={0} aria-valuemax={activeMedia.progress_total} style={{ height: 6, background: "#35405c", borderRadius: 8, overflow: "hidden" }}><div style={{ width: `${Math.min(100,Math.max(0,activeMedia.progress_current / activeMedia.progress_total * 100))}%`, height: "100%", background: "#a89cff", transition: "width .6s" }}/></div>}
            {keyframeImageUrl && <div style={{ display: "flex", alignItems: "center", gap: 9 }}><img src={keyframeImageUrl} alt="Most recent storyboard frame" style={{ width: 69, height: 48, objectFit: "cover", borderRadius: 6, border: "1px solid #46547c" }}/><span style={{ ...muted, fontSize: 11 }}><ImageIcon size={13} style={{ verticalAlign: "middle" }}/> Latest storyboard frame · Shot {latestKeyframe?.shot_number ?? "—"}</span></div>}
            {mediaError && <span style={{ ...muted, color: "#ffbfac", fontSize: 11 }}>Preview check: {mediaError}</span>}
            <button type="button" style={{ ...action, alignSelf: "flex-start" }} onClick={() => activeSavedProduction ? onOpenProduction(activeSavedProduction) : onOpenTab("autonomy")}><PlayCircle size={16}/>{activeSavedProduction ? "Open current production" : "View live production"}<ArrowRight size={14}/></button>
          </div>
        </div>
      )}
      <div style={{ background: "#19263e", border: "1px solid #354463", borderRadius: 11, padding: 13, marginTop: 12 }}>
        <strong style={{ display: "block", overflowWrap: "anywhere" }}>{currentProductionTitle && lifecycle.status === "RUNNING" ? currentProductionTitle : lifecycle.label}</strong>
        <p style={{ ...muted, marginTop: 6, overflowWrap: "anywhere" }}>{lifecycle.detail}</p>
        <div style={{ ...muted, marginTop: 12, display: "flex", gap: 7, alignItems: "start" }}><Clock3 size={15} style={{ flexShrink: 0 }}/><span><b style={{ color: "#ecedff" }}>Next:</b> {lifecycle.next}</span></div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5,minmax(0,1fr))", gap: 5, marginTop: 13 }}>
        {["Plan", "Create", "Review", "Publish", "Learn"].map((step, idx) => <div key={step} style={{ minWidth: 0, textAlign: "center" }}>
          <div style={{ height: 6, borderRadius: 8, background: lifecycle.status === "RUNNING" && idx <= lifecycle.phase ? "#9a8dff" : "#38405b" }}/>
          <span style={{ fontSize: 10, color: lifecycle.status === "RUNNING" && idx === lifecycle.phase ? "#e9e2ff" : "#aebbd4", display: "block", paddingTop: 6 }}>{step}</span>
        </div>)}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 10, alignItems: "center", marginTop: 13 }}>
        <div style={{ ...muted, fontSize: 11, display: "grid", gap: 4 }}>
          <span>{currentEvent ? `Last channel event: ${currentEvent.action.replace(/_/g, " ")} · ${when(currentEvent.occurred_at)}` : "Last channel event: unavailable"}</span>
          <span>{supervisorHeartbeatAt ? `Supervisor heartbeat: ${when(supervisorHeartbeatAt)}` : "Supervisor heartbeat: unavailable"}</span>
          {lifecycle.health && <span><ShieldAlert size={12} style={{ verticalAlign: "middle" }}/> {lifecycle.health}</span>}
          {snapshot && <span>Auto-approval: {snapshot.autonomy.autonomous_final_approval_enabled ? "enabled" : "disabled"} · Auto-publishing: {snapshot.autonomy.autonomous_publish_enabled ? "enabled" : "disabled"}</span>}
        </div>
        {nav(lifecycle.status === "NEEDS_ATTENTION" ? "Resolve in Autonomy" : "View live autonomy", "autonomy")}
      </div>
    </section>
    <section style={{ ...panel, background: "linear-gradient(118deg,#211f46,#142137 78%)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <div><div style={smallHeading}>CHANNEL OVERVIEW</div><h2 style={{ fontSize: 21, margin: "4px 0" }}>Channel pulse</h2><div style={{ ...muted, display: "flex", gap: 9, alignItems: "center", flexWrap: "wrap" }}><span style={{ border: "1px solid #687096", borderRadius: 30, padding: "3px 9px", color: "#f0efff", fontSize: 11 }}>{currentStatus}</span>{pending ? `${pending} uploaded release${pending===1?"":"s"} awaiting public verification` : autopilotStatus === "RUNNING" ? (currentProductionTitle ? `Creating: ${currentProductionTitle}` : "Production is underway") : "No production currently running"}</div></div>
        <button type="button" aria-label={refreshing ? "Refreshing channel data" : "Refresh channel data"} title={refreshing ? "Refreshing channel data" : "Refresh channel data"} style={{ ...action, width: 38, height: 38, padding: 0 }} disabled={refreshing} onClick={() => { setLoadToken(x => x+1); }}><RefreshCw size={16} className={refreshing ? "spin" : ""}/></button>
      </div>
      {error && <p style={{ color: "#ffc6a6", margin: "10px 0 0" }} role="alert"><CircleAlert size={14}/> {error}</p>}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 10, marginTop: 14 }}>
        {[
          { label: "Public releases", value: loading ? "…" : String(published.length), icon: <Youtube size={17}/> },
          { label: "24h measured", value: loading ? "…" : String(rankedCount), icon: <BarChart3 size={17}/> },
          { label: "Pending release", value: loading ? "…" : String(pending), icon: <CalendarClock size={17}/> },
          { label: "Saved productions", value: String(saved.length), icon: <FolderKanban size={17}/> },
        ].map(m => <div key={m.label} style={{ background: "#171d36", border: "1px solid #343b5c", borderRadius: 10, padding: "11px 13px" }}><div style={{ ...muted, fontSize: 12, display: "flex", justifyContent: "space-between" }}>{m.label}{m.icon}</div><div style={{ ...metric, marginBottom: 0 }}>{m.value}</div></div>)}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap", marginTop: 13 }}>
        <div style={{ ...muted, fontSize: 12 }}>{currentEvent ? `Latest: ${currentEvent.action.replace(/_/g, " ")} · ${when(currentEvent.occurred_at)}` : "Awaiting recent channel activity"}{lastUpdated ? ` · Checked ${lastUpdated}` : ""}</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{nav(pending ? "Review publishing" : autopilotStatus === "WAITING_FOR_FINAL_APPROVAL" ? "Review final video" : autopilotStatus === "NEEDS_ATTENTION" ? "Resolve issue" : autopilotStatus === "RUNNING" ? "View progress" : "Autonomy", "autonomy")}</div>
      </div>
    </section>
    {recentProduction && (
      <section style={panel} aria-label="Latest saved production">
        <div style={{ ...smallHeading, marginBottom: 9 }}>{recentVerification === "no_match" ? "LATEST NON-UPLOADED PRODUCTION" : "LATEST SAVED PRODUCTION"}</div>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ width: 105, minHeight: 59, flexShrink: 0, borderRadius: 9, overflow: "hidden", background: "#27304a", display: "grid", placeItems: "center" }}>
            {recentProduction.thumbnailUrl
              ? <img src={recentProduction.thumbnailUrl} alt="" loading="lazy" onError={event => { event.currentTarget.style.display = "none"; }} style={{ width: 105, height: 59, objectFit: "cover" }}/>
              : <FolderKanban size={25} color="#aab7d5" aria-label="No thumbnail available"/>}
          </div>
          <div style={{ flex: 1, minWidth: 160 }}>
            <strong style={{ display: "block", overflowWrap: "anywhere" }}>{recentProduction.title}</strong>
            <div style={{ ...muted, marginTop: 5 }}>{recentStatus} · Saved {when(recentProduction.updatedAt)}</div>
            {recentVerification === "no_match" && <div style={{ ...muted, marginTop: 3, fontSize: 11 }}>No associated upload found; this alone does not confirm the video is ready to publish.</div>}
          </div>
          {recentVerification === "published" && recentPublication?.youtube_url
            ? <a href={recentPublication.youtube_url} target="_blank" rel="noreferrer" style={action}>Watch on YouTube <ExternalLink size={15}/></a>
            : <button type="button" style={action} onClick={() => onOpenProduction(recentProduction)}>Open production <ArrowRight size={15}/></button>}
        </div>
      </section>
    )}
    <section style={panel}><div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}><div><div style={smallHeading}>CONTENT PERFORMANCE</div><h3 style={{ margin: "6px 0" }}>Top-performing videos</h3><p style={muted}>Ranked by views at the 24-hour checkpoint—not lifetime views. Only releases with a 24h checkpoint among the 20 most recent are compared.</p></div>{nav("Open Intelligence", "intelligence")}</div>
      {top ? <div className="revai-performance-columns" style={{ marginTop: 15, display: "grid", gridTemplateColumns: "minmax(0,1fr)", gap: 18, alignItems: "stretch" }}>
        <div style={{ border: "1px solid #4d4778", background: "#232443", padding: 14, borderRadius: 12 }}><div style={smallHeading}><CheckCircle2 size={13} style={{ verticalAlign: "middle" }}/> LEADING RELEASE · 24H</div><div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 8 }}><YouTubeThumbnail publication={top.publication} style={{ width: 148, maxWidth: "40%", aspectRatio: "16/9", borderRadius: 8, objectFit: "cover" }}/><strong>{titleOf(top.publication)}</strong></div><div style={{ fontSize: 20, fontWeight: 800, marginTop: 10 }}>{compact(top.snapshot.views ?? 0)} <span style={{ fontSize: 12, fontWeight: 400, color: "#b0bfd6" }}>views</span></div>{top.snapshot.average_percentage_viewed !== null && <p style={muted}>{top.snapshot.average_percentage_viewed.toFixed(1)}% avg viewed</p>}{top.publication.youtube_url && <a href={top.publication.youtube_url} target="_blank" rel="noreferrer" style={{ color: "#aea0ff", display: "inline-flex", gap: 5, alignItems: "center", marginTop: 10 }}>Watch video <ExternalLink size={13}/></a>}</div>
        <div style={{ padding: "7px 0", minWidth: 0, width: "100%" }}><strong>Other videos at 24 hours</strong>{ranking.slice(1, 5).map((v,i) => <div key={v.publication.publication_id} style={{ padding: "10px 0", borderBottom: "1px solid #303852", display: "flex", justifyContent: "space-between", gap: 12 }}><div style={{ display: "flex", gap: 9, minWidth: 0, flex: 1, alignItems: "center" }}><YouTubeThumbnail publication={v.publication} style={{ width: 64, aspectRatio: "16/9", objectFit: "cover", borderRadius: 5 }}/><div style={{ flex: 1, minWidth: 0 }}><div style={{ color: "#dbe2f4", fontSize: 12, overflowWrap: "anywhere" }}>{i + 2}. {titleOf(v.publication)}</div><div style={{ marginTop: 6, height: 5, background: "#323d55", borderRadius: 4, overflow: "hidden" }}><div style={{ height: "100%", width: `${Math.max(2, (v.snapshot.views ?? 0) / Math.max(1, top.snapshot.views ?? 0) * 100)}%`, background: "#8a75f1", borderRadius: 4 }}/></div></div></div><strong style={{ whiteSpace: "nowrap" }}>{compact(v.snapshot.views ?? 0)}</strong></div>)}</div>
        {ranking.length > 1 && <div style={{ ...muted, gridColumn: "1/-1", background: "#1c2840", border: "1px solid #354262", borderRadius: 9, padding: 12, display: "grid", gap: 7 }}>
          <strong style={{ color: "#e7eaff" }}>Evidence from the first 24 hours</strong>
          <span>The leading video recorded {((top.snapshot.views ?? 0) / Math.max(1,ranking[1].snapshot.views ?? 0)).toFixed(1)}× the runner-up's views ({compact(top.snapshot.views ?? 0)} vs {compact(ranking[1].snapshot.views ?? 0)}).</span>
          {top.snapshot.average_percentage_viewed != null && ranking[1].snapshot.average_percentage_viewed != null &&
            <span>Average viewed: {top.snapshot.average_percentage_viewed.toFixed(1)}% for the leader vs {ranking[1].snapshot.average_percentage_viewed.toFixed(1)}% for the runner-up. A higher view count does not necessarily mean higher retention.</span>}
          <span style={{ fontSize: 11 }}>Observed differences are not proof of creative causes. Compare hooks, pacing, topics and audiences in Deep analysis before changing your strategy.</span>
        </div>}
      </div> : <p style={{ ...muted, marginTop: 16 }}>{loading ? "Loading YouTube checkpoints…" : "No 24-hour performance checkpoints available yet. Open Autonomy to review release-level analytics as they arrive."}</p>}
    </section>
    <section style={panel}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}><div><div style={smallHeading}>CONTENT & ACTIONS</div><h3 style={{ margin: "6px 0" }}>Your next steps</h3></div>{nav("All productions", "productions")}</div>
      {latest && <div style={{ background: "#202a41", borderRadius: 10, padding: 11, marginTop: 12, display: "flex", gap: 12, alignItems: "center", minWidth: 0 }}>
        <YouTubeThumbnail publication={latest} style={{ width: 76, height: 52, objectFit: "cover", borderRadius: 8, flexShrink: 0 }}/>
        <div style={{ flex: 1, minWidth: 0 }}><div style={smallHeading}>LATEST YOUTUBE RELEASE</div><strong style={{ fontSize: 13, display: "block", marginTop: 2 }}>{titleOf(latest)}</strong><span style={{ ...muted, fontSize: 11 }}>{latest.status.replace(/_/g, " ")}</span></div>
        {latest.youtube_url && <a href={latest.youtube_url} target="_blank" rel="noreferrer" style={{ color: "#bfb4ff", display: "inline-flex", gap: 5, alignItems: "center", fontSize: 12, whiteSpace: "nowrap" }}>Watch <ExternalLink size={13}/></a>}
      </div>}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 17, marginBottom: 8 }}><div><div style={smallHeading}>CONTINUE WORKING</div><p style={{ ...muted, fontSize: 11, marginTop: 3 }}>Only in-progress saved checkpoints without a matching upload. Approval requests are hidden until independently verified.</p></div></div>
      <div style={{ display: "grid", gap: 7 }}>
        {actionable.map(p => <button key={p.id} type="button" onClick={() => onOpenProduction(p)} style={{ ...action, width: "100%", justifyContent: "space-between", background: "#19243a", textAlign: "left", padding: "10px 12px" }}>
          <span style={{ width: 30, height: 30, borderRadius: 8, background: "#293353", color: "#aaa1ff", display: "grid", placeItems: "center", flexShrink: 0 }}><FolderKanban size={17}/></span>
          <span style={{ flex: 1, minWidth: 0, fontSize: 13 }}>{p.title}<small style={{ display: "block", color: "#a9b5cb", marginTop: 3, fontSize: 11 }}>Saved checkpoint · {p.stageLabel}</small></span>
          <span style={{ fontSize: 12 }}>{/blocked|failed|error|attention/i.test(`${p.stageLabel} ${p.status}`) ? "Inspect" : "Continue"}</span><ArrowRight size={15}/>
        </button>)}
        {!actionable.length && <p style={muted}>{verifying ? "Checking production/publication lineage…" : "No confirmed action items from these records. Existing publications and uncertain approval checkpoints are excluded. Open Productions for the full history."}</p>}
      </div>
    </section>
  </div>;
}
