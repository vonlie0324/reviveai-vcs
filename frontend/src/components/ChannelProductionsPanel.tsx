import { ArrowDownAZ, ArrowRight, ChevronLeft, ChevronRight, CheckCircle2, Clock3, FolderKanban, ListFilter, Plus, Search, X, AlertCircle, ImageOff, Youtube, Globe2, LockKeyhole, CalendarClock, CircleHelp, UploadCloud } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { getMediaStudioJob, mediaAssetUrl, listYouTubePublications, getDeliveryPackagesForAssembly } from "../api";
import type { YouTubePublication, DeliveryPackage } from "../types";
import type { WorkspaceChannel, WorkspaceProduction } from "../workspace";
import { formatRelativeWorkspaceTime, getUniqueWorkspaceProductions } from "../workspace";
import "./ChannelProductionsPanel.css";

interface Props {
  channel: WorkspaceChannel;
  onOpenProduction: (production: WorkspaceProduction) => void;
  onNewProduction: () => void;
}
type ProductionStatus = WorkspaceProduction["status"];
type StatusFilter = "ALL" | ProductionStatus | "COMPLETED";
type SortOrder = "RECENT" | "OLDEST" | "TITLE";
const PAGE_SIZE = 8;
const libraryViewMemory = new Map<string, { query: string; status: StatusFilter; sort: SortOrder; page: number }>();
const milestoneNames: Record<string, string> = {
  M1: "Channel setup", M2A: "Production brief", M2B: "Visual production",
  "M2C.1": "Visual master", "M2C.2": "Audio finishing", "M2C.3": "Quality review",
  "M2C.4": "Delivery preparation", "M2C.5": "Publishing preparation",
};

// An awaiting-approval checkpoint must not be represented as ready to publish.
// Keep the persisted record untouched: the backend/workspace must remain authoritative.
function isCompleted(production: WorkspaceProduction): boolean {
  return /^(final video approved|production complete|production completed)$/i.test(production.stageLabel.trim()) && production.status === "READY";
}
function libraryStatus(production: WorkspaceProduction): StatusFilter {
  return isCompleted(production) ? "COMPLETED" : displayStatus(production);
}
function displayStatus(production: WorkspaceProduction): ProductionStatus {
  if (production.status === "BLOCKED") return "BLOCKED";
  const label = production.stageLabel.toLowerCase();
  if (/ready for (your )?approval|awaiting (your )?approval|needs (human )?review|final (video )?review|final qc review|audio master review|visual master review|production brief review/.test(label)) {
    return "REVIEW";
  }
  return production.status;
}
const statusMeta: Record<Exclude<StatusFilter, "ALL">, { label: string; action: string }> = {
  COMPLETED: { label: "Completed · Locked", action: "View" },
  ACTIVE: { label: "In progress", action: "Continue" },
  REVIEW: { label: "Needs review", action: "Review" },
  READY: { label: "Ready", action: "Open" },
  BLOCKED: { label: "Needs attention", action: "Resolve" },
};
const safeTime = (value: string) => {
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : 0;
};
const workflowStages = ["Brief", "Visuals", "Assembly", "Audio", "Quality", "Delivery", "Publishing"] as const;
const stageIndex: Record<WorkspaceProduction["stage"], number> = {
  BRIEF: 0, VISUALS: 1, VISUAL_MASTER: 2, AUDIO: 3, QC: 4, DELIVERY: 5, PUBLISHING: 6,
};

