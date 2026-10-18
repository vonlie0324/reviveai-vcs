export const WORKSPACE_STORAGE_KEY = "reviveai.workspace.v1";
const WORKSPACE_MIGRATION_KEY = "reviveai.workspace.migrated";

export function workspaceStorageKey(uid: string) { return `${WORKSPACE_STORAGE_KEY}:${uid}`; }

export interface CreatorWorkflowCheckpoint {
  version: 1;
  url?: string;
  analysisJobId: string;
  dnaJobId?: string;
  recoveryJobId?: string;
  productionBriefJobId?: string;
  mediaStudioJobId?: string;
  finalAssemblyJobId?: string;
  audioFinishingJobId?: string;
}

export type WorkspaceProductionStage =
  | "BRIEF"
  | "VISUALS"
  | "VISUAL_MASTER"
  | "AUDIO"
  | "QC"
  | "DELIVERY"
  | "PUBLISHING";

export interface WorkspaceProduction {
  id: string;
  title: string;
  stage: WorkspaceProductionStage;
  stageLabel: string;
  status: "ACTIVE" | "REVIEW" | "READY" | "BLOCKED";
  milestone: string;
  thumbnailUrl?: string | null;
  createdAt: string;
  updatedAt: string;
  checkpoint: CreatorWorkflowCheckpoint;
}

export interface WorkspaceChannel {
  channelId: string;
  title: string;
  handle?: string | null;
  thumbnailUrl?: string | null;
  channelUrl: string;
  subscriberCount?: number | null;
  publicVideoCount?: number | null;
  createdAt: string;
  updatedAt: string;
  lastOpenedAt: string;
  analysisJobId: string;
  dnaJobId?: string;
  recoveryJobId?: string;
  productions: WorkspaceProduction[];
}

export interface WorkspaceChannelAnalysisIndexItem {
  channel_id: string;
  analysis_job_id: string;
  channel_url: string;
  title: string;
  handle?: string | null;
  thumbnail_url?: string | null;
  subscriber_count?: number | null;
  public_video_count?: number | null;
  created_at: string;
  updated_at: string;
}

export interface ReviveWorkspace {
  version: 1;
  channels: WorkspaceChannel[];
  lastActiveChannelId?: string;
  lastActiveProductionId?: string;
}

const WORKSPACE_PRODUCTION_STAGE_RANK: Record<WorkspaceProductionStage, number> = {
  BRIEF: 0,
  VISUALS: 1,
  VISUAL_MASTER: 2,
  AUDIO: 3,
  QC: 4,
  DELIVERY: 5,
  PUBLISHING: 6,
};

function checkpointDepth(checkpoint: CreatorWorkflowCheckpoint): number {
  return [
    checkpoint.productionBriefJobId,
    checkpoint.mediaStudioJobId,
    checkpoint.finalAssemblyJobId,
    checkpoint.audioFinishingJobId,
  ].filter(Boolean).length;
}

