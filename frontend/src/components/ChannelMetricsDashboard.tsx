import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  BarChart3,
  CalendarDays,
  Clock3,
  Eye,
  Gauge,
  Heart,
  Info,
  MessageCircle,
  Sparkles,
  Trophy,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import type {
  AnalysisResult,
  DurationPerformanceBand,
  PerformanceTier,
  RankedVideoMetric,
} from "../types";

const NAV_ITEMS = [
  { id: "channel-health", label: "Health" },
  { id: "performance", label: "Performance" },
  { id: "cadence", label: "Cadence" },
  { id: "formats", label: "Formats" },
  { id: "leaders", label: "Evidence" },
] as const;

function formatNumber(value?: number | null, digits = 1) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(undefined, {
    notation: Math.abs(value) >= 10000 ? "compact" : "standard",
    maximumFractionDigits: digits,
  }).format(value);
}

function formatViews(value?: number | null) {
  return formatNumber(value, 0);
}

function formatRatio(value?: number | null) {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(value >= 10 ? 0 : 1)}×`;
}

function formatMonth(value: string) {
  const [year, month] = value.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, { month: "short" }).format(new Date(year, month - 1, 1));
}

function tierClass(key: string) {
  return `tier-${key}`;
}

export function ChannelMetricsDashboard({ result }: { result: AnalysisResult }) {
  const { metrics, summary } = result;
  const cadence = metrics.cadence;
  const views = metrics.views;
  const top = metrics.top_videos[0];
  const topRatio = top?.relative_to_median;
  const exceptionalTier = metrics.performance_tiers.find((tier) => tier.key === "exceptional");
  const [activeSection, setActiveSection] = useState<(typeof NAV_ITEMS)[number]["id"]>("channel-health");
  const [recencyMode, setRecencyMode] = useState<"lifetime" | "age-normalized">("lifetime");
  const canonicalInactivityDays = cadence.current_gap_days ?? summary.days_since_latest_upload;

  const peakMonth = useMemo(() => {
    if (!cadence.monthly_uploads.length) return null;
    return cadence.monthly_uploads.reduce((best, point) => point.upload_count > best.upload_count ? point : best);
  }, [cadence.monthly_uploads]);

  useEffect(() => {
    const updateActiveSection = () => {
      const anchor = 150;
      let current: (typeof NAV_ITEMS)[number]["id"] = NAV_ITEMS[0].id;
      for (const item of NAV_ITEMS) {
        const element = document.getElementById(item.id);
        if (element && element.getBoundingClientRect().top <= anchor) {
          current = item.id;
        }
      }
      setActiveSection(current);
    };

    updateActiveSection();
    window.addEventListener("scroll", updateActiveSection, { passive: true });
    window.addEventListener("resize", updateActiveSection);
    return () => {
      window.removeEventListener("scroll", updateActiveSection);
      window.removeEventListener("resize", updateActiveSection);
    };
  }, []);

  const recencyRecentValue = recencyMode === "lifetime"
    ? metrics.recency.recent_median_views
    : metrics.recency.recent_median_views_per_published_day;
  const recencyOlderValue = recencyMode === "lifetime"
    ? metrics.recency.older_median_views
    : metrics.recency.older_median_views_per_published_day;
  const recencyUnit = recencyMode === "lifetime" ? "views" : "views / published day";

  return (
    <section className="intelligence-section" aria-label="Evidence-backed channel metrics">
      <nav className="section-nav" aria-label="Channel intelligence sections">
        {NAV_ITEMS.map((item) => (
          <a
            key={item.id}
            href={`#${item.id}`}
            className={activeSection === item.id ? "active" : undefined}
            aria-current={activeSection === item.id ? "location" : undefined}
            onClick={(event) => {
              event.preventDefault();
              setActiveSection(item.id);
              document.getElementById(item.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
              window.history.replaceState(null, "", `#${item.id}`);
            }}
          >
            <span className="nav-active-dot" aria-hidden="true" />
            {item.label}
          </a>
        ))}
      </nav>

      <div className="section-heading intelligence-heading" id="channel-health">
        <div>
          <span className="eyebrow">Milestone 1B.2 · deterministic metrics</span>
          <h2>Channel health</h2>
          <p>Measured from the public upload history. No Gemini interpretation is used in this section.</p>
        </div>
        <div className="evidence-chip"><Gauge size={15} /> Evidence layer</div>
      </div>

      <div className="health-grid">
        <article className={`health-hero glass-card status-${cadence.status}`}>
          <div className="health-hero-top">
            <div className="health-icon"><Activity size={21} /></div>
            <span className="metric-kicker">Publishing status</span>
          </div>
          <div className="health-status-row">
            <div>
              <strong className="health-status">{cadence.status_label}</strong>
              <p>{cadence.status_explanation}</p>
            </div>
            <div className="dormancy-number">
              <strong>{cadence.current_gap_vs_historical_max ? formatRatio(cadence.current_gap_vs_historical_max) : formatNumber(canonicalInactivityDays, 0)}</strong>
              <span>{cadence.current_gap_vs_historical_max ? "vs prior max gap" : "days inactive"}</span>
            </div>
          </div>
          <div className="dormancy-emphasis">
            <span>Current inactivity</span>
            <strong>{formatNumber(canonicalInactivityDays, 0)} days</strong>
            <small>
              {cadence.current_gap_vs_historical_max
                ? `${formatRatio(cadence.current_gap_vs_historical_max)} longer than the channel's previous longest inactive gap.`
                : "Compared against active publishing days, not individual same-day uploads."}
            </small>
          </div>
          <div className="health-proof-row">
            <span>Historical longest inactive gap <strong>{formatNumber(cadence.longest_historical_active_day_gap_days, 0)} days</strong></span>
            <span>Median gap between active days <strong>{formatNumber(cadence.median_active_day_gap_days)} days</strong></span>
          </div>
        </article>

        <HealthMetric
          icon={<Eye size={18} />}
          label="Median video"
          value={`${formatViews(views.median)} views`}
          helper={views.p25 !== null && views.p75 !== null ? `Middle 50%: ${formatViews(views.p25)}–${formatViews(views.p75)}` : "Insufficient view data"}
        />
        <HealthMetric
          icon={<CalendarDays size={18} />}
          label="Publishing pattern"
          value={cadence.publishing_style}
          helper={`${formatNumber(cadence.typical_uploads_per_active_day)} ${cadence.typical_uploads_per_active_day === 1 ? "upload" : "uploads"} / active day · ${formatNumber(cadence.active_days_per_30_days)} active days / 30d`}
        />
        <HealthMetric
          icon={<Trophy size={18} />}
          label="Top video"
          value={`${formatViews(top?.views)} views`}
          helper={topRatio ? `${formatRatio(topRatio)} the channel median` : "No comparable median"}
        />
        <HealthMetric
          icon={<Heart size={18} />}
          label="Likes / 1K views"
          value={formatNumber(metrics.engagement.likes_per_1000_views, 2)}
          helper={`${metrics.engagement.like_coverage_videos} videos with public like counts`}
        />
      </div>

      <div className="analytics-grid" id="performance">
        <article className="analytics-card glass-card performance-card">
          <div className="card-heading-row">
            <div>
              <span className="eyebrow">Performance distribution</span>
              <h3>What is normal for this channel?</h3>
            </div>
            <BarChart3 size={20} />
          </div>

          <div className="distribution-numbers">
            <DistributionStat label="25th percentile" value={views.p25} />
            <DistributionStat label="Median" value={views.median} featured />
            <DistributionStat label="75th percentile" value={views.p75} />
            <DistributionStat label="90th percentile" value={views.p90} />
          </div>

          <TierBar tiers={metrics.performance_tiers} />

          <div className="distribution-footnote">
            <Info size={15} />
            <span>
              “Typical” means the middle 50% of this channel's lifetime public views. “Exceptional” begins at the 90th percentile.
            </span>
          </div>
        </article>

        <article className="analytics-card glass-card signal-card">
          <span className="eyebrow">Evidence signals</span>
          <h3>Fast facts worth carrying into M1C</h3>
          <div className="signal-list">
            <Signal
              icon={<Trophy size={17} />}
              title="Best observed public reach"
              value={`${formatViews(views.maximum)} views`}
              detail={topRatio ? `${formatRatio(topRatio)} the median video` : "Highest retrieved public view count"}
            />
            <Signal
              icon={<Sparkles size={17} />}
              title="Exceptional performers"
              value={`${exceptionalTier?.count ?? 0} videos`}
              detail={views.p90 !== null ? `At or above the channel's P90 threshold of ${formatViews(views.p90)} views` : "Not enough data"}
            />
            <Signal
              icon={<MessageCircle size={17} />}
              title="Comments / 1K views"
              value={formatNumber(metrics.engagement.comments_per_1000_views, 2)}
              detail={`${metrics.engagement.comment_coverage_videos} videos with public comment counts`}
            />
          </div>
        </article>
      </div>

      <div className="analytics-grid" id="cadence">
        <article className="analytics-card glass-card cadence-card">
          <div className="card-heading-row">
            <div>
              <span className="eyebrow">Publishing cadence</span>
              <h3>12 months ending at last upload</h3>
              <p>Cadence gaps are calculated between active publishing days, so multiple same-day uploads do not create misleading zero-day gaps.</p>
            </div>
            <Clock3 size={20} />
          </div>

          <div className="cadence-insight" role="note">
            <div className="cadence-insight-icon"><Activity size={17} /></div>
            <div>
              <strong>Publishing behavior changed abruptly.</strong>
              <span>
                Historically this channel used {cadence.publishing_style.toLowerCase()} with a {formatNumber(cadence.median_active_day_gap_days)}-day median gap between active days.
                {cadence.current_gap_vs_historical_max ? ` The current inactive period is ${formatRatio(cadence.current_gap_vs_historical_max)} longer than its previous longest gap.` : ""}
              </span>
            </div>
          </div>

          <MonthlyBars points={cadence.monthly_uploads} />
          <div className="cadence-facts">
            <MiniFact label="Median active-day gap" value={`${formatNumber(cadence.median_active_day_gap_days)} days`} />
            <MiniFact label={cadence.typical_uploads_per_active_day === 1 ? "Typical upload / active day" : "Typical uploads / active day"} value={formatNumber(cadence.typical_uploads_per_active_day)} />
            <MiniFact label="Previous longest inactive gap" value={`${formatNumber(cadence.longest_historical_active_day_gap_days, 0)} days`} />
            <MiniFact label="Current inactivity" value={`${formatNumber(canonicalInactivityDays, 0)} days`} emphasis />
          </div>
          <div className="cadence-meta-row">
            <span>{cadence.active_publishing_days} active publishing days</span>
            <span>{formatNumber(cadence.active_days_per_30_days)} active days / 30d historically</span>
            {peakMonth && <span>Peak month: {formatMonth(peakMonth.month)} · {peakMonth.upload_count} uploads</span>}
          </div>
        </article>

        <article className="analytics-card glass-card recency-card">
          <div className="recency-heading-row">
            <div>
              <span className="eyebrow">Recency context</span>
              <h3>Recent uploads vs. older archive</h3>
            </div>
            <div className="metric-toggle" aria-label="Recency comparison metric">
              <button
                type="button"
                className={recencyMode === "lifetime" ? "active" : undefined}
                aria-pressed={recencyMode === "lifetime"}
                onClick={() => setRecencyMode("lifetime")}
              >
                Lifetime
              </button>
              <button
                type="button"
                className={recencyMode === "age-normalized" ? "active" : undefined}
                aria-pressed={recencyMode === "age-normalized"}
                onClick={() => setRecencyMode("age-normalized")}
              >
                Age-normalized
              </button>
            </div>
          </div>
          <div className="recency-compare">
            <div>
              <span>Newest {metrics.recency.recent_video_count}</span>
              <strong>{recencyMode === "lifetime" ? formatViews(recencyRecentValue) : formatNumber(recencyRecentValue, 2)}</strong>
              <small>{recencyUnit}</small>
            </div>
            <div className="compare-divider">vs</div>
            <div>
              <span>Older {metrics.recency.older_video_count}</span>
              <strong>{recencyMode === "lifetime" ? formatViews(recencyOlderValue) : formatNumber(recencyOlderValue, 2)}</strong>
              <small>{recencyUnit}</small>
            </div>
          </div>
          <div className="caution-note">
            <AlertTriangle size={16} />
            <span>{metrics.recency.note}</span>
          </div>
        </article>
      </div>

      <article className="analytics-card glass-card format-card" id="formats">
        <div className="card-heading-row">
          <div>
            <span className="eyebrow">Duration evidence</span>
            <h3>Performance by video length</h3>
            <p>This is duration-based only; ReviveAI does not infer YouTube Shorts status from duration.</p>
          </div>
        </div>
        <DurationBands bands={metrics.duration_bands} />
      </article>

      <section className="leaderboard-section" id="leaders">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Traceable evidence</span>
            <h2>Performance leaders and lower-bound examples</h2>
            <p>Every item links back to the source video. M1C can later explain the content patterns behind these numbers.</p>
          </div>
        </div>
        <div className="leaderboard-grid">
          <RankedList title="Top performers" subtitle="Highest public lifetime views" videos={metrics.top_videos} tone="top" />
          <RankedList title="Lower-bound examples" subtitle="Lowest public lifetime views" videos={metrics.bottom_videos} tone="low" />
        </div>
      </section>

      <div className="metrics-provenance">
        <Info size={16} />
        <span>{metrics.metrics_notice}</span>
      </div>
    </section>
  );
}

