import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BarChart3, CalendarClock, CheckCircle2, ExternalLink, LoaderCircle, RefreshCw, Send, Unplug, Youtube } from "lucide-react";
import { confirmYouTubePublicationPublic, disconnectYouTubePublisher, getYouTubePublication, getYouTubePublisherConnection, listYouTubePublications, publishToYouTube, refreshYouTubeAnalytics, retryYouTubePublication, startYouTubePublisherConnection } from "../api";
import type { DeliveryPackage, PublishingDraft, RevivalProgram, YouTubeConnection, YouTubePerformanceSnapshot, YouTubePublication } from "../types";
import { formatMetric, latestPerformanceSnapshot, learningReady, metricValue, performanceStatus, publicationReleaseTiming } from "../youtubePerformance";

type Props = { deliveryPackage: DeliveryPackage; draft: PublishingDraft; recommendationId: string; program?: RevivalProgram | null; finalApproved: boolean };
const DAY_INDEX: Record<string, number> = { mon: 1, monday: 1, tue: 2, tues: 2, tuesday: 2, wed: 3, wednesday: 3, thu: 4, thur: 4, thurs: 4, thursday: 4, fri: 5, friday: 5, sat: 6, saturday: 6, sun: 0, sunday: 0 };
function dateKey(d: Date) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }
function recommendedDate(program: RevivalProgram | undefined | null, recommendationId: string): string | null {
  if (!program) return null;
  const idea = program.ideas.find(x => x.recommendation_id === recommendationId);
  if (!idea) return null;
  const slot = program.weekly_slate.find(x => x.idea_id === idea.idea_id);
  if (!slot) return null;
  const base = new Date(program.created_at);
  if (Number.isNaN(base.getTime())) return null;
  const d = new Date(base.getFullYear(), base.getMonth(), base.getDate() + ((slot.week - 1) * 7));
  const wanted = DAY_INDEX[slot.cadence_label.trim().toLowerCase()];
  if (wanted === undefined) return null;
  d.setDate(d.getDate() + ((wanted - d.getDay() + 7) % 7));
  return dateKey(d);
}
function niceDate(value: string) { return new Intl.DateTimeFormat(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" }).format(new Date(`${value}T12:00:00`)); }
function fetchedAt(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

export function YouTubePublishLoopPanel({ deliveryPackage, draft, recommendationId, program, finalApproved }: Props) {
  const [connection, setConnection] = useState<YouTubeConnection | null>(null);
  const [pubs, setPubs] = useState<YouTubePublication[]>([]);
  const [snaps, setSnaps] = useState<Record<string, YouTubePerformanceSnapshot[]>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadVersion = useRef(0);
  const popupTimer = useRef<number | null>(null);
  const matchingPublication = useCallback((p: YouTubePublication) => {
    // Older frontend publication types omit optional lineage returned by the API.
    const lineage = p as YouTubePublication & { audio_job_id?: string | null; assembly_job_id?: string | null };
    return !p.superseded_by_publication_id && (
      p.package_id === deliveryPackage.package_id ||
      p.publishing_draft_id === draft.draft_id ||
      (Boolean(lineage.audio_job_id) && lineage.audio_job_id === deliveryPackage.audio_job_id) ||
      (Boolean(lineage.assembly_job_id) && lineage.assembly_job_id === deliveryPackage.assembly_job_id) ||
      (p.recommendation_id === recommendationId &&
        (!p.program_id || !program?.program_id || p.program_id === program.program_id))
    );
  }, [deliveryPackage.package_id, deliveryPackage.audio_job_id, deliveryPackage.assembly_job_id,
        draft.draft_id, recommendationId, program?.program_id]);
  const current = useMemo(() => pubs.find(matchingPublication), [pubs, matchingPublication]);
  const target = current?.recommended_public_date || recommendedDate(program, recommendationId);

  const load = useCallback(async () => {
    const version = ++loadVersion.current;
    try {
      const [c, p] = await Promise.all([getYouTubePublisherConnection(), listYouTubePublications()]);
      const mine = p.find(matchingPublication);
      const detail = mine ? await getYouTubePublication(mine.publication_id) : null;
      if (version !== loadVersion.current) return;
      setConnection(c);
      setPubs(p);
      if (mine && detail) setSnaps(s => ({ ...s, [mine.publication_id]: detail.snapshots }));
      setError(null);
    } catch (caught) {
      if (version === loadVersion.current) setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [matchingPublication]);

  useEffect(() => {
    let stopped = false;
    let timer: number | null = null;
    const poll = async () => {
      await load();
      if (!stopped) timer = window.setTimeout(() => void poll(), document.hidden ? 300_000 : 60_000);
    };
    void poll();
    const onVisibility = () => { if (!document.hidden) void load(); };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stopped = true;
      ++loadVersion.current;
      if (timer != null) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [load]);

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      const data = event.data;
      if (data === "reviveai-youtube-connected" || data?.type === "reviveai-youtube-connected") void load();
      if (data?.type === "reviveai-youtube-error") setError(data.message || "YouTube connection failed.");
    };
    window.addEventListener("message", handler);
    return () => {
      window.removeEventListener("message", handler);
      if (popupTimer.current != null) window.clearInterval(popupTimer.current);
    };
  }, [load]);

  async function connect() {
    setBusy("connect"); setError(null);
    try {
      const response = await startYouTubePublisherConnection();
      const popup = window.open(response.authorization_url, "reviveai-youtube-oauth", "width=620,height=760");
      if (!popup) throw new Error("Your browser blocked the YouTube authorization window. Allow pop-ups for ReviveAI and try again.");
      if (popupTimer.current != null) window.clearInterval(popupTimer.current);
      popupTimer.current = window.setInterval(() => {
        if (!popup.closed) return;
        if (popupTimer.current != null) window.clearInterval(popupTimer.current);
        popupTimer.current = null;
        void load();
      }, 700);
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(null); }
  }
  async function publish() {
    if (busy || !finalApproved || draft.status !== "APPROVED" ||
        deliveryPackage.publishing_draft_id !== draft.draft_id) return;
    setBusy("publish"); setError(null);
    try {
      // A fresh server-side read protects against another tab or background upload.
      const existing = await listYouTubePublications();
      setPubs(existing);
      const duplicate = existing.find(matchingPublication);
      if (duplicate) {
        throw new Error(`A publication already exists (${duplicate.publication_id}, ${duplicate.status}). Open the existing publication instead of uploading again.`);
      }
      const verified = await getYouTubePublisherConnection();
      setConnection(verified);
      if (!verified.connected) throw new Error("YouTube is disconnected. Reconnect before uploading.");
      if (!window.confirm(`Upload this approved video as UNLISTED to ${verified.channel_title || "the connected YouTube channel"}?\n\nThis may create a new YouTube video. It will not resume Autopilot or make the video public.`)) return;
      const publication = await publishToYouTube({ package_id: deliveryPackage.package_id, publishing_draft_id: draft.draft_id,
        recommendation_id: recommendationId, program_id: program?.program_id ?? null, privacy_status: "unlisted", publish_at: null,
        recommended_public_date: target, made_for_kids: false, contains_synthetic_media: true });
      await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(null); }
  }
  async function retryUpload() {
    if (!current) return;
    setBusy("retry"); setError(null);
    try { await retryYouTubePublication(current.publication_id); await load(); }
    catch (caught) { await load(); setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(null); }
  }
  async function verifyPublic() {
    if (!current) return;
    setBusy("verify"); setError(null);
    try { await confirmYouTubePublicationPublic(current.publication_id); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(null); }
  }
  async function analytics() {
    if (!current?.youtube_video_id || !current.public_confirmed_at) return;
    setBusy("analytics"); setError(null);
    ++loadVersion.current;
    try {
      const fresh = await refreshYouTubeAnalytics(current.publication_id);
      ++loadVersion.current;
      setSnaps(previous => ({ ...previous, [current.publication_id]: [
        ...(previous[current.publication_id] || []).filter(item => item.checkpoint !== fresh.checkpoint), fresh,
      ] }));
      await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(null); }
  }
  async function disconnect() {
    setBusy("disconnect"); setError(null); ++loadVersion.current;
    try {
      const result = await disconnectYouTubePublisher();
      ++loadVersion.current;
      setConnection(result); setPubs([]); setSnaps({});
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(null); }
  }

  const latest = latestPerformanceSnapshot(current ? snaps[current.publication_id] : undefined);
  const gained = metricValue(latest, "subscribers_gained");
  const learningLabel = latest
    ? learningReady(latest) && latest.learning_synced
      ? `${latest.checkpoint} verified evidence is feeding Performance DNA`
      : `${latest.checkpoint} · ${performanceStatus(latest)}`
    : "Public release verified · performance clock started";

  return <section className="youtube-loop-panel glass-card">
    <div className="youtube-loop-head">
      <div><span className="eyebrow"><Youtube size={15} /> Closed-loop publishing</span><h3>Publish → measure → learn → plan next week</h3><p>ReviveAI recommends the release day; you keep control of the final Public switch in YouTube Studio.</p></div>
      {connection?.connected && <span className="youtube-connected"><CheckCircle2 size={15} /> {connection.channel_title || "YouTube connected"}</span>}
    </div>
    {error && <div className="inline-error" role="alert">{error}</div>}
    {!connection?.connected ? <div className="youtube-connect-card">
      <div><strong>Connect the channel you want ReviveAI to publish to</strong><small>Upload and read-only analytics permissions are requested.</small></div>
      <button className="primary-button" disabled={busy !== null} onClick={() => void connect()}>{busy === "connect" ? <LoaderCircle className="spin" size={16} /> : <Youtube size={16} />} Connect YouTube</button>
    </div> : !current ? <div className="youtube-publish-grid">
      <div><strong>Upload verified package as Unlisted</strong><p>ReviveAI uploads the approved master now, then reminds you when the loop-recommended release day is approaching.</p>
        {target && <div className="youtube-release-target"><CalendarClock size={17} /><div><span>Recommended public day</span><strong>{niceDate(target)}</strong></div></div>}
        <small>Final creator approval is required before uploading. You will make the video Public manually in YouTube Studio. ReviveAI will verify it before starting performance measurement.</small></div>
      <button className="primary-button" disabled={!finalApproved || draft.status !== "APPROVED" || deliveryPackage.publishing_draft_id !== draft.draft_id || busy !== null} onClick={() => void publish()}>{busy === "publish" ? <LoaderCircle className="spin" size={16} /> : <Send size={16} />} Upload as Unlisted</button>
    </div> : <div className="youtube-performance">
      <div className="youtube-publication-status">
        <div><strong>{current.status === "FAILED" ? "Upload failed" : current.public_confirmed_at ? "Public · measurement active" : "Uploaded · awaiting public release"}</strong><small>{current.youtube_video_id ? `YouTube video ${current.youtube_video_id}` : "Waiting for YouTube to return a video id."}</small></div>
        {current.youtube_url && <a className="secondary-button" href={current.youtube_url} target="_blank" rel="noreferrer">Open YouTube <ExternalLink size={14} /></a>}
      </div>
      <div className="youtube-performance-meta">
        <small>{publicationReleaseTiming(current).label}: {fetchedAt(publicationReleaseTiming(current).at)}</small>
        {current.status === "PUBLISHED" && current.publish_at && <small>Scheduled release: {fetchedAt(current.publish_at)}</small>}
        {current.public_release_at && current.public_confirmed_at && <small>First public verification: {fetchedAt(current.public_confirmed_at)}</small>}
      </div>
      {current.status === "FAILED" && !current.youtube_video_id && <div className="youtube-retry-card">
        <div><strong>Retry the same publication</strong>{current.error && <small className="youtube-retry-error">Last attempt: {current.error}</small>}</div>
        <button className="primary-button" disabled={busy !== null} onClick={() => void retryUpload()}>{busy === "retry" ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />} Retry upload to YouTube</button>
      </div>}
      {current.youtube_video_id && !current.public_confirmed_at && <div className="youtube-manual-release-card">
        <CalendarClock size={20} /><div><strong>{target ? `Set Public on ${niceDate(target)}` : "Set this video Public when ready"}</strong><small>Open YouTube Studio, change visibility to Public, save it, then return here and verify. The channel Publishing Queue will highlight this video as the recommended day nears.</small></div>
        <button className="primary-button" disabled={busy !== null} onClick={() => void verifyPublic()}>{busy === "verify" ? <LoaderCircle className="spin" size={16} /> : <CheckCircle2 size={16} />} I've set it Public — verify</button>
      </div>}
      <div className="youtube-metrics" aria-live="polite">
        <div><span>Views</span><strong>{formatMetric(latest, "views")}</strong><small>{formatMetric(latest, "likes")} likes · {formatMetric(latest, "comments")} comments</small></div>
        <div><span>Avg viewed</span><strong>{formatMetric(latest, "average_percentage_viewed")}</strong></div>
        <div><span>Shares</span><strong>{formatMetric(latest, "shares")}</strong></div>
        <div><span>Subscribers gained</span><strong>{gained == null ? formatMetric(latest, "subscribers_gained") : `+${gained.toLocaleString()}`}</strong></div>
      </div>
      <div className="youtube-learning-note"><BarChart3 size={18} /><div>
        <strong>{current.public_confirmed_at ? learningLabel : "Performance waits for the Public release"}</strong>
        <small>{current.public_confirmed_at ? "Views, likes and comments use current public counters. Delayed Analytics remain pending and are retried automatically; complete Analytics inform Performance DNA." : "Performance timing starts after the verified Public release."}</small>
        {latest?.statistics_observed_at && <small>Counters fetched {fetchedAt(latest.statistics_observed_at)}{latest.statistics_is_late ? " · current counts from a later fetch" : ""}</small>}
        {latest?.next_retry_at && <small>Next evidence retry: {fetchedAt(latest.next_retry_at)}</small>}
      </div></div>
      {(latest?.statistics_error || latest?.analytics_error) && <div className="youtube-evidence-error" role="status">{[latest.statistics_error, latest.analytics_error].filter(Boolean).join(" · ")}</div>}
      <button className="secondary-button" disabled={busy !== null || !current.youtube_video_id || !current.public_confirmed_at} onClick={() => void analytics()}>{busy === "analytics" ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />} Refresh performance</button>
    </div>}
    {connection?.connected && <button className="youtube-disconnect" disabled={busy !== null} onClick={() => void disconnect()}><Unplug size={13} /> Disconnect YouTube</button>}
  </section>;
}
