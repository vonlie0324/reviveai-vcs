import test from "node:test";
import assert from "node:assert/strict";
import {
  formatMetric, formatNetSubscribers, formatSummary, latestPerformanceSnapshot,
  learningReady, metricValue, observationDecisionReady, performanceStatus,
  statisticsReady, summarizePerformance, summaryCoverage, publicationReleaseTiming,
} from "../src/youtubePerformance";
import type { YouTubePerformanceSnapshot, YouTubePublication } from "../src/types";

function snapshot(patch: Partial<YouTubePerformanceSnapshot> = {}): YouTubePerformanceSnapshot {
  return { checkpoint: "24H", observed_at: "2026-10-02T08:00:00Z", age_hours: 24,
    views:1153, likes:37, comments:0, estimated_minutes_watched:null, average_view_duration_seconds:null,
    average_percentage_viewed:null, shares:null, subscribers_gained:null, subscribers_lost:null,
    evidence_version:2, statistics_status:"READY", analytics_status:"PENDING", ...patch };
}

function publication(patch: Partial<YouTubePublication> = {}): YouTubePublication {
  return { publication_id:"pub",package_id:"package",publishing_draft_id:"draft",recommendation_id:"idea",
    status:"PUBLISHED",privacy_status:"public",created_at:"2026-10-02T06:34:49Z",updated_at:"2026-10-04T13:31:02Z",
    publish_at:"2026-10-03T04:00:00Z",published_at:"2026-10-04T06:40:11Z",
    public_confirmed_at:"2026-10-04T06:40:11Z",...patch };
}

test("verified actual release is displayed independently from planned and verification times", () => {
  const item = publication({public_release_at:"2026-10-03T04:15:00Z",public_release_time_source:"YOUTUBE",release_clock_version:2});
  assert.deepEqual(publicationReleaseTiming(item),{label:"Public release",at:"2026-10-03T04:15:00Z"});
});

test("scheduled fallback is explicitly shown as an estimated release", () => {
  const item = publication({public_release_at:"2026-10-03T04:00:00Z",public_release_time_source:"SCHEDULE_ESTIMATE"});
  assert.equal(publicationReleaseTiming(item).label,"Estimated public release");
});

test("unmigrated published records display the verification time rather than an assumed release", () => {
  assert.deepEqual(publicationReleaseTiming(publication()),{label:"Public verified",at:"2026-10-04T06:40:11Z"});
});

test("scheduled private publication uses the planned release label", () => {
  assert.deepEqual(publicationReleaseTiming(publication({status:"SCHEDULED",privacy_status:"private",public_confirmed_at:null})),
    {label:"Scheduled public release",at:"2026-10-03T04:00:00Z"});
});

test("unscheduled publication does not invent a release timestamp", () => {
  assert.deepEqual(publicationReleaseTiming(publication({status:"SCHEDULED",publish_at:null})),
    {label:"Scheduled public release",at:null});
});

test("valid public counters and genuine comment zero render while delayed analytics stays pending", () => {
  const item = snapshot();
  assert.equal(formatMetric(item,"views"),(1153).toLocaleString());
  assert.equal(formatMetric(item,"comments"),"0");
  assert.equal(formatMetric(item,"average_percentage_viewed"),"Pending");
  assert.equal(formatNetSubscribers(item),"Pending");
  assert.ok(statisticsReady(item)); assert.ok(!learningReady(item));
});

test("a complete real zero response remains distinguishable from pending", () => {
  const item = snapshot({views:0,average_percentage_viewed:0,shares:0,subscribers_gained:0,subscribers_lost:0,analytics_status:"READY"});
  assert.equal(formatMetric(item,"views"),"0");
  assert.equal(formatMetric(item,"average_percentage_viewed"),"0.0%");
  assert.equal(formatNetSubscribers(item),"+0");
  assert.ok(learningReady(item));
});

test("null and non-finite metric values never call unsafe formatters or become zero", () => {
  for (const value of [null,NaN,Infinity,-1]) {
    const item = snapshot({average_percentage_viewed:value,analytics_status:"READY"});
    assert.equal(metricValue(item,"average_percentage_viewed"),null);
    assert.equal(formatMetric(item,"average_percentage_viewed"),"Pending");
  }
});

test("legacy numeric snapshots are unverified even when they contain zeros", () => {
  const item = snapshot({evidence_version:undefined,statistics_status:undefined,analytics_status:undefined,views:0});
  assert.equal(formatMetric(item,"views"),"Unverified"); assert.ok(!statisticsReady(item));
});

test("network/API error is shown separately from pending data", () => {
  const item = snapshot({statistics_status:"ERROR",analytics_status:"ERROR",views:null});
  assert.equal(formatMetric(item,"views"),"Unavailable");
  assert.equal(formatMetric(item,"shares"),"Unavailable");
  assert.match(performanceStatus(item),/Statistics unavailable.*Analytics unavailable/);
});

test("missing optional counters remain unavailable, not zero", () => {
  assert.equal(formatMetric(snapshot({likes:null}),"likes"),"Not available");
});

