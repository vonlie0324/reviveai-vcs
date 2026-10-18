import {
  CalendarClock,
  Eye,
  ExternalLink,
  Film,
  Gauge,
  Users,
} from "lucide-react";
import type { ReactNode } from "react";
import type { AnalysisResult } from "../types";

function formatNumber(value?: number | null) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(undefined, { notation: value >= 10000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(value);
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" }).format(new Date(value));
}

export function ChannelOverview({ result }: { result: AnalysisResult }) {
  const { channel, summary } = result;
  const avatar = channel.thumbnails.high || channel.thumbnails.medium || channel.thumbnails.default;

  return (
    <>
      <section className="channel-hero glass-card">
        <div className="channel-identity">
          {avatar ? <img className="channel-avatar" src={avatar} alt="" /> : <div className="channel-avatar placeholder" />}
          <div>
            <span className="eyebrow">Channel resolved</span>
            <h1>{channel.title}</h1>
            <p className="channel-handle">{channel.custom_url || channel.channel_id}</p>
          </div>
        </div>
        <a className="secondary-button" href={channel.channel_url} target="_blank" rel="noreferrer">
          Open YouTube
          <ExternalLink size={16} aria-hidden="true" />
        </a>
      </section>

      <section className="stat-grid" aria-label="Channel snapshot metrics">
        <Metric icon={<Users size={18} />} label="Subscribers" value={channel.subscriber_count_hidden ? "Hidden" : formatNumber(channel.subscriber_count)} helper="Public channel total" />
        <Metric icon={<Eye size={18} />} label="Lifetime views" value={formatNumber(channel.lifetime_view_count)} helper="Public channel total" />
        <Metric icon={<Film size={18} />} label="Public videos" value={formatNumber(channel.public_video_count_reported)} helper={`${summary.retrieved_videos.toLocaleString()} retrieved now`} />
        <Metric icon={<CalendarClock size={18} />} label="Latest upload" value={formatDate(summary.latest_upload_at)} helper={summary.days_since_latest_upload === null || summary.days_since_latest_upload === undefined ? "Date unavailable" : `${summary.days_since_latest_upload.toLocaleString()} days ago`} />
        <Metric icon={<Gauge size={18} />} label="≤ 3 min" value={formatNumber(summary.videos_le_180_seconds)} helper="Duration-based, not a Shorts claim" />
      </section>

      <section className="coverage-banner">
        <div>
          <strong>Public-data snapshot</strong>
          <p>{result.data_scope_notice}</p>
        </div>
        <span>{summary.youtube_api_requests} API requests</span>
      </section>
    </>
  );
}

function Metric({ icon, label, value, helper }: { icon: ReactNode; label: string; value: string; helper: string }) {
  return (
    <div className="metric-card glass-card">
      <div className="metric-icon" aria-hidden="true">{icon}</div>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-helper">{helper}</div>
    </div>
  );
}