function ProductionThumbnail({ url }: { url?: string | null }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const resolvedUrl = url?.trim() ? mediaAssetUrl(url.trim()) : null;
  const canShow = Boolean(resolvedUrl && resolvedUrl !== failedUrl && /^https?:\/\//i.test(resolvedUrl));
  return <span className="cpl-thumbnail">
    {canShow ? <img src={resolvedUrl!} alt="" loading="lazy" onError={() => setFailedUrl(resolvedUrl!)} /> : <ImageOff size={21} aria-hidden="true" />}
  </span>;
}

// Media jobs are matched by both channel and production brief, never by video title.
// The small in-memory cache avoids repeated API requests when switching pages or filters.
const mediaThumbnailCache = new Map<string, string | null>();
function getJobThumbnail(job: Awaited<ReturnType<typeof getMediaStudioJob>>): string | null {
  return job.result?.keyframes.find((asset) => asset.review_status === "APPROVED" && !!asset.asset_url)?.asset_url
    || job.result?.keyframes.find((asset) => !!asset.asset_url)?.asset_url
    || job.result?.reference_asset?.asset_url
    || null;
}

// Publication data is observational only. Never infer YouTube visibility from production completion.
// A title or a recommendation ID is not sufficient evidence of a matching upload.
type PublicationView = { label: string; tone: string; detail: string; icon: typeof Youtube };
function describePublication(p: YouTubePublication | null | undefined, loaded: boolean): PublicationView {
  if (!loaded || !p) return { label: "YouTube not verified", tone: "unknown", detail: loaded ? "No matching publication record found; upload status is unconfirmed" : "Publication records unavailable or loading", icon: CircleHelp };
  if (!p.youtube_video_id) {
    if (p.status === "FAILED") return { label: "Upload failed", tone: "failed", detail: "YouTube upload failed", icon: CircleHelp };
    return { label: "Not uploaded", tone: "unknown", detail: "No YouTube video ID is recorded", icon: UploadCloud };
  }
  if (p.status === "FAILED") return { label: "Upload failed", tone: "failed", detail: "Publication failed; recorded visibility may be stale", icon: CircleHelp };
  if (p.status === "UPLOADING") return { label: "Uploading", tone: "scheduled", detail: "YouTube upload is not finalized", icon: UploadCloud };
  if (p.status === "SCHEDULED" && p.publish_at && Date.parse(p.publish_at) > Date.now())
    return { label: "Scheduled", tone: "scheduled", detail: `Scheduled for ${new Date(p.publish_at).toLocaleString()}; recorded visibility: ${p.privacy_status}`, icon: CalendarClock };
  const verified = p.last_reconciled_at ? `Last checked ${new Date(p.last_reconciled_at).toLocaleString()}` : "Recorded visibility; not recently verified with YouTube";
  const privacy = p.privacy_status?.toLowerCase();
  if (p.status === "SCHEDULED" && privacy !== "public")
    return { label: "Scheduled", tone: "scheduled", detail: `Scheduled publication; recorded visibility: ${p.privacy_status}`, icon: CalendarClock };
  if (privacy === "public") return { label: "YouTube · Public", tone: "public", detail: `Recorded YouTube visibility: public. ${verified}`, icon: Globe2 };
  if (privacy === "unlisted") return { label: "YouTube · Unlisted", tone: "unlisted", detail: `Recorded YouTube visibility: unlisted. ${verified}`, icon: LockKeyhole };
  if (privacy === "private") return { label: "YouTube · Private", tone: "private", detail: `Recorded YouTube visibility: private. ${verified}`, icon: LockKeyhole };
  return { label: "Visibility unknown", tone: "unknown", detail: "YouTube upload exists but visibility is not confirmed", icon: CircleHelp };
}
function matchedPublication(production: WorkspaceProduction, records: YouTubePublication[], packages: DeliveryPackage[] = []): YouTubePublication | undefined {
  const cp = production.checkpoint;
  const ids = [cp.productionBriefJobId || production.id, cp.mediaStudioJobId, cp.finalAssemblyJobId, cp.audioFinishingJobId].filter(Boolean);
  const packageIds = new Set(packages.filter(pkg => pkg.assembly_job_id === cp.finalAssemblyJobId && (!cp.audioFinishingJobId || pkg.audio_job_id === cp.audioFinishingJobId)).map(pkg => pkg.package_id));
  return records.filter(p => !p.superseded_by_publication_id && (
    (!!p.package_id && packageIds.has(p.package_id)) ||
    ids.includes(p.production_job_id || "") || ids.includes(p.media_job_id || "") ||
    ids.includes(p.assembly_job_id || "") || ids.includes(p.audio_job_id || "")
  )).sort((a,b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))[0];
}

export function ChannelProductionsPanel({ channel, onOpenProduction, onNewProduction }: Props) {
  const savedView = libraryViewMemory.get(channel.channelId);
  const [query, setQuery] = useState(savedView?.query ?? "");
  const [status, setStatus] = useState<StatusFilter>(savedView?.status ?? "ALL");
  const [sort, setSort] = useState<SortOrder>(savedView?.sort ?? "RECENT");
  const [page, setPage] = useState(savedView?.page ?? 1);
  const updateQuery = (value: string) => { setQuery(value); setPage(1); };
  const updateStatus = (value: StatusFilter) => { setStatus(value); setPage(1); };
  const updateSort = (value: SortOrder) => { setSort(value); setPage(1); };
  const productions = useMemo(() => getUniqueWorkspaceProductions(channel.productions), [channel.productions]);
  const [youtubePublications, setYoutubePublications] = useState<YouTubePublication[]>([]);
  const [publicationLoaded, setPublicationLoaded] = useState(false);
  const [assemblyPackages, setAssemblyPackages] = useState<Record<string, DeliveryPackage[]>>({});
  useEffect(() => {
    let cancelled = false;
    setPublicationLoaded(false);
    setYoutubePublications([]);
    listYouTubePublications().then(records => {
      if (!cancelled) { setYoutubePublications(records); setPublicationLoaded(true); }
    }).catch(() => { if (!cancelled) setPublicationLoaded(false); });
    return () => { cancelled = true; };
  }, [channel.channelId]);

  const counts = useMemo(() => {
    const result = { ALL: productions.length, ACTIVE: 0, REVIEW: 0, READY: 0, BLOCKED: 0, COMPLETED: 0 };
    for (const production of productions) result[libraryStatus(production)] += 1;
    return result;
  }, [productions]);
  const items = useMemo(() => {
    const term = query.trim().toLocaleLowerCase();
    return productions.filter((production) =>
      (status === "ALL" || libraryStatus(production) === status) &&
      (!term || [production.title, production.stageLabel, production.milestone, statusMeta[libraryStatus(production) as Exclude<StatusFilter, "ALL">].label]
        .some((value) => value.toLocaleLowerCase().includes(term))),
    ).sort((a, b) => sort === "TITLE" ? a.title.localeCompare(b.title)
      : sort === "OLDEST" ? safeTime(a.updatedAt) - safeTime(b.updatedAt)
      : safeTime(b.updatedAt) - safeTime(a.updatedAt));
  }, [productions, query, status, sort]);
  const totalPages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  const currentPage = Math.min(Math.max(1, page), totalPages);
  const startIndex = (currentPage - 1) * PAGE_SIZE;
  const pageItems = items.slice(startIndex, startIndex + PAGE_SIZE);
  // Resolve legacy publications through authenticated, read-only delivery-package lineage.
  // Only query assemblies visible on the current page; never use title-based joins.
  useEffect(() => {
    let cancelled = false;
    setAssemblyPackages({});
    if (!publicationLoaded || !youtubePublications.length) return () => { cancelled = true; };
    const assemblyIds = [...new Set(pageItems.map(p => p.checkpoint.finalAssemblyJobId).filter((id): id is string => Boolean(id)))];
    const hydrate = async () => {
      let next = 0;
      const worker = async () => {
        while (!cancelled) {
          const index = next++;
          if (index >= assemblyIds.length) return;
          const assemblyId = assemblyIds[index];
          try {
            const packages = await getDeliveryPackagesForAssembly(assemblyId);
            if (!cancelled) setAssemblyPackages(current => ({ ...current, [assemblyId]: packages.filter(pkg => pkg.assembly_job_id === assemblyId) }));
          } catch {
            // Unknown stays unknown. Never infer "not published" from request failure.
          }
        }
      };
      await Promise.all(Array.from({length: Math.min(3, assemblyIds.length)}, () => worker()));
    };
    void hydrate();
    return () => { cancelled = true; };
  }, [channel.channelId, currentPage, items, publicationLoaded, youtubePublications]);
  const [resolvedThumbnails, setResolvedThumbnails] = useState<Record<string, string | null>>({});
  const pageMediaKeys = pageItems.map((production) => {
    const mediaId = production.checkpoint.mediaStudioJobId;
    return mediaId ? `${channel.channelId}:${production.id}:${mediaId}` : "";
  }).filter(Boolean).join("|");
  useEffect(() => {
    let cancelled = false;
    const pending = pageItems.filter((production) => {
      const mediaId = production.checkpoint.mediaStudioJobId;
      return Boolean(mediaId && !mediaThumbnailCache.has(`${channel.channelId}:${production.id}:${mediaId}`));
    });
    // Bound concurrency so one slow media-job response cannot block every thumbnail.
    // Only inspect the current page, and never replace a thumbnail from another job.
    const hydrate = async () => {
      let cursor = 0;
      const worker = async () => {
        while (!cancelled) {
          const index = cursor++;
          if (index >= pending.length) return;
          const production = pending[index];
          const mediaId = production.checkpoint.mediaStudioJobId!;
          const cacheKey = `${channel.channelId}:${production.id}:${mediaId}`;
          try {
            const job = await getMediaStudioJob(mediaId);
            if (cancelled) return;
            const matched = job.channel_id === channel.channelId
              && job.production_brief_job_id === (production.checkpoint.productionBriefJobId || production.id);
            const imageUrl = matched ? getJobThumbnail(job) : null;
            mediaThumbnailCache.set(cacheKey, imageUrl);
            setResolvedThumbnails((current) => ({ ...current, [cacheKey]: imageUrl }));
          } catch {
            // Transient failures are not cached so revisiting can retry.
          }
        }
      };
      await Promise.all(Array.from({ length: Math.min(3, pending.length) }, () => worker()));
    };
    void hydrate();
    return () => { cancelled = true; };
  }, [channel.channelId, pageMediaKeys]);

  // Keep the last viewed page across unmounts (e.g. opening a production),
  // while automatically clamping it if the dataset becomes smaller.
  libraryViewMemory.set(channel.channelId, { query, status, sort, page: currentPage });
  const filters: { key: StatusFilter; label: string }[] = [
    { key: "ALL", label: "All" }, { key: "REVIEW", label: "Needs review" },
    { key: "BLOCKED", label: "Needs attention" }, { key: "ACTIVE", label: "In progress" },
    { key: "READY", label: "Ready" }, { key: "COMPLETED", label: "Completed" },
  ];
  return (
    <section className="channel-productions-panel cpl" aria-label="Production library">
      <header className="cpl-heading">
        <div><span className="eyebrow">Production library</span><h2>Saved productions <span className="cpl-total">{counts.ALL}</span></h2><p>Find a production, continue from its checkpoint, or review pending work.</p></div>
      </header>
      <div className="cpl-overview" aria-label="Production summary">
        <button type="button" aria-pressed={status === "ALL"} onClick={() => updateStatus("ALL")} className="cpl-overview-card"><FolderKanban size={17}/><span>Total saved</span><strong>{counts.ALL}</strong></button>
        <button type="button" aria-pressed={status === "REVIEW"} onClick={() => updateStatus("REVIEW")} className="cpl-overview-card cpl-review"><Clock3 size={17}/><span>Needs review</span><strong>{counts.REVIEW}</strong></button>
        <button type="button" aria-pressed={status === "ACTIVE"} onClick={() => updateStatus("ACTIVE")} className="cpl-overview-card cpl-progress"><ListFilter size={17}/><span>In progress</span><strong>{counts.ACTIVE}</strong></button>
        <button type="button" aria-pressed={status === "COMPLETED"} onClick={() => updateStatus("COMPLETED")} className="cpl-overview-card cpl-ready"><CheckCircle2 size={17}/><span>Completed</span><strong>{counts.COMPLETED}</strong></button>
      </div>
      <div className="cpl-toolbar">
        <label className="cpl-search"><Search size={16} aria-hidden="true"/><input aria-label="Search productions" value={query} onChange={(event) => updateQuery(event.target.value)} placeholder="Search productions..."/>{query && <button type="button" title="Clear search" aria-label="Clear search" onClick={() => updateQuery("")}><X size={15}/></button>}</label>
        <div className="cpl-filter-row" aria-label="Filter by status">{filters.map((filter) => <button key={filter.key} type="button" aria-pressed={status === filter.key} className={status === filter.key ? "is-active" : ""} onClick={() => updateStatus(filter.key)}>{filter.label}<span>{counts[filter.key]}</span></button>)}</div>
        <label className="cpl-sort"><ArrowDownAZ size={16} aria-hidden="true"/><select aria-label="Sort productions" value={sort} onChange={(event) => updateSort(event.target.value as SortOrder)}><option value="RECENT">Recently updated</option><option value="OLDEST">Oldest updated</option><option value="TITLE">Title A–Z</option></select></label>
      </div>
      <div className="cpl-results-caption"><span>{items.length ? `${startIndex + 1}–${Math.min(startIndex + PAGE_SIZE, items.length)} of ${items.length}` : "0"} {items.length === 1 ? "production" : "productions"}{items.length !== counts.ALL ? ` (filtered from ${counts.ALL})` : ""}</span><span>Open a production to view its history or continue unfinished work</span></div>
      {items.length ? <div className="cpl-list">{pageItems.map((production) => {
        const shownStatus = libraryStatus(production) as Exclude<StatusFilter, "ALL">;
        const metadata = statusMeta[shownStatus];
        const selectedStage = stageIndex[production.stage];
        const record = matchedPublication(production, youtubePublications, assemblyPackages[production.checkpoint.finalAssemblyJobId || ""] || []);
        const youtube = describePublication(record, publicationLoaded);
        const PublicationIcon = youtube.icon;
        const watchUrl = record?.youtube_video_id && (record.youtube_url?.startsWith("https://www.youtube.com/watch?") ? record.youtube_url : `https://www.youtube.com/watch?v=${encodeURIComponent(record.youtube_video_id)}`);
        return <div key={production.id} className="cpl-item-container"><button className="cpl-item" type="button" onClick={() => onOpenProduction(production)} aria-label={`${metadata.action}: ${production.title}`}>
          <ProductionThumbnail url={(() => {
            const mediaId = production.checkpoint.mediaStudioJobId;
            const key = mediaId ? `${channel.channelId}:${production.id}:${mediaId}` : "";
            return (key && (resolvedThumbnails[key] || mediaThumbnailCache.get(key))) || production.thumbnailUrl;
          })()}/>
          <span className="cpl-item-main">
            <span className="cpl-item-heading"><strong title={production.title}>{production.title}</strong><span className={`cpl-status cpl-status-${shownStatus.toLowerCase()}`}>{metadata.label}</span></span>
            <span className="cpl-stage" title={production.stageLabel}>{production.stageLabel}</span>
            <span className={`cpl-youtube-status cpl-youtube-${youtube.tone}`} title={youtube.detail}>
              <PublicationIcon size={12} aria-hidden="true" />{youtube.label}
            </span>
            <span className="cpl-stage-steps" role="img" aria-label={`Saved stage: ${workflowStages[selectedStage]}`}>
              {workflowStages.map((name, index) => <span key={name} className={index <= selectedStage ? "is-reached" : ""} title={name}/>)}
            </span>
          </span>
          <span className="cpl-item-meta"><span>Updated {formatRelativeWorkspaceTime(production.updatedAt)}</span><span className="cpl-milestone" title={production.milestone}>{milestoneNames[production.milestone] ?? production.stageLabel}</span></span>
          <span className="cpl-item-action">{metadata.action}<ArrowRight size={15}/></span>
        </button>{watchUrl && <a className="cpl-watch-link" href={watchUrl} target="_blank" rel="noopener noreferrer" aria-label={`Watch ${production.title} on YouTube`}>Watch on YouTube ↗</a>}</div>;
      })}</div> : <div className="cpl-empty"><AlertCircle size={25}/><strong>{counts.ALL === 0 ? "No productions yet" : "No matching productions"}</strong><p>{counts.ALL === 0 ? "Start a new production to see it here." : "Change the filters or try a different search."}</p>{counts.ALL === 0 ? <button type="button" className="primary-button" onClick={onNewProduction}><Plus size={16}/> New production</button> : <button type="button" className="cpl-reset" onClick={() => {updateQuery(""); updateStatus("ALL");}}>Clear filters <ArrowRight size={14}/></button>}</div>}
      {items.length > PAGE_SIZE && (
        <nav className="cpl-pagination" aria-label="Production list pages">
          <span className="cpl-pagination-summary">Page {currentPage} of {totalPages}</span>
          <div className="cpl-pagination-controls">
            <button type="button" className="cpl-page-arrow" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)} aria-label="Previous page"><ChevronLeft size={16}/><span>Previous</span></button>
            {Array.from({ length: totalPages }, (_, index) => index + 1).map((pageNumber) => (
              <button key={pageNumber} type="button" className="cpl-page-number" aria-label={`Page ${pageNumber}`} aria-current={currentPage === pageNumber ? "page" : undefined} onClick={() => setPage(pageNumber)}>{pageNumber}</button>
            ))}
            <button type="button" className="cpl-page-arrow" disabled={currentPage === totalPages} onClick={() => setPage(currentPage + 1)} aria-label="Next page"><span>Next</span><ChevronRight size={16}/></button>
          </div>
        </nav>
      )}
    </section>
  );
}
