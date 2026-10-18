import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bot,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CirclePause,
  CirclePlay,
  Clock3,
  ExternalLink,
  LoaderCircle,
  Radio,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  UploadCloud,
  Youtube,
} from "lucide-react";

import {
  getYouTubeAutonomySnapshot,
  getYouTubePublication,
  refreshYouTubeAnalytics,
  startYouTubePublisherConnection,
} from "../api";
import "./AutonomousOperationsConsole.css";

import type {
  AutonomousActivityEvent,
  YouTubeAutonomyStatus,
  YouTubeConnection,
  YouTubePerformanceSnapshot,
  YouTubePublication,
  YouTubePublicationDetail,
} from "../types";

import {
  formatMetric, formatNetSubscribers, formatSummary, latestPerformanceSnapshot,
  performanceStatus, publicationReleaseTiming, summarizePerformance, summaryCoverage,
} from "../youtubePerformance";

type AutopilotUiStatus = "RUNNING" | "PAUSED" | "NEEDS_ATTENTION" | "WAITING_FOR_FINAL_APPROVAL" | "WAITING_FOR_LEARNING" | "COMPLETED" | "IDLE";

type Props = {
  status: AutopilotUiStatus;
  message: string;
  currentTitle?: string | null;
  heartbeatAt?: string | null;
  startedAt?: string | null;
  blockedCount?: number;
  archivedCount?: number;
  completedCount?: number;
  onPause: () => void;
  onResume: () => void;
  embeddedControls?: boolean;
};

const ACTIVITY_LIMIT = 300;
const RECENT_PUBLICATION_DETAILS = 8;
const ACTIVITY_PAGE_SIZE = 15;
const RELEASE_QUEUE_LIMIT = 5;
const RELEASE_HISTORY_LIMIT = 5;
const AUTONOMY_VIEW_CACHE_MS = 2 * 60 * 1000;

type AutonomyViewCache = {
  cachedAt: number;
  autonomy: YouTubeAutonomyStatus | null;
  connection: YouTubeConnection | null;
  events: AutonomousActivityEvent[];
  publications: YouTubePublication[];
  details: Record<string, YouTubePublicationDetail>;
  filter: "ALL" | "PRODUCTION" | "YOUTUBE" | "LEARNING" | "ISSUES";
  activityWindow: "TODAY" | "7D" | "30D" | "ALL";
  visibleActivityCount: number;
  showReleaseHistory: boolean;
  visibleReleaseHistoryCount: number;
};

let autonomyViewCache: AutonomyViewCache | null = null;


function autonomyRefreshMs(status: AutopilotUiStatus, hidden: boolean): number {
  if (hidden) return 300_000;
  switch (status) {
    case "RUNNING": return 8_000;
    case "WAITING_FOR_FINAL_APPROVAL": return 10_000;
    case "NEEDS_ATTENTION": return 30_000;
    case "WAITING_FOR_LEARNING": return 60_000;
    case "PAUSED": return 300_000;
    case "COMPLETED": return 600_000;
    default: return 300_000;
  }
}

function detailRefreshMs(status: AutopilotUiStatus): number {
  return status === "RUNNING" ? 60_000 : status === "WAITING_FOR_LEARNING" ? 300_000 : 600_000;
}

function parseTime(value?: string | null): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatDateTime(value?: string | null, timeZone?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZone: timeZone || undefined,
      timeZoneName: "short",
    }).format(parsed);
  } catch {
    return parsed.toLocaleString();
  }
}