function parsedWorkspaceTimestamp(value?: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function preferWorkspaceProduction(a: WorkspaceProduction, b: WorkspaceProduction): WorkspaceProduction {
  const stageDelta = WORKSPACE_PRODUCTION_STAGE_RANK[a.stage] - WORKSPACE_PRODUCTION_STAGE_RANK[b.stage];
  if (stageDelta !== 0) return stageDelta > 0 ? a : b;

  const checkpointDelta = checkpointDepth(a.checkpoint) - checkpointDepth(b.checkpoint);
  if (checkpointDelta !== 0) return checkpointDelta > 0 ? a : b;

  const updatedDelta = parsedWorkspaceTimestamp(a.updatedAt) - parsedWorkspaceTimestamp(b.updatedAt);
  if (updatedDelta !== 0) return updatedDelta > 0 ? a : b;

  if (Boolean(a.thumbnailUrl) !== Boolean(b.thumbnailUrl)) return a.thumbnailUrl ? a : b;
  return a;
}

function mergeCheckpoint(
  preferred: CreatorWorkflowCheckpoint,
  fallback: CreatorWorkflowCheckpoint,
): CreatorWorkflowCheckpoint {
  return {
    version: 1,
    url: preferred.url || fallback.url,
    analysisJobId: preferred.analysisJobId || fallback.analysisJobId,
    dnaJobId: preferred.dnaJobId || fallback.dnaJobId,
    recoveryJobId: preferred.recoveryJobId || fallback.recoveryJobId,
    productionBriefJobId: preferred.productionBriefJobId || fallback.productionBriefJobId,
    mediaStudioJobId: preferred.mediaStudioJobId || fallback.mediaStudioJobId,
    finalAssemblyJobId: preferred.finalAssemblyJobId || fallback.finalAssemblyJobId,
    audioFinishingJobId: preferred.audioFinishingJobId || fallback.audioFinishingJobId,
  };
}

function mergeSameWorkspaceProduction(
  existing: WorkspaceProduction,
  incoming: WorkspaceProduction,
): WorkspaceProduction {
  const preferred = preferWorkspaceProduction(existing, incoming);
  const fallback = preferred === existing ? incoming : existing;

  return {
    ...fallback,
    ...preferred,
    thumbnailUrl: preferred.thumbnailUrl || fallback.thumbnailUrl || null,
    createdAt:
      parsedWorkspaceTimestamp(existing.createdAt) <= parsedWorkspaceTimestamp(incoming.createdAt)
        ? existing.createdAt
        : incoming.createdAt,
    updatedAt:
      parsedWorkspaceTimestamp(existing.updatedAt) >= parsedWorkspaceTimestamp(incoming.updatedAt)
        ? existing.updatedAt
        : incoming.updatedAt,
    checkpoint: mergeCheckpoint(preferred.checkpoint, fallback.checkpoint),
  };
}

/**
 * Merge persisted production snapshots by job id without collapsing separate retries.
 * This preserves richer downstream browser state while allowing backend history to
 * repopulate a workspace after an analysis snapshot is no longer available.
 */
export function mergeWorkspaceProductions(
  existing: WorkspaceProduction[],
  incoming: WorkspaceProduction[],
): WorkspaceProduction[] {
  const byId = new Map<string, WorkspaceProduction>();

  for (const production of existing) byId.set(production.id, production);
  for (const production of incoming) {
    const saved = byId.get(production.id);
    byId.set(production.id, saved ? mergeSameWorkspaceProduction(saved, production) : production);
  }

  return Array.from(byId.values()).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export function normalizeWorkspaceProductionTitle(value?: string | null): string {
  return (value || "")
    .normalize("NFKD")
    .replace(/[’‘`]/g, "'")
    .replace(/[^a-zA-Z0-9]+/g, " ")
    .trim()
    .toLowerCase();
}

/**
 * Return the creator-facing production list. Retry/version records with the same
 * normalized title remain persisted for recovery, but only the strongest one is
 * shown and counted in the channel UI.
 */
export function getUniqueWorkspaceProductions(
  productions: WorkspaceProduction[],
): WorkspaceProduction[] {
  const byTitle = new Map<string, WorkspaceProduction>();

  for (const production of productions) {
    const key = normalizeWorkspaceProductionTitle(production.title) || `id:${production.id}`;
    const current = byTitle.get(key);
    if (!current) {
      byTitle.set(key, production);
      continue;
    }

    const preferred = preferWorkspaceProduction(current, production);
    const fallback = preferred === current ? production : current;
    byTitle.set(key, {
      ...preferred,
      thumbnailUrl: preferred.thumbnailUrl || fallback.thumbnailUrl || null,
    });
  }

  return Array.from(byTitle.values()).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

/**
 * Merge the tenant-scoped backend analysis index into the browser workspace cache.
 * Firestore is authoritative for the latest analysis id; richer browser-only
 * production/checkpoint metadata is preserved when it already exists.
 */
export function mergeWorkspaceWithAnalysisIndex(
  workspace: ReviveWorkspace,
  index: WorkspaceChannelAnalysisIndexItem[],
): ReviveWorkspace {
  if (!Array.isArray(index) || index.length === 0) return workspace;

  const localByChannel = new Map(workspace.channels.map((channel) => [channel.channelId, channel]));
  const merged: WorkspaceChannel[] = index.map((remote) => {
    const local = localByChannel.get(remote.channel_id);
    localByChannel.delete(remote.channel_id);
    return {
      channelId: remote.channel_id,
      title: remote.title || local?.title || "YouTube channel",
      handle: remote.handle ?? local?.handle ?? null,
      thumbnailUrl: remote.thumbnail_url ?? local?.thumbnailUrl ?? null,
      channelUrl: remote.channel_url || local?.channelUrl || "",
      subscriberCount: remote.subscriber_count ?? local?.subscriberCount ?? null,
      publicVideoCount: remote.public_video_count ?? local?.publicVideoCount ?? null,
      createdAt: local?.createdAt || remote.created_at,
      updatedAt:
        parsedWorkspaceTimestamp(remote.updated_at) >= parsedWorkspaceTimestamp(local?.updatedAt)
          ? remote.updated_at
          : local!.updatedAt,
      lastOpenedAt: local?.lastOpenedAt || remote.updated_at,
      analysisJobId: remote.analysis_job_id,
      dnaJobId: local?.dnaJobId,
      recoveryJobId: local?.recoveryJobId,
      productions: local?.productions ?? [],
    };
  });

  // Preserve local-only channels as a compatibility fallback. They may be legacy
  // records whose analysis predates durable Firestore persistence.
  merged.push(...localByChannel.values());
  merged.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));

  const validChannelIds = new Set(merged.map((channel) => channel.channelId));
  return {
    ...workspace,
    channels: merged,
    lastActiveChannelId:
      workspace.lastActiveChannelId && validChannelIds.has(workspace.lastActiveChannelId)
        ? workspace.lastActiveChannelId
        : merged[0]?.channelId,
  };
}

export const EMPTY_WORKSPACE: ReviveWorkspace = { version: 1, channels: [] };

export function loadWorkspace(uid: string): ReviveWorkspace {
  const userKey = workspaceStorageKey(uid);
  try {
    const raw = window.localStorage.getItem(userKey);
    if (raw) {
      const parsed = JSON.parse(raw) as ReviveWorkspace;
      if (parsed?.version === 1 && Array.isArray(parsed.channels)) return parsed;
    }

    // One-time migration from the pre-auth single-browser workspace. Removing the
    // legacy key after migration prevents another Firebase account on the same
    // browser from inheriting someone else's channel and production history.
    const migrationKey = `${WORKSPACE_MIGRATION_KEY}:${uid}`;
    const legacy = window.localStorage.getItem(WORKSPACE_STORAGE_KEY);
    if (legacy && !window.localStorage.getItem(migrationKey)) {
      const parsed = JSON.parse(legacy) as ReviveWorkspace;
      if (parsed?.version === 1 && Array.isArray(parsed.channels)) {
        window.localStorage.setItem(userKey, JSON.stringify(parsed));
        window.localStorage.setItem(migrationKey, new Date().toISOString());
        window.localStorage.removeItem(WORKSPACE_STORAGE_KEY);
        return parsed;
      }
    }
    return EMPTY_WORKSPACE;
  } catch {
    return EMPTY_WORKSPACE;
  }
}

export function saveWorkspace(workspace: ReviveWorkspace, uid: string) {
  window.localStorage.setItem(workspaceStorageKey(uid), JSON.stringify(workspace));
}

export function formatRelativeWorkspaceTime(value?: string | null) {
  if (!value) return "Recently";
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "Recently";
  const deltaMs = Math.max(0, Date.now() - timestamp);
  const minutes = Math.floor(deltaMs / 60_000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
