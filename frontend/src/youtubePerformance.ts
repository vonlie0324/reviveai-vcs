import type { PerformanceObservation, YouTubeMetricStatus, YouTubePerformanceSnapshot, YouTubePublication } from "./types";

export function publicationReleaseTiming(publication: YouTubePublication): { label: string; at: string | null } {
  if (publication.status === "PUBLISHED") {
    if (publication.public_release_at) {
      const label = publication.public_release_time_source === "YOUTUBE" ? "Public release"
        : publication.public_release_time_source === "SCHEDULE_ESTIMATE" ? "Estimated public release" : "Public verified";
      return { label, at: publication.public_release_at };
    }
    return { label: "Public verified", at: publication.public_confirmed_at ?? null };
  }
  return { label: "Scheduled public release", at: publication.publish_at ?? null };
}

export type PerformanceMetric = "views" | "likes" | "comments" | "estimated_minutes_watched"
  | "average_view_duration_seconds" | "average_percentage_viewed" | "shares"
  | "subscribers_gained" | "subscribers_lost";

const PUBLIC_METRICS = new Set<PerformanceMetric>(["views", "likes", "comments"]);
const CHECKPOINT_RANK: Record<string, number> = { EARLY: 0, "1H": 1, "6H": 2, "24H": 3, "72H": 4, "7D": 5, "28D": 6 };

export function isKnownNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function metricStatus(snapshot: YouTubePerformanceSnapshot, metric: PerformanceMetric): YouTubeMetricStatus {
  if ((snapshot.evidence_version ?? 1) < 2) return "UNVERIFIED";
  return (PUBLIC_METRICS.has(metric) ? snapshot.statistics_status : snapshot.analytics_status) ?? "UNVERIFIED";
}

export function metricValue(snapshot: YouTubePerformanceSnapshot | null | undefined, metric: PerformanceMetric): number | null {
  if (!snapshot) return null;
  const status = metricStatus(snapshot, metric);
  const value = snapshot[metric];
  return (status === "READY" || status === "PARTIAL") && isKnownNumber(value) && value >= 0 ? value : null;
}

export function formatMetric(snapshot: YouTubePerformanceSnapshot | null | undefined, metric: PerformanceMetric): string {
  if (!snapshot) return "—";
  const value = metricValue(snapshot, metric);
  if (value != null) {
    return metric === "average_percentage_viewed" ? `${value.toFixed(1)}%` : value.toLocaleString();
  }
  const status = metricStatus(snapshot, metric);
  if (status === "UNVERIFIED") return "Unverified";
  if (status === "ERROR") return "Unavailable";
  if (status === "READY" && PUBLIC_METRICS.has(metric)) return "Not available";
  return "Pending";
}

export function netSubscribers(snapshot: YouTubePerformanceSnapshot | null | undefined): number | null {
  const gained = metricValue(snapshot, "subscribers_gained");
  const lost = metricValue(snapshot, "subscribers_lost");
  return gained == null || lost == null ? null : gained - lost;
}

export function formatSignedNumber(value: number | null): string {
  return value == null ? "Pending" : `${value >= 0 ? "+" : ""}${value.toLocaleString()}`;
}

export function formatNetSubscribers(snapshot: YouTubePerformanceSnapshot | null | undefined): string {
  const net = netSubscribers(snapshot);
  if (net != null) return formatSignedNumber(net);
  return metricValue(snapshot, "subscribers_gained") == null
    ? formatMetric(snapshot, "subscribers_gained") : formatMetric(snapshot, "subscribers_lost");
}

export function latestPerformanceSnapshot(snapshots: readonly YouTubePerformanceSnapshot[] | undefined): YouTubePerformanceSnapshot | null {
  if (!snapshots?.length) return null;
  return snapshots.reduce((best, item) => {
    const rank = CHECKPOINT_RANK[item.checkpoint.toUpperCase()] ?? -1;
    const bestRank = CHECKPOINT_RANK[best.checkpoint.toUpperCase()] ?? -1;
    if (rank !== bestRank) return rank > bestRank ? item : best;
    const stamp = Date.parse(item.observed_at);
    const bestStamp = Date.parse(best.observed_at);
    return Number.isFinite(stamp) && (!Number.isFinite(bestStamp) || stamp > bestStamp) ? item : best;
  });
}

export function statisticsReady(snapshot: YouTubePerformanceSnapshot | null | undefined): boolean {
  return Boolean(snapshot && metricStatus(snapshot, "views") === "READY" && metricValue(snapshot, "views") != null);
}

export function learningReady(snapshot: YouTubePerformanceSnapshot | null | undefined): boolean {
  return Boolean(snapshot && statisticsReady(snapshot) && snapshot.analytics_status === "READY"
    && ["average_percentage_viewed", "shares", "subscribers_gained", "subscribers_lost"].every(
      metric => metricValue(snapshot, metric as PerformanceMetric) != null,
    ));
}