function HealthMetric({ icon, label, value, helper }: { icon: ReactNode; label: string; value: string; helper: string }) {
  return (
    <article className="health-metric glass-card">
      <div className="metric-icon" aria-hidden="true">{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{helper}</small>
    </article>
  );
}

function DistributionStat({ label, value, featured = false }: { label: string; value?: number | null; featured?: boolean }) {
  return (
    <div className={featured ? "distribution-stat featured" : "distribution-stat"}>
      <span>{label}</span>
      <strong>{formatViews(value)}</strong>
      <small>views</small>
    </div>
  );
}

function TierBar({ tiers }: { tiers: PerformanceTier[] }) {
  const total = tiers.reduce((sum, tier) => sum + tier.count, 0);
  if (!total) return <div className="empty-inline">No public view counts available.</div>;
  return (
    <div className="tier-block">
      <div className="tier-bar" aria-label="Performance tier distribution">
        {tiers.map((tier) => (
          <div
            key={tier.key}
            className={`tier-segment ${tierClass(tier.key)}`}
            style={{ width: `${(tier.count / total) * 100}%` }}
            title={`${tier.label}: ${tier.count}`}
          />
        ))}
      </div>
      <div className="tier-legend">
        {tiers.map((tier) => (
          <div key={tier.key} className="tier-legend-item" title={tier.description}>
            <span className={`tier-dot ${tierClass(tier.key)}`} />
            <span>{tier.label}</span>
            <strong>{tier.count}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function Signal({ icon, title, value, detail }: { icon: ReactNode; title: string; value: string; detail: string }) {
  return (
    <div className="signal-row">
      <div className="signal-icon">{icon}</div>
      <div>
        <span>{title}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </div>
  );
}

function MonthlyBars({ points }: { points: Array<{ month: string; upload_count: number }> }) {
  const max = Math.max(1, ...points.map((point) => point.upload_count));
  return (
    <div className="monthly-chart" aria-label="Monthly upload counts">
      {points.map((point) => (
        <div className="month-column" key={point.month} title={`${point.month}: ${point.upload_count} uploads`}>
          <div className="month-value">{point.upload_count || ""}</div>
          <div className="month-bar-track">
            <div className="month-bar" style={{ height: `${Math.max(point.upload_count ? 10 : 2, (point.upload_count / max) * 100)}%` }} />
          </div>
          <span>{formatMonth(point.month)}</span>
        </div>
      ))}
    </div>
  );
}

function MiniFact({ label, value, emphasis = false }: { label: string; value: string; emphasis?: boolean }) {
  return (
    <div className={emphasis ? "mini-fact emphasis" : "mini-fact"}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DurationBands({ bands }: { bands: DurationPerformanceBand[] }) {
  const maxMedian = Math.max(1, ...bands.map((band) => band.median_views || 0));
  return (
    <div className="duration-grid">
      {bands.map((band) => {
        const width = band.median_views ? (band.median_views / maxMedian) * 100 : 0;
        return (
          <div className="duration-row" key={band.key}>
            <div className="duration-label">
              <strong>{band.label}</strong>
              <span>{band.video_count} videos</span>
            </div>
            <div className="duration-bar-wrap">
              <div className="duration-bar" style={{ width: `${width}%` }} />
            </div>
            <div className="duration-value">
              <strong>{formatViews(band.median_views)}</strong>
              <span>median views</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RankedList({ title, subtitle, videos, tone }: { title: string; subtitle: string; videos: RankedVideoMetric[]; tone: "top" | "low" }) {
  return (
    <article className="ranked-card glass-card">
      <div className="ranked-heading">
        <div>
          <span className="eyebrow">{tone === "top" ? "Upper evidence" : "Lower evidence"}</span>
          <h3>{title}</h3>
          <p>{subtitle}</p>
        </div>
      </div>
      <div className="ranked-list">
        {videos.map((video, index) => (
          <a href={video.watch_url} target="_blank" rel="noreferrer" className="ranked-row" key={video.video_id}>
            <span className={`rank-number ${tone}`}>{index + 1}</span>
            {video.thumbnail_url ? <img src={video.thumbnail_url} alt="" loading="lazy" /> : <div className="rank-thumb-placeholder" />}
            <div className="rank-copy">
              <strong>{video.title}</strong>
              <span>{formatViews(video.views)} views · {formatRatio(video.relative_to_median)} median</span>
            </div>
            <ArrowUpRight size={16} />
          </a>
        ))}
      </div>
    </article>
  );
}
