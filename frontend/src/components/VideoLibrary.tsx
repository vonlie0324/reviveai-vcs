import { ChevronLeft, ChevronRight, ExternalLink, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { ChannelMetrics, VideoSnapshot } from "../types";

type SortKey = "newest" | "views" | "likes" | "comments";
type TierKey = "all" | "low" | "typical" | "strong" | "exceptional";
const PAGE_SIZE = 12;

function formatNumber(value?: number | null) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(undefined, { notation: value >= 10000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(value);
}

function formatDuration(seconds: number) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  if (hours) return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

function formatDate(value?: string | null) {
  if (!value) return "Unknown date";
  return new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" }).format(new Date(value));
}

function tierFor(video: VideoSnapshot, metrics: ChannelMetrics): TierKey | "unknown" {
  const views = video.view_count;
  const p25 = metrics.views.p25;
  const p75 = metrics.views.p75;
  const p90 = metrics.views.p90;
  if (views === null || views === undefined || p25 === null || p25 === undefined || p75 === null || p75 === undefined || p90 === null || p90 === undefined) return "unknown";
  if (views < p25) return "low";
  if (views < p75) return "typical";
  if (views < p90) return "strong";
  return "exceptional";
}

function tierLabel(key: TierKey | "unknown") {
  if (key === "low") return "Lower quartile";
  if (key === "typical") return "Typical";
  if (key === "strong") return "Strong";
  if (key === "exceptional") return "Exceptional";
  return "Unclassified";
}

export function VideoLibrary({ videos, metrics }: { videos: VideoSnapshot[]; metrics: ChannelMetrics }) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("newest");
  const [tier, setTier] = useState<TierKey>("all");
  const [page, setPage] = useState(1);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const items = videos.filter((video) => {
      const matchesText = !needle || (
        video.title.toLowerCase().includes(needle) ||
        video.description.toLowerCase().includes(needle) ||
        video.tags.some((tag) => tag.toLowerCase().includes(needle))
      );
      const videoTier = tierFor(video, metrics);
      const matchesTier = tier === "all" || videoTier === tier;
      return matchesText && matchesTier;
    });

    return [...items].sort((a, b) => {
      if (sort === "views") return (b.view_count || 0) - (a.view_count || 0);
      if (sort === "likes") return (b.like_count || 0) - (a.like_count || 0);
      if (sort === "comments") return (b.comment_count || 0) - (a.comment_count || 0);
      return new Date(b.published_at || 0).getTime() - new Date(a.published_at || 0).getTime();
    });
  }, [videos, query, sort, tier, metrics]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount);
  const visible = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  function changeQuery(value: string) {
    setQuery(value);
    setPage(1);
  }

  function changeSort(value: SortKey) {
    setSort(value);
    setPage(1);
  }

  function changeTier(value: TierKey) {
    setTier(value);
    setPage(1);
  }

  return (
    <section className="library-section" id="evidence-library">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Evidence library</span>
          <h2>Inspect the videos behind the metrics</h2>
          <p>{filtered.length.toLocaleString()} of {videos.length.toLocaleString()} retrieved videos</p>
        </div>
        <div className="library-controls">
          <label className="search-control">
            <Search size={17} aria-hidden="true" />
            <input value={query} onChange={(e) => changeQuery(e.target.value)} placeholder="Search titles, descriptions, tags" aria-label="Search uploaded videos" />
          </label>
          <select value={tier} onChange={(e) => changeTier(e.target.value as TierKey)} aria-label="Filter by channel performance tier">
            <option value="all">All tiers</option>
            <option value="exceptional">Exceptional</option>
            <option value="strong">Strong</option>
            <option value="typical">Typical range</option>
            <option value="low">Lower quartile</option>
          </select>
          <select value={sort} onChange={(e) => changeSort(e.target.value as SortKey)} aria-label="Sort videos">
            <option value="newest">Newest first</option>
            <option value="views">Most viewed</option>
            <option value="likes">Most liked</option>
            <option value="comments">Most commented</option>
          </select>
        </div>
      </div>

      {visible.length ? (
        <div className="video-grid">
          {visible.map((video) => <VideoCard video={video} metrics={metrics} key={video.video_id} />)}
        </div>
      ) : (
        <div className="empty-library">No videos match those filters.</div>
      )}

      <div className="pagination-row">
        <span>Page {safePage} of {pageCount}</span>
        <div>
          <button className="icon-button" onClick={() => setPage(Math.max(1, safePage - 1))} disabled={safePage <= 1} aria-label="Previous page"><ChevronLeft size={18} /></button>
          <button className="icon-button" onClick={() => setPage(Math.min(pageCount, safePage + 1))} disabled={safePage >= pageCount} aria-label="Next page"><ChevronRight size={18} /></button>
        </div>
      </div>
    </section>
  );
}

function VideoCard({ video, metrics }: { video: VideoSnapshot; metrics: ChannelMetrics }) {
  const image = video.thumbnails.medium || video.thumbnails.high || video.thumbnails.default;
  const tier = tierFor(video, metrics);
  const median = metrics.views.median || 0;
  const ratio = median > 0 && video.view_count !== null && video.view_count !== undefined ? video.view_count / median : null;
  return (
    <article className="video-card glass-card">
      <a className="thumbnail-wrap" href={video.watch_url} target="_blank" rel="noreferrer" aria-label={`Open ${video.title} on YouTube`}>
        {image ? <img src={image} alt="" loading="lazy" /> : <div className="thumbnail-placeholder" />}
        <span className="duration-chip">{formatDuration(video.duration_seconds)}</span>
        {tier !== "unknown" && <span className={`performance-chip tier-${tier}`}>{tierLabel(tier)}</span>}
      </a>
      <div className="video-body">
        <div className="video-date">{formatDate(video.published_at)}</div>
        <h3 title={video.title}>{video.title}</h3>
        <div className="video-stats">
          <span><strong>{formatNumber(video.view_count)}</strong> views</span>
          <span><strong>{formatNumber(video.like_count)}</strong> likes</span>
          <span><strong>{formatNumber(video.comment_count)}</strong> comments</span>
        </div>
        {ratio !== null && <div className="median-context">{ratio.toFixed(ratio >= 10 ? 0 : 1)}× channel median</div>}
        <a className="text-link" href={video.watch_url} target="_blank" rel="noreferrer">View source <ExternalLink size={14} /></a>
      </div>
    </article>
  );
}