function relativeTime(value?: string | null): string {
  const parsed = parseTime(value);
  if (parsed == null) return "—";
  const delta = Math.round((Date.now() - parsed) / 1000);
  if (delta < 5) return "just now";
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86_400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86_400)}d ago`;
}

function untilTime(value?: string | null): string {
  const parsed = parseTime(value);
  if (parsed == null) return "No release scheduled";
  const seconds = Math.round((parsed - Date.now()) / 1000);
  if (seconds <= 0) return "Release window reached";
  if (seconds < 3600) return `in ${Math.max(1, Math.round(seconds / 60))} min`;
  if (seconds < 86_400) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.round((seconds % 3600) / 60);
    return minutes ? `in ${hours}h ${minutes}m` : `in ${hours}h`;
  }
  const days = Math.floor(seconds / 86_400);
  const hours = Math.round((seconds % 86_400) / 3600);
  return hours ? `in ${days}d ${hours}h` : `in ${days}d`;
}

function publicationTitle(publication: YouTubePublication): string {
  return publication.video_title?.trim() || "Autonomous YouTube publication";
}

function signedPercent(value?: number | null): string | null {
  if (value == null || !Number.isFinite(value)) return null;
  return `${value >= 0 ? "+" : ""}${value.toFixed(0)}%`;
}

function primaryPerformanceLine(publication: YouTubePublication): string | null {
  const performance = publication.primary_performance;
  if (!performance) return null;
  const viewDelta = signedPercent(performance.delta_percent?.views);
  const score = performance.performance_score == null ? null : `score ${performance.performance_score.toFixed(0)}`;
  const comparison = viewDelta ? `${viewDelta} views vs baseline` : null;
  return [score, comparison].filter(Boolean).join(" · ") || `${performance.primary_checkpoint} evidence available`;
}

function publicationReleaseTimestamp(publication: YouTubePublication): number {
  const candidates = [
    publication.public_release_at,
    publication.public_confirmed_at,
    publication.published_at,
    publication.publish_at,
    publication.updated_at,
  ];
  for (const value of candidates) {
    const parsed = parseTime(value);
    if (parsed != null) return parsed;
  }
  return 0;
}

function uploadPercent(publication: YouTubePublication): number | null {
  const totalBytes = publication.upload_bytes_total ?? 0;
  const committedBytes = publication.upload_bytes_committed ?? 0;
  if (totalBytes <= 0) return null;
  return Math.max(0, Math.min(100, Math.round((committedBytes / totalBytes) * 100)));
}

function safeDetailEntries(event: AutonomousActivityEvent, timeZone?: string | null): Array<[string, string]> {
  const details = event.details || {};
  const entries: Array<[string, string]> = [];
  const hidden = /token|secret|authorization|session_uri|upload_session|credential|cookie|prompt|video_title|response|retry_count|evidence_version/i;
  const metrics = ["views", "average_percentage_viewed", "likes", "comments", "shares", "subscribers_gained", "subscribers_lost"];
  const legacyEmpty = event.action.toUpperCase().includes("ANALYTICS")
    && !details.statistics_status && !details.analytics_status
    && metrics.every(key => details[key] === 0);
  const labels: Record<string, string> = {
    approval_actor: "Approved by", qc_status: "QC", scheduled_public_at: "Scheduled public",
    publish_at: "Scheduled public", schedule_reason: "Timing rationale", checkpoint: "Learning checkpoint",
    views: "Views", average_percentage_viewed: "Avg viewed", likes: "Likes", comments: "Comments",
    shares: "Shares", subscribers_gained: "Subscribers gained", subscribers_lost: "Subscribers lost",
    bytes_total: "Upload size", youtube_video_id: "YouTube video", published_at: "Public since",
    statistics_status: "Statistics", analytics_status: "Analytics", statistics_observed_at: "Counters fetched",
    checkpoint_at: "Original capture", statistics_is_late: "Later counter fetch",
    statistics_error: "Statistics issue", analytics_error: "Analytics issue",
  };
  const priority = ["checkpoint", "statistics_status", "analytics_status", ...metrics, "statistics_observed_at"];
  const keys = [...new Set([...priority.filter(key => key in details), ...Object.keys(details)])];
  for (const key of keys) {
    const raw = details[key];
    if (hidden.test(key) || raw === "" || (raw == null && !metrics.includes(key))) continue;
    let value = String(raw);
    if (metrics.includes(key)) {
      const isPublic = ["views", "likes", "comments"].includes(key);
      const status = isPublic ? details.statistics_status : details.analytics_status;
      if (legacyEmpty || status === "UNVERIFIED") value = "Unverified";
      else if (raw == null) value = status === "ERROR" ? "Unavailable" : "Pending";
      else if (typeof raw === "number" && Number.isFinite(raw)) {
        value = key === "average_percentage_viewed" ? `${raw.toFixed(1)}%` : raw.toLocaleString();
      } else value = "Unavailable";
    } else if (["scheduled_public_at", "publish_at", "published_at", "statistics_observed_at", "checkpoint_at"].includes(key)) {
      value = formatDateTime(value, timeZone);
    } else if (key === "statistics_status" || key === "analytics_status") {
      value = value.toLowerCase().replace(/_/g, " ");
    } else if (key === "statistics_is_late") {
      value = raw ? "Current counters; historical timing retained" : "No";
    } else if (key === "bytes_total" && typeof raw === "number" && Number.isFinite(raw)) {
      value = `${(raw / 1024 / 1024).toFixed(1)} MB`;
    }
    entries.push([labels[key] || key.split("_").join(" "), value]);
  }
  return entries.slice(0, 12);
}

function latestSnapshot(detail?: YouTubePublicationDetail): YouTubePerformanceSnapshot | null {
  return latestPerformanceSnapshot(detail?.snapshots);
}

function snapshotAtCheckpoint(detail: YouTubePublicationDetail | undefined, checkpoint: string): YouTubePerformanceSnapshot | null {
  const target = checkpoint.trim().toUpperCase();
  if (!target) return null;
  const matches = (detail?.snapshots || []).filter((item) => item.checkpoint.toUpperCase() === target);
  if (!matches.length) return null;
  return matches.reduce((best, item) => Date.parse(item.observed_at) >= Date.parse(best.observed_at) ? item : best);
}

function currentPublications(publications: YouTubePublication[]): YouTubePublication[] {
  const seen = new Set<string>();
  return publications.filter(publication => {
    if (publication.superseded_by_publication_id) return false;
    const key = publication.recommendation_id || publication.publication_id;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function statusLabel(status: AutopilotUiStatus): string {
  switch (status) {
    case "RUNNING": return "Running autonomously";
    case "PAUSED": return "Paused";
    case "NEEDS_ATTENTION": return "Needs attention";
    case "WAITING_FOR_FINAL_APPROVAL": return "Waiting for approval";
    case "WAITING_FOR_LEARNING": return "Collecting early performance signal";
    case "COMPLETED": return "Campaign complete";
    default: return "Idle";
  }
}


function isYouTubeRelatedEvent(event: AutonomousActivityEvent): boolean {
  const phase = event.phase.toUpperCase();
  const action = event.action.toUpperCase();
  return (
    phase === "YOUTUBE"
    || action.includes("YOUTUBE")
    || action.includes("UPLOAD")
    || action === "VIDEO_PUBLIC"
    || action.includes("ANALYTICS")
  );
}

function eventIcon(event: AutonomousActivityEvent) {
  const action = event.action.toUpperCase();
  if (action.includes("APPROVAL")) return <ShieldCheck size={16} />;
  if (action.includes("UPLOAD")) return <UploadCloud size={16} />;
  if (action.includes("PUBLIC")) return <Youtube size={16} />;
  if (action.includes("ANALYTICS") || event.phase.toUpperCase() === "LEARNING") return <TrendingUp size={16} />;
  if (event.status === "ERROR" || event.status === "WARNING") return <AlertTriangle size={16} />;
  if (event.status === "SUCCESS") return <CheckCircle2 size={16} />;
  return <Activity size={16} />;
}

export function AutonomousOperationsConsole({
  status,
  message,
  currentTitle,
  heartbeatAt,
  startedAt,
  blockedCount = 0,
  archivedCount = 0,
  completedCount = 0,
  onPause,
  onResume,
  embeddedControls = false,
}: Props) {
  const cached = autonomyViewCache;
  const [autonomy, setAutonomy] = useState<YouTubeAutonomyStatus | null>(() => cached?.autonomy ?? null);
  const [connection, setConnection] = useState<YouTubeConnection | null>(() => cached?.connection ?? null);
  const [events, setEvents] = useState<AutonomousActivityEvent[]>(() => cached?.events ?? []);
  const [publications, setPublications] = useState<YouTubePublication[]>(() => cached?.publications ?? []);
  const [details, setDetails] = useState<Record<string, YouTubePublicationDetail>>(() => cached?.details ?? {});
  const [filter, setFilter] = useState<"ALL" | "PRODUCTION" | "YOUTUBE" | "LEARNING" | "ISSUES">(() => cached?.filter ?? "ALL");
  const [activityWindow, setActivityWindow] = useState<"TODAY" | "7D" | "30D" | "ALL">(() => cached?.activityWindow ?? "7D");
  const [visibleActivityCount, setVisibleActivityCount] = useState(() => cached?.visibleActivityCount ?? ACTIVITY_PAGE_SIZE);
  const [showReleaseHistory, setShowReleaseHistory] = useState(() => cached?.showReleaseHistory ?? true);
  const [visibleReleaseHistoryCount, setVisibleReleaseHistoryCount] = useState(() => cached?.visibleReleaseHistoryCount ?? RELEASE_HISTORY_LIMIT);
  const [expandedEventIds, setExpandedEventIds] = useState<Set<string>>(() => new Set());
  const [loading, setLoading] = useState(() => !cached);
  const [refreshing, setRefreshing] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [performanceRefreshingId, setPerformanceRefreshingId] = useState<string | null>(null);
  const [detailErrors, setDetailErrors] = useState<Record<string, string>>({});
  const performanceRefreshRef = useRef(false);
  const evidenceSignatureRef = useRef("");
  const detailRequestVersionRef = useRef<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);
  const detailRefreshAtRef = useRef(0);

  async function load(includeDetails = false): Promise<void> {
    setError(null);
    try {
      const snapshot = await getYouTubeAutonomySnapshot(ACTIVITY_LIMIT);
      const sortedEvents = snapshot.activity.slice().sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at));
      const sortedPublications = snapshot.publications.slice().sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
      setAutonomy(snapshot.autonomy);
      setConnection(snapshot.connection);
      setEvents(sortedEvents);
      setPublications(sortedPublications);

      autonomyViewCache = {
        cachedAt: Date.now(),
        autonomy: snapshot.autonomy,
        connection: snapshot.connection,
        events: sortedEvents,
        publications: sortedPublications,
        details: autonomyViewCache?.details ?? details,
        filter,
        activityWindow,
        visibleActivityCount,
        showReleaseHistory,
        visibleReleaseHistoryCount,
      };

      const evidenceSignature = snapshot.activity.filter(event => event.action.toUpperCase().includes("ANALYTICS"))
        .map(event => event.event_id).join("|");
      const detailDue = includeDetails || evidenceSignature !== evidenceSignatureRef.current
        || Date.now() - detailRefreshAtRef.current >= detailRefreshMs(status);
      if (detailDue && sortedPublications.length) {
        const recent = currentPublications(sortedPublications).slice(0, RECENT_PUBLICATION_DETAILS);
        const versions = recent.map(item => {
          const version = (detailRequestVersionRef.current[item.publication_id] || 0) + 1;
          detailRequestVersionRef.current[item.publication_id] = version;
          return version;
        });
        const resolved = await Promise.allSettled(recent.map((item) => getYouTubePublication(item.publication_id)));
        setDetails((current) => {
          const next = { ...current };
          resolved.forEach((result, index) => {
            const id = recent[index].publication_id;
            if (detailRequestVersionRef.current[id] === versions[index] && result.status === "fulfilled") next[id] = result.value;
          });
          if (autonomyViewCache) {
            autonomyViewCache = { ...autonomyViewCache, cachedAt: Date.now(), details: next };
          }
          return next;
        });
        setDetailErrors(current => {
          const next = { ...current };
          resolved.forEach((result, index) => {
            const id = recent[index].publication_id;
            if (detailRequestVersionRef.current[id] !== versions[index]) return;
            if (result.status === "fulfilled") delete next[id];
            else next[id] = "Performance details could not be refreshed. Showing the last loaded evidence if available.";
          });
          return next;
        });
        // Failed detail requests remain due rather than being cached for minutes.
        if (resolved.every(result => result.status === "fulfilled")) {
          detailRefreshAtRef.current = Date.now();
          evidenceSignatureRef.current = evidenceSignature;
        }
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;

    const schedule = () => {
      if (cancelled) return;
      timer = window.setTimeout(async () => {
        if (!cancelled) await load(false);
        schedule();
      }, autonomyRefreshMs(status, document.hidden));
    };

    const onVisibility = () => {
      if (!document.hidden && !cancelled) void load(false);
      if (timer != null) window.clearTimeout(timer);
      schedule();
    };

    const cacheIsFresh = Boolean(
      autonomyViewCache
      && Date.now() - autonomyViewCache.cachedAt < AUTONOMY_VIEW_CACHE_MS
      && autonomyViewCache.publications.length + autonomyViewCache.events.length > 0
    );

    if (cacheIsFresh) {
      setLoading(false);
      schedule();
    } else {
      // When cached data exists but is stale, keep it visible and refresh silently.
      if (autonomyViewCache) setLoading(false);
      void load(true).finally(schedule);
    }
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisibility);
      if (timer != null) window.clearTimeout(timer);
    };
  }, [status]);

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const payload = event.data;
      if (payload === "reviveai-youtube-connected" || payload?.type === "reviveai-youtube-connected") {
        setConnecting(false);
        void load(true);
      }
      if (payload?.type === "reviveai-youtube-error") {
        setConnecting(false);
        setError(payload.message || "YouTube connection failed.");
      }
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);

  async function connectYouTube(): Promise<void> {
    setConnecting(true);
    setError(null);
    try {
      const response = await startYouTubePublisherConnection();
      const popup = window.open(response.authorization_url, "reviveai-youtube-oauth", "width=620,height=760");
      if (!popup) throw new Error("Your browser blocked the YouTube authorization window. Allow pop-ups for ReviveAI and try again.");
      const timer = window.setInterval(() => {
        if (!popup.closed) return;
        window.clearInterval(timer);
        setConnecting(false);
        void load(true);
      }, 700);
    } catch (caught) {
      setConnecting(false);
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  const continuousEnabled = Boolean(autonomy?.continuous_campaign_enabled);
  const autonomousReady = Boolean(
    autonomy?.autonomous_publish_enabled
    && autonomy?.autonomous_final_approval_enabled
    && continuousEnabled
    && connection?.connected,
  );

  const heartbeatMs = parseTime(heartbeatAt);
  const heartbeatAgeSeconds = heartbeatMs == null ? null : Math.max(0, Math.round((Date.now() - heartbeatMs) / 1000));
  const heartbeatHealthy = status !== "RUNNING" || (heartbeatAgeSeconds != null && heartbeatAgeSeconds <= 90);

  const nextScheduled = useMemo(() => publications
    .filter((item) => item.status === "SCHEDULED" && item.publish_at)
    .sort((a, b) => Date.parse(a.publish_at || "") - Date.parse(b.publish_at || ""))[0] || null, [publications]);

  const activeUpload = useMemo(() => publications.find((item) => item.status === "UPLOADING") || null, [publications]);
  const activePublications = useMemo(() => currentPublications(publications), [publications]);

  const publicationById = useMemo(() => {
    const map = new Map<string, YouTubePublication>();
    publications.forEach((publication) => map.set(publication.publication_id, publication));
    return map;
  }, [publications]);

  const publicationByRecommendation = useMemo(() => {
    // `publications` is newest-first, so the first match is the latest state.
    const map = new Map<string, YouTubePublication>();
    publications.forEach((publication) => {
      if (publication.recommendation_id && !map.has(publication.recommendation_id)) {
        map.set(publication.recommendation_id, publication);
      }
    });
    return map;
  }, [publications]);

  function eventVideoTitle(event: AutonomousActivityEvent): string | null {
    if (!isYouTubeRelatedEvent(event)) return null;

    const explicitTitle = event.details?.video_title;
    if (typeof explicitTitle === "string" && explicitTitle.trim()) {
      return explicitTitle.trim();
    }

    if (event.publication_id) {
      const publication = publicationById.get(event.publication_id);
      if (publication) return publicationTitle(publication);
    }

    if (event.recommendation_id) {
      const publication = publicationByRecommendation.get(event.recommendation_id);
      if (publication) return publicationTitle(publication);
    }

    return null;
  }

  const primaryPerformanceCheckpoint = autonomy?.primary_performance_checkpoint || "24H";
  const performance = useMemo(() => summarizePerformance(activePublications
    .filter(publication => publication.status === "PUBLISHED" && publication.public_confirmed_at)
    .map(publication => snapshotAtCheckpoint(details[publication.publication_id], primaryPerformanceCheckpoint))),
  [details, activePublications, primaryPerformanceCheckpoint]);

  async function refreshPerformance(publication: YouTubePublication): Promise<void> {
    if (performanceRefreshRef.current) return;
    performanceRefreshRef.current = true;
    setPerformanceRefreshingId(publication.publication_id);
    setError(null);
    // Invalidate older detail reads before and after the provider refresh.
    const id = publication.publication_id;
    detailRequestVersionRef.current[id] = (detailRequestVersionRef.current[id] || 0) + 1;
    try {
      const fresh = await refreshYouTubeAnalytics(id);
      detailRequestVersionRef.current[id] = (detailRequestVersionRef.current[id] || 0) + 1;
      setDetails(current => ({ ...current, [id]: {
        publication: current[id]?.publication || publication,
        snapshots: [...(current[id]?.snapshots || []).filter(item => item.checkpoint !== fresh.checkpoint), fresh],
      } }));
      setDetailErrors(current => { const next = { ...current }; delete next[id]; return next; });
      await load(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to refresh YouTube performance.");
    } finally {
      performanceRefreshRef.current = false;
      setPerformanceRefreshingId(null);
    }
  }

  const filteredEvents = useMemo(() => {
    const now = Date.now();
    const cutoff = activityWindow === "TODAY" ? now - 24 * 60 * 60 * 1000
      : activityWindow === "7D" ? now - 7 * 24 * 60 * 60 * 1000
        : activityWindow === "30D" ? now - 30 * 24 * 60 * 60 * 1000
          : null;

    return events.filter((event) => {
      const occurredAt = parseTime(event.occurred_at);
      if (cutoff != null && occurredAt != null && occurredAt < cutoff) return false;
      if (filter === "ALL") return true;
      if (filter === "ISSUES") return event.status === "ERROR" || event.status === "WARNING";
      if (filter === "LEARNING") return event.phase.toUpperCase() === "LEARNING" || event.action.toUpperCase().includes("ANALYTICS");
      if (filter === "YOUTUBE") return event.phase.toUpperCase() === "YOUTUBE" || /UPLOAD|PUBLIC|YOUTUBE/.test(event.action.toUpperCase());
      return !["YOUTUBE", "LEARNING"].includes(event.phase.toUpperCase());
    });
  }, [events, filter, activityWindow]);

  const visibleEvents = useMemo(
    () => filteredEvents.slice(0, visibleActivityCount),
    [filteredEvents, visibleActivityCount],
  );

  useEffect(() => {
    setVisibleActivityCount(ACTIVITY_PAGE_SIZE);
  }, [filter, activityWindow]);

  useEffect(() => {
    if (!autonomyViewCache) return;
    autonomyViewCache = {
      ...autonomyViewCache,
      filter,
      activityWindow,
      visibleActivityCount,
      showReleaseHistory,
      visibleReleaseHistoryCount,
    };
  }, [filter, activityWindow, visibleActivityCount, showReleaseHistory, visibleReleaseHistoryCount]);

  const releaseQueues = useMemo(() => {
    const operational: YouTubePublication[] = [];
    const history: YouTubePublication[] = [];

    for (const publication of activePublications) {
      const snapshot = latestSnapshot(details[publication.publication_id]);
      const learningComplete = publication.status === "PUBLISHED" && Boolean(snapshot?.learning_synced);
      if (learningComplete) history.push(publication);
      else operational.push(publication);
    }

    operational.sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
    history.sort((a, b) => publicationReleaseTimestamp(b) - publicationReleaseTimestamp(a));

    return { operational, history };
  }, [activePublications, details]);

  const visibleOperationalPublications = useMemo(
    () => releaseQueues.operational.slice(0, RELEASE_QUEUE_LIMIT),
    [releaseQueues.operational],
  );

  const visibleHistoricalPublications = useMemo(
    () => releaseQueues.history.slice(0, visibleReleaseHistoryCount),
    [releaseQueues.history, visibleReleaseHistoryCount],
  );

  const latestApproval = useMemo(() => events.find((event) => event.action === "AUTONOMOUS_FINAL_APPROVAL") || null, [events]);
  const timeZone = autonomy?.publish_timezone || "Asia/Manila";
  const approvalEnabled = Boolean(autonomy?.autonomous_final_approval_enabled);
  const publishingEnabled = Boolean(autonomy?.autonomous_publish_enabled);
  const youtubeConnected = Boolean(connection?.connected);
  const setupRemaining = [!approvalEnabled, !publishingEnabled, !continuousEnabled, !youtubeConnected].filter(Boolean).length;
  const waitingForApproval = status === "WAITING_FOR_FINAL_APPROVAL";
  const waitingForLearning = status === "WAITING_FOR_LEARNING";

  const currentOperationPublication = useMemo(() => {
    if (!waitingForLearning || !activePublications.length) return null;

    const normalizedCurrentTitle = currentTitle?.trim().toLocaleLowerCase();
    if (normalizedCurrentTitle) {
      const exactTitleMatch = activePublications.find(
        (publication) => publicationTitle(publication).trim().toLocaleLowerCase() === normalizedCurrentTitle,
      );
      if (exactTitleMatch) return exactTitleMatch;
    }

    // During WAITING_FOR_LEARNING the current publication is normally the newest
    // operational release. Prefer scheduled/uploading rows first, then a published
    // release whose learning checkpoint has not been synchronized yet.
    const scheduledOrUploading = activePublications.find(
      (publication) => publication.status === "SCHEDULED" || publication.status === "UPLOADING",
    );
    if (scheduledOrUploading) return scheduledOrUploading;

    return activePublications.find((publication) => {
      if (publication.status !== "PUBLISHED") return false;
      return !latestSnapshot(details[publication.publication_id])?.learning_synced;
    }) || null;
  }, [waitingForLearning, activePublications, currentTitle, details]);

  const currentOperationSnapshot = currentOperationPublication
    ? latestSnapshot(details[currentOperationPublication.publication_id])
    : null;

  const currentOperationIsPublic = Boolean(
    currentOperationPublication
    && (
      currentOperationPublication.status === "PUBLISHED"
      || currentOperationPublication.privacy_status?.toLowerCase() === "public"
      || currentOperationPublication.public_confirmed_at
      || currentOperationPublication.public_release_at
    ),
  );

  const waitingForScheduledRelease = Boolean(
    waitingForLearning
    && currentOperationPublication
    && !currentOperationIsPublic
    && (
      currentOperationPublication.status === "SCHEDULED"
      || currentOperationPublication.status === "UPLOADING"
      || currentOperationPublication.publish_at
    ),
  );

  const activelyLearningFromRelease = Boolean(
    waitingForLearning
    && currentOperationPublication
    && currentOperationIsPublic
    && !currentOperationSnapshot?.learning_synced,
  );

  const waitingForReleaseSchedule = Boolean(
    waitingForScheduledRelease
    && currentOperationPublication
    && !currentOperationPublication.publish_at
  );

  const currentOperationLabel = waitingForScheduledRelease
    ? waitingForReleaseSchedule
      ? "Waiting for release schedule"
      : "Waiting for scheduled release"
    : activelyLearningFromRelease
      ? "Learning from latest release"
      : statusLabel(status);

  const currentOperationTitle = currentOperationPublication
    ? publicationTitle(currentOperationPublication)
    : currentTitle || null;

  const nextReleaseCardPublication = waitingForScheduledRelease && currentOperationPublication
    ? currentOperationPublication
    : nextScheduled;

  const currentOperationMessage = waitingForScheduledRelease
    ? `Continuous Autopilot is waiting for this video to become public${currentOperationPublication?.publish_at ? ` at ${formatDateTime(currentOperationPublication.publish_at, timeZone)}` : ""}. The ${autonomy?.next_production_checkpoint || "6H"} learning checkpoint begins only after YouTube confirms the public release.`
    : activelyLearningFromRelease
      ? `ReviveAI is collecting the ${autonomy?.next_production_checkpoint || "6H"} early signal so the next production can start while longer-term learning continues in parallel.`
      : message || "Waiting for the next autonomous action.";

  const heroTitle = waitingForScheduledRelease
    ? "ReviveAI is waiting for the latest release to go public before beginning the next learning checkpoint."
    : activelyLearningFromRelease
      ? "ReviveAI is learning from the latest release before choosing what to produce next."
      : waitingForLearning
        ? "ReviveAI is preparing the early performance checkpoint used to unlock the next production."
        : autonomousReady
          ? "Autonomy is active. You can monitor the channel from this timeline."
          : waitingForApproval && !approvalEnabled
            ? "Final video is ready, but autonomous approval is still gated."
            : "Autonomy is staged, but release safety is still gated.";

  const controlHint = status === "NEEDS_ATTENTION"
    ? "Resolve the issue shown in the activity log before continuing."
    : waitingForApproval && !approvalEnabled
      ? "Enable autonomous final approval to remove the last human approval gate."
      : waitingForApproval
        ? "AI approval is enabled. The backend supervisor will continue when the gate is verified."
        : waitingForScheduledRelease
          ? `Learning has not started yet. ReviveAI will begin the ${autonomy?.next_production_checkpoint || "6H"} checkpoint after YouTube confirms the scheduled video is public.`
          : activelyLearningFromRelease
            ? `ReviveAI will continue after verified ${autonomy?.next_production_checkpoint || "6H"} public statistics (or the configured maximum wait). Delayed Analytics will be reconciled separately.`
            : waitingForLearning
              ? `ReviveAI is waiting for the current release lifecycle to reach a verifiable learning state before continuing.`
              : status === "COMPLETED"
                ? continuousEnabled
                  ? "The saved campaign is complete. Continuous mode will adopt a durable completed publication when another eligible idea remains."
                  : "The current campaign is complete."
                : status === "IDLE"
                  ? "Start an Autopilot campaign from Intelligence when you are ready."
                  : null;

  if (loading) {
    return (
      <section className="autonomy-console glass-card autonomy-console-loading" aria-live="polite">
        <LoaderCircle className="spin" size={22} />
        <div><strong>Opening Autonomous Operations</strong><span>Loading supervisor, publishing, approval, and learning activity…</span></div>
      </section>
    );
  }

  return (
    <section className="autonomy-console" aria-label="ReviveAI autonomous operations">
      {!embeddedControls && <div className="autonomy-hero glass-card">
        <div className="autonomy-hero-copy autonomy-hero-copy-compact">
          <div className="autonomy-kicker"><Bot size={16} /> Autonomous Operations</div>
          <h2>{currentOperationLabel}</h2>

          {currentOperationTitle && (
            <div className="autonomy-current-production">
              <Radio size={15} />
              <strong>{currentOperationTitle}</strong>
            </div>
          )}

          <p className="autonomy-hero-summary">
            {waitingForScheduledRelease
              ? currentOperationPublication?.publish_at
                ? `Scheduled ${formatDateTime(currentOperationPublication.publish_at, timeZone)} · learning starts after YouTube confirms the video is public.`
                : "The release is prepared but does not have a public release time yet."
              : activelyLearningFromRelease
                ? `${autonomy?.next_production_checkpoint || "6H"} learning checkpoint · collecting verified public performance.`
                : currentOperationMessage}
          </p>
        </div>

        <div className="autonomy-hero-controls">
          <div className="autonomy-control-row">
            <span className={`autonomy-mode-pill ${autonomousReady ? "ready" : "setup"}`}>
              {autonomousReady ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
              {autonomousReady ? "Full autonomy ready" : `${setupRemaining} setup item${setupRemaining === 1 ? "" : "s"} remaining`}
            </span>
            <button className="secondary-button autonomy-refresh-button" type="button" onClick={() => { setRefreshing(true); void load(true); }} disabled={refreshing}>
              {refreshing ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />} Refresh
            </button>
          </div>

          {(status === "RUNNING" || waitingForLearning) && (
            <button className="secondary-button autonomy-pause-button autonomy-main-action" type="button" onClick={onPause}>
              <CirclePause size={16} /> Pause automation
            </button>
          )}
          {status === "PAUSED" && (
            <button className="primary-button autonomy-main-action" type="button" onClick={onResume}>
              <CirclePlay size={16} /> Resume automation
            </button>
          )}
          {waitingForApproval && !approvalEnabled && (
            <div className="autonomy-control-note warning"><ShieldCheck size={16} /><span>Final approval setup required</span></div>
          )}
          {waitingForApproval && approvalEnabled && (
            <div className="autonomy-control-note ready"><LoaderCircle className="spin" size={16} /><span>AI approval gate is being verified</span></div>
          )}
          {activelyLearningFromRelease && (
            <div className="autonomy-control-note ready"><TrendingUp size={16} /><span>Collecting performance evidence before the next production</span></div>
          )}
          {waitingForLearning && !waitingForScheduledRelease && !activelyLearningFromRelease && (
            <div className="autonomy-control-note ready"><Clock3 size={16} /><span>Preparing the next learning checkpoint</span></div>
          )}
          {status === "NEEDS_ATTENTION" && (
            <>
              <div className="autonomy-control-note danger"><AlertTriangle size={16} /><span>Review the issue below</span></div>
              <button className="primary-button autonomy-main-action" type="button" onClick={onResume}>
                <CirclePlay size={16} /> Retry after fix
              </button>
            </>
          )}
        </div>
      </div>}

      {error && <div className="autonomy-alert error" role="alert"><AlertTriangle size={18} /><span>{error}</span></div>}

      {!autonomousReady && (
        <div className="autonomy-setup-banner glass-card">
          <div className="autonomy-setup-icon"><ShieldCheck size={20} /></div>
          <div className="autonomy-setup-copy">
            <strong>{setupRemaining} setup item{setupRemaining === 1 ? "" : "s"} remaining</strong>
            <span>Complete the pending connection or safety gate to restore full autonomy.</span>
            <div className="autonomy-setup-checks" aria-label="Autonomy setup status">
              <span className={approvalEnabled ? "ok" : "pending"}>
                {approvalEnabled ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />} AI final approval <b>{approvalEnabled ? "Enabled" : "Disabled"}</b>
              </span>
              <span className={publishingEnabled ? "ok" : "pending"}>
                {publishingEnabled ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />} YouTube publishing <b>{publishingEnabled ? "Enabled" : "Disabled"}</b>
              </span>
              <span className={continuousEnabled ? "ok" : "pending"}>
                {continuousEnabled ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />} Continuous campaign <b>{continuousEnabled ? "Enabled" : "Disabled"}</b>
              </span>
              <span className={youtubeConnected ? "ok" : "pending"}>
                {youtubeConnected ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />} YouTube connection <b>{youtubeConnected ? "Connected" : "Not connected"}</b>
              </span>
            </div>
          </div>
          {!youtubeConnected && (
            <button className="primary-button autonomy-setup-action" type="button" disabled={connecting} onClick={() => void connectYouTube()}>
              {connecting ? <LoaderCircle className="spin" size={16} /> : <Youtube size={16} />} Connect YouTube
            </button>
          )}
        </div>
      )}

      <div className="autonomy-health-grid">
        <article className="autonomy-health-card glass-card">
          <span><Radio size={16} /> Supervisor</span>
          <strong>{heartbeatHealthy ? "Healthy" : "Needs attention"}</strong>
          <small>{heartbeatAt ? `Heartbeat ${relativeTime(heartbeatAt)}` : status === "RUNNING" ? "Waiting for first heartbeat" : "Heartbeat resumes when running"}</small>
          <div className={`autonomy-health-dot ${heartbeatHealthy ? "ok" : "bad"}`}>
            {statusLabel(status)}
          </div>
        </article>
        <article className="autonomy-health-card glass-card">
          <span><Youtube size={16} /> YouTube</span>
          <strong>{connection?.connected ? connection.channel_title || "Connected" : "Not connected"}</strong>
          <small>{autonomy?.autonomous_publish_enabled ? "Autonomous publishing enabled" : "Autonomous publishing disabled"}</small>
          <div className={`autonomy-health-dot ${connection?.connected && autonomy?.autonomous_publish_enabled ? "ok" : "warn"}`}>{connection?.connected ? "Connection saved" : "Action required"}</div>
          <button
            className="autonomy-youtube-reconnect"
            type="button"
            disabled={connecting}
            onClick={() => void connectYouTube()}
            title={connection?.connected ? "Renew Google authorization for this YouTube channel" : "Authorize YouTube publishing"}
          >
            {connecting ? <LoaderCircle className="spin" size={13} /> : <RefreshCw size={13} />}
            {connecting ? "Opening Google…" : connection?.connected ? "Reconnect YouTube" : "Connect YouTube"}
          </button>
        </article>
        <article className="autonomy-health-card glass-card autonomy-next-release-card">
          <span><CalendarClock size={16} /> Next release</span>
          <strong>
            {nextReleaseCardPublication
              ? publicationTitle(nextReleaseCardPublication)
              : activeUpload
                ? publicationTitle(activeUpload)
                : "No release selected"}
          </strong>
          <small>
            {nextReleaseCardPublication?.publish_at
              ? formatDateTime(nextReleaseCardPublication.publish_at, timeZone)
              : nextReleaseCardPublication
                ? "Release time not scheduled"
                : activeUpload
                  ? "YouTube upload is still in progress"
                  : "Planner will choose the next eligible window"}
          </small>
          <div className="autonomy-health-dot neutral">
            {nextReleaseCardPublication?.publish_at
              ? untilTime(nextReleaseCardPublication.publish_at)
              : nextReleaseCardPublication
                ? "Schedule required"
                : `${autonomy?.scheduled_count ?? 0} scheduled`}
          </div>
        </article>
        <article className="autonomy-health-card glass-card">
          <span><TrendingUp size={16} /> Learning loop</span>
          <strong>{performance.observations ? `${performance.observations} release${performance.observations === 1 ? "" : "s"} with statistics` : "Waiting for public data"}</strong>
          <small>{performance.verifiedLearning} with Analytics · {performance.pendingLearning} pending · {completedCount} productions completed{continuousEnabled ? ` · next decision after ${autonomy?.next_production_checkpoint || "6H"}` : ""}</small>
          <div className={`autonomy-health-dot ${blockedCount ? "warn" : "ok"}`}>
            {blockedCount
              ? `${blockedCount} need attention`
              : archivedCount
                ? `${archivedCount} historical exception${archivedCount === 1 ? "" : "s"} archived`
                : "No blocking production"}
          </div>
        </article>
      </div>

      <div className="autonomy-main-grid">
        <div className="autonomy-primary-column">
          <article className="autonomy-section glass-card">
            <div className="autonomy-section-head">
              <div>
                <span className="eyebrow"><Activity size={15} /> Activity log</span>
                <h3>Recent autonomous activity</h3>
                <p>Scan the latest actions. Expand an item only when you need the full evidence.</p>
              </div>
              <span className="autonomy-live-chip"><span /> Live</span>
            </div>

            <div className="autonomy-activity-toolbar">
              <div className="autonomy-filter-row" role="tablist" aria-label="Activity filters">
                {(["ALL", "PRODUCTION", "YOUTUBE", "LEARNING", "ISSUES"] as const).map((item) => (
                  <button key={item} type="button" className={filter === item ? "active" : ""} onClick={() => setFilter(item)}>
                    {item === "ALL" ? "All activity" : item === "PRODUCTION" ? "Production + approval" : item === "YOUTUBE" ? "YouTube" : item === "LEARNING" ? "Learning" : "Issues"}
                  </button>
                ))}
              </div>
              <label className="autonomy-time-filter">
                <span>Range</span>
                <select value={activityWindow} onChange={(event) => setActivityWindow(event.target.value as "TODAY" | "7D" | "30D" | "ALL")}>
                  <option value="TODAY">Last 24 hours</option>
                  <option value="7D">Last 7 days</option>
                  <option value="30D">Last 30 days</option>
                  <option value="ALL">All loaded</option>
                </select>
              </label>
            </div>

            {filteredEvents.length ? (
              <>
                <div className="autonomy-activity-summary">
                  {Math.min(visibleEvents.length, filteredEvents.length)} recent event{Math.min(visibleEvents.length, filteredEvents.length) === 1 ? "" : "s"}
                  {filteredEvents.length > visibleEvents.length ? ` · ${filteredEvents.length - visibleEvents.length} older matching` : ""}
                </div>
                <div className="autonomy-timeline autonomy-timeline-scroll">
                  {visibleEvents.map((event) => {
                    const detailEntries = safeDetailEntries(event, timeZone);
                    const videoTitle = eventVideoTitle(event);
                    const expanded = expandedEventIds.has(event.event_id);
                    const summaryEntries = detailEntries
                      .filter(([label]) => ["Learning checkpoint", "Views", "Likes", "Statistics", "Analytics"].includes(label))
                      .slice(0, 3);

                    return (
                      <article
                        key={event.event_id}
                        className={`autonomy-event autonomy-event-compact ${expanded ? "expanded" : ""} status-${event.status.toLowerCase()} action-${event.action.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}
                      >
                        <div className="autonomy-event-rail"><span>{eventIcon(event)}</span></div>
                        <div className="autonomy-event-body">
                          <button
                            type="button"
                            className="autonomy-event-toggle"
                            aria-expanded={expanded}
                            onClick={() => setExpandedEventIds((current) => {
                              const next = new Set(current);
                              if (next.has(event.event_id)) next.delete(event.event_id);
                              else next.add(event.event_id);
                              return next;
                            })}
                          >
                            <div className="autonomy-event-toggle-main">
                              <div className="autonomy-event-top">
                                <div>
                                  <strong>{event.action.split("_").join(" ")}</strong>
                                  <span>{event.phase}</span>
                                </div>
                                <time title={formatDateTime(event.occurred_at, timeZone)}>{relativeTime(event.occurred_at)}</time>
                              </div>

                              {videoTitle && (
                                <div className="autonomy-event-video-title compact">
                                  <Youtube size={13} />
                                  <strong>{videoTitle}</strong>
                                </div>
                              )}

                              {summaryEntries.length > 0 && (
                                <div className="autonomy-event-summary-chips">
                                  {summaryEntries.map(([label, value]) => (
                                    <span key={`${event.event_id}-summary-${label}`}>
                                      <b>{label}</b> {value}
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>
                            <span className="autonomy-event-chevron" aria-hidden="true">
                              {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                            </span>
                          </button>

                          {expanded && (
                            <div className="autonomy-event-expanded">
                              {event.message && <p>{event.message}</p>}
                              {detailEntries.length > 0 && (
                                <div className="autonomy-event-details">
                                  {detailEntries.map(([label, value]) => (
                                    <span key={`${event.event_id}-${label}`}><b>{label}</b>{value}</span>
                                  ))}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      </article>
                    );
                  })}
                </div>
                {visibleEvents.length < filteredEvents.length && (
                  <div className="autonomy-load-more-row">
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => setVisibleActivityCount((current) => current + ACTIVITY_PAGE_SIZE)}
                    >
                      Load older activity
                    </button>
                  </div>
                )}
              </>
            ) : (
              <div className="autonomy-empty-state"><Activity size={20} /><strong>No matching activity yet.</strong><span>New autonomous actions will appear here automatically.</span></div>
            )}
          </article>
        </div>

        <aside className="autonomy-side-column">
          <article className="autonomy-section glass-card autonomy-objective-card">
            <span className="eyebrow"><Sparkles size={15} /> Autonomous objective</span>
            <h3>Increase durable audience response</h3>
            <p className="autonomy-primary-cohort-note">Compared at the same {primaryPerformanceCheckpoint} release age.</p>
            <div className="autonomy-metric-grid">
              <div><span>Measured views</span><strong>{formatSummary(performance.views)}</strong><small>{summaryCoverage(performance.views)}</small></div>
              <div><span>Avg viewed</span><strong>{formatSummary(performance.weightedViewed, "percent")}</strong><small>{summaryCoverage(performance.weightedViewed)}</small></div>
              <div><span>Shares</span><strong>{formatSummary(performance.shares)}</strong><small>{summaryCoverage(performance.shares)}</small></div>
              <div><span>Net subscribers</span><strong>{formatSummary(performance.netSubscribers, "signed")}</strong><small>{summaryCoverage(performance.netSubscribers)}</small></div>
            </div>
          </article>

          <article className="autonomy-section glass-card">
            <div className="autonomy-section-head compact">
              <div>
                <span className="eyebrow"><UploadCloud size={15} /> Release queue</span>
                <h3>Release queue</h3>
                <p>{releaseQueues.operational.length} active · {releaseQueues.history.length} completed release{releaseQueues.history.length === 1 ? "" : "s"}</p>
              </div>
            </div>
            <div className="autonomy-cadence-strip">
              <div><CalendarClock size={15} /><span><strong>Daily publishing</strong> · one release every 24 hours</span></div>
              <small>Next production unlock: {autonomy?.next_production_checkpoint || "6H"} early signal · Primary comparison: {autonomy?.primary_performance_checkpoint || "24H"}</small>
            </div>
            {visibleOperationalPublications.length ? (
              <div className="autonomy-publication-list autonomy-release-queue-list">
                {visibleOperationalPublications.map((publication) => {
                  const percent = uploadPercent(publication);
                  const snapshot = latestSnapshot(details[publication.publication_id]);
                  const isPublic = publication.status === "PUBLISHED" || publication.privacy_status?.toLowerCase() === "public";
                  const releaseStatus = publication.status === "SCHEDULED"
                    ? publication.publish_at
                      ? "SCHEDULED · PRIVATE"
                      : "AWAITING SCHEDULE"
                    : publication.status;
                  const externalUrl = isPublic
                    ? publication.youtube_url || (publication.youtube_video_id ? `https://www.youtube.com/watch?v=${encodeURIComponent(publication.youtube_video_id)}` : null)
                    : publication.youtube_video_id
                      ? `https://studio.youtube.com/video/${encodeURIComponent(publication.youtube_video_id)}/edit`
                      : null;
                  const externalLabel = isPublic ? "Watch" : "Studio";
                  const releaseTiming = publicationReleaseTiming(publication);
                  return (
                    <article className={`autonomy-publication status-${publication.status.toLowerCase()}`} key={publication.publication_id}>
                      <div className="autonomy-publication-head">
                        <div><strong>{publicationTitle(publication)}</strong><span>{releaseStatus}</span></div>
                        {externalUrl && (
                          <a
                            className="autonomy-publication-link"
                            href={externalUrl}
                            target="_blank"
                            rel="noreferrer"
                            title={isPublic ? "Watch on YouTube" : "Open private/scheduled video in YouTube Studio"}
                          >
                            <span>{externalLabel}</span><ExternalLink size={14} />
                          </a>
                        )}
                      </div>
                      {publication.status === "UPLOADING" && percent != null && (
                        <div className="autonomy-upload-progress"><span style={{ width: `${percent}%` }} /><small>{percent}% uploaded</small></div>
                      )}
                      <dl className="autonomy-publication-compact-details">
                        <div>
                          <dt>{releaseTiming.at ? releaseTiming.label : "Release time"}</dt>
                          <dd>{releaseTiming.at ? formatDateTime(releaseTiming.at, timeZone) : "Not scheduled"}</dd>
                        </div>
                        {snapshot && (
                          <div>
                            <dt>{snapshot.checkpoint} performance</dt>
                            <dd>{formatMetric(snapshot, "views")} views · {formatMetric(snapshot, "average_percentage_viewed")} viewed · {formatNetSubscribers(snapshot)} subs</dd>
                          </div>
                        )}
                        {publication.primary_performance && (
                          <div className="primary-performance-row">
                            <dt>{publication.primary_performance.primary_checkpoint} primary score</dt>
                            <dd>{primaryPerformanceLine(publication)}</dd>
                          </div>
                        )}
                        {detailErrors[publication.publication_id] && <div className="error"><dt>Refresh issue</dt><dd>{detailErrors[publication.publication_id]}</dd></div>}
                        {publication.error && <div className="error"><dt>Issue</dt><dd>{publication.error}</dd></div>}
                      </dl>
                      {publication.public_confirmed_at && publication.youtube_video_id && <button
                        className="secondary-button autonomy-performance-refresh" type="button"
                        disabled={performanceRefreshingId !== null}
                        onClick={() => void refreshPerformance(publication)}>
                        {performanceRefreshingId === publication.publication_id ? <LoaderCircle className="spin" size={14} /> : <RefreshCw size={14} />}
                        Refresh performance
                      </button>}
                    </article>
                  );
                })}
                {releaseQueues.operational.length > visibleOperationalPublications.length && (
                  <div className="autonomy-queue-overflow-note">
                    {releaseQueues.operational.length - visibleOperationalPublications.length} additional active release{releaseQueues.operational.length - visibleOperationalPublications.length === 1 ? "" : "s"} are tracked. The most recently updated items are shown here.
                  </div>
                )}
              </div>
            ) : (
              <div className="autonomy-empty-state small"><CalendarClock size={18} /><strong>No active autonomous release.</strong><span>Completed releases remain available in release history below.</span></div>
            )}

            {releaseQueues.history.length > 0 && (
              <div className="autonomy-release-history">
                <button
                  type="button"
                  className="autonomy-history-toggle"
                  aria-expanded={showReleaseHistory}
                  onClick={() => setShowReleaseHistory((current) => !current)}
                >
                  <span>Release history</span>
                  <strong>{releaseQueues.history.length}</strong>
                  <span>{showReleaseHistory ? "Hide" : "Show"}</span>
                </button>

                {showReleaseHistory && (
                  <>
                    <div className="autonomy-publication-list autonomy-publication-history-list">
                      {visibleHistoricalPublications.map((publication) => {
                        const snapshot = latestSnapshot(details[publication.publication_id]);
                        const externalUrl = publication.youtube_url || (publication.youtube_video_id ? `https://www.youtube.com/watch?v=${encodeURIComponent(publication.youtube_video_id)}` : null);
                        return (
                          <article className="autonomy-publication status-published history autonomy-history-row" key={`history-${publication.publication_id}`}>
                            <div className="autonomy-history-date">
                              <CalendarClock size={14} />
                              <span>{formatDateTime(publication.public_release_at || publication.public_confirmed_at || publication.published_at, timeZone)}</span>
                            </div>
                            <div className="autonomy-publication-head">
                              <div>
                                <strong>{publicationTitle(publication)}</strong>
                                <span>{publication.primary_performance ? `${publication.primary_performance.primary_checkpoint} PRIMARY READY` : "LEARNING IN PROGRESS"}</span>
                              </div>
                              {externalUrl && (
                                <a className="autonomy-publication-link" href={externalUrl} target="_blank" rel="noreferrer" title="Watch on YouTube">
                                  <span>Watch</span><ExternalLink size={14} />
                                </a>
                              )}
                            </div>
                            {snapshot && (
                              <div className="autonomy-history-performance">
                                {formatMetric(snapshot, "views")} views · {formatMetric(snapshot, "average_percentage_viewed")} viewed · {formatNetSubscribers(snapshot)} subs
                              </div>
                            )}
                            {publication.primary_performance && (
                              <div className="autonomy-history-primary-performance">
                                {primaryPerformanceLine(publication)}
                              </div>
                            )}
                          </article>
                        );
                      })}
                    </div>
                    {visibleHistoricalPublications.length < releaseQueues.history.length && (
                      <div className="autonomy-load-more-row compact">
                        <button className="secondary-button" type="button" onClick={() => setVisibleReleaseHistoryCount((current) => current + RELEASE_HISTORY_LIMIT)}>
                          Load older releases
                        </button>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </article>

          {latestApproval && (
            <details className="autonomy-section glass-card autonomy-approval-card autonomy-disclosure-card">
              <summary>
                <span>
                  <span className="eyebrow"><ShieldCheck size={15} /> Latest autonomous approval</span>
                  <strong>Final video approved by AI Autopilot</strong>
                  <small>{formatDateTime(latestApproval.occurred_at, timeZone)}</small>
                </span>
                <ChevronDown size={16} />
              </summary>
              <div className="autonomy-disclosure-body">
                <div className="autonomy-approval-meta compact">
                  {safeDetailEntries(latestApproval, timeZone).map(([label, value]) => (
                    <span key={label}><b>{label}:</b> {value}</span>
                  ))}
                </div>
              </div>
            </details>
          )}

          <details className="autonomy-section glass-card autonomy-runtime-card autonomy-disclosure-card">
            <summary>
              <span>
                <span className="eyebrow"><BarChart3 size={15} /> Runtime details</span>
                <strong>Supervisor and publishing configuration</strong>
                <small>{heartbeatAt ? `Heartbeat ${relativeTime(heartbeatAt)}` : "Operational diagnostics"}</small>
              </span>
              <ChevronDown size={16} />
            </summary>
            <div className="autonomy-disclosure-body">
            <dl>
              <div><dt>Autopilot started</dt><dd>{formatDateTime(startedAt, timeZone)}</dd></div>
              <div><dt>Last supervisor heartbeat</dt><dd>{heartbeatAt ? `${formatDateTime(heartbeatAt, timeZone)} · ${relativeTime(heartbeatAt)}` : "—"}</dd></div>
              <div><dt>Autonomous final approval</dt><dd>{autonomy?.autonomous_final_approval_enabled ? "Enabled" : "Disabled"}</dd></div>
              <div><dt>Autonomous YouTube publishing</dt><dd>{autonomy?.autonomous_publish_enabled ? "Enabled" : "Disabled"}</dd></div>
              <div><dt>Continuous campaign</dt><dd>{continuousEnabled ? "Enabled" : "Disabled"}</dd></div>
              <div><dt>Learning checkpoint</dt><dd>{autonomy?.continuous_learning_checkpoint || "—"}</dd></div>
              <div><dt>Publication idempotency</dt><dd>{autonomy?.publication_idempotency_enabled ? "Protected" : "Unknown"}</dd></div>
              <div><dt>Publishing timezone</dt><dd>{timeZone}</dd></div>
              <div><dt>Candidate hours</dt><dd>{autonomy?.candidate_hours_local || "—"}</dd></div>
              <div><dt>Publications tracked</dt><dd>{autonomy?.publication_count ?? publications.length}</dd></div>
            </dl>
            </div>
          </details>
        </aside>
      </div>
    </section>
  );
}