export function performanceStatus(snapshot: YouTubePerformanceSnapshot | null | undefined): string {
  if (!snapshot) return "Waiting for the first performance checkpoint";
  const stats = metricStatus(snapshot, "views");
  const analytics = metricStatus(snapshot, "average_percentage_viewed");
  const publicLabel = snapshot.statistics_error && stats === "READY" ? "Last verified statistics"
    : stats === "READY" ? "Statistics available"
    : stats === "ERROR" ? "Statistics unavailable"
    : stats === "UNVERIFIED" ? "Statistics awaiting verification" : "Statistics pending";
  const analyticsLabel = snapshot.analytics_error ? "Analytics update failed"
    : analytics === "READY" ? "Analytics available"
    : analytics === "PARTIAL" ? "Analytics partial"
    : analytics === "ERROR" ? "Analytics unavailable"
    : analytics === "UNVERIFIED" ? "Analytics awaiting verification" : "Analytics pending";
  return `${publicLabel} · ${analyticsLabel}`;
}

export function observationDecisionReady(observation: PerformanceObservation): boolean {
  if (observation.evidence_source === "LEGACY_UNVERIFIED") return false;
  if (observation.evidence_source === "YOUTUBE_APIS") {
    return observation.statistics_status === "READY" && isKnownNumber(observation.views)
      && observation.analytics_status === "READY"
      && [observation.average_percentage_viewed, observation.shares,
        observation.subscribers_gained, observation.subscribers_lost].every(isKnownNumber);
  }
  // Old empty-row observations had no source tag and all eight metrics set to zero.
  if (!observation.evidence_source && observation.viewed_vs_swiped_percent == null
    && [observation.views, observation.average_percentage_viewed, observation.average_view_duration_seconds,
      observation.likes, observation.comments, observation.shares, observation.subscribers_gained,
      observation.subscribers_lost].every(value => value === 0)) return false;
  return true;
}

export type MetricSummary = { value: number | null; available: number; total: number; partial: boolean; unknownLabel?: string };

export function summarizePerformance(snapshots: Array<YouTubePerformanceSnapshot | null>) {
  const total = snapshots.length;
  function unknownLabel(metric: PerformanceMetric): string {
    if (snapshots.some(snapshot => !snapshot)) return "Pending";
    const statuses = snapshots.map(snapshot => metricStatus(snapshot!, metric));
    if (statuses.length && statuses.every(status => status === "UNVERIFIED")) return "Unverified";
    if (statuses.length && statuses.every(status => status === "ERROR" || status === "UNVERIFIED")) return "Unavailable";
    return "Pending";
  }
  function summary(values: Array<number | null>, metric: PerformanceMetric): MetricSummary {
    const known = values.filter((value): value is number => value != null);
    return { value: known.length ? known.reduce((sum, value) => sum + value, 0) : null,
      available: known.length, total, partial: known.length < total, unknownLabel: unknownLabel(metric) };
  }
  const retention = snapshots.flatMap(snapshot => {
    const percentage = metricValue(snapshot, "average_percentage_viewed");
    return percentage == null ? [] : [{ percentage, weight: snapshot?.analytics_views }];
  });
  // Use processed Analytics views from the same report window. Current public
  // counters must not weight delayed retention evidence from a different window.
  const allWeightsKnown = retention.every(item => isKnownNumber(item.weight) && item.weight >= 0);
  const weightTotal = allWeightsKnown ? retention.reduce((sum, item) => sum + (item.weight as number), 0) : 0;
  const percentage = retention.length
    ? weightTotal > 0
      ? retention.reduce((sum, item) => sum + item.percentage * (item.weight as number), 0) / weightTotal
      : retention.reduce((sum, item) => sum + item.percentage, 0) / retention.length
    : null;
  return {
    observations: snapshots.filter(statisticsReady).length,
    verifiedLearning: snapshots.filter(learningReady).length,
    pendingLearning: snapshots.filter(snapshot => !learningReady(snapshot)).length,
    views: summary(snapshots.map(snapshot => metricValue(snapshot, "views")), "views"),
    shares: summary(snapshots.map(snapshot => metricValue(snapshot, "shares")), "shares"),
    netSubscribers: summary(snapshots.map(netSubscribers), "subscribers_gained"),
    weightedViewed: { value: percentage, available: retention.length, total, partial: retention.length < total,
      unknownLabel: unknownLabel("average_percentage_viewed") } as MetricSummary,
  };
}

export function formatSummary(summary: MetricSummary, mode: "number" | "percent" | "signed" = "number"): string {
  if (summary.value == null) return summary.total ? summary.unknownLabel || "Pending" : "—";
  if (mode === "percent") return `${summary.value.toFixed(1)}%`;
  if (mode === "signed") return formatSignedNumber(summary.value);
  return summary.value.toLocaleString();
}

export function summaryCoverage(summary: MetricSummary): string {
  return summary.total ? `${summary.available} of ${summary.total} releases${summary.partial ? " · partial" : ""}` : "No public performance yet";
}