test("partial Analytics reveals only actually returned metrics", () => {
  const item = snapshot({analytics_status:"PARTIAL",shares:3});
  assert.equal(formatMetric(item,"shares"),"3");
  assert.equal(formatMetric(item,"average_percentage_viewed"),"Pending");
  assert.ok(!learningReady(item));
});

test("a historical reconciliation does not take precedence over a higher checkpoint", () => {
  const old = snapshot({checkpoint:"24H",observed_at:"2026-10-04T09:00:00Z"});
  const mature = snapshot({checkpoint:"72H",observed_at:"2026-10-04T08:00:00Z"});
  assert.equal(latestPerformanceSnapshot([mature,old]),mature);
});

test("same checkpoint ties use the latest valid original capture time", () => {
  const first = snapshot();
  const second = snapshot({observed_at:"2026-10-03T08:00:00Z"});
  assert.equal(latestPerformanceSnapshot([first,second]),second);
  assert.equal(latestPerformanceSnapshot([]),null);
});

test("missing snapshots cannot fabricate total zero views or retention", () => {
  const total = summarizePerformance([null,null]);
  assert.equal(total.views.value,null); assert.equal(total.weightedViewed.value,null);
  assert.equal(formatSummary(total.views),"Pending");
  assert.equal(total.observations,0);
});

test("empty publication list shows a dash, not claimed zero performance", () => {
  const total = summarizePerformance([]);
  assert.equal(formatSummary(total.views),"—");
});

test("partial totals include known values and disclose release coverage", () => {
  const total = summarizePerformance([snapshot(),null]);
  assert.equal(total.views.value,1153); assert.ok(total.views.partial);
  assert.equal(summaryCoverage(total.views),"1 of 2 releases · partial");
  assert.equal(total.shares.value,null); assert.equal(total.pendingLearning,2);
});

test("retention weights use matching Analytics views, never missing/current public counts", () => {
  const a = snapshot({average_percentage_viewed:80,analytics_views:100,analytics_status:"READY",views:10000});
  const b = snapshot({average_percentage_viewed:20,analytics_views:400,analytics_status:"READY",views:100});
  const pending = snapshot({views:1000000});
  const total = summarizePerformance([a,b,pending]);
  assert.equal(total.weightedViewed.value,32);
  assert.equal(total.weightedViewed.available,2); assert.ok(total.weightedViewed.partial);
});

test("retention without weights uses the available percentages only", () => {
  const a = snapshot({average_percentage_viewed:80,analytics_status:"READY"});
  const b = snapshot({average_percentage_viewed:20,analytics_status:"READY"});
  assert.equal(summarizePerformance([a,b,null]).weightedViewed.value,50);
});

test("unknown subscriber losses cannot manufacture a subscriber total", () => {
  const item = snapshot({subscribers_gained:10,subscribers_lost:null,analytics_status:"PARTIAL"});
  assert.equal(formatNetSubscribers(item),"Pending");
  assert.equal(summarizePerformance([item]).netSubscribers.value,null);
});

test("negative net subscribers use one minus sign", () => {
  const item = snapshot({subscribers_gained:2,subscribers_lost:4,analytics_status:"READY"});
  assert.equal(formatNetSubscribers(item),"-2");
});

test("retained verified response remains numeric with a failed-update status", () => {
  const item = snapshot({analytics_status:"READY",average_percentage_viewed:90,analytics_error:"HTTP 503"});
  assert.equal(formatMetric(item,"average_percentage_viewed"),"90.0%");
  assert.match(performanceStatus(item),/Analytics update failed/);
});

test("pending API observations do not count as verified learning", () => {
  assert.ok(!observationDecisionReady({recommendation_id:"idea",evidence_source:"YOUTUBE_APIS",
    statistics_status:"READY",analytics_status:"PENDING",views:1153}));
});

test("ambiguous legacy all-zero observations are excluded while tagged genuine zeros remain valid", () => {
  const old = {recommendation_id:"idea",views:0,average_percentage_viewed:0,average_view_duration_seconds:0,
    likes:0,comments:0,shares:0,subscribers_gained:0,subscribers_lost:0};
  assert.ok(!observationDecisionReady(old));
  assert.ok(observationDecisionReady({...old,evidence_source:"YOUTUBE_APIS",statistics_status:"READY",analytics_status:"READY"}));
});

test("manual observations retain their existing behavior", () => {
  assert.ok(observationDecisionReady({recommendation_id:"idea",evidence_source:"MANUAL",views:0}));
});

test("all-error totals are unavailable instead of pretending to await processing", () => {
  const result = summarizePerformance([snapshot({statistics_status:"ERROR",analytics_status:"ERROR",views:null})]);
  assert.equal(formatSummary(result.views),"Unavailable");
  assert.equal(formatSummary(result.shares),"Unavailable");
});

test("all-legacy totals are explicitly unverified", () => {
  const result = summarizePerformance([snapshot({evidence_version:1})]);
  assert.equal(formatSummary(result.views),"Unverified");
});
