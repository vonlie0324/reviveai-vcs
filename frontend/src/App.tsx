import { AlertTriangle, Bot, Hand, CircleAlert, Compass, LoaderCircle, Pause, Play, RotateCcw, ShieldCheck, Sparkles, Trash2, LayoutDashboard, Clapperboard, ChartNoAxesColumn, MoreHorizontal, Music2, Wallet, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { AutopilotStateConflictError, AutopilotStateMissingError, getServerAutopilotState, saveServerAutopilotState, startSingleProductionTrial, restoreSingleTrialCampaign, humanApproveFinalVideo, aiApproveMediaKeyframe, aiSalvageMediaKeyframe, aiCreateControlledMotionFallback, aiReviewProductionBrief, aiReviewPublishingDraft, aiReviewDeliveryQc, aiReviewAudioFinishing, aiReviewFinalAssembly, aiReviewMediaClip, aiReviewMediaReference, reconcileMediaAutopilotJob, acceptMediaKeyframeAdaptation, acceptProductionBriefAdaptation, addPublishingDraftToDeliveryPackage, approveAudioFinishingJob, approveFinalAssembly, approveMediaClip, approveMediaKeyframe, approveMediaReference, approveProductionBrief, approvePublishingDraft, createAnalysisJob, createAudioFinishingJob, createContentDnaJob, createFinalAssemblyJob, createMediaStudioJob, createProductionBriefJob, createPublishingDraft, createRecoveryJob, getAnalysisJob, getAudioFinishingJob, getAudioFinishingJobs, getContentDnaJob, getLatestContentDnaJobForAnalysis, getFinalAssemblyJob, getLatestFinalAssemblyJob, getLatestMediaStudioJob, getMediaStudioJob, getProductionBriefHistory, getProductionBriefJob, getLegacyAdoptionStatus, adoptLegacyWorkspace, getPublishingDrafts, getRecoveryJob, getLatestRecoveryJobForAnalysis, getChannelAnalysisIndex, getLatestAnalysisJobForChannel, getRevivalProgram, createRevivalProgram, updateRevivalProgramCadence, getDeliveryQcReport, runDeliveryQc, acknowledgeDeliveryQc, getLatestDeliveryPackage, getDeliveryPackagesForAssembly, createDeliveryPackage, regenerateMediaClip, regenerateMediaKeyframe, regenerateMediaReference, regeneratePublishingDraft, reviewMediaKeyframe, reviewMediaKeyframes, retryProductionBriefJob, startMediaAnimation, updatePublishingDraft, discoverTrendDirections, getSavedTrendDirections, refineCustomTrendDirection, createProductionBriefFromDirection} from "./api";
import { audioAssetUrl } from "./api";
import { BrandHeader } from "./components/BrandHeader";
import { ChannelInputCard } from "./components/ChannelInputCard";
import { ChannelMetricsDashboard } from "./components/ChannelMetricsDashboard";
import { ChannelOverview } from "./components/ChannelOverview";
import { ContentDnaPanel } from "./components/ContentDnaPanel";
import { ProgressTimeline } from "./components/ProgressTimeline";
import { CreatorJourney, type CreatorJourneyStep } from "./components/CreatorJourney";
import { RecoveryIntelligencePanel } from "./components/RecoveryIntelligencePanel";
import { ProductionBriefPanel } from "./components/ProductionBriefPanel";
import { MediaStudioPanel } from "./components/MediaStudioPanel";
import { FinalAssemblyPanel } from "./components/FinalAssemblyPanel";
import { AudioFinishingPanel } from "./components/AudioFinishingPanel";
import { FinalDeliveryQcPanel } from "./components/FinalDeliveryQcPanel";
import { DeliveryPackagePanel } from "./components/DeliveryPackagePanel";
import { PublishingAssistantPanel } from "./components/PublishingAssistantPanel";
import { YouTubePublishLoopPanel } from "./components/YouTubePublishLoopPanel";
import { YouTubePublishingQueue } from "./components/YouTubePublishingQueue";
import { FinalHumanReviewPanel } from "./components/FinalHumanReviewPanel";
import { DevRecoveredReviewPanel } from "./components/DevRecoveredReviewPanel";
import { AutopilotProductionPanel } from "./components/AutopilotProductionPanel";
import { AutopilotLiveMonitor } from "./components/AutopilotLiveMonitor";
import { AutonomousOperationsConsole } from "./components/AutonomousOperationsConsole";
import { VideoLibrary } from "./components/VideoLibrary";
import { WorkspaceDashboard } from "./components/WorkspaceDashboard";
import { WorkspaceContextBar } from "./components/WorkspaceContextBar";
import { ChannelCommandCenter } from "./components/ChannelCommandCenter";
import { ChannelAutonomySettings } from "./components/ChannelAutonomySettings";
import { ChannelProductionsPanel } from "./components/ChannelProductionsPanel";
import { ProductionCostDashboard } from "./components/ProductionCostDashboard";
import { SoundtrackLibraryPanel } from "./components/SoundtrackLibraryPanel";
import { AiActivityState } from "./components/AiActivityState";
import { RevivalProgramPanel } from "./components/RevivalProgramPanel";
import { GuidedProductionWorkspace, type GuidedStage } from "./components/GuidedProductionWorkspace";
import type { AnalysisJob, AudioFinishingJob, AudioMixOptions, ContentDnaJob, DeliveryPackage, DeliveryQcReport, FinalAssemblyJob, MediaStudioJob, NextContentRecommendation, ProductionBriefHistoryEntry, ProductionBriefJob, ProductionFidelityMode, PublishingDraft, LegacyAdoptionStatus, PublishingDraftContent, RecoveryJob, RevivalProgram, TrendDirection, TrendDirectionSet } from "./types";
import { getUniqueWorkspaceProductions, loadWorkspace, mergeWorkspaceProductions, mergeWorkspaceWithAnalysisIndex, saveWorkspace, type CreatorWorkflowCheckpoint, type ReviveWorkspace, type WorkspaceChannel, type WorkspaceProduction, type WorkspaceProductionStage } from "./workspace";
import { useAuth } from "./auth";
import { AuthLoadingScreen, SignInPage } from "./components/SignInPage";
import { PlatformAdminConsole } from "./components/PlatformAdminConsole";
import { API_BASE_URL, apiFetch } from "./http";


const TERMINAL = new Set(["COMPLETED", "FAILED"]);
const DNA_TERMINAL = new Set(["COMPLETED", "FAILED"]);
const RECOVERY_TERMINAL = new Set(["COMPLETED", "FAILED"]);
const PRODUCTION_TERMINAL = new Set(["COMPLETED", "FAILED"]);
const MEDIA_POLLING_STAGES = new Set(["QUEUED", "GENERATING_REFERENCE", "GENERATING_KEYFRAMES", "REVIEWING_KEYFRAME_FIDELITY", "GENERATING_CLIPS"]);
const MEDIA_REVIEW_STAGES = new Set(["AWAITING_REFERENCE_APPROVAL", "AWAITING_KEYFRAME_REVIEW", "AWAITING_CLIP_REVIEW"]);
const ACTIVE_SHOT_OPERATION_STATES = new Set(["REGENERATING", "FIDELITY_REVIEW"]);
const ACTIVE_CLIP_OPERATION_STATES = new Set(["QUEUED", "GENERATING"]);
const ASSEMBLY_POLLING_STAGES = new Set(["QUEUED", "PREPARING", "RENDERING"]);
const AUDIO_POLLING_STAGES = new Set(["QUEUED", "PREPARING", "SYNTHESIZING_VOICE", "BUILDING_MIX", "RENDERING"]);
const WORKFLOW_CHECKPOINT_KEY = "reviveai.creatorWorkflow.v1";
const AUTOPILOT_STORAGE_PREFIX = "reviveai.autopilot.v2";
const AUTOPILOT_MAX_RETRIES = 2;
const AUTOPILOT_MAX_GENERATION_ATTEMPTS = 3;
const AUTOPILOT_ALTERNATE_APPROACH_LIMIT = 5;
const AUTOPILOT_SHOT_REPLAN_LIMIT = 7;
const AUTOPILOT_STALE_CHECKPOINT_MS = 8 * 60 * 1000;
const AUTOPILOT_WATCHDOG_COOLDOWN_MS = 2 * 60 * 1000;
const AUTOPILOT_WATCHDOG_REQUEST_TIMEOUT_MS = 90 * 1000;

type AutopilotStatus = "IDLE" | "RUNNING" | "PAUSED" | "NEEDS_ATTENTION" | "WAITING_FOR_FINAL_APPROVAL" | "WAITING_FOR_LEARNING" | "COMPLETED";
type AutopilotWatchdogStatus = "IDLE" | "CHECKING" | "RECOVERED" | "WAITING";

interface AutopilotWatchdogState {
  status: AutopilotWatchdogStatus;
  message: string;
  lastRunAt: number | null;
}
type AutopilotAttentionStage =
  | "PRODUCTION_DIRECTION"
  | "REFERENCE"
  | "KEYFRAME_ADAPTATION"
  | "CLIPS"
  | "VISUAL_MASTER"
  | "AUDIO_MASTER"
  | "DELIVERY_QC"
  | "PUBLISHING_COPY"
  | "FINAL_VIDEO"
  | "FAILURE"
  | null;

interface AutopilotBlockedProduction {
  recommendationId: string;
  title: string;
  message: string;
  attentionStage: AutopilotAttentionStage;
  blockedAt: string;
  kind: "INFRASTRUCTURE" | "CONTENT" | "TECHNICAL";
  // Durable lineage is optional so old saved sessions hydrate safely. New
  // quarantines persist it to make Retry after fix deterministic.
  productionJobId?: string | null;
  recoveryJobId?: string | null;
  analysisJobId?: string | null;
  resolutionStatus?: "RETRYABLE" | "ARCHIVED" | "BLOCKING" | null;
  resolutionReason?: string | null;
  resolvedAt?: string | null;
  blocksAutonomy?: boolean | null;
}

function normalizeBlockedProduction(item: AutopilotBlockedProduction): AutopilotBlockedProduction {
  if (item.resolutionStatus && item.blocksAutonomy != null) return item;
  const hasLineage = Boolean(item.productionJobId || item.recoveryJobId || item.analysisJobId);
  if (item.kind === "INFRASTRUCTURE") {
    return {
      ...item,
      resolutionStatus: "BLOCKING",
      resolutionReason: item.resolutionReason || "INFRASTRUCTURE_ACTION_REQUIRED",
      resolvedAt: item.resolvedAt || null,
      blocksAutonomy: true,
    };
  }
  if (hasLineage) {
    return {
      ...item,
      resolutionStatus: "RETRYABLE",
      resolutionReason: item.resolutionReason || "DURABLE_LINEAGE_AVAILABLE",
      resolvedAt: item.resolvedAt || null,
      blocksAutonomy: false,
    };
  }
  return {
    ...item,
    resolutionStatus: "ARCHIVED",
    resolutionReason: item.resolutionReason || "LEGACY_LINEAGE_UNAVAILABLE",
    resolvedAt: item.resolvedAt || new Date().toISOString(),
    blocksAutonomy: false,
  };
}

function blockedProductionBlocksAutonomy(item: AutopilotBlockedProduction): boolean {
  return normalizeBlockedProduction(item).blocksAutonomy === true;
}

function blockingAutopilotProductions(items: AutopilotBlockedProduction[]): AutopilotBlockedProduction[] {
  return items.map(normalizeBlockedProduction).filter(blockedProductionBlocksAutonomy);
}

function archivedAutopilotProductions(items: AutopilotBlockedProduction[]): AutopilotBlockedProduction[] {
  return items.map(normalizeBlockedProduction).filter((item) => !blockedProductionBlocksAutonomy(item));
}

interface AutopilotSession {
  version: 2;
  scope: "CAMPAIGN" | "PRODUCTION";
  status: AutopilotStatus;
  executionOwner: "FRONTEND" | "BACKEND";
  executionVersion: number;
  recoveryJobId: string | null;
  programId: string | null;
  currentProductionJobId: string | null;
  currentMediaJobId: string | null;
  currentAssemblyJobId: string | null;
  currentAudioJobId: string | null;
  currentDeliveryPackageId: string | null;
  currentPublishingDraftId: string | null;
  currentPublicationId: string | null;
  learningCheckpointRequired: string | null;
  learningWaitStartedAt: string | null;
  lastSupervisorHeartbeatAt: string | null;
  currentRecommendationId: string | null;
  currentTitle: string | null;
  currentStartedAt: string | null;
  completedRecommendationIds: string[];
  blockedProductions: AutopilotBlockedProduction[];
  attempts: Record<string, number>;
  attentionStage: AutopilotAttentionStage;
  message: string;
  startedAt: string | null;
  updatedAt: string;
}

const AUTOPILOT_AUDIO_DEFAULTS: AudioMixOptions = {
  music_enabled: true,
  voiceover_enabled: true,
  ambience_sfx_enabled: true,
  voice_volume: 1,
  music_volume: 0.55,
  music_source: "YOUTUBE_AUDIO_LIBRARY",
  music_preset: "AUTO",
  trending_track_id: null,
  youtube_audio_library_track_id: null,
  ambience_volume: 0.7,
  duck_music_during_voiceover: true,
  voice_name: null,
};

function emptyAutopilotSession(): AutopilotSession {
  return {
    version: 2,
    scope: "CAMPAIGN",
    status: "IDLE",
    executionOwner: "BACKEND",
    executionVersion: 1,
    recoveryJobId: null,
    programId: null,
    currentProductionJobId: null,
    currentMediaJobId: null,
    currentAssemblyJobId: null,
    currentAudioJobId: null,
    currentDeliveryPackageId: null,
    currentPublishingDraftId: null,
    currentPublicationId: null,
    learningCheckpointRequired: null,
    learningWaitStartedAt: null,
    lastSupervisorHeartbeatAt: null,
    currentRecommendationId: null,
    currentTitle: null,
    currentStartedAt: null,
    completedRecommendationIds: [],
    blockedProductions: [],
    attempts: {},
    attentionStage: null,
    message: "Ready to produce the revival slate sequentially.",
    startedAt: null,
    updatedAt: new Date().toISOString(),
  };
}

function loadAutopilotSession(storageKey: string): AutopilotSession {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return emptyAutopilotSession();
    const parsed = JSON.parse(raw) as Partial<AutopilotSession>;
    if (parsed.version !== 2 || typeof parsed.status !== "string") return emptyAutopilotSession();
    return {
      ...emptyAutopilotSession(),
      ...parsed,
      executionOwner: parsed.executionOwner ?? "FRONTEND",
      executionVersion: parsed.executionVersion ?? 0,
      completedRecommendationIds: Array.isArray(parsed.completedRecommendationIds) ? parsed.completedRecommendationIds : [],
      blockedProductions: Array.isArray(parsed.blockedProductions) ? parsed.blockedProductions.map(normalizeBlockedProduction) : [],
      attempts: parsed.attempts && typeof parsed.attempts === "object" ? parsed.attempts : {},
    } as AutopilotSession;
  } catch {
    return emptyAutopilotSession();
  }
}

function orderedRevivalRecommendationIds(program: RevivalProgram): string[] {
  const ideasById = new Map(program.ideas.map((idea) => [idea.idea_id, idea]));
  const scheduled = [...program.weekly_slate]
    .sort((a, b) => a.week - b.week || a.slot - b.slot)
    .map((slot) => ideasById.get(slot.idea_id)?.recommendation_id)
    .filter((value): value is string => Boolean(value));
  const unscheduled = program.ideas.map((idea) => idea.recommendation_id);
  return Array.from(new Set([...scheduled, ...unscheduled]));
}

function isTransientAutopilotInfrastructureError(message: string): boolean {
  const value = message.toLowerCase();
  return [
    "oauth2.googleapis.com",
    "failed to resolve",
    "name resolution",
    "getaddrinfo",
    "temporary failure in name resolution",
    "connection reset",
    "connection aborted",
    "connection refused",
    "read timed out",
    "connect timeout",
    "service unavailable",
    "503",
    "429",
  ].some((needle) => value.includes(needle));
}

function friendlyAutopilotExceptionMessage(message: string): string {
  if (isTransientAutopilotInfrastructureError(message)) {
    return "A temporary Google/Gemini connectivity or authentication request failed. This production was moved to Needs attention so it does not block the rest of the revival campaign.";
  }
  return message;
}

function hasActiveShotOperation(job: MediaStudioJob | null): boolean {
  const operations = job?.result?.shot_operations ?? {};
  return Object.values(operations).some((operation) => ACTIVE_SHOT_OPERATION_STATES.has(operation.status));
}

function hasActiveClipOperation(job: MediaStudioJob | null): boolean {
  const operations = job?.result?.clip_operations ?? {};
  return Object.values(operations).some((operation) => ACTIVE_CLIP_OPERATION_STATES.has(operation.status));
}

function activeAiClipReviewOperation(job: MediaStudioJob | null): Record<string, unknown> | null {
  if (!job) return null;
  const detail = detailRecord(job.detail);
  const operations = detailRecord(detail.ai_clip_review_operations);
  for (const value of Object.values(operations)) {
    const operation = detailRecord(value);
    if (String(operation.status || "").toUpperCase() === "RUNNING") return operation;
  }
  return null;
}

function hasActiveAiClipReviewOperation(job: MediaStudioJob | null): boolean {
  return Boolean(activeAiClipReviewOperation(job));
}

function shouldPollMediaJob(job: MediaStudioJob | null): boolean {
  return Boolean(job && (MEDIA_POLLING_STAGES.has(job.stage) || hasActiveShotOperation(job) || hasActiveClipOperation(job) || hasActiveAiClipReviewOperation(job)));
}

function detailRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

function parsedTimestamp(value?: string | null): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function latestAutopilotBackendCheckpoint(args: {
  productionJob: ProductionBriefJob | null;
  mediaJob: MediaStudioJob | null;
  assemblyJob: FinalAssemblyJob | null;
  audioJob: AudioFinishingJob | null;
  qc: DeliveryQcReport | null;
  deliveryPackage: DeliveryPackage | null;
  publishingDraft: PublishingDraft | null;
}): number | null {
  const values = [
    parsedTimestamp(args.productionJob?.updated_at),
    parsedTimestamp(args.mediaJob?.updated_at),
    parsedTimestamp(args.assemblyJob?.updated_at),
    parsedTimestamp(args.audioJob?.updated_at),
    parsedTimestamp(args.qc?.generated_at),
    parsedTimestamp(args.deliveryPackage?.generated_at),
    parsedTimestamp(args.publishingDraft?.updated_at),
  ].filter((value): value is number => value != null);
  return values.length ? Math.max(...values) : null;
}

function assemblyMatchesCurrentMedia(assembly: FinalAssemblyJob | null | undefined, media: MediaStudioJob | null | undefined): boolean {
  if (!assembly?.result || !media?.result) return false;
  const currentClips = new Map(media.result.video_clips.map((clip) => [clip.shot_number, clip.asset_id]));
  if (assembly.result.timeline.length !== media.result.required_clips) return false;
  return assembly.result.timeline.every((item) => currentClips.get(item.shot_number) === item.source_clip_asset_id);
}

function humanFinalApproved(job: AudioFinishingJob | null): boolean {
  return Boolean(job && detailRecord(job.detail).human_final_approved === true);
}

function aiReviewExhausted(job: { detail?: Record<string, unknown> | null } | null): boolean {
  return Boolean(job && detailRecord(job.detail).ai_review_exhausted === true);
}

function aiDecisionPassed(value: unknown): boolean {
  return String(detailRecord(value).decision || "").toUpperCase() === "PASS";
}

function planAiPassed(job: ProductionBriefJob | null | undefined): boolean {
  if (!job?.result || job.stage !== "COMPLETED") return false;
  const detail = detailRecord(job.detail);
  const reviewIsCurrent = String(detail.ai_plan_review_for_generated_at || "") === job.result.generated_at;
  return job.result.review_status === "APPROVED"
    && String(detail.approval_actor || "").toUpperCase() === "AI"
    && reviewIsCurrent
    && aiDecisionPassed(detail.ai_plan_review);
}

function referenceAiPassed(job: MediaStudioJob | null | undefined): boolean {
  if (!job?.result?.reference_asset || !job.result.reference_approved) return false;
  const detail = detailRecord(job.detail);
  const review = detail.reference_ai_review ?? detail.ai_reference_review;
  return String(detail.reference_approval_actor || "").toUpperCase() === "AI"
    && aiDecisionPassed(review);
}

function keyframesAiPassed(job: MediaStudioJob | null | undefined): boolean {
  if (!job?.result || job.result.required_keyframes <= 0) return false;
  if (job.result.keyframes.length < job.result.required_keyframes) return false;
  const detail = detailRecord(job.detail);
  const actors = detailRecord(detail.keyframe_approval_actor);
  const salvaged = detailRecord(detail.ai_salvaged_keyframes);
  return job.result.keyframes.every((asset) => {
    const salvage = detailRecord(salvaged[String(asset.shot_number)]);
    const salvagePassed = String(salvage.outcome || "").toUpperCase() === "AI_SALVAGED"
      && asset.fidelity_report?.status === "ADAPTATION_ACCEPTED"
      && asset.fidelity_report.creator_override === false;
    return asset.review_status === "APPROVED"
      && (asset.fidelity_report?.status === "PASS" || salvagePassed)
      && String(actors[String(asset.shot_number)] || "").toUpperCase() === "AI";
  });
}

function clipsAiPassed(job: MediaStudioJob | null | undefined): boolean {
  if (!job?.result || job.result.required_clips <= 0) return false;
  if (job.result.video_clips.length < job.result.required_clips) return false;
  const detail = detailRecord(job.detail);
  const actors = detailRecord(detail.clip_approval_actor);
  const reviews = detailRecord(detail.ai_clip_reviews);
  return job.result.video_clips.every((clip) =>
    clip.review_status === "APPROVED"
    && String(actors[String(clip.shot_number)] || "").toUpperCase() === "AI"
    && aiDecisionPassed(reviews[String(clip.shot_number)])
  );
}

function visualMasterAiPassed(assembly: FinalAssemblyJob | null | undefined, media: MediaStudioJob | null | undefined): boolean {
  if (!assembly?.result || assembly.stage !== "DELIVERED" || assembly.result.review_status !== "APPROVED") return false;
  const detail = detailRecord(assembly.detail);
  return String(detail.approval_actor || "").toUpperCase() === "AI"
    && aiDecisionPassed(detail.ai_visual_master_review)
    && assemblyMatchesCurrentMedia(assembly, media);
}

function audioMasterAiPassed(audio: AudioFinishingJob | null | undefined, assembly: FinalAssemblyJob | null | undefined): boolean {
  if (!audio?.result || audio.stage !== "DELIVERED" || audio.result.review_status !== "APPROVED") return false;
  const detail = detailRecord(audio.detail);
  return String(detail.approval_actor || "").toUpperCase() === "AI"
    && aiDecisionPassed(detail.ai_audio_review)
    && Boolean(assembly?.job_id && audio.assembly_job_id === assembly.job_id);
}

function publishingAiPassed(draft: PublishingDraft | null | undefined): boolean {
  return Boolean(
    draft
    && draft.status === "APPROVED"
    && (draft.generation_note || "").includes("[AI_REVIEW_APPROVED]")
  );
}

type AiReviewGateKey =
  | "PLAN"
  | "REFERENCE"
  | "KEYFRAMES"
  | "MOTION"
  | "VISUAL_MASTER"
  | "AUDIO"
  | "QC"
  | "PUBLISHING"
  | "PACKAGE";

interface AiReviewGateSummary {
  gates: Record<AiReviewGateKey, boolean>;
  allPassed: boolean;
  firstIncomplete: AiReviewGateKey | null;
  blockingReason: string | null;
}

function summarizeAiReviewGates(args: {
  productionJob: ProductionBriefJob | null;
  mediaJob: MediaStudioJob | null;
  assemblyJob: FinalAssemblyJob | null;
  audioJob: AudioFinishingJob | null;
  qc: DeliveryQcReport | null;
  deliveryPackage: DeliveryPackage | null;
  publishingDraft: PublishingDraft | null;
}): AiReviewGateSummary {
  const { productionJob, mediaJob, assemblyJob, audioJob, qc, deliveryPackage, publishingDraft } = args;
  const gates: Record<AiReviewGateKey, boolean> = {
    PLAN: planAiPassed(productionJob),
    REFERENCE: referenceAiPassed(mediaJob),
    KEYFRAMES: keyframesAiPassed(mediaJob),
    MOTION: clipsAiPassed(mediaJob),
    VISUAL_MASTER: visualMasterAiPassed(assemblyJob, mediaJob),
    AUDIO: audioMasterAiPassed(audioJob, assemblyJob),
    QC: Boolean(qc && audioJob && qc.audio_job_id === audioJob.job_id && qc.overall_status === "READY"),
    PUBLISHING: publishingAiPassed(publishingDraft),
    PACKAGE: Boolean(
      deliveryPackage
      && audioJob
      && qc
      && publishingDraft
      && deliveryPackage.audio_job_id === audioJob.job_id
      && deliveryPackage.qc_report_id === qc.report_id
      && deliveryPackage.publishing_draft_id === publishingDraft.draft_id
    ),
  };

  const ordered: AiReviewGateKey[] = ["PLAN", "REFERENCE", "KEYFRAMES", "MOTION", "VISUAL_MASTER", "AUDIO", "QC", "PUBLISHING", "PACKAGE"];
  const firstIncomplete = ordered.find((key) => !gates[key]) ?? null;

  const mediaDetail = detailRecord(mediaJob?.detail);
  const exhaustedClips = Array.isArray(mediaDetail.ai_review_exhausted_clips) ? mediaDetail.ai_review_exhausted_clips : [];
  let blockingReason: string | null = null;
  if (mediaDetail.ai_review_exhausted === true) {
    const stage = String(mediaDetail.ai_review_exhausted_stage || "visual identity").toLowerCase();
    blockingReason = `AI ${stage} review exhausted its automatic regeneration attempts.`;
  } else if (exhaustedClips.length > 0) {
    blockingReason = `AI motion review could not clear shot ${String(exhaustedClips[0])} within the automatic retry limit.`;
  } else if (aiReviewExhausted(assemblyJob)) {
    blockingReason = "AI visual-master review exhausted its automatic rerender attempts.";
  } else if (aiReviewExhausted(audioJob)) {
    blockingReason = "AI audio review exhausted its automatic remix attempts.";
  } else if (qc?.overall_status === "BLOCKED") {
    blockingReason = "Deterministic delivery QC found a blocking technical failure.";
  } else if ((publishingDraft?.generation_note || "").includes("exhausted automatic copy revisions")) {
    blockingReason = "AI publishing review exhausted its automatic rewrite attempts.";
  }

  return { gates, allPassed: firstIncomplete === null, firstIncomplete, blockingReason };
}

function aiGateLabel(key: AiReviewGateKey | null): string {
  switch (key) {
    case "PLAN": return "plan + text review";
    case "REFERENCE": return "visual identity review";
    case "KEYFRAMES": return "storyboard fidelity review";
    case "MOTION": return "motion fidelity review";
    case "VISUAL_MASTER": return "visual-master review";
    case "AUDIO": return "audio review";
    case "QC": return "technical delivery QC";
    case "PUBLISHING": return "publishing-text review";
    case "PACKAGE": return "final package verification";
    default: return "AI review";
  }
}

function normalizeProductionTitle(value?: string | null): string {
  return (value || "")
    .normalize("NFKD")
    .replace(/[’‘`]/g, "'")
    .replace(/[^a-zA-Z0-9]+/g, " ")
    .trim()
    .toLowerCase();
}

function CreatorApp() {
  const { user: authenticatedUser } = useAuth();
  const currentUser = authenticatedUser!;
  const workflowCheckpointKey = `${WORKFLOW_CHECKPOINT_KEY}:${currentUser.uid}`;
  const autopilotStorageKey = `${AUTOPILOT_STORAGE_PREFIX}:${currentUser.uid}`; // legacy migration only
  const [autopilot, setAutopilot] = useState<AutopilotSession>(() => emptyAutopilotSession());
  const [autopilotHydrated, setAutopilotHydrated] = useState(false);
  const [autopilotCheckpointAbsent, setAutopilotCheckpointAbsent] = useState(false);
  const [autopilotPersistenceError, setAutopilotPersistenceError] = useState<string | null>(null);
  const [autopilotSyncNotice, setAutopilotSyncNotice] = useState<string | null>(null);
  const [autopilotHydrationRetryTick, setAutopilotHydrationRetryTick] = useState(0);
  const [autopilotPersistRetryTick, setAutopilotPersistRetryTick] = useState(0);
  const autopilotServerRevisionRef = useRef<number | null>(null);
  const autopilotLastPersistedUpdatedAtRef = useRef<string | null>(null);
  const autopilotPersistTimerRef = useRef<number | null>(null);
  const autopilotPersistChainRef = useRef<Promise<void>>(Promise.resolve());
  const [autopilotRecoveryPending, setAutopilotRecoveryPending] = useState(false);
  const [briefReconcileConfirmOpen, setBriefReconcileConfirmOpen] = useState(false);
  const [briefReconcilePending, setBriefReconcilePending] = useState(false);
  const [briefReconcileError, setBriefReconcileError] = useState<string | null>(null);
  const [autonomyStartConfirmOpen, setAutonomyStartConfirmOpen] = useState(false);
  const [autonomyPreflightConfirmed, setAutonomyPreflightConfirmed] = useState(false);
  const [autopilotWatchdog, setAutopilotWatchdog] = useState<AutopilotWatchdogState>({ status: "IDLE", message: "", lastRunAt: null });
  const autopilotWatchdogRunningRef = useRef(false);
  const [url, setUrl] = useState("");
  const [job, setJob] = useState<AnalysisJob | null>(null);
  const [dnaJob, setDnaJob] = useState<ContentDnaJob | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [dnaRequestError, setDnaRequestError] = useState<string | null>(null);
  const [recoveryJob, setRecoveryJob] = useState<RecoveryJob | null>(null);
  const [recoveryRequestError, setRecoveryRequestError] = useState<string | null>(null);
  const [revivalProgram, setRevivalProgram] = useState<RevivalProgram | null>(null);
  const [revivalProgramPending, setRevivalProgramPending] = useState(false);
  const [revivalProgramError, setRevivalProgramError] = useState<string | null>(null);
  const [trendDirections, setTrendDirections] = useState<TrendDirectionSet | null>(null);
  const [trendDirectionPending, setTrendDirectionPending] = useState(false);
  const [trendDirectionError, setTrendDirectionError] = useState<string | null>(null);
  const [customDirectionPending, setCustomDirectionPending] = useState(false);
  const [directionStudioRequested, setDirectionStudioRequested] = useState(false);
  const [revivalLineageCheckPending, setRevivalLineageCheckPending] = useState(false);
  const [revivalRestorePending, setRevivalRestorePending] = useState(false);
  const [revivalRestorePhase, setRevivalRestorePhase] = useState<"CONTENT_DNA" | "RECOVERY" | null>(null);
  const [productionBriefJob, setProductionBriefJob] = useState<ProductionBriefJob | null>(null);
  const [productionBriefError, setProductionBriefError] = useState<string | null>(null);
  const [selectedRecommendationId, setSelectedRecommendationId] = useState<string | null>(null);
  const [singleTrialConfirmation, setSingleTrialConfirmation] = useState<{ recommendationId: string; title: string } | null>(null);
  const [pendingTrialBrief, setPendingTrialBrief] = useState<{ recommendationId: string; title: string } | null>(null);
  const [singleTrialSubmitting, setSingleTrialSubmitting] = useState(false);
  const [savedProductionAutopilotConfirmation, setSavedProductionAutopilotConfirmation] = useState<{ productionId: string; title: string; switching: boolean } | null>(null);
  const [savedProductionStartError, setSavedProductionStartError] = useState<string | null>(null);
  const [productionHistory, setProductionHistory] = useState<ProductionBriefHistoryEntry[]>([]);
  const [productionHistoryReady, setProductionHistoryReady] = useState(false);
  const [mediaStudioJob, setMediaStudioJob] = useState<MediaStudioJob | null>(null);
  const [mediaStudioError, setMediaStudioError] = useState<string | null>(null);
  const [finalAssemblyJob, setFinalAssemblyJob] = useState<FinalAssemblyJob | null>(null);
  const [finalAssemblyError, setFinalAssemblyError] = useState<string | null>(null);
  const [audioFinishingJob, setAudioFinishingJob] = useState<AudioFinishingJob | null>(null);
  const [audioVersionHistory, setAudioVersionHistory] = useState<AudioFinishingJob[]>([]);
  const [audioFinishingError, setAudioFinishingError] = useState<string | null>(null);
  const [deliveryQcReport, setDeliveryQcReport] = useState<DeliveryQcReport | null>(null);
  const [deliveryQcError, setDeliveryQcError] = useState<string | null>(null);
  const [deliveryQcPending, setDeliveryQcPending] = useState(false);
  const [deliveryQcResumePending, setDeliveryQcResumePending] = useState(false);
  const [deliveryPackage, setDeliveryPackage] = useState<DeliveryPackage | null>(null);
  const [deliveryPackageError, setDeliveryPackageError] = useState<string | null>(null);
  const [deliveryPackagePending, setDeliveryPackagePending] = useState(false);
  const [deliveryPackageResumePending, setDeliveryPackageResumePending] = useState(false);
  const [deliveryPackageHistory, setDeliveryPackageHistory] = useState<DeliveryPackage[]>([]);
  const [publishingDraft, setPublishingDraft] = useState<PublishingDraft | null>(null);
  const [publishingDraftHistory, setPublishingDraftHistory] = useState<PublishingDraft[]>([]);
  const [publishingError, setPublishingError] = useState<string | null>(null);
  const [publishingResumePending, setPublishingResumePending] = useState(false);
  const [publishingAction, setPublishingAction] = useState<"GENERATE" | "SAVE" | "REGENERATE" | "APPROVE" | "PACKAGE" | "FORK" | null>(null);
  const [finalHumanApprovalPending, setFinalHumanApprovalPending] = useState(false);
  const [finalHumanApprovalError, setFinalHumanApprovalError] = useState<string | null>(null);
  const [finalHumanOverrideReason, setFinalHumanOverrideReason] = useState<string | null>(null);
  const [finalApprovalDialog, setFinalApprovalDialog] = useState<"NORMAL" | "OVERRIDE" | null>(null);
  const [finalOverrideNote, setFinalOverrideNote] = useState("Reviewed the finished video and accept the creative-quality differences.");
  const [mediaResumePending, setMediaResumePending] = useState(false);
  const [assemblyResumePending, setAssemblyResumePending] = useState(false);
  const [audioResumePending, setAudioResumePending] = useState(false);
  const pollingRef = useRef<number | null>(null);
  const dnaPollingRef = useRef<number | null>(null);
  const recoveryPollingRef = useRef<number | null>(null);
  const productionPollingRef = useRef<number | null>(null);
  const mediaPollingRef = useRef<number | null>(null);
  const assemblyPollingRef = useRef<number | null>(null);
  const audioPollingRef = useRef<number | null>(null);
  const autopilotActionRef = useRef(false);
  const workflowRestoreAttemptedRef = useRef(false);
  const [workflowRestorePending, setWorkflowRestorePending] = useState(true);
  const [workspace, setWorkspace] = useState<ReviveWorkspace>(() => loadWorkspace(currentUser.uid));
  const [workspaceView, setWorkspaceView] = useState<"workspace" | "add-channel" | "channel" | "production">(() => loadWorkspace(currentUser.uid).channels.length ? "workspace" : "add-channel");
  const [workspaceRestoreError, setWorkspaceRestoreError] = useState<string | null>(null);
  const [legacyAdoptionStatus, setLegacyAdoptionStatus] = useState<LegacyAdoptionStatus | null>(null);
  const [legacyAdoptionPending, setLegacyAdoptionPending] = useState(false);
  const [legacyAdoptionError, setLegacyAdoptionError] = useState<string | null>(null);
  const [analysisIntent, setAnalysisIntent] = useState<"ADD" | "REFRESH">("ADD");
  const [channelPendingRemoval, setChannelPendingRemoval] = useState<WorkspaceChannel | null>(null);
  const [manageChannelsOpen, setManageChannelsOpen] = useState(false);
  const [channelSettingsOpen, setChannelSettingsOpen] = useState(false);
  const [channelTab, setChannelTab] = useState<"overview" | "autonomy" | "directions" | "soundtracks" | "intelligence" | "productions" | "costs">("overview");
  const [productionReturnLocation, setProductionReturnLocation] = useState<"workspace" | "overview" | "autonomy" | "directions" | "soundtracks" | "intelligence" | "productions" | "costs">("productions");
  const [activeChannelId, setActiveChannelId] = useState<string | null>(() => loadWorkspace(currentUser.uid).lastActiveChannelId ?? null);
  const [activeProductionId, setActiveProductionId] = useState<string | null>(() => loadWorkspace(currentUser.uid).lastActiveProductionId ?? null);

  const isRunning = Boolean(job && !TERMINAL.has(job.stage));
  useEffect(() => {
    if (workspaceView !== "channel") setChannelSettingsOpen(false);
  }, [workspaceView, activeChannelId]);

  const approvedAudioMaster = [audioFinishingJob, ...audioVersionHistory]
    .filter((item): item is AudioFinishingJob => Boolean(item))
    .filter((item) => item.stage === "DELIVERED" && item.result?.review_status === "APPROVED")
    .sort((a, b) => b.version_number - a.version_number || b.updated_at.localeCompare(a.updated_at))[0] ?? null;

    
  useEffect(() => {
    let cancelled = false;

    async function restoreCreatorWorkflow() {
      // M2D.1: a returning creator lands in the workspace instead of reopening
      // a long single-channel report. The legacy checkpoint is only used once
      // to migrate pre-workspace sessions.
      if (workspace.channels.length > 0) {
        workflowRestoreAttemptedRef.current = true;
        if (!cancelled) setWorkflowRestorePending(false);
        return;
      }
      let checkpoint: CreatorWorkflowCheckpoint | null = null;
      try {
        // SECURITY: never adopt the pre-authentication, unscoped workflow checkpoint.
        // That legacy key has no trustworthy owner identity, so assigning it to the
        // next account that signs in can expose another creator's private ReviveAI
        // analysis/production state. Only this Firebase uid's namespaced checkpoint
        // may be restored. The unscoped key is discarded rather than migrated.
        window.localStorage.removeItem(WORKFLOW_CHECKPOINT_KEY);
        const raw = window.localStorage.getItem(workflowCheckpointKey);
        if (raw) {
          const parsed = JSON.parse(raw) as CreatorWorkflowCheckpoint;
          if (parsed?.version === 1 && parsed.analysisJobId) {
            checkpoint = parsed;
          }
        }
      } catch {
        window.localStorage.removeItem(workflowCheckpointKey);
      }

      if (!checkpoint) {
        workflowRestoreAttemptedRef.current = true;
        if (!cancelled) setWorkflowRestorePending(false);
        return;
      }

      try {
        const restoredAnalysis = await getAnalysisJob(checkpoint.analysisJobId);
        if (cancelled) return;
        setJob(restoredAnalysis);
        if (checkpoint.url) setUrl(checkpoint.url);

        const tasks: Array<Promise<void>> = [];
        if (checkpoint.dnaJobId) tasks.push(getContentDnaJob(checkpoint.dnaJobId).then((item) => { if (!cancelled) setDnaJob(item); }).catch(() => undefined));
        if (checkpoint.recoveryJobId) tasks.push(getRecoveryJob(checkpoint.recoveryJobId).then((item) => { if (!cancelled) setRecoveryJob(item); }).catch(() => undefined));
        if (checkpoint.productionBriefJobId) tasks.push(getProductionBriefJob(checkpoint.productionBriefJobId).then((item) => {
          if (!cancelled) {
            setProductionBriefJob(item);
            setSelectedRecommendationId(item.recommendation_id);
          }
        }).catch(() => undefined));
        if (checkpoint.mediaStudioJobId) tasks.push(getMediaStudioJob(checkpoint.mediaStudioJobId).then((item) => { if (!cancelled) setMediaStudioJob(item); }).catch(() => undefined));
        if (checkpoint.finalAssemblyJobId) tasks.push(getFinalAssemblyJob(checkpoint.finalAssemblyJobId).then((item) => { if (!cancelled) setFinalAssemblyJob(item); }).catch(() => undefined));
        if (checkpoint.audioFinishingJobId) tasks.push(getAudioFinishingJob(checkpoint.audioFinishingJobId).then((item) => {
          if (!cancelled) {
            setAudioFinishingJob(item);
            setAudioVersionHistory((current) => [item, ...current.filter((version) => version.job_id !== item.job_id)]);
          }
        }).catch(() => undefined));
        await Promise.all(tasks);
      } catch {
        window.localStorage.removeItem(workflowCheckpointKey);
      } finally {
        workflowRestoreAttemptedRef.current = true;
        if (!cancelled) setWorkflowRestorePending(false);
      }
    }

    void restoreCreatorWorkflow();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    saveWorkspace(workspace, currentUser.uid);
  }, [workspace, currentUser.uid]);

  // Cross-device workspace bootstrap: Firestore-backed completed analyses are the
  // authoritative channel index. localStorage remains a fast browser cache only.
  useEffect(() => {
    let cancelled = false;

    async function hydrateWorkspaceFromServer() {
      try {
        const index = await getChannelAnalysisIndex();
        if (cancelled || index.length === 0) return;

        setWorkspace((current) => mergeWorkspaceWithAnalysisIndex(current, index));
        if (workspaceView === "add-channel" && !job) {
          setWorkspaceView("workspace");
        }
      } catch (error) {
        // The local cache is still usable if the lightweight server index is
        // temporarily unavailable. Do not turn this into a blocking error banner.
        console.warn("Unable to hydrate channel workspace from the server", error);
      }
    }

    void hydrateWorkspaceFromServer();
    return () => { cancelled = true; };
  }, [currentUser.uid]);

  // v3.0: hydrate the campaign supervisor from the authenticated, tenant-scoped backend.
  // localStorage is read only once as a migration source for pre-v3 sessions.
  useEffect(() => {
    let cancelled = false;
    let hydrationSucceeded = false;
    setAutopilotHydrated(false);

    async function hydrateAutopilot() {
      try {
        const serverState = await getServerAutopilotState<AutopilotSession>();
        if (cancelled) return;
        if (serverState) {
          autopilotServerRevisionRef.current = serverState.revision;
          autopilotLastPersistedUpdatedAtRef.current = serverState.session.updatedAt;
          setAutopilot({
            ...emptyAutopilotSession(),
            ...serverState.session,
            completedRecommendationIds: Array.isArray(serverState.session.completedRecommendationIds) ? serverState.session.completedRecommendationIds : [],
            blockedProductions: Array.isArray(serverState.session.blockedProductions) ? serverState.session.blockedProductions.map(normalizeBlockedProduction) : [],
            attempts: serverState.session.attempts && typeof serverState.session.attempts === "object" ? serverState.session.attempts : {},
          });
          window.localStorage.removeItem(autopilotStorageKey);
        } else {
          // One-time migration from v2.x browser persistence. The next persistence effect
          // writes this snapshot to the server and then removes the legacy key.
          const legacy = loadAutopilotSession(autopilotStorageKey);
          autopilotServerRevisionRef.current = 0;
          autopilotLastPersistedUpdatedAtRef.current = null;
          setAutopilot(legacy);
        }
        hydrationSucceeded = true;
        setAutopilotCheckpointAbsent(false);
        setAutopilotPersistenceError(null);
      } catch (error) {
        if (cancelled) return;
        // A missing record requires a deliberate one-time initialization action.
        // A transient network/storage error must NEVER initialize or overwrite state.
        setAutopilotCheckpointAbsent(error instanceof AutopilotStateMissingError);
        setAutopilotPersistenceError(error instanceof Error ? error.message : "Unable to restore Autopilot state from the server.");
        window.setTimeout(() => {
          if (!cancelled) setAutopilotHydrationRetryTick((value) => value + 1);
        }, 5000);
      } finally {
        if (!cancelled && hydrationSucceeded) setAutopilotHydrated(true);
      }
    }

    void hydrateAutopilot();
    return () => { cancelled = true; };
  }, [currentUser.uid, autopilotStorageKey, autopilotHydrationRetryTick]);

  // v3.1: backend-owned Autopilot continues without the browser. While this page is
  // open, poll only the compact supervisor state so the UI mirrors progress made by
  // Cloud Run. The persisted job stores remain authoritative for generated artifacts.
  useEffect(() => {
    if (!autopilotHydrated || autopilot.executionOwner !== "BACKEND") return;
    let cancelled = false;

    async function syncBackendAutopilot() {
      try {
        const serverState = await getServerAutopilotState<AutopilotSession>();
        if (cancelled || !serverState) return;
        if (autopilotServerRevisionRef.current != null && serverState.revision <= autopilotServerRevisionRef.current) return;
        autopilotServerRevisionRef.current = serverState.revision;
        autopilotLastPersistedUpdatedAtRef.current = serverState.session.updatedAt;
        setAutopilot({
          ...emptyAutopilotSession(),
          ...serverState.session,
          completedRecommendationIds: Array.isArray(serverState.session.completedRecommendationIds) ? serverState.session.completedRecommendationIds : [],
          blockedProductions: Array.isArray(serverState.session.blockedProductions) ? serverState.session.blockedProductions.map(normalizeBlockedProduction) : [],
          attempts: serverState.session.attempts && typeof serverState.session.attempts === "object" ? serverState.session.attempts : {},
        });
        setAutopilotPersistenceError(null);
      } catch (error) {
        if (!cancelled) setAutopilotPersistenceError(error instanceof Error ? error.message : "Unable to refresh backend Autopilot state.");
      }
    }

    let timer: number | null = null;
    const pollDelay = () => {
      if (document.hidden) return 300_000;
      switch (autopilot.status) {
        case "RUNNING": return 5_000;
        case "WAITING_FOR_FINAL_APPROVAL": return 10_000;
        case "NEEDS_ATTENTION": return 30_000;
        case "WAITING_FOR_LEARNING": return 60_000;
        case "PAUSED": return 300_000;
        case "COMPLETED": return 600_000;
        default: return 300_000;
      }
    };
    const schedule = () => {
      if (cancelled) return;
      timer = window.setTimeout(async () => {
        await syncBackendAutopilot();
        schedule();
      }, pollDelay());
    };
    const onVisibility = () => {
      if (!document.hidden) void syncBackendAutopilot();
      if (timer != null) window.clearTimeout(timer);
      schedule();
    };

    void syncBackendAutopilot().finally(schedule);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisibility);
      if (timer != null) window.clearTimeout(timer);
    };
  }, [autopilotHydrated, autopilot.executionOwner, autopilot.status, currentUser.uid]);

  // Follow only the one-video trial initiated in this browser. Never navigate
  // to an empty Production Brief, and never hijack a manually opened production.
  useEffect(() => {
    if (!pendingTrialBrief) return;
    if (autopilot.scope !== "PRODUCTION" || autopilot.currentRecommendationId !== pendingTrialBrief.recommendationId) {
      setPendingTrialBrief(null);
      return;
    }
    if (autopilot.status === "NEEDS_ATTENTION" || autopilot.status === "PAUSED" || autopilot.status === "COMPLETED") {
      setPendingTrialBrief(null);
      return;
    }
    const briefId = autopilot.currentProductionJobId;
    if (!briefId || workspaceView !== "channel") return;
    let cancelled = false;
    getProductionBriefJob(briefId).then((brief) => {
      if (cancelled || brief.recommendation_id !== pendingTrialBrief.recommendationId) return;
      setProductionBriefJob(brief);
      setSelectedRecommendationId(brief.recommendation_id);
      setActiveProductionId(brief.job_id);
      setWorkspaceRestoreError(null);
      setPendingTrialBrief(null);
      setWorkspaceView("production");
    }).catch(() => {
      // Brief may not be readable yet. Wait for a later supervisor poll;
      // do not classify eventual consistency as a missing saved production.
    });
    return () => { cancelled = true; };
  }, [pendingTrialBrief, autopilot.scope, autopilot.status, autopilot.currentRecommendationId, autopilot.currentProductionJobId, autopilot.updatedAt, workspaceView]);

  // The backend supervisor publishes the currently owned Production Brief id. Reconnect
  // that durable job into the existing UI; the existing resume effects then discover
  // Media Studio, assembly, audio, QC, package, and publishing checkpoints normally.
  useEffect(() => {
    if (autopilot.executionOwner !== "BACKEND") return;
    const productionId = autopilot.currentProductionJobId;
    // The supervisor can reconnect in the background, but never take over a
    // creator-selected workspace/channel or a manually opened production.
    if (workspaceView === "channel" || workspaceView === "production") return;
    if (!productionId || productionBriefJob?.job_id === productionId) return;
    let cancelled = false;

    setMediaStudioJob(null);
    setFinalAssemblyJob(null);
    setAudioFinishingJob(null);
    setAudioVersionHistory([]);
    setDeliveryQcReport(null);
    setDeliveryPackage(null);
    setDeliveryPackageHistory([]);
    setPublishingDraft(null);
    setPublishingDraftHistory([]);

    getProductionBriefJob(productionId)
      .then((job) => {
        if (cancelled) return;
        setProductionBriefJob(job);
        setSelectedRecommendationId(job.recommendation_id);
        // The selected production belongs exclusively to explicit navigation.
      })
      .catch((error) => {
        if (!cancelled) setProductionBriefError(error instanceof Error ? error.message : "Unable to reconnect the backend Autopilot production.");
      });

    return () => { cancelled = true; };
  }, [autopilot.executionOwner, autopilot.currentProductionJobId, productionBriefJob?.job_id, workspaceView]);

  // Persist every supervisor transition to the backend. Writes are serialized so rapid
  // stage changes cannot arrive out of order, and revision conflicts adopt the newer
  // server snapshot rather than overwriting another browser/tab.
  useEffect(() => {
    if (!autopilotHydrated) return;
    if (autopilot.updatedAt === autopilotLastPersistedUpdatedAtRef.current) return;
    if (autopilotPersistTimerRef.current != null) window.clearTimeout(autopilotPersistTimerRef.current);

    const snapshot: AutopilotSession = JSON.parse(JSON.stringify(autopilot));
    autopilotPersistTimerRef.current = window.setTimeout(() => {
      autopilotPersistChainRef.current = autopilotPersistChainRef.current.then(async () => {
        try {
          const saved = await saveServerAutopilotState<AutopilotSession>(snapshot, autopilotServerRevisionRef.current);
          autopilotServerRevisionRef.current = saved.revision;
          autopilotLastPersistedUpdatedAtRef.current = saved.session.updatedAt;
          setAutopilotPersistenceError(null);
          window.localStorage.removeItem(autopilotStorageKey);
        } catch (error) {
          if (error instanceof AutopilotStateConflictError && error.current) {
            const current = error.current as { revision: number; session: AutopilotSession };
            autopilotServerRevisionRef.current = current.revision;
            autopilotLastPersistedUpdatedAtRef.current = current.session.updatedAt;
            setAutopilot({ ...emptyAutopilotSession(), ...current.session });

            // A 409 is an expected optimistic-concurrency reconciliation, not a
            // persistence failure. The backend supervisor, another browser tab,
            // or another session may have advanced the authoritative checkpoint.
            // Adopt that checkpoint and do not trigger the 5-second error retry loop.
            setAutopilotPersistenceError(null);
            setAutopilotSyncNotice(
              "A newer Autopilot checkpoint was saved on the server. ReviveAI loaded the latest state automatically."
            );
            return;
          }
          setAutopilotPersistenceError(error instanceof Error ? error.message : "Unable to save Autopilot state to the server.");
        }
      }, async () => undefined);
    }, 120);

    return () => {
      if (autopilotPersistTimerRef.current != null) {
        window.clearTimeout(autopilotPersistTimerRef.current);
        autopilotPersistTimerRef.current = null;
      }
    };
  }, [autopilot, autopilotHydrated, autopilotStorageKey, autopilotPersistRetryTick]);

  useEffect(() => {
    if (!autopilotHydrated || !autopilotPersistenceError) return;
    const timer = window.setTimeout(() => setAutopilotPersistRetryTick((value) => value + 1), 5000);
    return () => window.clearTimeout(timer);
  }, [autopilotHydrated, autopilotPersistenceError, autopilotPersistRetryTick]);

  // Successful conflict reconciliation is informational only. Clear the notice
  // automatically; unlike a real persistence error it must never schedule a retry.
  useEffect(() => {
    if (!autopilotSyncNotice) return;
    const timer = window.setTimeout(() => setAutopilotSyncNotice(null), 5000);
    return () => window.clearTimeout(timer);
  }, [autopilotSyncNotice]);

  // v2.9 migration: older Autopilot sessions used one campaign-wide NEEDS_ATTENTION
  // state. Convert that single blocker into a per-production exception so other
  // revival ideas can continue automatically without clearing saved progress.
  useEffect(() => {
    if (!autopilotHydrated) return;
    if (autopilot.executionOwner === "BACKEND") return;
    if (!revivalProgram) return;
    if (autopilot.status !== "NEEDS_ATTENTION" || autopilot.attentionStage === "FINAL_VIDEO") return;
    if (!autopilot.currentRecommendationId) return;
    if (autopilot.blockedProductions.some((item) => item.recommendationId === autopilot.currentRecommendationId)) return;

    const now = new Date().toISOString();
    const blocked: AutopilotBlockedProduction = {
      recommendationId: autopilot.currentRecommendationId,
      title: autopilot.currentTitle || "Production",
      message: friendlyAutopilotExceptionMessage(autopilot.message),
      attentionStage: autopilot.attentionStage || "FAILURE",
      blockedAt: now,
      kind: isTransientAutopilotInfrastructureError(autopilot.message) ? "INFRASTRUCTURE" : "CONTENT",
      productionJobId: autopilot.currentProductionJobId,
      recoveryJobId: autopilot.recoveryJobId,
      analysisJobId: productionBriefJob?.analysis_job_id || null,
    };
    const blockedProductions = [...autopilot.blockedProductions, blocked];
    const blockedIds = new Set(blockedProductions.map((item) => item.recommendationId));
    const completedIds = new Set(autopilot.completedRecommendationIds);
    const hasAnotherIdea = orderedRevivalRecommendationIds(revivalProgram).some(
      (id) => !completedIds.has(id) && !blockedIds.has(id),
    );

    setAutopilot((current) => ({
      ...current,
      status: hasAnotherIdea ? "RUNNING" : "NEEDS_ATTENTION",
      currentRecommendationId: null,
      currentTitle: null,
      currentStartedAt: null,
      blockedProductions,
      attentionStage: hasAnotherIdea ? null : blocked.attentionStage,
      message: hasAnotherIdea
        ? `${blocked.title} was moved to Needs attention. ReviveAI is continuing the revival campaign with another idea.`
        : `${blocked.title} was moved to Needs attention. No other unblocked ideas remain.`,
      updatedAt: now,
    }));
  }, [
    revivalProgram?.program_id,
    autopilot.status,
    autopilot.attentionStage,
    autopilot.currentRecommendationId,
    autopilot.currentTitle,
    autopilot.message,
    autopilot.completedRecommendationIds.join("|"),
    autopilot.blockedProductions.map((item) => item.recommendationId).join("|"),
  ]);


  useEffect(() => {
    if (!workflowRestoreAttemptedRef.current) return;
    if (!job?.job_id) {
      window.localStorage.removeItem(workflowCheckpointKey);
      return;
    }

    const checkpoint: CreatorWorkflowCheckpoint = {
      version: 1,
      url: url.trim() || undefined,
      analysisJobId: job.job_id,
      dnaJobId: dnaJob?.job_id,
      recoveryJobId: recoveryJob?.job_id,
      productionBriefJobId: productionBriefJob?.job_id,
      mediaStudioJobId: mediaStudioJob?.job_id,
      finalAssemblyJobId: finalAssemblyJob?.job_id,
      audioFinishingJobId: audioFinishingJob?.job_id,
    };
    window.localStorage.setItem(workflowCheckpointKey, JSON.stringify(checkpoint));
  }, [
    job?.job_id,
    dnaJob?.job_id,
    recoveryJob?.job_id,
    productionBriefJob?.job_id,
    mediaStudioJob?.job_id,
    finalAssemblyJob?.job_id,
    audioFinishingJob?.job_id,
    url,
  ]);

  useEffect(() => {
    if (!job || TERMINAL.has(job.stage)) return;

    pollingRef.current = window.setInterval(async () => {
      try {
        const next = await getAnalysisJob(job.job_id);
        setJob(next);
        if (TERMINAL.has(next.stage) && pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
      } catch (error) {
        setRequestError(error instanceof Error ? error.message : "Could not refresh analysis status.");
      }
    }, 850);

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [job?.job_id, job?.stage]);

  useEffect(() => {
    if (!dnaJob || DNA_TERMINAL.has(dnaJob.stage)) return;

    dnaPollingRef.current = window.setInterval(async () => {
      try {
        const next = await getContentDnaJob(dnaJob.job_id);
        setDnaJob(next);
        if (DNA_TERMINAL.has(next.stage) && dnaPollingRef.current) {
          clearInterval(dnaPollingRef.current);
          dnaPollingRef.current = null;
        }
      } catch (error) {
        setDnaRequestError(error instanceof Error ? error.message : "Could not refresh Content DNA status.");
      }
    }, 1000);

    return () => {
      if (dnaPollingRef.current) {
        clearInterval(dnaPollingRef.current);
        dnaPollingRef.current = null;
      }
    };
  }, [dnaJob?.job_id, dnaJob?.stage]);

  useEffect(() => {
    if (!recoveryJob || RECOVERY_TERMINAL.has(recoveryJob.stage)) return;

    recoveryPollingRef.current = window.setInterval(async () => {
      try {
        const next = await getRecoveryJob(recoveryJob.job_id);
        if (!next) {
          setRecoveryJob(null);
          setRecoveryRequestError("Recovery Intelligence job was not found. ReviveAI will attempt to restore the saved workflow lineage.");
          if (recoveryPollingRef.current) {
            clearInterval(recoveryPollingRef.current);
            recoveryPollingRef.current = null;
          }
          return;
        }
        setRecoveryJob(next);
        if (RECOVERY_TERMINAL.has(next.stage) && recoveryPollingRef.current) {
          clearInterval(recoveryPollingRef.current);
          recoveryPollingRef.current = null;
        }
      } catch (error) {
        setRecoveryRequestError(error instanceof Error ? error.message : "Could not refresh Recovery Intelligence status.");
      }
    }, 900);

    return () => {
      if (recoveryPollingRef.current) {
        clearInterval(recoveryPollingRef.current);
        recoveryPollingRef.current = null;
      }
    };
  }, [recoveryJob?.job_id, recoveryJob?.stage]);



  useEffect(() => {
    if (
      !recoveryJob ||
      recoveryJob.stage !== "COMPLETED" ||
      !recoveryJob.result
    ) {
      setRevivalProgram(null);
      setRevivalProgramError(null);
      setRevivalProgramPending(false);
      return;
    }

    // Capture the narrowed recovery id before entering the async closure.
    // TypeScript does not preserve the recoveryJob null check across that boundary.
    const recoveryJobId = recoveryJob.job_id;
    let cancelled = false;

    async function restoreOrCreateRevivalProgram() {
      setRevivalProgramPending(true);
      setRevivalProgramError(null);

      try {
        // Normal path: restore the program already persisted for this recovery job.
        let program = await getRevivalProgram(recoveryJobId);

        // Backward compatibility: getRevivalProgram returns null only for HTTP 404.
        // Older productions can therefore self-heal by creating the missing program
        // from their completed Recovery Intelligence.
        if (!program) {
          program = await createRevivalProgram(recoveryJobId);
        }

        if (cancelled) return;

        setRevivalProgram(program);
        setRevivalProgramError(null);
      } catch (error) {
        if (cancelled) return;

        setRevivalProgram(null);
        setRevivalProgramError(
          error instanceof Error
            ? error.message
            : "Unable to restore the revival program.",
        );
      } finally {
        if (!cancelled) {
          setRevivalProgramPending(false);
        }
      }
    }

    void restoreOrCreateRevivalProgram();

    return () => {
      cancelled = true;
    };
  }, [recoveryJob?.job_id, recoveryJob?.stage]);

  useEffect(() => {
    if (!productionBriefJob || PRODUCTION_TERMINAL.has(productionBriefJob.stage)) return;

    productionPollingRef.current = window.setInterval(async () => {
      try {
        const next = await getProductionBriefJob(productionBriefJob.job_id);
        setProductionBriefJob(next);
        if (PRODUCTION_TERMINAL.has(next.stage) && productionPollingRef.current) {
          clearInterval(productionPollingRef.current);
          productionPollingRef.current = null;
        }
      } catch (error) {
        setProductionBriefError(error instanceof Error ? error.message : "Could not refresh Production Studio status.");
      }
    }, 900);

    return () => {
      if (productionPollingRef.current) {
        clearInterval(productionPollingRef.current);
        productionPollingRef.current = null;
      }
    };
  }, [productionBriefJob?.job_id, productionBriefJob?.stage]);

  useEffect(() => {
    if (!shouldPollMediaJob(mediaStudioJob)) return;
    mediaPollingRef.current = window.setInterval(async () => {
      try {
        const next = await getMediaStudioJob(mediaStudioJob!.job_id);
        setMediaStudioJob(next);
        if (!shouldPollMediaJob(next) && mediaPollingRef.current) {
          clearInterval(mediaPollingRef.current);
          mediaPollingRef.current = null;
        }
      } catch (error) {
        setMediaStudioError(error instanceof Error ? error.message : "Could not refresh Media Studio status.");
      }
    }, 900);
    return () => {
      if (mediaPollingRef.current) {
        clearInterval(mediaPollingRef.current);
        mediaPollingRef.current = null;
      }
    };
  }, [mediaStudioJob?.job_id, mediaStudioJob?.stage, JSON.stringify(mediaStudioJob?.result?.shot_operations ?? {}), JSON.stringify(mediaStudioJob?.result?.clip_operations ?? {})]);

  useEffect(() => {
    if (!finalAssemblyJob || !ASSEMBLY_POLLING_STAGES.has(finalAssemblyJob.stage)) return;
    assemblyPollingRef.current = window.setInterval(async () => {
      try {
        const next = await getFinalAssemblyJob(finalAssemblyJob.job_id);
        setFinalAssemblyJob(next);
        if (!ASSEMBLY_POLLING_STAGES.has(next.stage) && assemblyPollingRef.current) {
          clearInterval(assemblyPollingRef.current);
          assemblyPollingRef.current = null;
        }
      } catch (error) {
        setFinalAssemblyError(error instanceof Error ? error.message : "Could not refresh Final Assembly status.");
      }
    }, 900);
    return () => {
      if (assemblyPollingRef.current) {
        clearInterval(assemblyPollingRef.current);
        assemblyPollingRef.current = null;
      }
    };
  }, [finalAssemblyJob?.job_id, finalAssemblyJob?.stage]);

  useEffect(() => {
    if (!audioFinishingJob || !AUDIO_POLLING_STAGES.has(audioFinishingJob.stage)) return;
    audioPollingRef.current = window.setInterval(async () => {
      try {
        const next = await getAudioFinishingJob(audioFinishingJob.job_id);
        setAudioFinishingJob(next);
        setAudioVersionHistory((current) => [next, ...current.filter((item) => item.job_id !== next.job_id)]);
        if (!AUDIO_POLLING_STAGES.has(next.stage) && audioPollingRef.current) {
          clearInterval(audioPollingRef.current);
          audioPollingRef.current = null;
        }
      } catch (error) {
        setAudioFinishingError(error instanceof Error ? error.message : "Could not refresh Audio Finishing status.");
      }
    }, 900);
    return () => {
      if (audioPollingRef.current) {
        clearInterval(audioPollingRef.current);
        audioPollingRef.current = null;
      }
    };
  }, [audioFinishingJob?.job_id, audioFinishingJob?.stage]);

  useEffect(() => {
    const channelId = job?.stage === "COMPLETED"
      ? job.result?.channel.channel_id
      : productionBriefJob?.channel_id || activeChannelId;
    setProductionHistoryReady(false);
    if (!channelId) {
      setProductionHistory([]);
      return;
    }
    let cancelled = false;
    getProductionBriefHistory(channelId)
      .then((items) => { if (!cancelled) { setProductionHistory(items); setProductionHistoryReady(true); } })
      .catch(() => { if (!cancelled) { setProductionHistory([]); setProductionHistoryReady(false); } });
    return () => { cancelled = true; };
  }, [job?.stage, job?.result?.channel.channel_id, productionBriefJob?.channel_id, productionBriefJob?.stage, productionBriefJob?.result?.review_status, activeChannelId]);

  useEffect(() => {
    const productionId = productionBriefJob?.job_id;
    const approved = productionBriefJob?.stage === "COMPLETED" && productionBriefJob.result?.review_status === "APPROVED";
    if (!productionId || !approved) {
      setMediaResumePending(false);
      return;
    }
    if (mediaStudioJob?.production_brief_job_id === productionId) return;

    let cancelled = false;
    setMediaResumePending(true);
    setMediaStudioError(null);
    getLatestMediaStudioJob(productionId)
      .then((existing) => {
        if (cancelled) return;
        if (existing) {
          setMediaStudioJob(existing);
        } else if (mediaStudioJob?.production_brief_job_id !== productionId) {
          setMediaStudioJob(null);
        }
      })
      .catch((error) => {
        if (!cancelled) setMediaStudioError(error instanceof Error ? error.message : "Unable to check for a saved Media Studio job.");
      })
      .finally(() => { if (!cancelled) setMediaResumePending(false); });
    return () => { cancelled = true; };
  }, [productionBriefJob?.job_id, productionBriefJob?.stage, productionBriefJob?.result?.review_status]);

  useEffect(() => {
    const mediaId = mediaStudioJob?.job_id;
    const canHaveAssembly = mediaStudioJob?.stage === "READY_FOR_ASSEMBLY" && Boolean(mediaStudioJob.result?.assembly_ready);
    if (!mediaId || !canHaveAssembly) {
      setAssemblyResumePending(false);
    setAudioResumePending(false);
      return;
    }
    if (finalAssemblyJob?.media_job_id === mediaId) return;

    let cancelled = false;
    setAssemblyResumePending(true);
    setFinalAssemblyError(null);
    getLatestFinalAssemblyJob(mediaId)
      .then((existing) => {
        if (cancelled) return;
        if (existing) {
          setFinalAssemblyJob(existing);
        } else if (finalAssemblyJob?.media_job_id !== mediaId) {
          setFinalAssemblyJob(null);
        }
      })
      .catch((error) => {
        if (!cancelled) setFinalAssemblyError(error instanceof Error ? error.message : "Unable to check for a saved final assembly.");
      })
      .finally(() => { if (!cancelled) setAssemblyResumePending(false); });
    return () => { cancelled = true; };
  }, [mediaStudioJob?.job_id, mediaStudioJob?.stage, mediaStudioJob?.result?.assembly_ready]);

  useEffect(() => {
    const assemblyId = finalAssemblyJob?.job_id;
    const visualApproved = finalAssemblyJob?.stage === "DELIVERED" && finalAssemblyJob.result?.review_status === "APPROVED";
    if (!assemblyId || !visualApproved) {
      setAudioResumePending(false);
      return;
    }
    if (audioFinishingJob?.assembly_job_id === assemblyId && audioVersionHistory.length > 0) return;

    let cancelled = false;
    setAudioResumePending(true);
    setAudioFinishingError(null);
    getAudioFinishingJobs(assemblyId)
      .then((versions) => {
        if (cancelled) return;
        setAudioVersionHistory(versions);
        const existing = versions[0] ?? null;
        if (existing) {
          setAudioFinishingJob(existing);
        } else if (audioFinishingJob?.assembly_job_id !== assemblyId) {
          setAudioFinishingJob(null);
          setAudioVersionHistory([]);
        }
      })
      .catch((error) => {
        if (!cancelled) setAudioFinishingError(error instanceof Error ? error.message : "Unable to check for a saved audio master.");
      })
      .finally(() => { if (!cancelled) setAudioResumePending(false); });
    return () => { cancelled = true; };
  }, [finalAssemblyJob?.job_id, finalAssemblyJob?.stage, finalAssemblyJob?.result?.review_status, audioVersionHistory.length]);

  useEffect(() => {
    const approvedJobId = approvedAudioMaster?.job_id;
    if (!approvedJobId) {
      setDeliveryQcReport(null);
      setDeliveryQcError(null);
      setDeliveryQcResumePending(false);
      return;
    }
    if (deliveryQcReport?.audio_job_id === approvedJobId) return;

    let cancelled = false;
    setDeliveryQcResumePending(true);
    setDeliveryQcError(null);
    getDeliveryQcReport(approvedJobId)
      .then((saved) => { if (!cancelled) setDeliveryQcReport(saved); })
      .catch((error) => {
        if (!cancelled) setDeliveryQcError(error instanceof Error ? error.message : "Unable to check for a saved delivery QC report.");
      })
      .finally(() => { if (!cancelled) setDeliveryQcResumePending(false); });
    return () => { cancelled = true; };
  }, [approvedAudioMaster?.job_id, deliveryQcReport?.audio_job_id]);

  useEffect(() => {
    const approvedJobId = approvedAudioMaster?.job_id;
    const assemblyJobId = approvedAudioMaster?.assembly_job_id;
    const qcReportId = deliveryQcReport?.report_id;
    if (!approvedJobId || !assemblyJobId || !qcReportId || !(Boolean(deliveryQcReport && (deliveryQcReport.overall_status === "READY" || (deliveryQcReport.overall_status === "REVIEW" && deliveryQcReport.human_acknowledgment))) || (deliveryQcReport?.overall_status === "REVIEW" && deliveryQcReport.human_acknowledgment?.report_id === deliveryQcReport.report_id && deliveryQcReport.fail_count === 0))) {
      setDeliveryPackage(null);
      setDeliveryPackageHistory([]);
      setDeliveryPackageError(null);
      setDeliveryPackageResumePending(false);
      return;
    }

    let cancelled = false;
    setDeliveryPackage(null);
    setDeliveryPackageResumePending(true);
    setDeliveryPackageError(null);
    Promise.all([
      getLatestDeliveryPackage(approvedJobId),
      getDeliveryPackagesForAssembly(assemblyJobId),
    ])
      .then(([saved, history]) => {
        if (cancelled) return;
        setDeliveryPackage(saved?.qc_report_id === qcReportId ? saved : null);
        setDeliveryPackageHistory(history);
      })
      .catch((error) => {
        if (!cancelled) setDeliveryPackageError(error instanceof Error ? error.message : "Unable to check for saved delivery packages.");
      })
      .finally(() => { if (!cancelled) setDeliveryPackageResumePending(false); });
    return () => { cancelled = true; };
  }, [approvedAudioMaster?.job_id, approvedAudioMaster?.assembly_job_id, deliveryQcReport?.report_id, deliveryQcReport?.overall_status, deliveryQcReport?.human_acknowledgment?.report_id]);

  useEffect(() => {
    const approvedJobId = approvedAudioMaster?.job_id;
    if (!approvedJobId || !deliveryPackage) {
      setPublishingDraft(null);
      setPublishingDraftHistory([]);
      setPublishingError(null);
      setPublishingResumePending(false);
      return;
    }
    let cancelled = false;
    setPublishingResumePending(true);
    setPublishingError(null);
    getPublishingDrafts(approvedJobId)
      .then((items) => {
        if (cancelled) return;
        setPublishingDraftHistory(items);
        setPublishingDraft((current) => {
          if (current && items.some((item) => item.draft_id === current.draft_id)) return current;
          return items[0] ?? null;
        });
      })
      .catch((error) => {
        if (!cancelled) setPublishingError(error instanceof Error ? error.message : "Unable to load saved publishing drafts.");
      })
      .finally(() => { if (!cancelled) setPublishingResumePending(false); });
    return () => { cancelled = true; };
  }, [approvedAudioMaster?.job_id, deliveryPackage?.package_id]);

  async function openProductionHistory(jobId: string) {
    setProductionBriefError(null);
    try {
      const next = await getProductionBriefJob(jobId);
      setProductionBriefJob(next);
      if (mediaStudioJob?.production_brief_job_id !== next.job_id) {
        setMediaStudioJob(null);
        setMediaStudioError(null);
        setFinalAssemblyJob(null);
        setFinalAssemblyError(null);
        setAudioFinishingJob(null);
        setAudioVersionHistory([]);
        setAudioFinishingError(null);
        setDeliveryQcReport(null);
        setDeliveryQcError(null);
      }
      setSelectedRecommendationId(next.recommendation_id);
      setActiveProductionId(next.job_id);
      setWorkspaceView("production");
      window.setTimeout(() => {
        document.getElementById("production-studio")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 80);
    } catch (error) {
      setProductionBriefError(error instanceof Error ? error.message : "Unable to open the saved production brief.");
    }
  }

  async function analyze() {
    setRequestError(null);
    setDnaRequestError(null);
    setRecoveryRequestError(null);
    setProductionBriefError(null);
    setMediaStudioError(null);
    setMediaStudioJob(null);
    setFinalAssemblyJob(null);
    setFinalAssemblyError(null);
    setAudioFinishingJob(null);
    setAudioVersionHistory([]);
    setAudioFinishingError(null);
    setDeliveryQcReport(null);
    setDeliveryQcError(null);
    setProductionBriefJob(null);
    setSelectedRecommendationId(null);
    setRecoveryJob(null);
    setDnaJob(null);
    setJob(null);
    try {
      const next = await createAnalysisJob(url.trim());
      setJob(next);
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : "Unable to start analysis.");
    }
  }

  async function buildContentDna() {
    if (!job || job.stage !== "COMPLETED") return;
    setDnaRequestError(null);
    setRecoveryRequestError(null);
    setProductionBriefError(null);
    setMediaStudioError(null);
    setMediaStudioJob(null);
    setFinalAssemblyJob(null);
    setFinalAssemblyError(null);
    setAudioFinishingJob(null);
    setAudioVersionHistory([]);
    setAudioFinishingError(null);
    setDeliveryQcReport(null);
    setDeliveryQcError(null);
    setProductionBriefJob(null);
    setSelectedRecommendationId(null);
    setRecoveryJob(null);
    setDnaJob(null);
    try {
      const next = await createContentDnaJob(job.job_id);
      setDnaJob(next);
      window.setTimeout(() => {
        document.getElementById("content-dna")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 80);
    } catch (error) {
      setDnaRequestError(error instanceof Error ? error.message : "Unable to start Content DNA.");
    }
  }

  async function buildRecoveryIntelligence() {
    if (!dnaJob || dnaJob.stage !== "COMPLETED" || !dnaJob.result) return;
    setRecoveryRequestError(null);
    setProductionBriefError(null);
    setMediaStudioError(null);
    setMediaStudioJob(null);
    setFinalAssemblyJob(null);
    setFinalAssemblyError(null);
    setAudioFinishingJob(null);
    setAudioVersionHistory([]);
    setAudioFinishingError(null);
    setDeliveryQcReport(null);
    setDeliveryQcError(null);
    setProductionBriefJob(null);
    setSelectedRecommendationId(null);
    setRecoveryJob(null);
    setRevivalProgram(null);
    setRevivalProgramError(null);
    try {
      const next = await createRecoveryJob(dnaJob.job_id);
      setRecoveryJob(next);
      window.setTimeout(() => {
        document.getElementById("recovery-intelligence")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 80);
    } catch (error) {
      setRecoveryRequestError(error instanceof Error ? error.message : "Unable to start Recovery Intelligence.");
    }
  }


  function openRevivalPrerequisite(target: "dna" | "recovery") {
    setChannelTab("intelligence");
    window.setTimeout(() => {
      document.getElementById(target === "dna" ? "content-dna" : "recovery-intelligence")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 90);
  }

  async function buildRevivalProgram() {
    if (!recoveryJob || recoveryJob.stage !== "COMPLETED" || !recoveryJob.result) return;
    setRevivalProgramPending(true);
    setRevivalProgramError(null);
    try {
      const next = await createRevivalProgram(recoveryJob.job_id);
      setRevivalProgram(next);
      window.setTimeout(() => document.getElementById("revival-program")?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
    } catch (error) {
      setRevivalProgramError(error instanceof Error ? error.message : "Unable to create the revival program.");
    } finally {
      setRevivalProgramPending(false);
    }
  }

  async function loadSavedDirections() {
    if (!recoveryJob || recoveryJob.stage !== "COMPLETED" || !recoveryJob.result) return false;
    try {
      const saved = await getSavedTrendDirections(recoveryJob.job_id);
      if (!saved) return false;
      setTrendDirections(saved);
      return true;
    } catch (error) {
      // A cached snapshot is an optimization. Keep the workspace usable if reading it fails.
      console.warn("Unable to restore saved directions", error);
      return false;
    }
  }

  async function discoverCurrentDirections() {
    if (!recoveryJob || recoveryJob.stage !== "COMPLETED" || !recoveryJob.result) return;
    setTrendDirectionPending(true);
    setTrendDirectionError(null);
    try {
      const next = await discoverTrendDirections(recoveryJob.job_id);
      setTrendDirections(next);
    } catch (error) {
      setTrendDirectionError(error instanceof Error ? error.message : "Unable to discover current content opportunities.");
    } finally { setTrendDirectionPending(false); }
  }

  async function refineCreatorDirection(idea: string) {
    if (!recoveryJob || recoveryJob.stage !== "COMPLETED" || !recoveryJob.result) return;
    setCustomDirectionPending(true); setTrendDirectionError(null);
    try {
      const direction = await refineCustomTrendDirection(recoveryJob.job_id, idea);
      setTrendDirections((current) => ({ recovery_job_id: recoveryJob.job_id, generated_at: new Date().toISOString(), market_window_days: current?.market_window_days ?? 30, methodology_notice: current?.methodology_notice ?? "Custom direction enhanced using channel identity and fresh public YouTube signals. Opportunity score is not a probability of virality.", directions: [direction, ...(current?.directions ?? []).filter((item) => item.lane !== "CUSTOM")] }));
    } catch (error) { setTrendDirectionError(error instanceof Error ? error.message : "Unable to strengthen that direction."); }
    finally { setCustomDirectionPending(false); }
  }

  async function produceTrendDirection(direction: TrendDirection) {
    if (!recoveryJob || recoveryJob.stage !== "COMPLETED" || !recoveryJob.result) return;
    setProductionBriefError(null); setSelectedRecommendationId(`direction_${direction.direction_id}`); setProductionBriefJob(null);
    setMediaStudioJob(null); setMediaStudioError(null); setFinalAssemblyJob(null); setFinalAssemblyError(null); setAudioFinishingJob(null); setAudioVersionHistory([]); setAudioFinishingError(null); setDeliveryQcReport(null); setDeliveryQcError(null);
    try {
      const next = await createProductionBriefFromDirection(recoveryJob.job_id, direction, "STANDARD");
      setProductionBriefJob(next); setActiveProductionId(next.job_id); setWorkspaceView("production");
      window.setTimeout(() => document.getElementById("production-studio")?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    } catch (error) { setProductionBriefError(error instanceof Error ? error.message : "Unable to start production from this direction."); }
  }

  async function changeRevivalCadence(intensity: import("./types").RevivalCadenceIntensity) {
    if (!recoveryJob || !revivalProgram) return;
    setRevivalProgramPending(true);
    setRevivalProgramError(null);
    try {
      const next = await updateRevivalProgramCadence(recoveryJob.job_id, intensity);
      setRevivalProgram(next);
    } catch (error) {
      setRevivalProgramError(error instanceof Error ? error.message : "Unable to update the revival cadence.");
    } finally {
      setRevivalProgramPending(false);
    }
  }

  async function buildProductionBrief(item: NextContentRecommendation, fidelityMode: ProductionFidelityMode = "STANDARD") {
    if (!recoveryJob || recoveryJob.stage !== "COMPLETED" || !recoveryJob.result) return;
    setProductionBriefError(null);
    setSelectedRecommendationId(item.recommendation_id);
    setProductionBriefJob(null);
    setMediaStudioJob(null);
    setMediaStudioError(null);
    setFinalAssemblyJob(null);
    setFinalAssemblyError(null);
    setAudioFinishingJob(null);
    setAudioVersionHistory([]);
    setAudioFinishingError(null);
    setDeliveryQcReport(null);
    setDeliveryQcError(null);
    try {
      const next = await createProductionBriefJob(recoveryJob.job_id, item.recommendation_id, fidelityMode);
      setProductionBriefJob(next);
      setActiveProductionId(next.job_id);
      setWorkspaceView("production");
      window.setTimeout(() => {
        document.getElementById("production-studio")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 80);
    } catch (error) {
      setProductionBriefError(error instanceof Error ? error.message : "Unable to start the production brief.");
    }
  }

  async function retryProductionBrief() {
    if (!productionBriefJob) return;
    setProductionBriefError(null);
    try {
      const next = await retryProductionBriefJob(productionBriefJob.job_id, productionBriefJob.fidelity_mode);
      setProductionBriefJob(next);
      setSelectedRecommendationId(next.recommendation_id);
    } catch (error) {
      setProductionBriefError(error instanceof Error ? error.message : "Unable to retry the production brief from its saved source snapshot.");
    }
  }

  async function keepOriginalDirection() {
    if (!productionBriefJob) return;
    setProductionBriefError(null);
    try {
      const next = await retryProductionBriefJob(productionBriefJob.job_id, "STRICT");
      setProductionBriefJob(next);
      setSelectedRecommendationId(next.recommendation_id);
    } catch (error) {
      setProductionBriefError(error instanceof Error ? error.message : "Unable to regenerate from the immutable original direction.");
    }
  }

  async function acceptCreativeAdaptation() {
    if (!productionBriefJob || productionBriefJob.stage !== "COMPLETED") return;
    setProductionBriefError(null);
    try {
      const next = await acceptProductionBriefAdaptation(productionBriefJob.job_id);
      setProductionBriefJob(next);
    } catch (error) {
      setProductionBriefError(error instanceof Error ? error.message : "Unable to accept the creative adaptation.");
    }
  }

  async function approveCurrentProductionBrief() {
    if (!productionBriefJob || productionBriefJob.stage !== "COMPLETED") return;
    setProductionBriefError(null);
    try {
      const next = await approveProductionBrief(productionBriefJob.job_id);
      setProductionBriefJob(next);
    } catch (error) {
      setProductionBriefError(error instanceof Error ? error.message : "Unable to approve the production brief.");
    }
  }

  async function startMediaStudio() {
    if (!productionBriefJob || productionBriefJob.stage !== "COMPLETED" || productionBriefJob.result?.review_status !== "APPROVED") return;
    setMediaStudioError(null);
    setMediaStudioJob(null);
    setFinalAssemblyJob(null);
    setFinalAssemblyError(null);
    setAudioFinishingJob(null);
    setAudioVersionHistory([]);
    setAudioFinishingError(null);
    setDeliveryQcReport(null);
    setDeliveryQcError(null);
    try {
      const next = await createMediaStudioJob(productionBriefJob.job_id);
      setMediaStudioJob(next);
      window.setTimeout(() => document.getElementById("media-studio")?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    } catch (error) {
      setMediaStudioError(error instanceof Error ? error.message : "Unable to start visual reference generation.");
    }
  }

  async function approveReference() {
    if (!mediaStudioJob) return;
    setMediaStudioError(null);
    try { setMediaStudioJob(await approveMediaReference(mediaStudioJob.job_id)); }
    catch (error) { setMediaStudioError(error instanceof Error ? error.message : "Unable to approve the character reference."); }
  }

  async function regenerateReference() {
    if (!mediaStudioJob) return;
    setMediaStudioError(null);
    try { setMediaStudioJob(await regenerateMediaReference(mediaStudioJob.job_id)); }
    catch (error) { setMediaStudioError(error instanceof Error ? error.message : "Unable to regenerate the character reference."); }
  }

  async function approveKeyframe(shotNumber: number) {
    if (!mediaStudioJob) return;
    setMediaStudioError(null);
    try { setMediaStudioJob(await approveMediaKeyframe(mediaStudioJob.job_id, shotNumber)); }
    catch (error) { setMediaStudioError(error instanceof Error ? error.message : `Unable to approve shot ${shotNumber}.`); }
  }

  async function regenerateKeyframe(shotNumber: number) {
    if (!mediaStudioJob) return;
    setMediaStudioError(null);
    try { setMediaStudioJob(await regenerateMediaKeyframe(mediaStudioJob.job_id, shotNumber)); }
    catch (error) { setMediaStudioError(error instanceof Error ? error.message : `Unable to regenerate shot ${shotNumber}.`); }
  }

  async function reviewAllKeyframes() {
    if (!mediaStudioJob) return;
    setMediaStudioError(null);
    try { setMediaStudioJob(await reviewMediaKeyframes(mediaStudioJob.job_id)); }
    catch (error) { setMediaStudioError(error instanceof Error ? error.message : "Unable to run storyboard fidelity review."); }
  }

  async function reviewKeyframe(shotNumber: number) {
    if (!mediaStudioJob) return;
    setMediaStudioError(null);
    try { setMediaStudioJob(await reviewMediaKeyframe(mediaStudioJob.job_id, shotNumber)); }
    catch (error) { setMediaStudioError(error instanceof Error ? error.message : `Unable to review shot ${shotNumber}.`); }
  }

  async function acceptKeyframeAdaptation(shotNumber: number) {
    if (!mediaStudioJob) return;
    setMediaStudioError(null);
    try { setMediaStudioJob(await acceptMediaKeyframeAdaptation(mediaStudioJob.job_id, shotNumber)); }
    catch (error) { setMediaStudioError(error instanceof Error ? error.message : `Unable to accept the shot ${shotNumber} adaptation.`); }
  }


  async function startAnimation() {
    if (!mediaStudioJob) return;
    setMediaStudioError(null);
    try { setMediaStudioJob(await startMediaAnimation(mediaStudioJob.job_id)); }
    catch (error) { setMediaStudioError(error instanceof Error ? error.message : "Unable to start Veo shot animation."); }
  }

  async function approveClip(shotNumber: number) {
    if (!mediaStudioJob) return;
    setMediaStudioError(null);
    try { setMediaStudioJob(await approveMediaClip(mediaStudioJob.job_id, shotNumber)); }
    catch (error) { setMediaStudioError(error instanceof Error ? error.message : `Unable to approve animated shot ${shotNumber}.`); }
  }

  async function regenerateClip(shotNumber: number) {
    if (!mediaStudioJob) return;
    setMediaStudioError(null);
    setFinalAssemblyJob(null);
    setFinalAssemblyError(null);
    setAudioFinishingJob(null);
    setAudioVersionHistory([]);
    setAudioFinishingError(null);
    setDeliveryQcReport(null);
    setDeliveryQcError(null);
    try { setMediaStudioJob(await regenerateMediaClip(mediaStudioJob.job_id, shotNumber)); }
    catch (error) { setMediaStudioError(error instanceof Error ? error.message : `Unable to regenerate animated shot ${shotNumber}.`); }
  }

  async function startFinalAssembly() {
    if (!mediaStudioJob || mediaStudioJob.stage !== "READY_FOR_ASSEMBLY" || !mediaStudioJob.result?.assembly_ready) return;
    setFinalAssemblyError(null);
    try {
      const next = await createFinalAssemblyJob(mediaStudioJob.job_id);
      setFinalAssemblyJob(next);
      window.setTimeout(() => document.getElementById("final-assembly")?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    } catch (error) {
      setFinalAssemblyError(error instanceof Error ? error.message : "Unable to start final Short assembly.");
    }
  }

  async function approveCurrentFinalAssembly() {
    if (!finalAssemblyJob) return;
    setFinalAssemblyError(null);
    try { setFinalAssemblyJob(await approveFinalAssembly(finalAssemblyJob.job_id)); }
    catch (error) { setFinalAssemblyError(error instanceof Error ? error.message : "Unable to approve the visual master."); }
  }

  async function startAudioFinishing(options: AudioMixOptions) {
    if (!finalAssemblyJob || finalAssemblyJob.stage !== "DELIVERED" || finalAssemblyJob.result?.review_status !== "APPROVED") return;
    setAudioFinishingError(null);
    try {
      const next = await createAudioFinishingJob(finalAssemblyJob.job_id, options);
      setAudioFinishingJob(next);
      setAudioVersionHistory((current) => [next, ...current.filter((item) => item.job_id !== next.job_id)]);
      window.setTimeout(() => document.getElementById("audio-finishing")?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    } catch (error) {
      setAudioFinishingError(error instanceof Error ? error.message : "Unable to start audio finishing.");
    }
  }

  async function approveCurrentAudioFinishing() {
    if (!audioFinishingJob) return;
    setAudioFinishingError(null);
    try {
      const next = await approveAudioFinishingJob(audioFinishingJob.job_id);
      setAudioFinishingJob(next);
      setAudioVersionHistory((current) => [next, ...current.filter((item) => item.job_id !== next.job_id)]);
      setDeliveryQcReport((current) => current?.audio_job_id === next.job_id ? current : null);
      setDeliveryQcError(null);
    }
    catch (error) { setAudioFinishingError(error instanceof Error ? error.message : "Unable to approve the delivery master."); }
  }

  async function runFinalDeliveryQc() {
    if (!approvedAudioMaster) return;
    setDeliveryQcPending(true);
    setDeliveryQcError(null);
    try {
      const report = await runDeliveryQc(approvedAudioMaster.job_id);
      setDeliveryQcReport(report);
      setDeliveryPackage(null);
      setDeliveryPackageError(null);
      window.setTimeout(() => document.getElementById("final-delivery-qc")?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    } catch (error) {
      setDeliveryQcError(error instanceof Error ? error.message : "Unable to run final delivery quality control.");
    } finally {
      setDeliveryQcPending(false);
    }
  }

  async function acknowledgeQcWarning(reportId: string) {
    if (!approvedAudioMaster || deliveryQcReport?.report_id !== reportId) return;
    setDeliveryQcPending(true);
    setDeliveryQcError(null);
    try {
      const updated = await acknowledgeDeliveryQc(approvedAudioMaster.job_id, reportId);
      setDeliveryQcReport(updated);
    } catch (error) {
      setDeliveryQcError(error instanceof Error ? error.message : "Unable to save QC acknowledgment.");
    } finally {
      setDeliveryQcPending(false);
    }
  }

  async function buildDeliveryPackage() {
    if (!approvedAudioMaster || !deliveryQcReport) return;
    const qcEligible =
      deliveryQcReport.overall_status === "READY" ||
      (deliveryQcReport.overall_status === "REVIEW" &&
        deliveryQcReport.human_acknowledgment?.report_id === deliveryQcReport.report_id &&
        deliveryQcReport.fail_count === 0);
    if (!qcEligible) return;
    if (deliveryPackage?.qc_report_id === deliveryQcReport.report_id) {
      document.getElementById("delivery-package")?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    setDeliveryPackagePending(true);
    setDeliveryPackageError(null);
    try {
      const next = await createDeliveryPackage(approvedAudioMaster.job_id);
      setDeliveryPackage(next);
      setDeliveryPackageHistory((current) => [next, ...current.filter((item) => item.package_id !== next.package_id)].sort((a, b) => b.package_version - a.package_version));
      window.setTimeout(() => document.getElementById("delivery-package")?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    } catch (error) {
      setDeliveryPackageError(error instanceof Error ? error.message : "Unable to create the delivery package.");
    } finally {
      setDeliveryPackagePending(false);
    }
  }

  function rememberPublishingDraft(next: PublishingDraft) {
    setPublishingDraft(next);
    setPublishingDraftHistory((current) => [next, ...current.filter((item) => item.draft_id !== next.draft_id)].sort((a, b) => b.version_number - a.version_number));
  }

  async function generatePublishingCopy() {
    if (!approvedAudioMaster || !deliveryPackage) return;
    setPublishingAction("GENERATE");
    setPublishingError(null);
    try {
      const next = await createPublishingDraft(approvedAudioMaster.job_id);
      rememberPublishingDraft(next);
      window.setTimeout(() => document.getElementById("publishing-assistant")?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    } catch (error) {
      setPublishingError(error instanceof Error ? error.message : "Unable to prepare publishing copy.");
    } finally {
      setPublishingAction(null);
    }
  }

  async function savePublishingCopy(content: PublishingDraftContent) {
    if (!publishingDraft) return;
    setPublishingAction("SAVE");
    setPublishingError(null);
    try {
      const next = await updatePublishingDraft(publishingDraft.draft_id, content);
      rememberPublishingDraft(next);
    } catch (error) {
      setPublishingError(error instanceof Error ? error.message : "Unable to save publishing edits.");
    } finally {
      setPublishingAction(null);
    }
  }

  async function regeneratePublishingCopy(fields: string[]) {
    if (!publishingDraft) return;
    setPublishingAction("REGENERATE");
    setPublishingError(null);
    try {
      const next = await regeneratePublishingDraft(publishingDraft.draft_id, fields);
      rememberPublishingDraft(next);
    } catch (error) {
      setPublishingError(error instanceof Error ? error.message : "Unable to regenerate the selected publishing fields.");
    } finally {
      setPublishingAction(null);
    }
  }

  async function approveCurrentPublishingCopy() {
    if (!publishingDraft) return;
    setPublishingAction("APPROVE");
    setPublishingError(null);
    try {
      const next = await approvePublishingDraft(publishingDraft.draft_id);
      rememberPublishingDraft(next);
    } catch (error) {
      setPublishingError(error instanceof Error ? error.message : "Unable to approve the publishing copy.");
    } finally {
      setPublishingAction(null);
    }
  }

  async function forkApprovedPublishingCopy() {
    if (!publishingDraft || publishingDraft.status !== "APPROVED") return;
    setPublishingAction("FORK");
    setPublishingError(null);
    try {
      // The update endpoint is version-safe: it creates a new DRAFT based on the
      // approved version instead of mutating the approved record. Sending the
      // exact approved content gives the creator an explicit editable fork.
      const next = await updatePublishingDraft(publishingDraft.draft_id, publishingDraft.content);
      rememberPublishingDraft(next);
      window.setTimeout(() => document.getElementById("publishing-assistant")?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    } catch (error) {
      setPublishingError(error instanceof Error ? error.message : "Unable to create an editable publishing version.");
    } finally {
      setPublishingAction(null);
    }
  }

  async function addPublishingCopyToPackage() {
    if (!publishingDraft || publishingDraft.status !== "APPROVED") return;
    setPublishingAction("PACKAGE");
    setPublishingError(null);
    try {
      const next = await addPublishingDraftToDeliveryPackage(publishingDraft.draft_id);

      // Update immediately so the creator sees the new package version without a
      // refresh, then reconcile against the persisted package store.
      setDeliveryPackage(next);
      setDeliveryPackageHistory((current) => [next, ...current.filter((item) => item.package_id !== next.package_id)].sort((a, b) => b.package_version - a.package_version));

      try {
        const [latest, history] = await Promise.all([
          getLatestDeliveryPackage(next.audio_job_id),
          getDeliveryPackagesForAssembly(next.assembly_job_id),
        ]);
        setDeliveryPackage(latest ?? next);
        setDeliveryPackageHistory(history.length > 0 ? history : [next]);
      } catch {
        // Package creation already succeeded. Keep the optimistic state if the
        // follow-up history refresh is temporarily unavailable.
      }
    } catch (error) {
      setPublishingError(error instanceof Error ? error.message : "Unable to add the approved publishing copy to the delivery package.");
    } finally {
      setPublishingAction(null);
    }
  }



  async function approveFinalVideoAsHuman(overrideReason?: string) {
    if (!approvedAudioMaster) return;
    setFinalHumanApprovalPending(true);
    setFinalHumanApprovalError(null);
    try {
      const next = await humanApproveFinalVideo(approvedAudioMaster.job_id, overrideReason);
      setFinalHumanOverrideReason(null);
      setAudioFinishingJob(next);
      setAudioVersionHistory((current) => [next, ...current.filter((item) => item.job_id !== next.job_id)]
        .sort((a, b) => b.version_number - a.version_number || b.updated_at.localeCompare(a.updated_at)));
      // Final approval is a terminal production checkpoint. Any watchdog/recovery
      // message belongs to the previous running operation and must not leak into
      // the completed screen.
      setAutopilotWatchdog({
        status: "IDLE",
        message: "",
        lastRunAt: null,
      });
      if (["NEEDS_ATTENTION", "WAITING_FOR_FINAL_APPROVAL"].includes(autopilot.status) && autopilot.attentionStage === "FINAL_VIDEO") {
        updateAutopilot({
          status: "RUNNING",
          attentionStage: null,
          message: autopilot.scope === "PRODUCTION"
            ? "Final human approval recorded. This production is complete."
            : "Final human approval recorded. Autopilot is closing this production and moving to the next planned idea.",
        });
      }
    } catch (error) {
      const description = error instanceof Error ? error.message : "Unable to record final video approval.";
      setFinalHumanApprovalError(description);
      if (!overrideReason && /AI motion review|AI review|AI-salvaged|fidelity gate/i.test(description)) setFinalHumanOverrideReason(description);
    } finally {
      setFinalHumanApprovalPending(false);
    }
  }

  function clearLoadedWorkflow() {
    setJob(null);
    setDnaJob(null);
    setRecoveryJob(null);
    setProductionBriefJob(null);
    setSelectedRecommendationId(null);
    setProductionHistory([]);
    setMediaStudioJob(null);
    setMediaStudioError(null);
    setFinalAssemblyJob(null);
    setFinalAssemblyError(null);
    setAudioFinishingJob(null);
    setAudioVersionHistory([]);
    setAudioFinishingError(null);
    setDeliveryQcReport(null);
    setDeliveryQcError(null);
    setDeliveryQcPending(false);
    setDeliveryQcResumePending(false);
    setDeliveryPackage(null);
    setDeliveryPackageError(null);
    setDeliveryPackagePending(false);
    setDeliveryPackageResumePending(false);
    setDeliveryPackageHistory([]);
    setPublishingDraft(null);
    setPublishingDraftHistory([]);
    setPublishingError(null);
    setPublishingResumePending(false);
    setPublishingAction(null);
    setMediaResumePending(false);
    setAssemblyResumePending(false);
    setAudioResumePending(false);
    setRequestError(null);
    setDnaRequestError(null);
    setRecoveryRequestError(null);
    setProductionBriefError(null);
    setWorkspaceRestoreError(null);
  }

  async function restoreWorkspaceCheckpoint(
    checkpoint: CreatorWorkflowCheckpoint,
    includeProduction: boolean,
    channelId?: string,
  ) {
    clearLoadedWorkflow();
    setWorkflowRestorePending(true);
    setWorkspaceRestoreError(null);

    let productionAvailable = !includeProduction;
    let analysisAvailable = false;
    let restoredAnalysis: AnalysisJob | null = null;

    try {
      // A production is its own persisted workspace. Restore it first so a stale
      // channel-analysis id can never turn a valid saved production into a blank page.
      if (includeProduction && checkpoint.productionBriefJobId) {
        try {
          const item = await getProductionBriefJob(checkpoint.productionBriefJobId);
          setProductionBriefJob(item);
          setSelectedRecommendationId(item.recommendation_id);
          productionAvailable = true;
        } catch (error) {
          setWorkspaceRestoreError(error instanceof Error ? error.message : "This saved production could not be restored.");
        }
      }

      // Fast path: use the browser's remembered analysis id.
      try {
        restoredAnalysis = await getAnalysisJob(checkpoint.analysisJobId);
      } catch {
        // Cross-device/self-healing path: the browser cache may be absent or may
        // point at a legacy job id. Resolve the newest durable completed analysis
        // for the same channel from the tenant-scoped Firestore index instead of
        // forcing a fresh YouTube analysis.
        if (channelId) {
          restoredAnalysis = await getLatestAnalysisJobForChannel(channelId);
        }
      }

      if (restoredAnalysis) {
        setJob(restoredAnalysis);
        analysisAvailable = true;
        if (checkpoint.url || restoredAnalysis.url) setUrl(checkpoint.url || restoredAnalysis.url);

        if (channelId && restoredAnalysis.job_id !== checkpoint.analysisJobId) {
          setWorkspace((current) => ({
            ...current,
            channels: current.channels.map((item) =>
              item.channelId === channelId
                ? { ...item, analysisJobId: restoredAnalysis!.job_id, updatedAt: restoredAnalysis!.updated_at }
                : item,
            ),
          }));
        }
      } else if (!includeProduction) {
        setWorkspaceRestoreError(
          "No saved channel intelligence could be restored. Refresh only if you want ReviveAI to analyze YouTube again.",
        );
      }

      const restoredAnalysisId = restoredAnalysis?.job_id;

      // Restore Content DNA and Recovery Intelligence from their remembered ids when
      // possible. If those ids are browser-local/stale, discover the latest durable
      // lineage for the restored analysis automatically.
      const restoreDna = async () => {
        let item: ContentDnaJob | null = null;
        if (checkpoint.dnaJobId) {
          try { item = await getContentDnaJob(checkpoint.dnaJobId); } catch { /* fall through */ }
        }
        if (!item && restoredAnalysisId) {
          try { item = await getLatestContentDnaJobForAnalysis(restoredAnalysisId); } catch { /* optional lineage */ }
        }
        if (item) setDnaJob(item);
        return item;
      };

      const restoreRecovery = async () => {
        let item: RecoveryJob | null = null;
        if (checkpoint.recoveryJobId) {
          try { item = await getRecoveryJob(checkpoint.recoveryJobId); } catch { /* fall through */ }
        }
        if (!item && restoredAnalysisId) {
          try { item = await getLatestRecoveryJobForAnalysis(restoredAnalysisId); } catch { /* optional lineage */ }
        }
        if (item) setRecoveryJob(item);
        return item;
      };

      const [restoredDna, restoredRecovery] = await Promise.all([restoreDna(), restoreRecovery()]);

      if (channelId && (restoredDna || restoredRecovery)) {
        setWorkspace((current) => ({
          ...current,
          channels: current.channels.map((item) =>
            item.channelId === channelId
              ? {
                  ...item,
                  dnaJobId: restoredDna?.job_id || item.dnaJobId,
                  recoveryJobId: restoredRecovery?.job_id || item.recoveryJobId,
                }
              : item,
          ),
        }));
      }

      const tasks: Array<Promise<void>> = [];
      // Older browser checkpoints may refer to downstream artifacts belonging
      // to another production. Discover the correct lineage from the brief via
      // the resume effects rather than injecting unverified cached job IDs.
      // This also keeps an opened Monet-Pup independent of recovered Sherlock Bones.

      await Promise.all(tasks);

      if (includeProduction && !productionAvailable) {
        setWorkspaceRestoreError((current) => current || "This production record is no longer available. Return to Productions and choose another saved item.");
      }
    } finally {
      setWorkflowRestorePending(false);
    }

    return { productionAvailable, analysisAvailable };
  }

  async function openDirectionStudioForChannel(channel: WorkspaceChannel) {
    setDirectionStudioRequested(true);
    setTrendDirectionError(null);
    setTrendDirections(null);
    await openWorkspaceChannel(channel);
  }

  async function openWorkspaceChannel(channel: WorkspaceChannel) {
    setActiveChannelId(channel.channelId);
    setActiveProductionId(null);
    setChannelTab("overview");
    setWorkspaceView("channel");
    const checkpoint: CreatorWorkflowCheckpoint = {
      version: 1,
      url: channel.channelUrl,
      analysisJobId: channel.analysisJobId,
      dnaJobId: channel.dnaJobId,
      recoveryJobId: channel.recoveryJobId,
    };
    setWorkspace((current) => ({
      ...current,
      lastActiveChannelId: channel.channelId,
      channels: current.channels.map((item) => item.channelId === channel.channelId ? { ...item, lastOpenedAt: new Date().toISOString() } : item),
    }));
    await restoreWorkspaceCheckpoint(checkpoint, false, channel.channelId);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  useEffect(() => {
    // Do not reference activeWorkspaceChannel here: that derived value is declared
    // later in CreatorApp and would be inside JavaScript's temporal dead zone
    // while hooks for this render are being registered. activeChannelId is already
    // available and is the stable identity we actually need for this transition.
    if (!directionStudioRequested || workflowRestorePending || workspaceView !== "channel" || !activeChannelId) return;
    const requestedChannel = workspace.channels.find((item) => item.channelId === activeChannelId);
    if (!requestedChannel) return;
    if (!recoveryJob || recoveryJob.stage !== "COMPLETED" || !recoveryJob.result) return;

    setChannelTab("directions");
    const timer = window.setTimeout(() => {
      document.getElementById("direction-studio")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 120);

    if (!trendDirections && !trendDirectionPending) {
      void (async () => {
        const restored = await loadSavedDirections();
        if (!restored) await discoverCurrentDirections();
      })();
    }
    setDirectionStudioRequested(false);
    return () => window.clearTimeout(timer);
  }, [directionStudioRequested, workflowRestorePending, workspaceView, activeChannelId, recoveryJob?.job_id, recoveryJob?.stage]);

  async function recoverWorkspaceProduction(channel: WorkspaceChannel, production: WorkspaceProduction) {
    try {
      const history = await getProductionBriefHistory(channel.channelId);
      setProductionHistory(history);
      const wanted = normalizeProductionTitle(production.title);
      const candidates = history
        .filter((entry) => {
          const titles = [entry.working_title, entry.source_snapshot.recommendation.title];
          return titles.some((title) => normalizeProductionTitle(title) === wanted);
        })
        .sort((a, b) => {
          const approvalDelta = Number(b.review_status === "APPROVED") - Number(a.review_status === "APPROVED");
          if (approvalDelta) return approvalDelta;
          return b.updated_at.localeCompare(a.updated_at);
        });

      for (const candidate of candidates) {
        try {
          const recovered = await getProductionBriefJob(candidate.job_id);
          const recoveredTitle = recovered.result?.creative_direction.working_title
            || recovered.source_snapshot.recommendation.title
            || production.title;
          const recoveredCheckpoint: CreatorWorkflowCheckpoint = {
            version: 1,
            url: channel.channelUrl,
            analysisJobId: recovered.analysis_job_id || channel.analysisJobId,
            dnaJobId: recovered.content_dna_job_id || channel.dnaJobId,
            recoveryJobId: recovered.recovery_job_id || channel.recoveryJobId,
            productionBriefJobId: recovered.job_id,
          };
          const repairedProduction: WorkspaceProduction = {
            ...production,
            id: recovered.job_id,
            title: recoveredTitle,
            stage: "BRIEF",
            stageLabel: recovered.result?.review_status === "APPROVED" ? "Production brief approved" : "Production brief review",
            status: recovered.result?.review_status === "APPROVED" ? "ACTIVE" : "REVIEW",
            milestone: "M2A",
            updatedAt: recovered.updated_at,
            checkpoint: recoveredCheckpoint,
          };

          setWorkspace((current) => ({
            ...current,
            lastActiveChannelId: channel.channelId,
            lastActiveProductionId: recovered.job_id,
            channels: current.channels.map((item) => item.channelId !== channel.channelId ? item : {
              ...item,
              productions: [
                repairedProduction,
                ...item.productions.filter((saved) => saved.id !== production.id && saved.id !== recovered.job_id),
              ],
            }),
          }));
          setActiveProductionId(recovered.job_id);
          setWorkspaceRestoreError(null);
          return { production: repairedProduction, job: recovered };
        } catch {
          // Try the next same-title persisted production. Tenant scoping is enforced server-side.
        }
      }
    } catch {
      // Keep the original restore error below.
    }
    return null;
  }

  async function inspectLegacyWorkspaceRecovery() {
    try {
      const status = await getLegacyAdoptionStatus();
      setLegacyAdoptionStatus(status);
      setLegacyAdoptionError(null);
      return status;
    } catch (error) {
      setLegacyAdoptionStatus(null);
      setLegacyAdoptionError(error instanceof Error ? error.message : "Unable to inspect legacy workspace data.");
      return null;
    }
  }

  async function adoptLegacyWorkspaceAndRetry(channel: WorkspaceChannel, production: WorkspaceProduction) {
    setLegacyAdoptionPending(true);
    setLegacyAdoptionError(null);
    try {
      await adoptLegacyWorkspace();
      setLegacyAdoptionStatus(null);
      setWorkspaceRestoreError(null);
      clearLoadedWorkflow();
      const restored = await restoreWorkspaceCheckpoint(production.checkpoint, true, channel.channelId);
      if (!restored.productionAvailable) {
        const recovered = await recoverWorkspaceProduction(channel, production);
        if (recovered) {
          clearLoadedWorkflow();
          setWorkflowRestorePending(true);
          setProductionBriefJob(recovered.job);
          setSelectedRecommendationId(recovered.job.recommendation_id);
          setWorkspaceRestoreError(null);
          setWorkflowRestorePending(false);
          return;
        }
        throw new Error("Legacy data was copied, but this production still could not be resolved. Return to Productions and reopen it once.");
      }
      setWorkspaceRestoreError(null);
    } catch (error) {
      setLegacyAdoptionError(error instanceof Error ? error.message : "Legacy workspace recovery failed.");
    } finally {
      setLegacyAdoptionPending(false);
    }
  }

  async function openWorkspaceProduction(channel: WorkspaceChannel, production: WorkspaceProduction) {
    // Keep the original entry point on retries from the detail screen.
    if (workspaceView !== "production") {
      setProductionReturnLocation(workspaceView === "workspace" ? "workspace" : channelTab);
    }
    setActiveChannelId(channel.channelId);
    setActiveProductionId(production.id);
    setWorkspaceView("production");
    setWorkspaceRestoreError(null);
    setWorkspace((current) => ({
      ...current,
      lastActiveChannelId: channel.channelId,
      lastActiveProductionId: production.id,
      channels: current.channels.map((item) => item.channelId === channel.channelId ? { ...item, lastOpenedAt: new Date().toISOString() } : item),
    }));
    const restored = await restoreWorkspaceCheckpoint(production.checkpoint, true, channel.channelId);
    if (!restored.productionAvailable) {
      const recovered = await recoverWorkspaceProduction(channel, production);
      if (recovered) {
        clearLoadedWorkflow();
        setWorkflowRestorePending(true);
        setProductionBriefJob(recovered.job);
        setSelectedRecommendationId(recovered.job.recommendation_id);
        setWorkspaceRestoreError(null);
        setWorkflowRestorePending(false);
      } else {
        const legacyStatus = await inspectLegacyWorkspaceRecovery();
        if (legacyStatus?.eligible && legacyStatus.legacy_items > 0) {
          setWorkspaceRestoreError(
            "This production was created before secure tenant isolation. ReviveAI found legacy workspace data on this server that can be recovered into your authenticated workspace."
          );
        } else {
          setWorkspaceRestoreError(
            legacyStatus?.message ||
            "This saved card points to an older production record that is not available in your signed-in workspace. ReviveAI could not find a secure same-title copy in your tenant."
          );
        }
      }
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function returnFromProduction(destination?: "productions" | "overview") {
    if (!destination && productionReturnLocation === "workspace") {
      setWorkspaceView("workspace");
    } else {
      setChannelTab(destination ?? (productionReturnLocation === "workspace" ? "productions" : productionReturnLocation));
      setWorkspaceView("channel");
    }
    setActiveProductionId(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function refreshSavedChannel(channel: WorkspaceChannel) {
    clearLoadedWorkflow();
    setAnalysisIntent("REFRESH");
    setActiveChannelId(channel.channelId);
    setActiveProductionId(null);
    setWorkspaceView("add-channel");
    setUrl(channel.channelUrl);
    setWorkflowRestorePending(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function removeSavedChannel(channel: WorkspaceChannel) {
    setChannelPendingRemoval(channel);
  }

  function confirmRemoveSavedChannel() {
    const channel = channelPendingRemoval;
    if (!channel) return;

    clearLoadedWorkflow();
    window.localStorage.removeItem(workflowCheckpointKey);

    setWorkspace((current) => {
      const remaining = current.channels.filter((item) => item.channelId !== channel.channelId);
      return {
        ...current,
        channels: remaining,
        lastActiveChannelId:
          current.lastActiveChannelId === channel.channelId
            ? remaining[0]?.channelId
            : current.lastActiveChannelId,
        lastActiveProductionId:
          current.lastActiveChannelId === channel.channelId
            ? undefined
            : current.lastActiveProductionId,
      };
    });

    setChannelPendingRemoval(null);
    setActiveChannelId(null);
    setActiveProductionId(null);
    setAnalysisIntent("ADD");
    setUrl("");
    setWorkspaceRestoreError(null);
    setWorkflowRestorePending(false);
    setWorkspaceView("workspace");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function goWorkspaceHome() {
    clearLoadedWorkflow();
    window.localStorage.removeItem(workflowCheckpointKey);
    setWorkspaceView("workspace");
    setActiveProductionId(null);
    setWorkflowRestorePending(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function startAddChannel() {
    clearLoadedWorkflow();
    window.localStorage.removeItem(workflowCheckpointKey);
    setAnalysisIntent("ADD");
    setActiveChannelId(null);
    setActiveProductionId(null);
    setWorkspaceView("add-channel");
    setUrl("");
    setWorkflowRestorePending(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function reset() {
    startAddChannel();
  }


  function updateAutopilot(patch: Partial<AutopilotSession>) {
    setAutopilot((current) => {
      const changed = Object.entries(patch).some(([key, value]) => {
        const currentValue = current[key as keyof AutopilotSession];
        if (currentValue === value) return false;
        if (currentValue && value && typeof currentValue === "object" && typeof value === "object") {
          return JSON.stringify(currentValue) !== JSON.stringify(value);
        }
        return true;
      });
      if (!changed) return current;
      return { ...current, ...patch, updatedAt: new Date().toISOString() };
    });
  }

  function quarantineCurrentAutopilotProduction(stage: AutopilotAttentionStage, rawMessage: string) {
    setAutopilot((current) => {
      if (!current.currentRecommendationId || stage === "FINAL_VIDEO") {
        return {
          ...current,
          status: "NEEDS_ATTENTION",
          attentionStage: stage,
          message: rawMessage,
          updatedAt: new Date().toISOString(),
        };
      }

      const now = new Date().toISOString();
      const message = friendlyAutopilotExceptionMessage(rawMessage);
      const kind: AutopilotBlockedProduction["kind"] = isTransientAutopilotInfrastructureError(rawMessage)
        ? "INFRASTRUCTURE"
        : stage === "DELIVERY_QC"
          ? "TECHNICAL"
          : "CONTENT";
      const isBlocking = kind === "INFRASTRUCTURE";
      const blocked: AutopilotBlockedProduction = {
        recommendationId: current.currentRecommendationId,
        title: current.currentTitle || "Production",
        message,
        attentionStage: stage,
        blockedAt: now,
        kind,
        productionJobId: current.currentProductionJobId,
        recoveryJobId: current.recoveryJobId,
        analysisJobId: productionBriefJob?.analysis_job_id || null,
        resolutionStatus: isBlocking ? "BLOCKING" : "ARCHIVED",
        resolutionReason: isBlocking ? "INFRASTRUCTURE_ACTION_REQUIRED" : "PRODUCTION_RETRIES_EXHAUSTED",
        resolvedAt: isBlocking ? null : now,
        blocksAutonomy: isBlocking,
      };
      const blockedProductions = [
        ...current.blockedProductions.filter((item) => item.recommendationId !== blocked.recommendationId),
        blocked,
      ];
      const blockedIds = new Set(blockedProductions.map((item) => item.recommendationId));
      const completedIds = new Set(current.completedRecommendationIds);
      const hasAnotherIdea = Boolean(revivalProgram && orderedRevivalRecommendationIds(revivalProgram).some(
        (id) => !completedIds.has(id) && !blockedIds.has(id),
      ));

      return {
        ...current,
        status: hasAnotherIdea ? "RUNNING" : (isBlocking ? "NEEDS_ATTENTION" : "COMPLETED"),
        currentRecommendationId: null,
        currentTitle: null,
        currentStartedAt: null,
        currentProductionJobId: null,
        currentMediaJobId: null,
        currentAssemblyJobId: null,
        currentAudioJobId: null,
        currentDeliveryPackageId: null,
        currentPublishingDraftId: null,
        currentPublicationId: null,
        blockedProductions,
        attentionStage: !hasAnotherIdea && isBlocking ? stage : null,
        message: hasAnotherIdea
          ? `${blocked.title} was preserved as a production exception. ReviveAI is moving to the next available idea.`
          : isBlocking
            ? `${blocked.title} is blocked by an infrastructure issue and requires attention before autonomy can continue safely.`
            : `${blocked.title} was archived after automatic recovery attempts. No other unblocked ideas remain; historical failures are preserved without blocking autonomy.`,
        updatedAt: now,
      };
    });
  }

  function setAutopilotAttention(stage: AutopilotAttentionStage, message: string) {
    if (stage === "FINAL_VIDEO") {
      updateAutopilot({ status: "NEEDS_ATTENTION", attentionStage: stage, message });
      return;
    }
    quarantineCurrentAutopilotProduction(stage, message);
  }

  function startAutopilot() {
    if (!autopilotHydrated) return;
    if (!revivalProgram || !recoveryJob || recoveryJob.stage !== "COMPLETED" || !recoveryJob.result) return;
    const now = new Date().toISOString();
    const sameProgram = autopilot.programId === revivalProgram.program_id;
    setAutopilot({
      version: 2,
      scope: "CAMPAIGN",
      status: "RUNNING",
      executionOwner: "BACKEND",
      executionVersion: 1,
      recoveryJobId: recoveryJob.job_id,
      programId: revivalProgram.program_id,
      currentProductionJobId: null,
      currentMediaJobId: null,
      currentAssemblyJobId: null,
      currentAudioJobId: null,
      currentDeliveryPackageId: null,
      currentPublishingDraftId: null,
      currentPublicationId: null,
      learningCheckpointRequired: null,
      learningWaitStartedAt: null,
      lastSupervisorHeartbeatAt: null,
      currentRecommendationId: null,
      currentTitle: null,
      currentStartedAt: null,
      completedRecommendationIds: sameProgram ? autopilot.completedRecommendationIds : [],
      blockedProductions: sameProgram ? autopilot.blockedProductions.map(normalizeBlockedProduction) : [],
      attempts: sameProgram ? autopilot.attempts : {},
      attentionStage: null,
      message: "Autopilot started. The AI assistant will create, review, correct, and package each production; you will approve only the finished video.",
      startedAt: now,
      updatedAt: now,
    });
  }

  async function startSelectedTrial(recommendationId: string, title: string) {
    if (!autopilotHydrated || autopilotPersistenceError || autopilot.scope !== "CAMPAIGN" || !["IDLE", "PAUSED"].includes(autopilot.status)) {
      setAutopilotPersistenceError("An idle or paused campaign and synchronized backend checkpoint are required.");
      return;
    }
    const trialRecoveryId = autopilot.recoveryJobId || (recoveryJob?.stage === "COMPLETED" && recoveryJob.result ? recoveryJob.job_id : null);
    if (!trialRecoveryId || autopilotServerRevisionRef.current == null) {
      setAutopilotPersistenceError("A completed Recovery Intelligence checkpoint and synchronized backend revision are required.");
      return;
    }
    setSingleTrialSubmitting(true);
    try {
      const saved = await startSingleProductionTrial<AutopilotSession>({
        expected_revision: autopilotServerRevisionRef.current,
        recommendation_id: recommendationId,
        recovery_job_id: trialRecoveryId,
        title,
      });
      autopilotServerRevisionRef.current = saved.revision;
      autopilotLastPersistedUpdatedAtRef.current = saved.session.updatedAt;
      setAutopilot({ ...emptyAutopilotSession(), ...saved.session });
      setAutopilotPersistenceError(null);
      setSelectedRecommendationId(recommendationId);
      setPendingTrialBrief({ recommendationId, title });
      // The start endpoint creates an Autopilot session, NOT a Production Brief.
      // Stay in the campaign until the supervisor persists a real job ID.
      setWorkspaceView("channel");
      setSingleTrialConfirmation(null);
    } catch (error) {
      setAutopilotPersistenceError(error instanceof Error ? error.message : "Could not safely start the trial.");
      setSingleTrialConfirmation(null);
    } finally {
      setSingleTrialSubmitting(false);
    }
  }

  async function restoreArchivedCampaign() {
    if (autopilotServerRevisionRef.current == null) return;
    try {
      const saved = await restoreSingleTrialCampaign<AutopilotSession>(autopilotServerRevisionRef.current);
      autopilotServerRevisionRef.current = saved.revision;
      autopilotLastPersistedUpdatedAtRef.current = saved.session.updatedAt;
      setAutopilot({ ...emptyAutopilotSession(), ...saved.session });
      setAutopilotPersistenceError(null);
      setWorkspaceView("channel");
    } catch (error) {
      setAutopilotPersistenceError(error instanceof Error ? error.message : "Unable to restore the paused campaign");
    }
  }

  async function startSavedProductionAutopilot() {
    if (singleTrialSubmitting) return;
    setSavedProductionStartError(null);
    const selection = savedProductionAutopilotConfirmation;
    if (!selection) return;
    if (!productionBriefJob || productionBriefJob.job_id !== selection.productionId) {
      setSavedProductionStartError("The selected production changed. Cancel, reopen the production and try again.");
      return;
    }
    if (!autopilotHydrated) {
      setSavedProductionStartError("The saved Autopilot checkpoint is still loading. Please try again shortly.");
      return;
    }
    setSingleTrialSubmitting(true);
    try {
      // An older persistence warning must not block a new, explicitly confirmed
      // production. The server checkpoint is authoritative for this transition.
      const before = await getServerAutopilotState<AutopilotSession>();
      if (!before || !Number.isInteger(before.revision)) {
        throw new Error("Could not load the latest Autopilot revision. The switch was not submitted.");
      }
      autopilotServerRevisionRef.current = before.revision;
      autopilotLastPersistedUpdatedAtRef.current = before.session.updatedAt;
      if (before.session.currentProductionJobId === selection.productionId && before.session.status === "RUNNING") {
        setAutopilot({ ...emptyAutopilotSession(), ...before.session });
        setAutopilotPersistenceError(null);
        setSavedProductionAutopilotConfirmation(null);
        return;
      }
      const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/autopilot-state/switch-production`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: before.revision,
          production_job_id: selection.productionId,
          confirm: "ARCHIVE_CURRENT_AND_START_SELECTED_PRODUCTION",
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 409) {
          // Never automatically resubmit an archival request on conflict.
          throw new Error(typeof payload.detail === "string" ? payload.detail
            : payload.detail?.message || "The server checkpoint changed while starting. Refresh the page and confirm again.");
        }
        throw new Error(typeof payload.detail === "string" ? payload.detail
          : payload.detail?.message || `Unable to safely switch Autopilot (HTTP ${response.status}).`);
      }
      const saved = payload as { revision: number; session: AutopilotSession };
      if (!Number.isInteger(saved.revision) || !saved.session || saved.session.currentProductionJobId !== selection.productionId) {
        throw new Error("The server response did not confirm the selected production. Check Autopilot state before trying again.");
      }
      autopilotServerRevisionRef.current = saved.revision;
      autopilotLastPersistedUpdatedAtRef.current = saved.session.updatedAt;
      setAutopilot({ ...emptyAutopilotSession(), ...saved.session });
      setAutopilotPersistenceError(null);
      setAutopilotSyncNotice(null);
      setSelectedRecommendationId(productionBriefJob.recommendation_id);
      setSavedProductionAutopilotConfirmation(null);
    } catch (error) {
      // Keep the dialog visible, rather than silently swallowing the click.
      setSavedProductionStartError(error instanceof Error ? error.message : "Autopilot switch failed safely.");
    } finally {
      setSingleTrialSubmitting(false);
    }
  }

  function runAutopilotForRecommendation(recommendationId: string) {
    if (!autopilotHydrated) {
      setAutopilotPersistenceError("AI Autopilot is still restoring its saved state. Try again in a moment.");
      return;
    }

    const blockedItem = autopilot.blockedProductions.find((item) => item.recommendationId === recommendationId) ?? null;
    const currentProduction = productionBriefJob?.recommendation_id === recommendationId
      ? productionBriefJob
      : null;

    // Resolve a durable Production Brief using the strongest lineage first.
    // Recommendation IDs are not globally unique across Recovery Intelligence runs,
    // so a bare recommendation_1 match is intentionally the last legacy fallback.
    const historyForRecommendation = productionHistory
      .filter((entry) => entry.source_snapshot.recommendation.recommendation_id === recommendationId)
      .sort((left, right) => {
        const leftApproved = left.review_status === "APPROVED" ? 1 : 0;
        const rightApproved = right.review_status === "APPROVED" ? 1 : 0;
        if (leftApproved !== rightApproved) return rightApproved - leftApproved;
        return new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime();
      });

    let historicalProduction = blockedItem?.productionJobId
      ? historyForRecommendation.find((entry) => entry.job_id === blockedItem.productionJobId) ?? null
      : null;

    if (!historicalProduction && blockedItem?.recoveryJobId) {
      historicalProduction = historyForRecommendation.find(
        (entry) => entry.recovery_job_id === blockedItem.recoveryJobId,
      ) ?? null;
    }

    if (!historicalProduction && blockedItem?.analysisJobId) {
      historicalProduction = historyForRecommendation.find(
        (entry) => entry.analysis_job_id === blockedItem.analysisJobId,
      ) ?? null;
    }

    // Legacy blocked records predate durable lineage fields. Use the saved title as
    // a second key before accepting a recommendation-id-only match.
    if (!historicalProduction && blockedItem?.title) {
      const wanted = normalizeProductionTitle(blockedItem.title);
      historicalProduction = historyForRecommendation.find((entry) => (
        normalizeProductionTitle(entry.working_title || "") === wanted
        || normalizeProductionTitle(entry.source_snapshot.recommendation.title || "") === wanted
      )) ?? null;
    }

    if (!historicalProduction && historyForRecommendation.length === 1) {
      historicalProduction = historyForRecommendation[0];
    }

    const snapshotRecommendation = currentProduction?.source_snapshot.recommendation
      || historicalProduction?.source_snapshot.recommendation;
    const activeRecoveryRecommendation = recoveryJob?.stage === "COMPLETED" && recoveryJob.result
      ? recoveryJob.result.recommendations.find((item) => item.recommendation_id === recommendationId)
      : null;
    const recommendation = snapshotRecommendation || activeRecoveryRecommendation;

    if (!recommendation) {
      setAutopilotPersistenceError(
        "ReviveAI could not reconnect this production to its durable source direction. The retry was stopped safely; no newer server checkpoint was overwritten.",
      );
      return;
    }

    // A persisted production is authoritative for its own recovery lineage. This
    // lets old blocked work resume even after the channel has run a newer Recovery
    // Intelligence analysis. If there is no durable production, the current recovery
    // job remains required to start one.
    const resolvedRecoveryJobId = historicalProduction?.recovery_job_id
      || currentProduction?.recovery_job_id
      || blockedItem?.recoveryJobId
      || recoveryJob?.job_id
      || null;
    if (!resolvedRecoveryJobId) {
      setAutopilotPersistenceError("ReviveAI found the saved direction but not its Recovery Intelligence lineage. Retry was stopped safely.");
      return;
    }

    const idea = revivalProgram?.ideas.find((item) => item.recommendation_id === recommendationId);
    const now = new Date().toISOString();
    const title = currentProduction?.result?.creative_direction.working_title
      || historicalProduction?.working_title
      || idea?.title
      || recommendation.title;
    const savedProductionJobId = currentProduction?.job_id || historicalProduction?.job_id || null;
    const resolvedAnalysisJobId = currentProduction?.analysis_job_id
      || historicalProduction?.analysis_job_id
      || blockedItem?.analysisJobId
      || null;
    const hasSavedProduction = Boolean(savedProductionJobId);

    setAutopilotPersistenceError(null);
    setAutopilot((current) => ({
      ...current,
      version: 2,
      scope: "PRODUCTION",
      status: "RUNNING",
      executionOwner: "BACKEND",
      executionVersion: 1,
      recoveryJobId: resolvedRecoveryJobId,
      // Never carry a different production's job chain into this retry.
      currentProductionJobId: savedProductionJobId,
      currentMediaJobId: currentProduction?.job_id === savedProductionJobId ? mediaStudioJob?.job_id || null : null,
      currentAssemblyJobId: currentProduction?.job_id === savedProductionJobId ? finalAssemblyJob?.job_id || null : null,
      currentAudioJobId: currentProduction?.job_id === savedProductionJobId ? audioFinishingJob?.job_id || null : null,
      currentDeliveryPackageId: currentProduction?.job_id === savedProductionJobId ? deliveryPackage?.package_id || null : null,
      currentPublishingDraftId: currentProduction?.job_id === savedProductionJobId ? publishingDraft?.draft_id || null : null,
      currentPublicationId: currentProduction?.job_id === savedProductionJobId ? current.currentPublicationId : null,
      lastSupervisorHeartbeatAt: current.lastSupervisorHeartbeatAt || null,
      programId: revivalProgram?.program_id || `production:${resolvedRecoveryJobId}`,
      currentRecommendationId: recommendationId,
      currentTitle: title,
      currentStartedAt: now,
      // Keep the blocked record during recovery. It is the durable retry lineage and
      // will be removed by the successful learning/completion path. If recovery fails
      // again, quarantine replaces this record instead of losing its history.
      blockedProductions: current.blockedProductions.map((item) => (
        item.recommendationId === recommendationId
          ? {
              ...item,
              productionJobId: savedProductionJobId || item.productionJobId || null,
              recoveryJobId: resolvedRecoveryJobId,
              analysisJobId: resolvedAnalysisJobId || item.analysisJobId || null,
            }
          : item
      )),
      attentionStage: null,
      message: hasSavedProduction
        ? `AI Autopilot reconnected ${title} from its durable production checkpoint and is continuing from the last verified stage.`
        : `AI Autopilot is starting ${title}. Intermediate planning, visual, audio, and quality reviews are delegated to AI.`,
      startedAt: current.startedAt || now,
      updatedAt: now,
    }));
    setSelectedRecommendationId(recommendationId);
    setWorkspaceView("production");
  }

  function takeControlOfCurrentProduction() {
    if (!productionBriefJob || !autopilotOwnsCurrentProduction) return;
    setAutopilot((current) => ({
      ...current,
      status: "IDLE",
      scope: "PRODUCTION",
      currentRecommendationId: null,
      currentTitle: null,
      currentStartedAt: null,
      attentionStage: null,
      message: "Creator Mode is active. AI Autopilot can resume this production from its persisted checkpoints at any time.",
      updatedAt: new Date().toISOString(),
    }));
  }

  function pauseAutopilot() {
    if (!["RUNNING", "WAITING_FOR_LEARNING"].includes(autopilot.status)) return;
    updateAutopilot({ status: "PAUSED", message: "Autopilot is paused. In-flight generation can finish, but ReviveAI will not advance to the next action." });
  }

  function resumeAutopilot() {
    if (!["PAUSED", "NEEDS_ATTENTION", "WAITING_FOR_FINAL_APPROVAL", "WAITING_FOR_LEARNING"].includes(autopilot.status)) return;
    if (autopilot.attentionStage === "FINAL_VIDEO") {
      setWorkspaceView("production");
      // Do not let background job hydration overwrite explicit library navigation.
      window.setTimeout(() => document.getElementById("final-human-review")?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
      return;
    }
    updateAutopilot({
      status: "RUNNING",
      executionOwner: "BACKEND",
      executionVersion: 1,
      attentionStage: null,
      message: "Autopilot resumed. The backend supervisor is checking the current production state.",
    });
  }

  async function reconcileExistingProductionBrief() {
    if (briefReconcilePending || !autopilotHydrated) return;
    setBriefReconcilePending(true);
    setBriefReconcileError(null);
    try {
      // Re-read server state immediately: never submit a stale revision.
      const before = await getServerAutopilotState<AutopilotSession>();
      if (!before) throw new Error("Server Autopilot checkpoint is unavailable.");
      const original = "production_26f4223c5db340d6a958e4b813ed0810";
      const replacement = "production_e75711ad5c094141aa87354b6422ef20";
      if (before.session.currentProductionJobId === replacement) {
        autopilotServerRevisionRef.current = before.revision;
        autopilotLastPersistedUpdatedAtRef.current = before.session.updatedAt;
        setAutopilot({ ...emptyAutopilotSession(), ...before.session });
        setBriefReconcileConfirmOpen(false);
        return;
      }
      if (before.session.scope !== "PRODUCTION" || before.session.status !== "NEEDS_ATTENTION"
          || before.session.currentProductionJobId !== original
          || before.session.currentRecommendationId !== "replenished_9a5e3b4f52f9eb7a0b48"
          || before.session.attempts?.[`brief-config-repair:${original}`] !== 1) {
        throw new Error("Autopilot state no longer matches the one-time brief repair. No action was taken.");
      }
      const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/autopilot-state/reconcile-brief-configuration`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_revision: before.revision,
          failed_production_job_id: original,
          replacement_production_job_id: replacement,
          confirm: "ADOPT_EXISTING_BRIEF_NO_REGENERATION",
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(typeof payload.detail === "string" ? payload.detail
          : payload.detail?.message || `Brief reconciliation failed (HTTP ${response.status}).`);
      }
      const saved = payload as { revision: number; session: AutopilotSession };
      autopilotServerRevisionRef.current = saved.revision;
      autopilotLastPersistedUpdatedAtRef.current = saved.session.updatedAt;
      setAutopilot({ ...emptyAutopilotSession(), ...saved.session });
      setBriefReconcileConfirmOpen(false);
    } catch (error) {
      setBriefReconcileError(error instanceof Error ? error.message : "Unable to reconcile the existing brief.");
    } finally {
      setBriefReconcilePending(false);
    }
  }

  async function recoverAutopilotException() {
    if (autopilotRecoveryPending || autopilot.status !== "NEEDS_ATTENTION") return;

    // A missing brief reservation is infrastructure configuration, not a creative
    // failure. The backend performs a one-time, revision-checked retry without
    // resetting the original retry count or creating an unrelated production.
    if (autopilot.scope === "PRODUCTION"
        && autopilot.attentionStage === "FAILURE"
        && autopilot.message.trim() === "Configure REVIVEAI_GEMINI_BRIEF_RESERVATION_USD"
        && autopilot.currentProductionJobId) {
      if (autopilotServerRevisionRef.current == null) {
        setAutopilotPersistenceError("Autopilot server revision unavailable. Refresh before recovery.");
        return;
      }
      setAutopilotRecoveryPending(true);
      setAutopilotPersistenceError(null);
      try {
        const response = await apiFetch(`${API_BASE_URL}/api/v1/youtube/autopilot-state/recover-brief-configuration`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision: autopilotServerRevisionRef.current,
            production_job_id: autopilot.currentProductionJobId,
            confirm: "RETRY_BRIEF_AFTER_CONFIG_FIX",
          }),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          throw new Error(typeof payload.detail === "string" ? payload.detail
            : payload.detail?.message || `Brief configuration recovery failed (HTTP ${response.status}).`);
        }
        const saved = await response.json() as { revision: number; session: AutopilotSession };
        autopilotServerRevisionRef.current = saved.revision;
        autopilotLastPersistedUpdatedAtRef.current = saved.session.updatedAt;
        setAutopilot({ ...emptyAutopilotSession(), ...saved.session });
      } catch (error) {
        setAutopilotPersistenceError(error instanceof Error ? error.message : "Brief configuration recovery failed.");
      } finally {
        setAutopilotRecoveryPending(false);
      }
      return;
    }

    const normalizedBlocked = autopilot.blockedProductions.map(normalizeBlockedProduction);
    const blockingItems = normalizedBlocked.filter(blockedProductionBlocksAutonomy);

    // v3.6: legacy content failures without durable lineage are historical audit
    // records, not campaign-level blockers. Persist the migration and let the backend
    // supervisor resume from authoritative server state instead of guessing a direction.
    if (!autopilot.currentRecommendationId && blockingItems.length === 0) {
      setAutopilotPersistenceError(null);
      setAutopilot((current) => ({
        ...current,
        status: "RUNNING",
        executionOwner: "BACKEND",
        executionVersion: 1,
        attentionStage: null,
        blockedProductions: current.blockedProductions.map(normalizeBlockedProduction),
        message: `${normalizedBlocked.length} historical production exception${normalizedBlocked.length === 1 ? " was" : "s were"} archived safely. They remain in history and no longer block autonomous production.`,
        updatedAt: new Date().toISOString(),
      }));
      return;
    }

    if (!autopilot.currentRecommendationId && blockingItems.length > 0) {
      const retryable = blockingItems.find((item) => item.resolutionStatus === "RETRYABLE" || Boolean(item.productionJobId));
      if (retryable) {
        runAutopilotForRecommendation(retryable.recommendationId);
        return;
      }
      setAutopilotPersistenceError("A blocking infrastructure issue still requires attention before Autopilot can continue safely.");
      return;
    }
    setAutopilotRecoveryPending(true);
    try {
      const failedKeyframe = mediaStudioJob?.result?.keyframes.find((asset) =>
        asset.fidelity_report?.status === "REVIEW_REQUIRED"
        || (asset.fidelity_report?.status === "ADAPTATION_ACCEPTED" && asset.fidelity_report?.creator_override)
      );
      if (mediaStudioJob && failedKeyframe?.shot_number) {
        const shot = failedKeyframe.shot_number;
        if (failedKeyframe.generation_attempt < AUTOPILOT_SHOT_REPLAN_LIMIT) {
          const next = await regenerateMediaKeyframe(
            mediaStudioJob.job_id,
            shot,
            "Autonomous recovery: replan this shot around a simpler, identity-safe composition. Preserve the narrative purpose and locked Production Identity, but simplify pose, framing, props, and action staging so the scene is reliably executable. Prefer a clear close/medium shot over a complex full-body composition.",
          );
          setMediaStudioJob(next);
          updateAutopilot({
            status: "RUNNING",
            executionOwner: "BACKEND",
            executionVersion: 1,
            attentionStage: null,
            message: `Autonomous recovery is replanning shot ${shot}. No action is needed; ReviveAI will salvage the shot if literal fidelity still cannot be reached.`,
          });
          return;
        }
        setMediaStudioJob(await aiSalvageMediaKeyframe(mediaStudioJob.job_id, shot));
        updateAutopilot({
          status: "RUNNING",
          executionOwner: "BACKEND",
          executionVersion: 1,
          attentionStage: null,
          message: `Shot ${shot} was AI-salvaged after repeated fidelity failures. ReviveAI is continuing production automatically.`,
        });
        return;
      }

      const exhaustedClips = ((detailRecord(mediaStudioJob?.detail).ai_review_exhausted_clips as unknown[] | undefined) ?? []).map(Number);
      const salvageClipShot = exhaustedClips.find((shot) => Number.isFinite(shot));
      if (mediaStudioJob && salvageClipShot) {
        setMediaStudioJob(await aiCreateControlledMotionFallback(mediaStudioJob.job_id, salvageClipShot));
        updateAutopilot({
          status: "RUNNING",
          executionOwner: "BACKEND",
          executionVersion: 1,
          attentionStage: null,
          message: `Animated shot ${salvageClipShot} was recovered with controlled motion. ReviveAI is continuing to final assembly.`,
        });
        return;
      }

      if (mediaStudioJob?.result?.reference_asset && aiReviewExhausted(mediaStudioJob)) {
        const next = await regenerateMediaReference(
          mediaStudioJob.job_id,
          "AI recovery pass: rebuild the canonical reference with a materially different composition while preserving the locked identity exactly.",
        );
        setMediaStudioJob(next);
        updateAutopilot({
          status: "RUNNING",
          executionOwner: "BACKEND",
          executionVersion: 1,
          attentionStage: null,
          message: "AI recovery started. Generating a fresh canonical reference before re-running visual identity review.",
        });
        return;
      }

      if (productionBriefJob?.stage === "COMPLETED" && productionBriefJob.result) {
        const planDetail = detailRecord(productionBriefJob.detail);
        const planFailed = productionBriefJob.result.direction_fidelity.status === "REVIEW_REQUIRED"
          || productionBriefJob.result.consistency_report.status !== "PASS"
          || (planDetail.ai_plan_review && !aiDecisionPassed(planDetail.ai_plan_review));
        if (planFailed) {
          const next = await retryProductionBriefJob(productionBriefJob.job_id, "STRICT");
          setProductionBriefJob(next);
          setSelectedRecommendationId(next.recommendation_id);
          updateAutopilot({
            status: "RUNNING",
            executionOwner: "BACKEND",
            executionVersion: 1,
            attentionStage: null,
            message: "AI recovery started. Rebuilding the production plan from the immutable original direction.",
          });
          return;
        }
      }

      updateAutopilot({
        status: "RUNNING",
        attentionStage: null,
        message: "Rechecking the latest production checkpoints. Hard technical blockers remain fail-closed; creative visual exceptions recover automatically.",
      });
    } catch (error) {
      updateAutopilot({
        status: "NEEDS_ATTENTION",
        attentionStage: "FAILURE",
        message: error instanceof Error ? `AI recovery could not start: ${error.message}` : "AI recovery could not start. Review the exception and try again.",
      });
    } finally {
      setAutopilotRecoveryPending(false);
    }
  }

  function recordAutopilotAttempt(key: string, message: string) {
    setAutopilot((current) => ({
      ...current,
      attempts: { ...current.attempts, [key]: (current.attempts[key] ?? 0) + 1 },
      message,
      updatedAt: new Date().toISOString(),
    }));
  }

  async function recoverKeyframeMismatch(shotNumber: number, generationAttempt: number, inheritedHumanAdaptation = false) {
    if (!mediaStudioJob) return;

    if (generationAttempt < AUTOPILOT_MAX_GENERATION_ATTEMPTS) {
      updateAutopilot({
        message: inheritedHumanAdaptation
          ? `Shot ${shotNumber} contains a prior adaptation. Regenerating toward the locked storyboard (v${generationAttempt + 1}).`
          : `Shot ${shotNumber} missed storyboard fidelity. Correcting only that shot (v${generationAttempt + 1}).`,
      });
      setMediaStudioJob(await regenerateMediaKeyframe(
        mediaStudioJob.job_id,
        shotNumber,
        inheritedHumanAdaptation
          ? "Autopilot replaces prior human adaptation with source-faithful AI-reviewed output."
          : "Autopilot fidelity correction: preserve all elements that passed and correct the reviewer-identified mismatch only.",
      ));
      return;
    }

    if (generationAttempt < AUTOPILOT_ALTERNATE_APPROACH_LIMIT) {
      updateAutopilot({
        message: `Shot ${shotNumber} is entering alternate-generation recovery (v${generationAttempt + 1}). ReviveAI is changing composition and staging instead of repeating the same prompt.`,
      });
      setMediaStudioJob(await regenerateMediaKeyframe(
        mediaStudioJob.job_id,
        shotNumber,
        "Alternate-generation recovery: preserve the locked Production Identity and narrative purpose, but use a materially different composition, pose, camera framing, and action staging. Do not reuse the failed layout. Prefer a simpler, clearer execution that directly satisfies the required action.",
      ));
      return;
    }

    if (generationAttempt < AUTOPILOT_SHOT_REPLAN_LIMIT) {
      updateAutopilot({
        message: `Shot ${shotNumber} is being autonomously replanned (v${generationAttempt + 1}). The story purpose stays locked while the visual execution is simplified.`,
      });
      setMediaStudioJob(await regenerateMediaKeyframe(
        mediaStudioJob.job_id,
        shotNumber,
        "Autonomous shot replan: keep the same narrative purpose, character identity, setting continuity, and essential action, but simplify the visual execution aggressively. Prefer a close or medium shot, one clear action, fewer visible props, minimal body complexity, and straightforward camera framing. Preserve story meaning rather than literal failed staging.",
      ));
      return;
    }

    updateAutopilot({
      message: `Shot ${shotNumber} exhausted literal storyboard-fidelity generation. ReviveAI is salvaging the safest identity-preserving keyframe and continuing automatically.`,
    });
    setMediaStudioJob(await aiSalvageMediaKeyframe(mediaStudioJob.job_id, shotNumber));
  }

  async function reconcileStaleAutopilotCheckpoint() {
    if (autopilotWatchdogRunningRef.current || autopilot.status !== "RUNNING") return;
    if (!productionBriefJob || !autopilotOwnsCurrentProduction) return;

    const latest = latestAutopilotBackendCheckpoint({
      productionJob: productionBriefJob,
      mediaJob: mediaStudioJob,
      assemblyJob: finalAssemblyJob,
      audioJob: audioFinishingJob || approvedAudioMaster,
      qc: deliveryQcReport,
      deliveryPackage,
      publishingDraft,
    });
    if (latest == null || Date.now() - latest < AUTOPILOT_STALE_CHECKPOINT_MS) return;
    if (autopilotWatchdog.lastRunAt && Date.now() - autopilotWatchdog.lastRunAt < AUTOPILOT_WATCHDOG_COOLDOWN_MS) return;

    autopilotWatchdogRunningRef.current = true;
    setAutopilotWatchdog({
      status: "CHECKING",
      message: "No backend checkpoint has advanced recently. ReviveAI is reconciling saved job state before deciding whether anything must be retried.",
      lastRunAt: Date.now(),
    });

    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), AUTOPILOT_WATCHDOG_REQUEST_TIMEOUT_MS);
    try {
      let recoveredSomething = false;

      const mediaAiGateIncomplete = Boolean(mediaStudioJob && (
        hasActiveAiClipReviewOperation(mediaStudioJob)
        || !referenceAiPassed(mediaStudioJob)
        || !keyframesAiPassed(mediaStudioJob)
        || !clipsAiPassed(mediaStudioJob)
        || hasActiveShotOperation(mediaStudioJob)
        || hasActiveClipOperation(mediaStudioJob)
      ));

      // Reconcile Media Studio whenever an AI visual/motion gate is incomplete, even if
      // the legacy assembly_ready flag is already true.  Older human-approved clips can
      // make assembly_ready=true while Autopilot is still waiting for AI motion ownership.
      // v2.7 skipped reconciliation in exactly that state and could wait indefinitely.
      if (mediaStudioJob && mediaAiGateIncomplete) {
        const before = mediaStudioJob.updated_at;
        const refreshed = await reconcileMediaAutopilotJob(mediaStudioJob.job_id, controller.signal);
        setMediaStudioJob(refreshed);
        const watchdogDetail = detailRecord(detailRecord(refreshed.detail).autopilot_watchdog);
        recoveredSomething = String(watchdogDetail.outcome || "").toUpperCase() === "RECOVERED"
          || refreshed.updated_at !== before
          || clipsAiPassed(refreshed);
      } else if (finalAssemblyJob && ASSEMBLY_POLLING_STAGES.has(finalAssemblyJob.stage)) {
        const refreshed = await getFinalAssemblyJob(finalAssemblyJob.job_id);
        setFinalAssemblyJob(refreshed);
        recoveredSomething = refreshed.updated_at !== finalAssemblyJob.updated_at || !ASSEMBLY_POLLING_STAGES.has(refreshed.stage);
        if (!recoveredSomething && mediaStudioJob?.result?.assembly_ready) {
          const replacement = await createFinalAssemblyJob(mediaStudioJob.job_id);
          setFinalAssemblyJob(replacement);
          recoveredSomething = true;
        }
      } else if (audioFinishingJob && AUDIO_POLLING_STAGES.has(audioFinishingJob.stage)) {
        const refreshed = await getAudioFinishingJob(audioFinishingJob.job_id);
        setAudioFinishingJob(refreshed);
        setAudioVersionHistory((current) => [refreshed, ...current.filter((item) => item.job_id !== refreshed.job_id)]);
        recoveredSomething = refreshed.updated_at !== audioFinishingJob.updated_at || !AUDIO_POLLING_STAGES.has(refreshed.stage);
        if (!recoveredSomething && finalAssemblyJob?.stage === "DELIVERED") {
          const replacement = await createAudioFinishingJob(finalAssemblyJob.job_id, AUTOPILOT_AUDIO_DEFAULTS);
          setAudioFinishingJob(replacement);
          setAudioVersionHistory((current) => [replacement, ...current.filter((item) => item.job_id !== replacement.job_id)]);
          recoveredSomething = true;
        }
      } else if (productionBriefJob) {
        const refreshed = await getProductionBriefJob(productionBriefJob.job_id);
        setProductionBriefJob(refreshed);
        recoveredSomething = refreshed.updated_at !== productionBriefJob.updated_at;
      }

      // A stale unresolved fetch can leave the supervisor lock set forever. The watchdog
      // owns recovery from this point, so releasing the local lock is safe; backend
      // reconciliation remains idempotent and authoritative.
      autopilotActionRef.current = false;
      setAutopilotWatchdog({
        status: recoveredSomething ? "RECOVERED" : "WAITING",
        message: recoveredSomething
          ? "A stale checkpoint was restored. Autopilot is continuing from the latest durable backend state."
          : "The backend is reachable but the current provider operation has not produced a new checkpoint yet. ReviveAI will check again automatically.",
        lastRunAt: Date.now(),
      });
      if (recoveredSomething) {
        updateAutopilot({ message: "Stalled checkpoint recovered. Continuing automatic production from the latest verified state." });
      }
    } catch (error) {
      autopilotActionRef.current = false;
      const timedOut = error instanceof DOMException && error.name === "AbortError";
      setAutopilotWatchdog({
        status: "WAITING",
        message: timedOut
          ? "The recovery check timed out. ReviveAI will retry the watchdog automatically without advancing an unverified gate."
          : error instanceof Error
            ? `Automatic checkpoint recovery could not complete: ${error.message}`
            : "Automatic checkpoint recovery could not complete. ReviveAI will retry automatically.",
        lastRunAt: Date.now(),
      });
    } finally {
      window.clearTimeout(timeout);
      autopilotWatchdogRunningRef.current = false;
    }
  }

  async function driveAutopilot() {
    if (!autopilotHydrated) return;
    if (autopilotActionRef.current || autopilot.status !== "RUNNING") return;
    if (!recoveryJob || recoveryJob.stage !== "COMPLETED" || !recoveryJob.result) return;
    if (autopilot.recoveryJobId !== recoveryJob.job_id) return;
    if (autopilot.scope === "CAMPAIGN" && (!revivalProgram || autopilot.programId !== revivalProgram.program_id)) return;

    autopilotActionRef.current = true;
    try {
      const recovery = recoveryJob.result;
      const currentRecommendationId = autopilot.currentRecommendationId;

      if (!currentRecommendationId) {
        if (autopilot.scope === "PRODUCTION") {
          setAutopilotAttention("FAILURE", "The production Autopilot lost its saved direction. Reopen the production and run Autopilot again.");
          return;
        }
        if (!revivalProgram) return;
        // Existing production history is resumable work, not a reason to skip an idea.
        // Only ideas that this Autopilot session has actually finished are excluded.
        const completedByAutopilot = new Set(autopilot.completedRecommendationIds);
        const normalizedBlocked = autopilot.blockedProductions.map(normalizeBlockedProduction);
        const blockedByAutopilot = new Set(normalizedBlocked.map((item) => item.recommendationId));
        const nextRecommendationId = orderedRevivalRecommendationIds(revivalProgram).find(
          (id) => !completedByAutopilot.has(id) && !blockedByAutopilot.has(id),
        );
        if (!nextRecommendationId) {
          const blockingItems = normalizedBlocked.filter(blockedProductionBlocksAutonomy);
          if (blockingItems.length > 0) {
            updateAutopilot({
              status: "NEEDS_ATTENTION",
              attentionStage: blockingItems[0].attentionStage || "FAILURE",
              currentRecommendationId: null,
              currentTitle: null,
              currentStartedAt: null,
              blockedProductions: normalizedBlocked,
              message: `${blockingItems.length} blocking production issue${blockingItems.length === 1 ? "" : "s"} still need attention. Historical failures remain preserved separately.`,
            });
          } else {
            updateAutopilot({
              status: "COMPLETED",
              attentionStage: null,
              currentRecommendationId: null,
              currentTitle: null,
              currentStartedAt: null,
              blockedProductions: normalizedBlocked,
              message: normalizedBlocked.length
                ? `Autopilot finished every available idea. ${normalizedBlocked.length} historical production exception${normalizedBlocked.length === 1 ? " is" : "s are"} preserved and do not block autonomy.`
                : "Autopilot finished every available idea in this revival program.",
            });
          }
          return;
        }

        const recommendation = recovery.recommendations.find((item) => item.recommendation_id === nextRecommendationId);
        const idea = revivalProgram.ideas.find((item) => item.recommendation_id === nextRecommendationId);
        if (!recommendation) {
          setAutopilotAttention("FAILURE", "The next revival idea no longer has a matching Recovery Intelligence recommendation. Refresh the revival plan before continuing.");
          return;
        }

        const savedProduction = productionHistory.find(
          (entry) => entry.source_snapshot.recommendation.recommendation_id === nextRecommendationId,
        );

        updateAutopilot({
          currentRecommendationId: nextRecommendationId,
          currentTitle: idea?.title || recommendation.title,
          currentStartedAt: new Date().toISOString(),
          message: savedProduction
            ? `Adopting existing production: ${idea?.title || recommendation.title}`
            : `Starting production: ${idea?.title || recommendation.title}`,
          attentionStage: null,
        });

        setProductionBriefError(null);
        setSelectedRecommendationId(nextRecommendationId);
        setProductionBriefJob(null);
        setMediaStudioJob(null);
        setMediaStudioError(null);
        setFinalAssemblyJob(null);
        setFinalAssemblyError(null);
        setAudioFinishingJob(null);
        setAudioVersionHistory([]);
        setAudioFinishingError(null);
        setDeliveryQcReport(null);
        setDeliveryQcError(null);
        setDeliveryPackage(null);
        setPublishingDraft(null);
        setPublishingDraftHistory([]);

        if (savedProduction) {
          const restored = await getProductionBriefJob(savedProduction.job_id);
          setProductionBriefJob(restored);
          setSelectedRecommendationId(restored.recommendation_id);
          setActiveProductionId(restored.job_id);
          setWorkspaceView("production");
          return;
        }

        const next = await createProductionBriefJob(recoveryJob.job_id, nextRecommendationId, "STANDARD");
        setProductionBriefJob(next);
        setActiveProductionId(next.job_id);
        setWorkspaceView("production");
        return;
      }

      if (!productionBriefJob || productionBriefJob.recommendation_id !== currentRecommendationId) {
        const saved = productionHistory.find((entry) => entry.source_snapshot.recommendation.recommendation_id === currentRecommendationId);
        if (saved) {
          const restored = await getProductionBriefJob(saved.job_id);
          setProductionBriefJob(restored);
          setSelectedRecommendationId(restored.recommendation_id);
          setActiveProductionId(restored.job_id);
          setWorkspaceView("production");
          return;
        }
        // A just-created job may not have propagated to history yet. Do not create a duplicate.
        updateAutopilot({ message: "Waiting for the current production to reconnect before advancing." });
        return;
      }

      if (!PRODUCTION_TERMINAL.has(productionBriefJob.stage)) {
        updateAutopilot({ message: productionBriefJob.message || "Building the production brief." });
        return;
      }

      if (productionBriefJob.stage === "FAILED") {
        const key = `brief:${currentRecommendationId}`;
        const attempts = autopilot.attempts[key] ?? 0;
        if (attempts < AUTOPILOT_MAX_RETRIES) {
          recordAutopilotAttempt(key, `Production brief failed. Retrying automatically (${attempts + 1}/${AUTOPILOT_MAX_RETRIES}).`);
          const next = await retryProductionBriefJob(productionBriefJob.job_id, productionBriefJob.fidelity_mode);
          setProductionBriefJob(next);
          setSelectedRecommendationId(next.recommendation_id);
          return;
        }
        setAutopilotAttention("FAILURE", productionBriefJob.error || "The production brief failed repeatedly and needs review.");
        return;
      }

      const brief = productionBriefJob.result;
      if (!brief) {
        setAutopilotAttention("FAILURE", "The production brief completed without a result. Review this production before continuing.");
        return;
      }

      if (brief.direction_fidelity.status === "REVIEW_REQUIRED") {
        const key = `direction:${currentRecommendationId}`;
        const attempts = autopilot.attempts[key] ?? 0;
        if (attempts < AUTOPILOT_MAX_GENERATION_ATTEMPTS) {
          recordAutopilotAttempt(key, `The draft drifted from the approved recovery direction. AI is regenerating from the immutable original direction (${attempts + 1}/${AUTOPILOT_MAX_GENERATION_ATTEMPTS}).`);
          const next = await retryProductionBriefJob(productionBriefJob.job_id, "STRICT");
          setProductionBriefJob(next);
          setSelectedRecommendationId(next.recommendation_id);
          return;
        }
        setAutopilotAttention("FAILURE", "AI could not restore the approved source direction after automatic retries. This production was paused rather than asking you to approve an intermediate creative deviation.");
        return;
      }

      if (brief.consistency_report.status !== "PASS") {
        const key = `consistency:${currentRecommendationId}`;
        const attempts = autopilot.attempts[key] ?? 0;
        if (attempts < AUTOPILOT_MAX_RETRIES) {
          recordAutopilotAttempt(key, `Production consistency did not pass. Regenerating the brief automatically (${attempts + 1}/${AUTOPILOT_MAX_RETRIES}).`);
          const next = await retryProductionBriefJob(productionBriefJob.job_id, productionBriefJob.fidelity_mode);
          setProductionBriefJob(next);
          return;
        }
        setAutopilotAttention("FAILURE", brief.consistency_report.blocking_issues[0] || "Production consistency still needs correction after automatic retries.");
        return;
      }

      {
        const briefDetail = detailRecord(productionBriefJob.detail);
        const planReview = briefDetail.ai_plan_review as Record<string, unknown> | undefined;
        const planReviewIsCurrent = String(briefDetail.ai_plan_review_for_generated_at || "") === brief.generated_at;
        const planAiApproved = brief.review_status === "APPROVED" && briefDetail.approval_actor === "AI" && planReviewIsCurrent && planReview?.decision === "PASS";
        if (!planAiApproved) {
          if (planReviewIsCurrent && planReview?.decision === "REGENERATE") {
            const key = `plan-critic:${currentRecommendationId}`;
            const attempts = autopilot.attempts[key] ?? 0;
            if (attempts < AUTOPILOT_MAX_GENERATION_ATTEMPTS) {
              recordAutopilotAttempt(key, `The independent AI plan critic found a material issue. Regenerating the brief (${attempts + 1}/${AUTOPILOT_MAX_GENERATION_ATTEMPTS}).`);
              const next = await retryProductionBriefJob(productionBriefJob.job_id, "STRICT");
              setProductionBriefJob(next);
              setSelectedRecommendationId(next.recommendation_id);
              return;
            }
            setAutopilotAttention("FAILURE", "The production plan could not pass the independent AI text critic after automatic retries. No intermediate human approval was requested.");
            return;
          }
          updateAutopilot({ message: "Independent AI plan critic is reviewing the brief, storyboard, and early publishing direction before any media is generated." });
          setProductionBriefJob(await aiReviewProductionBrief(productionBriefJob.job_id));
          return;
        }
      }

      if (!mediaStudioJob || mediaStudioJob.production_brief_job_id !== productionBriefJob.job_id) {
        if (mediaResumePending) return;
        const existing = await getLatestMediaStudioJob(productionBriefJob.job_id);
        if (existing) {
          setMediaStudioJob(existing);
          return;
        }
        updateAutopilot({ message: "Starting visual reference generation." });
        setMediaStudioJob(await createMediaStudioJob(productionBriefJob.job_id));
        return;
      }

      if (shouldPollMediaJob(mediaStudioJob)) {
        updateAutopilot({ message: mediaStudioJob.message || "Generating visual assets." });
        return;
      }

      if (mediaStudioJob.stage === "FAILED") {
        const key = `media:${currentRecommendationId}`;
        const attempts = autopilot.attempts[key] ?? 0;
        if (attempts < AUTOPILOT_MAX_RETRIES) {
          recordAutopilotAttempt(key, `Media generation paused. Retrying the failed visual step automatically (${attempts + 1}/${AUTOPILOT_MAX_RETRIES}).`);
          if (mediaStudioJob.result?.reference_approved) {
            setMediaStudioJob(await approveMediaReference(mediaStudioJob.job_id, "Autopilot retry after interrupted keyframe generation."));
          } else {
            setMediaStudioJob(await regenerateMediaReference(mediaStudioJob.job_id, "Autopilot retry after reference generation failure."));
          }
          return;
        }
        setAutopilotAttention("FAILURE", mediaStudioJob.error || "Media generation failed repeatedly and needs review.");
        return;
      }

      if (mediaStudioJob.result?.reference_asset && !referenceAiPassed(mediaStudioJob)
        && !["QUEUED", "GENERATING_REFERENCE"].includes(mediaStudioJob.stage)) {
        if (aiReviewExhausted(mediaStudioJob)) {
          setAutopilotAttention("FAILURE", "The AI visual reviewer could not clear the canonical reference after automatic regeneration attempts. The production is paused as an exception; no intermediate human approval was requested.");
          return;
        }
        updateAutopilot({ message: "AI visual reviewer is checking the canonical character reference against the locked identity and historical channel evidence." });
        setMediaStudioJob(await aiReviewMediaReference(mediaStudioJob.job_id));
        return;
      }

      if (mediaStudioJob.stage === "AWAITING_REFERENCE_APPROVAL") {
        if (aiReviewExhausted(mediaStudioJob)) {
          setAutopilotAttention("FAILURE", "The AI visual reviewer could not clear the canonical reference after automatic regeneration attempts. The production is paused as an exception; no intermediate human approval was requested.");
          return;
        }
        updateAutopilot({ message: "AI visual reviewer is checking the canonical character reference against the locked Production Identity." });
        setMediaStudioJob(await aiReviewMediaReference(mediaStudioJob.job_id));
        return;
      }

      if (mediaStudioJob.result?.keyframes.length && !hasActiveShotOperation(mediaStudioJob)) {
        const keyframeActors = detailRecord(mediaStudioJob.detail).keyframe_approval_actor as Record<string, unknown> | undefined;
        const missingFidelityAnywhere = mediaStudioJob.result.keyframes.find((asset) => !asset.fidelity_report);
        if (missingFidelityAnywhere) {
          updateAutopilot({ message: "Running Gemini storyboard-fidelity review for the generated keyframes." });
          setMediaStudioJob(await reviewMediaKeyframes(mediaStudioJob.job_id));
          return;
        }
        const inheritedAdaptation = mediaStudioJob.result.keyframes.find((asset) =>
          asset.fidelity_report?.status === "ADAPTATION_ACCEPTED" && asset.fidelity_report?.creator_override
        );
        if (inheritedAdaptation?.shot_number) {
          await recoverKeyframeMismatch(inheritedAdaptation.shot_number, inheritedAdaptation.generation_attempt, true);
          return;
        }
        const reviewMismatch = mediaStudioJob.result.keyframes.find((asset) => asset.fidelity_report?.status === "REVIEW_REQUIRED");
        if (reviewMismatch?.shot_number) {
          await recoverKeyframeMismatch(reviewMismatch.shot_number, reviewMismatch.generation_attempt);
          return;
        }
        const needsAiOwnership = mediaStudioJob.result.keyframes.find((asset) =>
          asset.shot_number
          && asset.fidelity_report?.status === "PASS"
          && String(keyframeActors?.[String(asset.shot_number)] || "") !== "AI"
        );
        if (needsAiOwnership?.shot_number) {
          updateAutopilot({ message: `AI storyboard-fidelity review passed shot ${needsAiOwnership.shot_number}. Recording the AI approval and preserving the rest of the production.` });
          setMediaStudioJob(await aiApproveMediaKeyframe(mediaStudioJob.job_id, needsAiOwnership.shot_number));
          return;
        }
      }

      if (mediaStudioJob.stage === "AWAITING_KEYFRAME_REVIEW") {
        if (!mediaStudioJob.result) {
          setAutopilotAttention("FAILURE", "Media Studio returned no keyframe result.");
          return;
        }
        if (hasActiveShotOperation(mediaStudioJob)) return;

        const missingFidelity = mediaStudioJob.result.keyframes.some((asset) => !asset.fidelity_report);
        if (missingFidelity) {
          updateAutopilot({ message: "Running Gemini storyboard-fidelity review for the generated keyframes." });
          setMediaStudioJob(await reviewMediaKeyframes(mediaStudioJob.job_id));
          return;
        }

        const needsCorrection = mediaStudioJob.result.keyframes.find((asset) => asset.fidelity_report?.status === "REVIEW_REQUIRED");
        if (needsCorrection?.shot_number) {
          await recoverKeyframeMismatch(needsCorrection.shot_number, needsCorrection.generation_attempt);
          return;
        }

        const approvable = mediaStudioJob.result.keyframes.find((asset) =>
          asset.review_status !== "APPROVED"
          && ["PASS", "ADAPTATION_ACCEPTED"].includes(asset.fidelity_report?.status || "")
        );
        if (approvable?.shot_number) {
          updateAutopilot({ message: `AI visual review passed shot ${approvable.shot_number}. Locking it and preserving the rest of the storyboard.` });
          setMediaStudioJob(await aiApproveMediaKeyframe(mediaStudioJob.job_id, approvable.shot_number));
          return;
        }
      }

      if (mediaStudioJob.stage === "READY_FOR_ANIMATION" && mediaStudioJob.result?.animation_ready) {
        updateAutopilot({ message: "All keyframes are fidelity-cleared. Starting Veo animation." });
        setMediaStudioJob(await startMediaAnimation(mediaStudioJob.job_id));
        return;
      }

      if (mediaStudioJob.stage === "AWAITING_CLIP_REVIEW") {
        if (!mediaStudioJob.result) {
          setAutopilotAttention("FAILURE", "Media Studio returned no clip result.");
          return;
        }
        if (hasActiveClipOperation(mediaStudioJob)) return;
        const failedOperation = Object.values(mediaStudioJob.result.clip_operations ?? {}).find((operation) => operation.status === "FAILED");
        if (failedOperation) {
          if (failedOperation.target_generation_attempt < AUTOPILOT_MAX_GENERATION_ATTEMPTS) {
            updateAutopilot({ message: `Animated shot ${failedOperation.shot_number} failed. Retrying only that shot automatically.` });
            setMediaStudioJob(await regenerateMediaClip(mediaStudioJob.job_id, failedOperation.shot_number, "Autopilot retry for failed Veo shot."));
            return;
          }
          updateAutopilot({ message: `Animated shot ${failedOperation.shot_number} exhausted Veo generation. ReviveAI is switching to a controlled-motion fallback so production can continue.` });
          setMediaStudioJob(await aiCreateControlledMotionFallback(mediaStudioJob.job_id, failedOperation.shot_number));
          return;
        }

        const unapprovedClips = mediaStudioJob.result.video_clips.filter((clip) => clip.review_status !== "APPROVED");
        if (unapprovedClips.length > 0) {
          const nextClip = unapprovedClips[0];
          const exhausted = (detailRecord(mediaStudioJob.detail).ai_review_exhausted_clips as unknown[] | undefined) ?? [];
          if (exhausted.map(Number).includes(nextClip.shot_number)) {
            updateAutopilot({ message: `Animated shot ${nextClip.shot_number} exhausted AI motion review. ReviveAI is replacing it with a controlled-motion fallback and continuing automatically.` });
            setMediaStudioJob(await aiCreateControlledMotionFallback(mediaStudioJob.job_id, nextClip.shot_number));
            return;
          }
          updateAutopilot({ message: `AI video reviewer is checking animated shot ${nextClip.shot_number} against its keyframe and storyboard.` });
          setMediaStudioJob(await aiReviewMediaClip(mediaStudioJob.job_id, nextClip.shot_number));
          return;
        }
      }

      if (mediaStudioJob.stage === "READY_FOR_ASSEMBLY" && mediaStudioJob.result?.assembly_ready) {
        const mediaDetail = detailRecord(mediaStudioJob.detail);
        const clipActors = detailRecord(mediaDetail.clip_approval_actor);
        const clipReviews = detailRecord(mediaDetail.ai_clip_reviews);
        const clipNeedingAiReview = mediaStudioJob.result.video_clips.find((clip) =>
          String(clipActors[String(clip.shot_number)] || "").toUpperCase() !== "AI"
          || !aiDecisionPassed(clipReviews[String(clip.shot_number)])
        );
        if (clipNeedingAiReview) {
          updateAutopilot({ message: `AI video reviewer is validating adopted animated shot ${clipNeedingAiReview.shot_number} before assembly.` });
          setMediaStudioJob(await aiReviewMediaClip(mediaStudioJob.job_id, clipNeedingAiReview.shot_number));
          return;
        }
        if (finalAssemblyJob && finalAssemblyJob.media_job_id === mediaStudioJob.job_id && !assemblyMatchesCurrentMedia(finalAssemblyJob, mediaStudioJob)) {
          updateAutopilot({ message: "Visual source clips changed after AI review. Rebuilding the final visual master from the current approved clips." });
          setFinalAssemblyJob(await createFinalAssemblyJob(mediaStudioJob.job_id));
          return;
        }
        if (!finalAssemblyJob || finalAssemblyJob.media_job_id !== mediaStudioJob.job_id) {
          if (assemblyResumePending) return;
          const existing = await getLatestFinalAssemblyJob(mediaStudioJob.job_id);
          if (existing && assemblyMatchesCurrentMedia(existing, mediaStudioJob)) {
            setFinalAssemblyJob(existing);
            return;
          }
          updateAutopilot({ message: existing ? "Existing visual master used older clip assets. Rebuilding it from the current AI-reviewed clips." : "All animated shots passed AI review. Building the visual master." });
          setFinalAssemblyJob(await createFinalAssemblyJob(mediaStudioJob.job_id));
          return;
        }
      }

      if (!finalAssemblyJob) return;
      if (ASSEMBLY_POLLING_STAGES.has(finalAssemblyJob.stage)) {
        updateAutopilot({ message: finalAssemblyJob.message || "Rendering the visual master." });
        return;
      }
      if (finalAssemblyJob.stage === "FAILED") {
        setAutopilotAttention("FAILURE", finalAssemblyJob.error || "Final assembly failed and requires review before another render is started.");
        return;
      }
      if (finalAssemblyJob.stage === "DELIVERED" && finalAssemblyJob.result?.review_status === "APPROVED" && !visualMasterAiPassed(finalAssemblyJob, mediaStudioJob)) {
        updateAutopilot({ message: "AI visual reviewer is re-checking the existing visual master before Autopilot adopts it." });
        setFinalAssemblyJob(await aiReviewFinalAssembly(finalAssemblyJob.job_id));
        return;
      }
      if (finalAssemblyJob.stage === "COMPLETED") {
        updateAutopilot({ message: aiReviewExhausted(finalAssemblyJob)
          ? "Visual-master retries were exhausted. ReviveAI is applying the best-render fallback and continuing to deterministic QC."
          : "AI visual reviewer is checking the assembled master for sequence, captions, and render integrity." });
        setFinalAssemblyJob(await aiReviewFinalAssembly(finalAssemblyJob.job_id));
        return;
      }
      if (!(finalAssemblyJob.stage === "DELIVERED" && finalAssemblyJob.result?.review_status === "APPROVED")) return;

      if (!audioFinishingJob || audioFinishingJob.assembly_job_id !== finalAssemblyJob.job_id) {
        if (audioResumePending) return;
        const versions = await getAudioFinishingJobs(finalAssemblyJob.job_id);
        if (versions.length > 0) {
          setAudioVersionHistory(versions);
          setAudioFinishingJob(versions[0]);
          return;
        }
        updateAutopilot({ message: "Visual master passed AI review. Creating voice, music, ambience, and the final audio mix." });
        const next = await createAudioFinishingJob(finalAssemblyJob.job_id, AUTOPILOT_AUDIO_DEFAULTS);
        setAudioFinishingJob(next);
        setAudioVersionHistory((current) => [next, ...current.filter((item) => item.job_id !== next.job_id)]);
        return;
      }

      if (AUDIO_POLLING_STAGES.has(audioFinishingJob.stage)) {
        updateAutopilot({ message: audioFinishingJob.message || "Rendering the audio master." });
        return;
      }
      if (audioFinishingJob.stage === "FAILED") {
        setAutopilotAttention("FAILURE", audioFinishingJob.error || "Audio finishing failed. The production is paused as an exception; no intermediate approval is requested.");
        return;
      }
      if (audioFinishingJob.stage === "DELIVERED" && audioFinishingJob.result?.review_status === "APPROVED" && !audioMasterAiPassed(audioFinishingJob, finalAssemblyJob)) {
        updateAutopilot({ message: "AI audio reviewer is listening to the existing audio master before Autopilot adopts it." });
        const reviewed = await aiReviewAudioFinishing(audioFinishingJob.job_id);
        setAudioFinishingJob(reviewed);
        setAudioVersionHistory((current) => [reviewed, ...current.filter((item) => item.job_id !== reviewed.job_id)]
          .sort((a, b) => b.version_number - a.version_number || b.updated_at.localeCompare(a.updated_at)));
        return;
      }
      if (audioFinishingJob.stage === "COMPLETED") {
        updateAutopilot({ message: aiReviewExhausted(audioFinishingJob)
          ? "Audio remix attempts were exhausted. ReviveAI is keeping the best available mix and continuing to deterministic delivery QC."
          : "AI audio reviewer is listening to narration, music, ambience, and mix balance." });
        const reviewed = await aiReviewAudioFinishing(audioFinishingJob.job_id);
        setAudioFinishingJob(reviewed);
        setAudioVersionHistory((current) => [reviewed, ...current.filter((item) => item.job_id !== reviewed.job_id)]
          .sort((a, b) => b.version_number - a.version_number || b.updated_at.localeCompare(a.updated_at)));
        return;
      }

      const approvedMaster = [audioFinishingJob, ...audioVersionHistory]
        .filter((item): item is AudioFinishingJob => Boolean(item))
        .filter((item) => audioMasterAiPassed(item, finalAssemblyJob))
        .sort((a, b) => b.version_number - a.version_number || b.updated_at.localeCompare(a.updated_at))[0] ?? null;
      if (!approvedMaster) return;

      if (!deliveryQcReport || deliveryQcReport.audio_job_id !== approvedMaster.job_id) {
        if (deliveryQcPending || deliveryQcResumePending) return;
        updateAutopilot({ message: "Running deterministic final delivery QC." });
        setDeliveryQcPending(true);
        try {
          setDeliveryQcReport(await runDeliveryQc(approvedMaster.job_id));
        } finally {
          setDeliveryQcPending(false);
        }
        return;
      }

      if (deliveryQcReport.overall_status === "BLOCKED") {
        setAutopilotAttention("FAILURE", "Deterministic Final Delivery QC found a blocking technical failure. AI is not allowed to override hard delivery failures.");
        return;
      }
      if (deliveryQcReport.overall_status === "REVIEW") {
        updateAutopilot({ message: "AI reviewer is evaluating non-blocking delivery-QC warnings." });
        setDeliveryQcReport(await aiReviewDeliveryQc(approvedMaster.job_id));
        return;
      }

      if (!deliveryPackage || deliveryPackage.qc_report_id !== deliveryQcReport.report_id) {
        if (deliveryPackagePending || deliveryPackageResumePending) return;
        updateAutopilot({ message: "QC passed. Creating the versioned delivery package." });
        setDeliveryPackagePending(true);
        try {
          const next = await createDeliveryPackage(approvedMaster.job_id);
          setDeliveryPackage(next);
          setDeliveryPackageHistory((current) => [next, ...current.filter((item) => item.package_id !== next.package_id)].sort((a, b) => b.package_version - a.package_version));
        } finally {
          setDeliveryPackagePending(false);
        }
        return;
      }

      if (!publishingDraft) {
        if (publishingResumePending || publishingAction) return;
        updateAutopilot({ message: "Delivery package is ready. Generating creator-editable publishing copy." });
        setPublishingAction("GENERATE");
        try {
          const next = await createPublishingDraft(approvedMaster.job_id);
          rememberPublishingDraft(next);
        } finally {
          setPublishingAction(null);
        }
        return;
      }

      const publishingAiApproved = publishingDraft.status === "APPROVED" && (publishingDraft.generation_note || "").includes("[AI_REVIEW_APPROVED]");
      if (!publishingAiApproved) {
        if (publishingAction) return;
        updateAutopilot({ message: "AI publishing critic is checking titles, captions, hashtags, accessibility text, and factual consistency." });
        setPublishingAction("REGENERATE");
        try {
          const next = await aiReviewPublishingDraft(publishingDraft.draft_id);
          rememberPublishingDraft(next);
        } finally {
          setPublishingAction(null);
        }
        return;
      }

      if (deliveryPackage.publishing_draft_id !== publishingDraft.draft_id) {
        if (publishingAction) return;
        updateAutopilot({ message: "Publishing copy passed the AI critic. Adding it to the final delivery package." });
        setPublishingAction("PACKAGE");
        try {
          const next = await addPublishingDraftToDeliveryPackage(publishingDraft.draft_id);
          setDeliveryPackage(next);
          setDeliveryPackageHistory((current) => [next, ...current.filter((item) => item.package_id !== next.package_id)].sort((a, b) => b.package_version - a.package_version));
        } finally {
          setPublishingAction(null);
        }
        return;
      }

      if (!humanFinalApproved(approvedMaster)) {
        const handoff = summarizeAiReviewGates({
          productionJob: productionBriefJob,
          mediaJob: mediaStudioJob,
          assemblyJob: finalAssemblyJob,
          audioJob: approvedMaster,
          qc: deliveryQcReport,
          deliveryPackage,
          publishingDraft,
        });
        if (!handoff.allPassed) {
          const reason = handoff.blockingReason
            || `Final handoff verification found an incomplete ${aiGateLabel(handoff.firstIncomplete)} gate.`;
          setAutopilotAttention("FAILURE", `${reason} ReviveAI will not expose the final approval until every required AI review is verified.`);
          return;
        }
        updateAutopilot({
          status: "WAITING_FOR_FINAL_APPROVAL",
          attentionStage: "FINAL_VIDEO",
          message: "Production complete. Every required AI review gate passed. Watch the finished picture + sound and approve the final video.",
        });
        window.setTimeout(() => document.getElementById("final-human-review")?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
        return;
      }

      setAutopilot((current) => {
        const completedRecommendationIds = current.currentRecommendationId
          ? Array.from(new Set([...current.completedRecommendationIds, current.currentRecommendationId]))
          : current.completedRecommendationIds;
        const blockedProductions = current.currentRecommendationId
          ? current.blockedProductions.filter((item) => item.recommendationId !== current.currentRecommendationId)
          : current.blockedProductions;
        if (current.scope === "PRODUCTION") {
          return {
            ...current,
            status: "COMPLETED",
            attentionStage: null,
            completedRecommendationIds,
            blockedProductions,
            message: "Individual production complete. AI Autopilot finished this video and will not start another production.",
            updatedAt: new Date().toISOString(),
          };
        }
        return {
          ...current,
          status: "RUNNING",
          attentionStage: null,
          currentRecommendationId: null,
          currentTitle: null,
          currentStartedAt: null,
          completedRecommendationIds,
          blockedProductions,
          message: "Production complete. Moving to the next revival idea.",
          updatedAt: new Date().toISOString(),
        };
      });
    } catch (error) {
      setAutopilotAttention("FAILURE", error instanceof Error ? error.message : "Autopilot hit an unexpected error and paused safely.");
    } finally {
      autopilotActionRef.current = false;
    }
  }

  const result = job?.stage === "COMPLETED" ? job.result : null;
  const dnaReady = dnaJob?.stage === "COMPLETED" && Boolean(dnaJob.result);
  const recoveryReady = recoveryJob?.stage === "COMPLETED" && Boolean(recoveryJob.result);
  const productionReady = productionBriefJob?.stage === "COMPLETED" && Boolean(productionBriefJob.result);
  const productionApproved = productionReady && productionBriefJob?.result?.review_status === "APPROVED";
  const mediaReady = mediaStudioJob?.stage === "READY_FOR_ANIMATION" && Boolean(mediaStudioJob.result?.animation_ready);
  const assemblyReady = mediaStudioJob?.stage === "READY_FOR_ASSEMBLY" && Boolean(mediaStudioJob.result?.assembly_ready);
  const finalAssemblyReady = finalAssemblyJob?.stage === "COMPLETED" && Boolean(finalAssemblyJob.result);
  const finalAssemblyApproved = finalAssemblyJob?.stage === "DELIVERED" && finalAssemblyJob.result?.review_status === "APPROVED";
  const audioFinishingReady = audioFinishingJob?.stage === "COMPLETED" && Boolean(audioFinishingJob.result);
  const deliveryMasterApproved = Boolean(approvedAudioMaster);
  const deliveryQcReady = Boolean(deliveryQcReport && (deliveryQcReport.overall_status === "READY" || (deliveryQcReport.overall_status === "REVIEW" && deliveryQcReport.human_acknowledgment)));
  const deliveryQcReview = deliveryQcReport?.overall_status === "REVIEW";
  const deliveryQcBlocked = deliveryQcReport?.overall_status === "BLOCKED";
  const deliveryPackageReady = Boolean(deliveryPackage);
  const publishingPackaged = Boolean(deliveryPackage?.publishing_draft_id);
  const finalVideoHumanApproved = humanFinalApproved(approvedAudioMaster);
  const aiGateSummary = summarizeAiReviewGates({
    productionJob: productionBriefJob,
    mediaJob: mediaStudioJob,
    assemblyJob: finalAssemblyJob,
    audioJob: approvedAudioMaster,
    qc: deliveryQcReport,
    deliveryPackage,
    publishingDraft,
  });
  const aiGateSignature = [
    ...Object.entries(aiGateSummary.gates).map(([key, value]) => `${key}:${value ? 1 : 0}`),
    `blocked:${aiGateSummary.blockingReason || ""}`,
  ].join("|");
  const finalVideoReadyForHumanReview = Boolean(approvedAudioMaster && aiGateSummary.allPassed);
  const autopilotOwnsCurrentProduction = Boolean(
    productionBriefJob
    && autopilot.currentRecommendationId === productionBriefJob.recommendation_id
    && !["IDLE", "COMPLETED"].includes(autopilot.status)
  );
  const finalApprovalMode = Boolean(
    autopilotOwnsCurrentProduction
    && autopilot.status === "WAITING_FOR_FINAL_APPROVAL"
    && autopilot.attentionStage === "FINAL_VIDEO"
    && finalVideoReadyForHumanReview
    && !finalVideoHumanApproved
  );

  // v2.3 final-handoff reconciliation. A persisted WAITING state is valid only
  // when every required AI gate is independently verifiable against current assets.
  // Stale v2.1/v2.2 sessions are automatically resumed or moved to a real exception.
  useEffect(() => {
    if (autopilot.executionOwner === "BACKEND") return;
    if (!autopilotOwnsCurrentProduction || finalVideoHumanApproved) return;

    if (aiGateSummary.allPassed) {
      if (autopilot.status === "WAITING_FOR_FINAL_APPROVAL" && autopilot.attentionStage === "FINAL_VIDEO") return;
      if (autopilot.status === "RUNNING" || (autopilot.status === "NEEDS_ATTENTION" && autopilot.attentionStage === "FINAL_VIDEO")) {
        updateAutopilot({
          status: "WAITING_FOR_FINAL_APPROVAL",
          attentionStage: "FINAL_VIDEO",
          message: "Production complete. Every required AI review gate passed. Your final video is waiting for approval.",
        });
      }
      return;
    }

    const staleFinalHandoff = autopilot.status === "WAITING_FOR_FINAL_APPROVAL"
      || (autopilot.status === "NEEDS_ATTENTION" && autopilot.attentionStage === "FINAL_VIDEO");
    if (!staleFinalHandoff) return;

    if (aiGateSummary.blockingReason) {
      updateAutopilot({
        status: "NEEDS_ATTENTION",
        attentionStage: "FAILURE",
        message: `${aiGateSummary.blockingReason} Final approval stays locked until the failed AI gate is corrected.`,
      });
      return;
    }

    updateAutopilot({
      status: "RUNNING",
      attentionStage: null,
      message: `Final handoff verification found incomplete ${aiGateLabel(aiGateSummary.firstIncomplete)}. Autopilot resumed from that AI gate instead of asking for premature final approval.`,
    });
  }, [
    autopilotOwnsCurrentProduction,
    finalVideoHumanApproved,
    autopilot.status,
    autopilot.attentionStage,
    aiGateSignature,
    productionBriefJob?.recommendation_id,
  ]);

  // v2.5 migrates creative visual exceptions into autonomous recovery. Existing
  // v2.4 sessions that stopped after 3-5 failed shot attempts resume once without
  // requiring another user click. Hard technical exceptions remain fail-closed.
  useEffect(() => {
    if (autopilot.executionOwner === "BACKEND") return;
    if (!autopilotOwnsCurrentProduction || autopilot.status !== "NEEDS_ATTENTION" || autopilot.attentionStage !== "FAILURE") return;
    if (!mediaStudioJob?.result || autopilotRecoveryPending) return;

    const failedKeyframe = mediaStudioJob.result.keyframes.find((asset) =>
      asset.fidelity_report?.status === "REVIEW_REQUIRED"
      || (asset.fidelity_report?.status === "ADAPTATION_ACCEPTED" && asset.fidelity_report?.creator_override)
    );
    if (failedKeyframe?.shot_number) {
      const resumeKey = `v2.5-auto-resume:keyframe:${failedKeyframe.shot_number}:${failedKeyframe.generation_attempt}`;
      if ((autopilot.attempts[resumeKey] ?? 0) > 0) return;
      setAutopilot((current) => ({
        ...current,
        status: "RUNNING",
        attentionStage: null,
        attempts: { ...current.attempts, [resumeKey]: 1 },
        message: `Autonomous recovery resumed shot ${failedKeyframe.shot_number}. ReviveAI will replan or salvage this shot and continue without intermediate approval.`,
        updatedAt: new Date().toISOString(),
      }));
      return;
    }

    const exhaustedClips = ((detailRecord(mediaStudioJob.detail).ai_review_exhausted_clips as unknown[] | undefined) ?? []).map(Number);
    const shot = exhaustedClips.find((value) => Number.isFinite(value));
    if (shot) {
      const resumeKey = `v2.5-auto-resume:clip:${shot}`;
      if ((autopilot.attempts[resumeKey] ?? 0) > 0) return;
      setAutopilot((current) => ({
        ...current,
        status: "RUNNING",
        attentionStage: null,
        attempts: { ...current.attempts, [resumeKey]: 1 },
        message: `Autonomous recovery resumed animated shot ${shot}. ReviveAI will use a controlled-motion fallback if Veo cannot clear the AI motion gate.`,
        updatedAt: new Date().toISOString(),
      }));
    }
  }, [
    autopilotOwnsCurrentProduction,
    autopilot.status,
    autopilot.attentionStage,
    JSON.stringify(autopilot.attempts),
    autopilotRecoveryPending,
    mediaStudioJob?.job_id,
    mediaStudioJob?.stage,
    JSON.stringify(mediaStudioJob?.result?.keyframes.map((asset) => [asset.shot_number, asset.generation_attempt, asset.fidelity_report?.status, asset.fidelity_report?.creator_override]) ?? []),
    JSON.stringify(detailRecord(mediaStudioJob?.detail).ai_review_exhausted_clips ?? []),
  ]);

  // v2.6 stale-job watchdog. This runs independently of the normal Autopilot
  // action lock so it can recover a request that never resolved in the browser.
  useEffect(() => {
    if (autopilot.executionOwner === "BACKEND") return;
    if (autopilot.status !== "RUNNING" || !autopilotOwnsCurrentProduction) return;
    const check = () => {
      const latest = latestAutopilotBackendCheckpoint({
        productionJob: productionBriefJob,
        mediaJob: mediaStudioJob,
        assemblyJob: finalAssemblyJob,
        audioJob: audioFinishingJob || approvedAudioMaster,
        qc: deliveryQcReport,
        deliveryPackage,
        publishingDraft,
      });
      if (latest != null && Date.now() - latest >= AUTOPILOT_STALE_CHECKPOINT_MS) {
        void reconcileStaleAutopilotCheckpoint();
      }
    };
    check();
    const timer = window.setInterval(check, 30_000);
    return () => window.clearInterval(timer);
  }, [
    autopilot.status,
    autopilotOwnsCurrentProduction,
    autopilotWatchdog.lastRunAt,
    productionBriefJob?.job_id,
    productionBriefJob?.updated_at,
    mediaStudioJob?.job_id,
    mediaStudioJob?.updated_at,
    finalAssemblyJob?.job_id,
    finalAssemblyJob?.updated_at,
    audioFinishingJob?.job_id,
    audioFinishingJob?.updated_at,
    approvedAudioMaster?.job_id,
    approvedAudioMaster?.updated_at,
    deliveryQcReport?.report_id,
    deliveryQcReport?.generated_at,
    deliveryPackage?.package_id,
    deliveryPackage?.generated_at,
    publishingDraft?.draft_id,
    publishingDraft?.updated_at,
  ]);

  useEffect(() => {
    // v3.1: backend-owned Autopilot is advanced by the Cloud Run supervisor. Keep
    // the legacy browser driver only for explicitly FRONTEND-owned sessions.
    if (autopilot.executionOwner === "BACKEND") return;
    if (autopilot.status !== "RUNNING") return;
    void driveAutopilot();
  }, [
    autopilot.status,
    autopilot.executionOwner,
    autopilot.currentRecommendationId,
    autopilot.programId,
    autopilot.recoveryJobId,
    autopilot.completedRecommendationIds.join("|"),
    JSON.stringify(autopilot.attempts),
    revivalProgram?.program_id,
    recoveryJob?.job_id,
    recoveryJob?.stage,
    productionHistory.map((entry) => `${entry.job_id}:${entry.updated_at}`).join("|"),
    productionBriefJob?.job_id,
    productionBriefJob?.stage,
    productionBriefJob?.result?.review_status,
    productionBriefJob?.result?.direction_fidelity.status,
    productionBriefJob?.result?.consistency_report.status,
    JSON.stringify(productionBriefJob?.detail ?? {}),
    mediaStudioJob?.job_id,
    mediaStudioJob?.stage,
    JSON.stringify(mediaStudioJob?.result?.shot_operations ?? {}),
    JSON.stringify(mediaStudioJob?.result?.clip_operations ?? {}),
    mediaStudioJob?.result?.approved_keyframes,
    mediaStudioJob?.result?.approved_clips,
    finalAssemblyJob?.job_id,
    finalAssemblyJob?.stage,
    finalAssemblyJob?.result?.review_status,
    JSON.stringify(finalAssemblyJob?.detail ?? {}),
    audioFinishingJob?.job_id,
    audioFinishingJob?.stage,
    audioFinishingJob?.result?.review_status,
    JSON.stringify(audioFinishingJob?.detail ?? {}),
    approvedAudioMaster?.job_id,
    deliveryQcReport?.report_id,
    deliveryQcReport?.overall_status,
    deliveryPackage?.package_id,
    deliveryPackage?.publishing_draft_id,
    publishingDraft?.draft_id,
    publishingDraft?.status,
    publishingDraft?.generation_note,
    mediaResumePending,
    assemblyResumePending,
    audioResumePending,
    deliveryQcPending,
    deliveryQcResumePending,
    deliveryPackagePending,
    deliveryPackageResumePending,
    publishingResumePending,
    publishingAction,
  ]);

  useEffect(() => {
    if (autopilot.executionOwner === "BACKEND") return;
    if (autopilot.status !== "NEEDS_ATTENTION") return;
    const resume = (message: string) => updateAutopilot({ status: "RUNNING", attentionStage: null, message });
    switch (autopilot.attentionStage) {
      case "PRODUCTION_DIRECTION":
        if (productionBriefJob?.result
          && productionBriefJob.result.direction_fidelity.status !== "REVIEW_REQUIRED"
          && productionBriefJob.result.consistency_report.status === "PASS") {
          resume("Direction decision recorded. Autopilot is continuing.");
        }
        break;
      case "REFERENCE":
        if (mediaStudioJob?.result?.reference_approved && mediaStudioJob.stage !== "AWAITING_REFERENCE_APPROVAL") {
          resume("Reference approved. Autopilot is continuing with storyboard keyframes.");
        }
        break;
      case "KEYFRAME_ADAPTATION":
        if (mediaStudioJob?.result
          && !hasActiveShotOperation(mediaStudioJob)
          && !mediaStudioJob.result.keyframes.some((asset) => asset.fidelity_report?.status === "REVIEW_REQUIRED")) {
          resume("Keyframe decision recorded. Autopilot is continuing.");
        }
        break;
      case "CLIPS":
        if (mediaStudioJob?.result?.assembly_ready || mediaStudioJob?.stage === "READY_FOR_ASSEMBLY") {
          resume("Animated clips approved. Autopilot is continuing to final assembly.");
        }
        break;
      case "VISUAL_MASTER":
        if (finalAssemblyJob?.stage === "DELIVERED" && finalAssemblyJob.result?.review_status === "APPROVED") {
          resume("Visual master approved. Autopilot is continuing to audio finishing.");
        }
        break;
      case "AUDIO_MASTER":
        if (approvedAudioMaster) resume("Audio master approved. Autopilot is continuing to final delivery QC.");
        break;
      case "DELIVERY_QC":
        if (Boolean(deliveryQcReport && (deliveryQcReport.overall_status === "READY" || (deliveryQcReport.overall_status === "REVIEW" && deliveryQcReport.human_acknowledgment)))) resume("Delivery QC is ready. Autopilot is continuing to packaging.");
        break;
      case "PUBLISHING_COPY":
        if (publishingDraft?.status === "APPROVED") resume("Publishing copy approved. Autopilot is finalizing the delivery package.");
        break;
      default:
        break;
    }
  }, [
    autopilot.status,
    autopilot.attentionStage,
    productionBriefJob?.job_id,
    productionBriefJob?.stage,
    productionBriefJob?.result?.direction_fidelity.status,
    productionBriefJob?.result?.consistency_report.status,
    mediaStudioJob?.job_id,
    mediaStudioJob?.stage,
    mediaStudioJob?.result?.reference_approved,
    mediaStudioJob?.result?.assembly_ready,
    JSON.stringify(mediaStudioJob?.result?.shot_operations ?? {}),
    JSON.stringify(mediaStudioJob?.result?.keyframes.map((asset) => [asset.asset_id, asset.review_status, asset.fidelity_report?.status]) ?? []),
    finalAssemblyJob?.stage,
    finalAssemblyJob?.result?.review_status,
    approvedAudioMaster?.job_id,
    deliveryQcReport?.overall_status,
    publishingDraft?.status,
  ]);

  const workspaceProductionStage: WorkspaceProductionStage = publishingPackaged || deliveryPackageReady
    ? "PUBLISHING"
    : deliveryQcReady
      ? "DELIVERY"
      : deliveryMasterApproved
        ? "QC"
        : finalAssemblyApproved
          ? "AUDIO"
          : finalAssemblyReady || assemblyReady
            ? "VISUAL_MASTER"
            : mediaStudioJob
              ? "VISUALS"
              : "BRIEF";
  const workspaceStageLabel = finalVideoHumanApproved
    ? "Final video approved"
    : finalVideoReadyForHumanReview
      ? "Final video ready for your approval"
      : publishingPackaged
    ? "Publishing package ready"
    : publishingDraft?.status === "APPROVED"
      ? "Publishing copy approved"
      : deliveryPackageReady
        ? "Publishing assistant"
        : deliveryQcReady
          ? "Delivery package"
          : deliveryQcBlocked
            ? "Final QC blocked"
            : deliveryQcReview
              ? "Final QC review"
              : deliveryMasterApproved
                ? "Final delivery QC"
                : audioFinishingReady
                  ? "Audio master review"
                  : finalAssemblyApproved
                    ? "Audio finishing"
                    : finalAssemblyReady
                      ? "Visual master review"
                      : assemblyReady
                        ? "Build visual master"
                        : mediaStudioJob
                          ? "Visual production"
                          : productionReady
                            ? "Production brief review"
                            : "Production brief";
  const workspaceMilestone = workspaceProductionStage === "PUBLISHING" ? "M2C.5"
    : workspaceProductionStage === "DELIVERY" ? "M2C.4"
      : workspaceProductionStage === "QC" ? "M2C.3"
        : workspaceProductionStage === "AUDIO" ? "M2C.2"
          : workspaceProductionStage === "VISUAL_MASTER" ? "M2C.1"
            : workspaceProductionStage === "VISUALS" ? "M2B"
              : "M2A";

  useEffect(() => {
    if (!result || !job?.job_id) return;
    const now = new Date().toISOString();
    const channel = result.channel;
    const checkpoint: CreatorWorkflowCheckpoint = {
      version: 1,
      url: url.trim() || channel.channel_url,
      analysisJobId: job.job_id,
      dnaJobId: dnaJob?.job_id,
      recoveryJobId: recoveryJob?.job_id,
      productionBriefJobId: productionBriefJob?.job_id,
      mediaStudioJobId: mediaStudioJob?.job_id,
      finalAssemblyJobId: finalAssemblyJob?.job_id,
      audioFinishingJobId: audioFinishingJob?.job_id,
    };

    setWorkspace((current) => {
      const existingChannel = current.channels.find((item) => item.channelId === channel.channel_id);
      const historicalProductions: WorkspaceProduction[] = productionHistory.map((entry) => ({
        id: entry.job_id,
        title: entry.working_title || entry.source_snapshot.recommendation.title || "Untitled production",
        stage: "BRIEF",
        stageLabel: entry.review_status === "APPROVED" ? "Production brief approved" : "Production brief review",
        status: entry.review_status === "APPROVED" ? "ACTIVE" : "REVIEW",
        milestone: "M2A",
        thumbnailUrl: existingChannel?.productions.find((item) => item.id === entry.job_id)?.thumbnailUrl || null,
        createdAt: entry.captured_at,
        updatedAt: entry.updated_at,
        checkpoint: {
          version: 1,
          url: url.trim() || channel.channel_url,
          analysisJobId: entry.analysis_job_id || job.job_id,
          dnaJobId: dnaJob?.job_id,
          recoveryJobId: entry.recovery_job_id,
          productionBriefJobId: entry.job_id,
        },
      }));

      let productions = mergeWorkspaceProductions(existingChannel?.productions ?? [], historicalProductions);

      if (productionBriefJob?.job_id) {
        const title = productionBriefJob.result?.creative_direction.working_title
          || productionBriefJob.source_snapshot.recommendation.title
          || "Untitled production";
        const status: WorkspaceProduction["status"] = deliveryQcBlocked || mediaStudioJob?.stage === "FAILED" || finalAssemblyJob?.stage === "FAILED" || audioFinishingJob?.stage === "FAILED"
          ? "BLOCKED"
          : publishingPackaged || deliveryPackageReady
            ? "READY"
            : productionReady && !productionApproved || finalAssemblyReady || audioFinishingReady || deliveryQcReview
              ? "REVIEW"
              : "ACTIVE";
        const existingProduction = productions.find((item) => item.id === productionBriefJob.job_id);
        const mediaThumbnail = mediaStudioJob?.result?.keyframes.find((asset) => asset.review_status === "APPROVED")?.asset_url
          || mediaStudioJob?.result?.keyframes[0]?.asset_url
          || mediaStudioJob?.result?.reference_asset?.asset_url
          || existingProduction?.thumbnailUrl
          || null;
        const production: WorkspaceProduction = {
          id: productionBriefJob.job_id,
          title,
          stage: workspaceProductionStage,
          stageLabel: workspaceStageLabel,
          status,
          milestone: workspaceMilestone,
          thumbnailUrl: mediaThumbnail,
          createdAt: existingProduction?.createdAt || productionBriefJob.created_at,
          updatedAt: productionBriefJob.updated_at > now ? productionBriefJob.updated_at : now,
          checkpoint,
        };
        productions = mergeWorkspaceProductions(productions, [production]);
      }

      const nextChannel: WorkspaceChannel = {
        channelId: channel.channel_id,
        title: channel.title,
        handle: channel.custom_url || null,
        thumbnailUrl: channel.thumbnails.high || channel.thumbnails.medium || channel.thumbnails.default || null,
        channelUrl: channel.channel_url,
        subscriberCount: channel.subscriber_count,
        publicVideoCount: channel.public_video_count_reported ?? result.summary.retrieved_videos,
        createdAt: existingChannel?.createdAt || now,
        updatedAt: now,
        lastOpenedAt: workspaceView === "workspace" ? existingChannel?.lastOpenedAt || now : now,
        analysisJobId: job.job_id,
        dnaJobId: dnaJob?.job_id || existingChannel?.dnaJobId,
        recoveryJobId: recoveryJob?.job_id || existingChannel?.recoveryJobId,
        productions,
      };

      return {
        ...current,
        channels: [nextChannel, ...current.channels.filter((item) => item.channelId !== channel.channel_id)],
        lastActiveChannelId: channel.channel_id,
        lastActiveProductionId: workspaceView === "production"
          ? (activeProductionId || current.lastActiveProductionId)
          : current.lastActiveProductionId,
      };
    });

    setActiveChannelId(channel.channel_id);
    if (productionBriefJob?.job_id) setActiveProductionId(productionBriefJob.job_id);
    if (workspaceView === "add-channel" && job.stage === "COMPLETED") {
      setChannelTab("overview");
      setWorkspaceView("channel");
    }
  }, [
    result?.channel.channel_id, result?.channel.title, job?.job_id, job?.stage, dnaJob?.job_id, recoveryJob?.job_id,
    productionBriefJob?.job_id, productionBriefJob?.stage, productionBriefJob?.updated_at, productionBriefJob?.result?.review_status,
    mediaStudioJob?.job_id, mediaStudioJob?.stage, mediaStudioJob?.updated_at, finalAssemblyJob?.job_id, finalAssemblyJob?.stage,
    audioFinishingJob?.job_id, audioFinishingJob?.stage, deliveryQcReport?.overall_status, deliveryPackage?.package_id,
    publishingDraft?.draft_id, publishingDraft?.status, productionHistory.length, workspaceProductionStage, workspaceStageLabel, workspaceMilestone,
  ]);

  const activeWorkspaceChannel = workspace.channels.find((item) => item.channelId === activeChannelId)
    ?? (result ? workspace.channels.find((item) => item.channelId === result.channel.channel_id) : undefined);
  const activeWorkspaceProduction = activeWorkspaceChannel?.productions.find((item) => item.id === activeProductionId)
    ?? (!activeProductionId && productionBriefJob ? activeWorkspaceChannel?.productions.find((item) => item.id === productionBriefJob.job_id) : undefined);

  // A saved production's identity comes from the selected production, never a
  // late-arriving publishing draft from another production. Keep the draft title
  // available only when its entire audio→assembly→media→brief chain matches.
  const selectedBriefMatches = Boolean(productionBriefJob && (
    !activeProductionId || productionBriefJob.job_id === activeProductionId
  ));
  const packagedPublishingTitle = selectedBriefMatches
    && publishingDraft && deliveryPackage && approvedAudioMaster && finalAssemblyJob && mediaStudioJob
    && deliveryPackage.publishing_draft_id === publishingDraft.draft_id
    && deliveryPackage.audio_job_id === publishingDraft.audio_job_id
    && approvedAudioMaster.job_id === publishingDraft.audio_job_id
    && approvedAudioMaster.assembly_job_id === finalAssemblyJob.job_id
    && finalAssemblyJob.media_job_id === mediaStudioJob.job_id
    && mediaStudioJob.production_brief_job_id === productionBriefJob?.job_id
    ? publishingDraft.content?.youtube?.title?.trim()
    : undefined;
  // A generated, saved brief has a concise working title. Prioritize it over
  // browser-cached production cards, which may contain a full creator prompt.
  const visibleProductionTitle = (selectedBriefMatches ? productionBriefJob?.result?.creative_direction.working_title?.trim() : undefined)
    || activeWorkspaceProduction?.title
    || (selectedBriefMatches ? productionBriefJob?.source_snapshot.recommendation.title : undefined)
    || packagedPublishingTitle
    || "Untitled production";

  // Production history is durable backend data and must remain available even when
  // an older channel-analysis snapshot has expired. Hydrate the saved production
  // library independently from `result` / `job`, using the channel's persisted
  // lineage only as a fallback for checkpoint fields.
  useEffect(() => {
    if (!activeChannelId || productionHistory.length === 0) return;

    setWorkspace((current) => {
      const channelIndex = current.channels.findIndex((item) => item.channelId === activeChannelId);
      if (channelIndex < 0) return current;

      const channel = current.channels[channelIndex];
      const historicalProductions: WorkspaceProduction[] = productionHistory.map((entry) => ({
        id: entry.job_id,
        title: entry.working_title || entry.source_snapshot.recommendation.title || "Untitled production",
        stage: "BRIEF",
        stageLabel: entry.review_status === "APPROVED" ? "Production brief approved" : "Production brief review",
        status: entry.review_status === "APPROVED" ? "ACTIVE" : "REVIEW",
        milestone: "M2A",
        thumbnailUrl: channel.productions.find((item) => item.id === entry.job_id)?.thumbnailUrl || null,
        createdAt: entry.captured_at,
        updatedAt: entry.updated_at,
        checkpoint: {
          version: 1,
          url: channel.channelUrl,
          analysisJobId: entry.analysis_job_id || channel.analysisJobId,
          dnaJobId: channel.dnaJobId,
          recoveryJobId: entry.recovery_job_id || channel.recoveryJobId,
          productionBriefJobId: entry.job_id,
        },
      }));

      const productions = mergeWorkspaceProductions(channel.productions, historicalProductions);
      if (JSON.stringify(productions) === JSON.stringify(channel.productions)) return current;

      const channels = [...current.channels];
      channels[channelIndex] = { ...channel, productions };
      return { ...current, channels };
    });
  }, [activeChannelId, productionHistory]);

  const activeWorkspaceProductionCount = activeWorkspaceChannel
    ? getUniqueWorkspaceProductions(activeWorkspaceChannel.productions).length
    : 0;

  // M2E.1.2: repair missing browser lineage from tenant-owned persisted intelligence.
  // We first discover the newest saved Recovery/DNA jobs for the current analysis,
  // then fall back to IDs referenced by saved productions. This avoids asking the
  // creator to rebuild intelligence merely because local workspace metadata is old.
  useEffect(() => {
    if (workspaceView !== "channel" || !activeWorkspaceChannel || !job?.job_id || job.stage !== "COMPLETED") return;
    if (recoveryReady && dnaReady) return;

    const activeWorkspaceChannelId = activeWorkspaceChannel.channelId;
    const activeWorkspaceRecoveryJobId = activeWorkspaceChannel.recoveryJobId;
    let cancelled = false;
    async function reconcileRevivalLineage() {
      setRevivalLineageCheckPending(true);
      try {
        const latestRecovery = await getLatestRecoveryJobForAnalysis(job!.job_id).catch(() => null);
        if (cancelled) return;
        if (latestRecovery) {
          setRecoveryJob(latestRecovery);
          const recoveredDna = await getContentDnaJob(latestRecovery.content_dna_job_id).catch(() => null);
          if (cancelled) return;
          if (recoveredDna) setDnaJob(recoveredDna);
          setWorkspace((current) => ({
            ...current,
            channels: current.channels.map((channel) => channel.channelId !== activeWorkspaceChannelId ? channel : {
              ...channel,
              recoveryJobId: latestRecovery.job_id,
              dnaJobId: latestRecovery.content_dna_job_id || channel.dnaJobId,
            }),
          }));
          if (latestRecovery.stage === "COMPLETED" && latestRecovery.result) return;
        }

        const latestDna = await getLatestContentDnaJobForAnalysis(job!.job_id).catch(() => null);
        if (cancelled) return;
        if (latestDna) {
          setDnaJob(latestDna);
          setWorkspace((current) => ({
            ...current,
            channels: current.channels.map((channel) => channel.channelId !== activeWorkspaceChannelId ? channel : {
              ...channel,
              dnaJobId: latestDna.job_id,
            }),
          }));
          if (latestDna.stage === "COMPLETED" && latestDna.result) return;
        }

        const historyRecoveryIds = productionHistory
          .slice()
          .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
          .map((entry) => entry.recovery_job_id);
        const candidateIds = Array.from(new Set([
          activeWorkspaceRecoveryJobId,
          ...historyRecoveryIds,
        ].filter((value): value is string => Boolean(value))));
        for (const recoveryId of candidateIds) {
          try {
            const recovered = await getRecoveryJob(recoveryId);
            if (cancelled) return;
            if (!recovered) continue;
            setRecoveryJob(recovered);
            const recoveredDna = await getContentDnaJob(recovered.content_dna_job_id).catch(() => null);
            if (cancelled) return;
            if (recoveredDna) setDnaJob(recoveredDna);
            setWorkspace((current) => ({
              ...current,
              channels: current.channels.map((channel) => channel.channelId !== activeWorkspaceChannelId ? channel : {
                ...channel,
                recoveryJobId: recovered.job_id,
                dnaJobId: recovered.content_dna_job_id || channel.dnaJobId,
              }),
            }));
            return;
          } catch {
            // Try the next tenant-owned Recovery job referenced by saved productions.
          }
        }
      } finally {
        if (!cancelled) setRevivalLineageCheckPending(false);
      }
    }

    void reconcileRevivalLineage();
    return () => { cancelled = true; };
  }, [
    workspaceView,
    activeWorkspaceChannel?.channelId,
    activeWorkspaceChannel?.recoveryJobId,
    job?.job_id,
    job?.stage,
    recoveryReady,
    dnaReady,
    productionHistory.map((entry) => `${entry.recovery_job_id}:${entry.updated_at}`).join("|"),
  ]);

  async function restoreRevivalIntelligenceFromSavedEvidence() {
    if (!job || job.stage !== "COMPLETED" || !job.result) return;
    setRevivalRestorePending(true);
    setRevivalProgramError(null);
    try {
      setRevivalRestorePhase("CONTENT_DNA");
      let restoredDna = await getLatestContentDnaJobForAnalysis(job.job_id).catch(() => null);
      if (!restoredDna || restoredDna.stage === "FAILED") {
        restoredDna = await createContentDnaJob(job.job_id);
      }
      setDnaJob(restoredDna);
      for (let attempt = 0; attempt < 400 && !DNA_TERMINAL.has(restoredDna.stage); attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 900));
        restoredDna = await getContentDnaJob(restoredDna.job_id);
        setDnaJob(restoredDna);
      }
      if (restoredDna.stage !== "COMPLETED" || !restoredDna.result) {
        throw new Error(restoredDna.error || "Content DNA could not be restored from the saved channel evidence.");
      }

      setRevivalRestorePhase("RECOVERY");
      let restoredRecovery = await getLatestRecoveryJobForAnalysis(job.job_id).catch(() => null);
      if (!restoredRecovery || restoredRecovery.stage === "FAILED" || restoredRecovery.content_dna_job_id !== restoredDna.job_id) {
        restoredRecovery = await createRecoveryJob(restoredDna.job_id);
      }
      setRecoveryJob(restoredRecovery);
      for (let attempt = 0; attempt < 400 && !RECOVERY_TERMINAL.has(restoredRecovery.stage); attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 900));
        const refreshedRecovery = await getRecoveryJob(restoredRecovery.job_id);
        if (!refreshedRecovery) {
          setRecoveryJob(null);
          throw new Error("Recovery Intelligence job disappeared while it was being restored. Please retry the restore operation.");
        }
        restoredRecovery = refreshedRecovery;
        setRecoveryJob(restoredRecovery);
      }
      if (restoredRecovery.stage !== "COMPLETED" || !restoredRecovery.result) {
        throw new Error(restoredRecovery.error || "Recovery Intelligence could not be restored from the saved channel evidence.");
      }

      setWorkspace((current) => ({
        ...current,
        channels: current.channels.map((channel) => channel.channelId !== job.result!.channel.channel_id ? channel : {
          ...channel,
          dnaJobId: restoredDna!.job_id,
          recoveryJobId: restoredRecovery!.job_id,
        }),
      }));
    } catch (error) {
      setRevivalProgramError(error instanceof Error ? error.message : "Unable to restore Revival Intelligence from the saved channel evidence.");
    } finally {
      setRevivalRestorePending(false);
      setRevivalRestorePhase(null);
    }
  }

  const creatorJourneySteps: CreatorJourneyStep[] = [
    {
      id: "strategy",
      label: "Strategy & recovery direction",
      shortLabel: "Strategy",
      milestone: "M1",
      detail: recoveryReady
        ? "Evidence, Content DNA, and a recovery direction are ready."
        : dnaReady
          ? "Turn Content DNA into a creator-selected recovery direction."
          : "Build Content DNA, then choose a recovery direction grounded in the channel evidence.",
      targetId: recoveryReady || recoveryJob ? "recovery-intelligence" : "content-dna",
      status: recoveryReady || Boolean(productionBriefJob?.source_snapshot) ? "COMPLETE" : "CURRENT",
    },
    {
      id: "story",
      label: "Story & production brief",
      shortLabel: "Story",
      milestone: "M2A",
      detail: productionApproved
        ? "The production brief is human-approved and locked for media generation."
        : productionReady
          ? "Review and approve the generated production brief before visual generation."
          : "Create the production brief from the selected recovery direction.",
      targetId: recoveryReady || productionBriefJob ? "production-studio" : null,
      status: productionApproved ? "COMPLETE" : recoveryReady ? (productionReady ? "REVIEW" : "CURRENT") : "LOCKED",
    },
    {
      id: "visuals",
      label: "Visual continuity & animation",
      shortLabel: "Visuals",
      milestone: "M2B",
      detail: assemblyReady
        ? "All approved visual clips are ready to assemble."
        : mediaReady
          ? "Approved keyframes are ready for Veo animation and clip review."
          : "Lock visual continuity, review keyframes, and approve animated clips.",
      targetId: productionApproved || mediaStudioJob ? "media-studio" : null,
      status: assemblyReady ? "COMPLETE" : productionApproved ? (mediaStudioJob?.stage === "FAILED" ? "BLOCKED" : mediaStudioJob && MEDIA_REVIEW_STAGES.has(mediaStudioJob.stage) ? "REVIEW" : "CURRENT") : "LOCKED",
    },
    {
      id: "master",
      label: "Approved visual master",
      shortLabel: "Visual master",
      milestone: "M2C.1",
      detail: finalAssemblyApproved
        ? "The approved visual master is immutable for downstream audio finishing."
        : finalAssemblyReady
          ? "Watch the assembled Short and approve the visual master."
          : "Assemble the approved clips into the final portrait master.",
      targetId: assemblyReady || finalAssemblyJob ? "final-assembly" : null,
      status: finalAssemblyApproved ? "COMPLETE" : assemblyReady ? (finalAssemblyJob?.stage === "FAILED" ? "BLOCKED" : finalAssemblyReady ? "REVIEW" : "CURRENT") : "LOCKED",
    },
    {
      id: "audio",
      label: "Audio finishing & soundtrack",
      shortLabel: "Audio",
      milestone: "M2C.2",
      detail: deliveryMasterApproved
        ? `Audio master v${approvedAudioMaster?.version_number ?? ""} is approved.`
        : audioFinishingReady
          ? "Listen through the finished mix and approve the delivery master."
          : "Choose the soundtrack, balance the mix, and create an audio master from the same approved picture.",
      targetId: finalAssemblyApproved || audioFinishingJob ? "audio-finishing" : null,
      status: deliveryMasterApproved ? "COMPLETE" : finalAssemblyApproved ? (audioFinishingJob?.stage === "FAILED" ? "BLOCKED" : audioFinishingReady ? "REVIEW" : "CURRENT") : "LOCKED",
    },
    {
      id: "qc",
      label: "Final delivery quality control",
      shortLabel: "QC",
      milestone: "M2C.3",
      detail: deliveryQcReady
        ? "All blocking delivery checks passed."
        : deliveryQcBlocked
          ? "One or more blocking delivery checks failed and need correction."
          : deliveryQcReview
            ? "QC found review notes that need a final human check."
            : "Verify lineage, codecs, duration, loudness, captions, rights, and delivery integrity.",
      targetId: deliveryMasterApproved ? "final-delivery-qc" : null,
      status: deliveryQcReady ? "COMPLETE" : deliveryMasterApproved ? (deliveryQcBlocked ? "BLOCKED" : deliveryQcReview ? "REVIEW" : "CURRENT") : "LOCKED",
    },
    {
      id: "delivery",
      label: "Versioned delivery package",
      shortLabel: "Delivery",
      milestone: "M2C.4",
      detail: deliveryPackageReady
        ? `Delivery package v${deliveryPackage?.package_version ?? ""} is available for download.`
        : "Create the versioned ZIP with the verified master and companion delivery assets.",
      targetId: deliveryQcReady ? "delivery-package" : null,
      status: deliveryPackageReady ? "COMPLETE" : deliveryQcReady ? "CURRENT" : "LOCKED",
    },
    {
      id: "publishing",
      label: "Creator-approved publishing copy",
      shortLabel: "Publishing",
      milestone: "M2C.5",
      detail: publishingPackaged
        ? `Approved publishing copy is included in delivery package v${deliveryPackage?.package_version ?? ""}.`
        : publishingDraft?.status === "APPROVED"
          ? "The publishing draft is approved; add it to a new delivery-package version."
          : publishingDraft
            ? "Review, edit, or selectively regenerate the platform copy, then approve it."
            : "Generate editable YouTube, TikTok, and Instagram publishing copy from the approved story.",
      targetId: deliveryPackageReady ? "publishing-assistant" : null,
      status: publishingPackaged ? "COMPLETE" : deliveryPackageReady ? (publishingDraft ? "REVIEW" : "CURRENT") : "LOCKED",
    },
  ];

  const currentCreatorJourneyStep = creatorJourneySteps.find((step) => !["COMPLETE", "LOCKED"].includes(step.status))
    ?? creatorJourneySteps[creatorJourneySteps.length - 1];

  const creatorJourneyContinueLabel = publishingPackaged
    ? "View publishing package"
    : currentCreatorJourneyStep.id === "strategy"
      ? dnaReady ? "Continue to recovery" : "Build Content DNA"
      : currentCreatorJourneyStep.id === "story"
        ? productionReady ? "Review production brief" : "Create production brief"
        : currentCreatorJourneyStep.id === "visuals"
          ? mediaStudioJob && MEDIA_REVIEW_STAGES.has(mediaStudioJob.stage) ? "Review visual assets" : mediaReady ? "Continue to animation" : "Open visual studio"
          : currentCreatorJourneyStep.id === "master"
            ? finalAssemblyReady ? "Review visual master" : "Build visual master"
            : currentCreatorJourneyStep.id === "audio"
              ? audioFinishingReady ? "Review audio master" : "Open audio finishing"
              : currentCreatorJourneyStep.id === "qc"
                ? deliveryQcBlocked ? "Review failed QC" : deliveryQcReview ? "Review QC notes" : "Run final QC"
                : currentCreatorJourneyStep.id === "delivery"
                  ? "Create delivery package"
                  : publishingDraft?.status === "APPROVED" ? "Package approved copy" : publishingDraft ? "Review publishing copy" : "Create publishing copy";

  function openNewProductionFromChannel() {
    setWorkspaceView("channel");
    setChannelTab("intelligence");
    setActiveProductionId(null);
    window.setTimeout(() => {
      document.getElementById(recoveryReady ? "recovery-intelligence" : dnaReady ? "content-dna" : "channel-intelligence")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 80);
  }

  const autopilotProductionPanel = productionBriefJob && autopilotOwnsCurrentProduction ? (
    <AutopilotProductionPanel
      title={visibleProductionTitle}
      status={autopilot.status}
      message={autopilot.message}
      attentionStage={autopilot.attentionStage}
      productionJob={productionBriefJob}
      mediaJob={mediaStudioJob}
      assemblyJob={finalAssemblyJob}
      audioJob={audioFinishingJob || approvedAudioMaster}
      qc={deliveryQcReport}
      publishingDraft={publishingDraft}
      publishingPackaged={publishingPackaged}
      finalHumanApproved={finalVideoHumanApproved}
    />
  ) : null;

  const productionIdeaPanel = productionBriefJob ? (
    autopilotOwnsCurrentProduction ? null : (
      <ProductionBriefPanel
        job={productionBriefJob}
        history={productionHistory}
        error={productionBriefError}
        onRetry={retryProductionBrief}
        onApprove={approveCurrentProductionBrief}
        onKeepOriginalDirection={keepOriginalDirection}
        onAcceptAdaptation={acceptCreativeAdaptation}
        onOpenHistory={openProductionHistory}
        onStartMediaStudio={startMediaStudio}
      />
    )
  ) : null;

  const productionCreatePanel = productionBriefJob ? (
    autopilotOwnsCurrentProduction ? null : (
      <>
        {(productionApproved || mediaStudioJob) && (
          <MediaStudioPanel
            productionJob={productionBriefJob}
            job={mediaStudioJob}
            error={mediaStudioError}
            resumePending={mediaResumePending}
            onStart={startMediaStudio}
            onApproveReference={approveReference}
            onRegenerateReference={regenerateReference}
            onApproveKeyframe={approveKeyframe}
            onRegenerateKeyframe={regenerateKeyframe}
            onReviewAllKeyframes={reviewAllKeyframes}
            onReviewKeyframe={reviewKeyframe}
            onAcceptKeyframeAdaptation={acceptKeyframeAdaptation}
            onStartAnimation={startAnimation}
            onApproveClip={approveClip}
            onRegenerateClip={regenerateClip}
          />
        )}
        {(assemblyReady || finalAssemblyJob) && (
          <FinalAssemblyPanel
            mediaJob={mediaStudioJob}
            job={finalAssemblyJob}
            error={finalAssemblyError}
            resumePending={assemblyResumePending}
            onStart={startFinalAssembly}
            onApprove={approveCurrentFinalAssembly}
          />
        )}
      </>
    )
  ) : null;

  const productionFinishPanel = productionBriefJob && (finalAssemblyApproved || audioFinishingJob) ? (
    autopilotOwnsCurrentProduction ? null : (
      <AudioFinishingPanel
        assemblyJob={finalAssemblyJob}
        job={audioFinishingJob}
        versions={audioVersionHistory}
        error={audioFinishingError}
        resumePending={audioResumePending}
        onStart={startAudioFinishing}
        onApprove={approveCurrentAudioFinishing}
      />
    )
  ) : null;

  // A manually acknowledged, non-blocking QC warning may advance to the same
  // creator-controlled publishing flow as a READY report. Blocking failures never qualify.
  const manualQcClearedForPublishing = Boolean(deliveryQcReport && (
    deliveryQcReport.overall_status === "READY" || (
      deliveryQcReport.overall_status === "REVIEW" &&
      deliveryQcReport.fail_count === 0 &&
      deliveryQcReport.human_acknowledgment?.report_id === deliveryQcReport.report_id
    )
  ));

  const productionDeliverPanel = productionBriefJob ? (
    <>
      {!autopilotOwnsCurrentProduction && approvedAudioMaster && (
        <FinalDeliveryQcPanel
          audioJob={approvedAudioMaster}
          report={deliveryQcReport}
          pending={deliveryQcPending}
          resumePending={deliveryQcResumePending}
          error={deliveryQcError}
          onRun={runFinalDeliveryQc}
          packageReady={Boolean(deliveryPackage)}
          packagePending={deliveryPackagePending}
          onCreatePackage={buildDeliveryPackage}
          acknowledgmentPending={deliveryQcPending}
          onAcknowledge={acknowledgeQcWarning}
        />
      )}
      {!autopilotOwnsCurrentProduction && approvedAudioMaster && manualQcClearedForPublishing && (
        <DeliveryPackagePanel
          deliveryPackage={deliveryPackage}
          pending={deliveryPackagePending}
          resumePending={deliveryPackageResumePending}
          error={deliveryPackageError}
          audioVersion={approvedAudioMaster.version_number}
          history={deliveryPackageHistory}
          onCreate={buildDeliveryPackage}
        />
      )}
      {!autopilotOwnsCurrentProduction && approvedAudioMaster && deliveryPackage && (
        <PublishingAssistantPanel
          draft={publishingDraft}
          history={publishingDraftHistory}
          deliveryPackage={deliveryPackage}
          deliveryPackageHistory={deliveryPackageHistory}
          resumePending={publishingResumePending}
          action={publishingAction}
          error={publishingError}
          onGenerate={generatePublishingCopy}
          onSave={savePublishingCopy}
          onRegenerate={regeneratePublishingCopy}
          onApprove={approveCurrentPublishingCopy}
          onAddToPackage={addPublishingCopyToPackage}
          onContinueToYouTube={() => document.getElementById("production-youtube-publishing")?.scrollIntoView({ behavior: "smooth", block: "start" })}
          finalVideoApproved={finalVideoHumanApproved}
          onGoToFinalApproval={() => document.getElementById("production-final-approval")?.scrollIntoView({ behavior: "smooth", block: "center" })}
          onFork={forkApprovedPublishingCopy}
          onOpenVersion={(next) => { setPublishingDraft(next); setPublishingError(null); }}
        />
      )}
      {!autopilotOwnsCurrentProduction && deliveryPackage && publishingDraft?.status === "APPROVED" &&
        deliveryPackage.publishing_draft_id === publishingDraft.draft_id &&
        approvedAudioMaster && manualQcClearedForPublishing &&
        deliveryPackage.qc_report_id === deliveryQcReport?.report_id &&
        deliveryPackage.audio_job_id === approvedAudioMaster.job_id && (
        <>
          {!finalVideoHumanApproved && import.meta.env.DEV &&
            approvedAudioMaster.job_id === "audio_92d788728faf41a78c20d7cc5e19c35d" &&
            publishingDraft.draft_id === "publishing_8bce387ccdec472abaf0f94a2224a6c9" &&
            deliveryPackage.package_id === "deliverypkg_0cf6523ec2fd4cac8311e370efb2d95a" &&
            <DevRecoveredReviewPanel />
          }
          {!finalVideoHumanApproved && (
            <section id="production-final-approval" className="glass-card" style={{ padding: 20, marginTop: 16, display: "grid", gap: 12, scrollMarginTop: 100 }}>
              <strong>Step 1 · Final creator approval required</strong>
              <p style={{ margin: 0, opacity: 0.85 }}>
                Your QC-verified master and approved publishing copy are ready. Approve the finished
                video before enabling the YouTube upload. This does not resume Autopilot or upload anything.
              </p>
              {finalHumanApprovalError && <div className="inline-error" role="alert">{finalHumanApprovalError}</div>}
              {finalHumanOverrideReason && (
                <div style={{ display: "grid", gap: 8, padding: 12, border: "1px solid rgba(255,184,110,.6)", borderRadius: 10 }}>
                  <strong>AI creative-quality warning</strong>
                  <p style={{ margin: 0 }}>{finalHumanOverrideReason}</p>
                  <p style={{ margin: 0, opacity: 0.85 }}>You may accept this exact finished video despite the AI finding. Delivery QC, package integrity, and publishing authorization remain required.</p>
                  <button className="secondary-button" type="button" disabled={finalHumanApprovalPending}
                    onClick={() => setFinalApprovalDialog("OVERRIDE")}>Approve anyway — human quality override</button>
                </div>
              )}
              <button className="primary-button" type="button" disabled={finalHumanApprovalPending}
                onClick={() => setFinalApprovalDialog("NORMAL")}>
                {finalHumanApprovalPending ? "Recording final approval…" : "Approve finished video"}
              </button>
            </section>
          )}
          <div id="production-youtube-publishing" style={{ scrollMarginTop: 90 }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center", padding: "14px 16px", marginTop: 12, background: "rgba(116,93,230,.10)", border: "1px solid rgba(135,114,239,.28)", borderRadius: 12 }}>
            <span style={{ fontWeight: 700 }}>Step 2 · YouTube publishing</span>
            <span style={{ color: finalVideoHumanApproved ? "#a4edcc" : "#b4bad4", fontSize: 12 }}>
              {finalVideoHumanApproved ? "Final creator approval complete" : "Complete Step 1 before uploading or scheduling"}
            </span>
          </div>
          <YouTubePublishLoopPanel
          deliveryPackage={deliveryPackage}
          draft={publishingDraft}
          recommendationId={productionBriefJob.recommendation_id}
          program={revivalProgram}
          finalApproved={finalVideoHumanApproved}
        />
          </div>
        </>
      )}
      {(finalApprovalMode || finalVideoHumanApproved) && mediaStudioJob && approvedAudioMaster && deliveryQcReport && deliveryPackage && publishingDraft && (
        <FinalHumanReviewPanel
          productionJob={productionBriefJob}
          mediaJob={mediaStudioJob}
          assemblyJob={finalAssemblyJob}
          audioJob={approvedAudioMaster}
          qc={deliveryQcReport}
          deliveryPackage={deliveryPackage}
          publishingDraft={publishingDraft}
          pending={finalHumanApprovalPending}
          error={finalHumanApprovalError}
          onApprove={approveFinalVideoAsHuman}
        />
      )}
    </>
  ) : null;

  const guidedProductionStages: GuidedStage[] = productionBriefJob ? [
    {
      id: "idea",
      label: "1 Plan",
      description: autopilotOwnsCurrentProduction
        ? (productionApproved ? "AI plan review passed." : "AI is reviewing the production plan and source fidelity.")
        : productionApproved ? "Your video plan is approved." : productionReady ? "Review the video plan, then approve it." : "Shape the idea into a clear video plan.",
      complete: productionApproved,
      available: true,
      node: productionIdeaPanel,
    },
    {
      id: "create",
      label: "2 Visuals",
      description: autopilotOwnsCurrentProduction
        ? (finalAssemblyApproved ? "Reference, keyframes, motion, and visual assembly passed AI review." : "AI is reviewing visual identity, storyboard fidelity, motion, and assembly.")
        : finalAssemblyApproved ? "Your picture is approved." : assemblyReady ? "Review the assembled video." : mediaReady ? "Review the scenes and animation." : "Create and review the visual scenes.",
      complete: finalAssemblyApproved,
      available: productionApproved || Boolean(mediaStudioJob),
      node: productionCreatePanel,
    },
    {
      id: "finish",
      label: "3 Audio",
      description: autopilotOwnsCurrentProduction
        ? (deliveryMasterApproved ? "Voice, music, ambience, and mix passed AI review." : "AI is creating and listening to the voice, soundtrack, ambience, and final mix.")
        : deliveryMasterApproved ? "Voice, music, ambience, and captions are approved." : "Choose the voice and soundtrack, then approve the final mix.",
      complete: deliveryMasterApproved,
      available: finalAssemblyApproved || Boolean(audioFinishingJob),
      node: productionFinishPanel,
    },
    {
      id: "deliver",
      label: "4 AI review",
      description: finalVideoHumanApproved
        ? "AI review passed and final human approval is recorded."
        : finalVideoReadyForHumanReview
          ? "AI review is complete. The finished video is waiting for your approval."
          : autopilotOwnsCurrentProduction
            ? "AI is completing technical QC, delivery packaging, and publishing-text review."
            : publishingPackaged ? "Publishing package is ready." : deliveryPackageReady ? "Review the publishing copy." : deliveryQcReady ? "Create the delivery package." : "Run final quality checks and prepare the finished video.",
      complete: finalVideoReadyForHumanReview || finalVideoHumanApproved,
      available: Boolean(approvedAudioMaster) || autopilotOwnsCurrentProduction,
      node: productionDeliverPanel,
    },
  ] : [];

  return (
    <div className="app-shell workspace-app-shell">
      <BrandHeader />

      <main>
        {(!autopilotHydrated && autopilotPersistenceError) && (
          <div className="error-banner autopilot-server-warning" role="alert">
            <AlertTriangle size={18} />
            <div>
              <strong>Autopilot checkpoint could not be safely restored</strong>
              <p>{autopilotPersistenceError} Autopilot is locked until the server checkpoint is available; no new session will be written.</p>
              <button type="button" onClick={() => setAutopilotHydrationRetryTick((value) => value + 1)}>Retry secure restore</button>
              {autopilotCheckpointAbsent && (
                <button type="button" onClick={async () => {
                  const confirmed = window.confirm("Only initialize if this is a NEW workspace with no prior Autopilot production. If you previously ran Autopilot, CANCEL and investigate the original checkpoint instead. Create a new empty workspace?");
                  if (!confirmed) return;
                  try {
                    const fresh = emptyAutopilotSession();
                    const saved = await saveServerAutopilotState<AutopilotSession>(fresh, 0);
                    autopilotServerRevisionRef.current = saved.revision;
                    autopilotLastPersistedUpdatedAtRef.current = saved.session.updatedAt;
                    setAutopilot({ ...emptyAutopilotSession(), ...saved.session });
                    setAutopilotPersistenceError(null);
                    setAutopilotCheckpointAbsent(false);
                    setAutopilotHydrated(true);
                  } catch (error) {
                    setAutopilotPersistenceError(error instanceof Error ? error.message : "Unable to initialize workspace safely.");
                  }
                }}>Initialize new workspace (only if no prior run)</button>
              )}
            </div>
          </div>
        )}
        {((!autopilotHydrated && !autopilotPersistenceError) || workflowRestorePending) && (
          <section className="workflow-restore-card glass-card autopilot-server-sync" aria-live="polite" role="status">
            <LoaderCircle className="spinner" size={20} aria-hidden="true" />
            <div>
              <span className="eyebrow">Creator workspace · secure restore</span>
              <strong>{workflowRestorePending ? "Restoring your workspace…" : "Connecting Autopilot…"}</strong>
              <small>{workflowRestorePending
                ? "Reconnecting to your saved channels and productions."
                : "Loading the authenticated server checkpoint without interrupting your saved work."}</small>
            </div>
          </section>
        )}
        {autopilotHydrated && autopilotPersistenceError && (
          <div className="error-banner autopilot-server-warning" role="status">
            <AlertTriangle size={18} />
            <div>
              <strong>Autopilot server sync needs attention</strong>
              <p>{autopilotPersistenceError} ReviveAI will retry automatically; the browser will not overwrite a newer server checkpoint.</p>
            </div>
          </div>
        )}

        {autopilotHydrated && !autopilotPersistenceError && autopilotSyncNotice && (
          <div className="glass-card autopilot-server-sync" role="status" aria-live="polite">
            <ShieldCheck size={18} aria-hidden="true" />
            <div>
              <strong>Autopilot synced with the server</strong>
              <p>{autopilotSyncNotice}</p>
            </div>
          </div>
        )}

        {!workflowRestorePending && workspaceView === "workspace" && (
          <>
            <WorkspaceDashboard
              workspace={workspace}
              displayName={currentUser.name}
              onAddChannel={startAddChannel}
              onOpenChannel={(channel) => { void openWorkspaceChannel(channel); }}
              onOpenProduction={(channel, production) => { void openWorkspaceProduction(channel, production); }}
              onManageChannels={() => setManageChannelsOpen(true)}
            />
          </>
        )}

        {!workflowRestorePending && workspaceView === "add-channel" && (
          <>
            {workspace.channels.length > 0 && (
              <button className="workspace-back-button" type="button" onClick={goWorkspaceHome}>← Back to workspace</button>
            )}
            <section className={`hero-section add-channel-hero ${workspace.channels.length === 0 && analysisIntent === "ADD" ? "first-channel-hero" : ""}`}>
              <div className="hero-copy">
                <div className="hero-badge"><Sparkles size={15} /> {analysisIntent === "REFRESH" ? "Reconnect saved intelligence" : workspace.channels.length === 0 ? "Public YouTube data only" : "Add a channel to your workspace"}</div>
                <h1>{analysisIntent === "REFRESH" ? "Refresh this channel's intelligence snapshot." : workspace.channels.length === 0 ? "Create your first channel workspace." : "Bring another YouTube channel into ReviveAI."}</h1>
                <p>
                  {analysisIntent === "REFRESH"
                    ? "Your productions remain intact. ReviveAI rebuilds only the public channel evidence snapshot and reconnects it to this workspace."
                    : workspace.channels.length === 0
                      ? "Paste any YouTube channel, video, or Short URL. ReviveAI analyzes the public archive once and keeps that intelligence ready for every future production."
                      : "Analyze the public archive once. ReviveAI saves the channel intelligence and keeps every production independent, so you can switch channels without starting over."}
                </p>
                <div className="trust-row">
                  <span><ShieldCheck size={16} /> Public data only</span>
                  <span><ShieldCheck size={16} /> Private saved workspace</span>
                  <span><ShieldCheck size={16} /> Independent productions</span>
                </div>
              </div>
              <ChannelInputCard
                url={url}
                onUrlChange={setUrl}
                onSubmit={analyze}
                disabled={isRunning}
                context={analysisIntent === "REFRESH" ? "refresh" : workspace.channels.length === 0 ? "first" : "add"}
              />
            </section>
          </>
        )}

        {workspaceView === "add-channel" && requestError && (
          <div className="error-banner" role="alert">
            <AlertTriangle size={20} />
            <div><strong>Could not start the analysis</strong><p>{requestError}</p></div>
          </div>
        )}

        {workspaceView === "add-channel" && job && !TERMINAL.has(job.stage) && <ProgressTimeline job={job} />}

        {workspaceView === "add-channel" && job?.stage === "FAILED" && (
          <section className="failure-card glass-card" role="alert">
            <AlertTriangle size={28} />
            <div>
              <span className="eyebrow">Analysis stopped</span>
              <h2>We couldn't build this channel intelligence report.</h2>
              <p>{job.error || "Unknown error."}</p>
              <button className="secondary-button" onClick={reset}><RotateCcw size={16} /> Try another link</button>
            </div>
          </section>
        )}

        {!workflowRestorePending && activeWorkspaceChannel && (workspaceView === "channel" || workspaceView === "production") && (
          <WorkspaceContextBar
            workspace={workspace}
            channel={activeWorkspaceChannel}
            productionTitle={workspaceView === "production" ? visibleProductionTitle : null}
            onHome={goWorkspaceHome}
            onSwitchChannel={(channel) => { setChannelSettingsOpen(false); void openWorkspaceChannel(channel); }}
            onAddChannel={startAddChannel}
            onChannelHome={() => { setWorkspaceView("channel"); setActiveProductionId(null); setChannelTab("overview"); window.scrollTo({ top: 0, behavior: "smooth" }); }}
            onOpenChannelSettings={() => setChannelSettingsOpen(true)}
          />
        )}

        {!workflowRestorePending && activeWorkspaceChannel && workspaceView === "channel" && (
          <section className="channel-workspace">
            <style>{`
              .channel-workspace-heading { margin-bottom: 12px !important; gap: 12px !important; padding-bottom: 0 !important; }
              .channel-workspace-heading h1 { font-size: clamp(26px, 3vw, 34px) !important; margin: 3px 0 !important; }
              .channel-workspace-heading p { margin-top: 3px !important; }
              .channel-workspace-heading .primary-button, .channel-workspace-heading .secondary-button { min-height: 40px; display: inline-flex; align-items: center; justify-content: center; gap: 8px; border-radius: 10px; }
              .v3-overview-extras { margin-top: 10px !important; }
              .revive-channel-navigation { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 0 0 12px; position: relative; z-index: 5; }
              .revive-channel-navigation .channel-workspace-tabs { display: flex; flex-wrap: wrap; gap: 4px; width: auto; margin: 0; }
              .revive-channel-navigation .channel-workspace-tabs button { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
              .revive-channel-more { position: relative; }
              .revive-channel-more > summary { list-style: none; cursor: pointer; display: inline-flex; gap: 7px; align-items: center; padding: 9px 13px; border: 1px solid rgba(155,152,221,.3); border-radius: 10px; color: #d5d7f1; background: rgba(24,28,49,.8); font-size: 13px; font-weight: 600; }
              .revive-channel-more > summary::-webkit-details-marker { display: none; }
              .revive-channel-more[open] > summary, .revive-channel-more > summary:hover, .revive-channel-more > summary.more-selected { background: rgba(110,86,211,.21); border-color: rgba(148,127,244,.55); color: #fff; }
              .revive-channel-more-menu { position: absolute; top: calc(100% + 7px); left: 0; min-width: 220px; padding: 7px; border-radius: 12px; border: 1px solid rgba(153,147,215,.3); background: #171b2f; box-shadow: 0 18px 45px rgba(0,0,0,.5); display: grid; gap: 3px; }
              .revive-channel-more-menu button { border: none; width: 100%; display: flex; align-items: center; gap: 9px; text-align: left; background: transparent; padding: 11px 10px; border-radius: 8px; color: #e5e5f7; font-size: 13px; cursor: pointer; }
              .revive-channel-more-menu button:hover, .revive-channel-more-menu button.active { background: rgba(110,86,211,.25); }
              @media (max-width: 640px) { .revive-channel-navigation { flex-wrap: nowrap; overflow-x: auto; padding-bottom: 5px; } .revive-channel-navigation .channel-workspace-tabs { flex-wrap: nowrap; } .revive-channel-more-menu { position: fixed; top: auto; left: 12px; right: 12px; bottom: 12px; min-width: 0; z-index: 50; } }
              .channel-settings-modal-backdrop { position: fixed; inset: 0; background: rgba(4, 7, 18, .72); backdrop-filter: blur(8px); display: grid; place-items: center; padding: 16px; z-index: 120; }
              .channel-settings-modal-wrap { width: 100%; display: grid; place-items: center; }
            `}</style>
            <div className="channel-workspace-heading">
              <div>
                <span className="eyebrow">Channel workspace</span>
                <h1>{result?.channel.title || activeWorkspaceChannel.title}</h1>
                <p>Live activity, publishing and performance for your channel.</p>
              </div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end" }}>
                {result && recoveryReady && (
                  <button className="secondary-button direction-entry-button" type="button" onClick={() => { setDirectionStudioRequested(true); setTrendDirections(null); setChannelTab("directions"); }}>
                    <Compass size={16} /> Explore ideas
                  </button>
                )}

                {result
                  ? dnaReady && recoveryReady ? <button className="primary-button" type="button" onClick={openNewProductionFromChannel}><Plus size={16} /> New production</button> : null
                  : <button className="primary-button" type="button" onClick={() => refreshSavedChannel(activeWorkspaceChannel)}><RotateCcw size={16} /> Analyze again</button>}
              </div>
            </div>

            <nav className="revive-channel-navigation" aria-label="Channel workspace navigation">
              <div className="channel-workspace-tabs" role="tablist" aria-label="Main channel workspaces">
                <button type="button" role="tab" aria-selected={channelTab === "overview"} className={channelTab === "overview" ? "active" : ""} onClick={() => setChannelTab("overview")}><LayoutDashboard size={15}/> Overview</button>
                <button type="button" role="tab" aria-selected={channelTab === "autonomy"} className={channelTab === "autonomy" ? "active" : ""} onClick={() => setChannelTab("autonomy")}><Bot size={15}/> Autonomy</button>
                <button type="button" role="tab" aria-selected={channelTab === "productions"} className={channelTab === "productions" ? "active" : ""} onClick={() => setChannelTab("productions")}><Clapperboard size={15}/> Productions <span>{activeWorkspaceProductionCount}</span></button>
                <button type="button" role="tab" aria-selected={channelTab === "intelligence"} className={channelTab === "intelligence" ? "active" : ""} onClick={() => setChannelTab("intelligence")}><ChartNoAxesColumn size={15}/> Intelligence</button>
              </div>
              <details className="revive-channel-more">
                <summary className={["directions", "soundtracks", "costs"].includes(channelTab) ? "more-selected" : ""} aria-label="More channel tools"><MoreHorizontal size={17}/> More <span aria-hidden="true">▾</span></summary>
                <div className="revive-channel-more-menu" aria-label="Additional channel tools">
                  <button type="button" className={channelTab === "directions" ? "active" : ""} aria-current={channelTab === "directions" ? "page" : undefined} onClick={() => { setChannelTab("directions"); if (!trendDirections && !trendDirectionPending) void (async () => { const restored = await loadSavedDirections(); if (!restored) await discoverCurrentDirections(); })(); }}><Compass size={16}/> Creative Directions</button>
                  <button type="button" className={channelTab === "soundtracks" ? "active" : ""} aria-current={channelTab === "soundtracks" ? "page" : undefined} onClick={() => setChannelTab("soundtracks")}><Music2 size={16}/> Soundtracks</button>
                  <button type="button" className={channelTab === "costs" ? "active" : ""} aria-current={channelTab === "costs" ? "page" : undefined} onClick={() => setChannelTab("costs")}><Wallet size={16}/> Production Costs</button>
                </div>
              </details>
            </nav>

            {channelSettingsOpen && activeWorkspaceChannel && (
              <div
                className="channel-settings-modal-backdrop"
                role="dialog"
                aria-modal="true"
                aria-label="Channel autonomy settings"
                onClick={() => setChannelSettingsOpen(false)}
              >
                <div className="channel-settings-modal-wrap" onClick={(event) => event.stopPropagation()}>
                  <ChannelAutonomySettings
                    channelId={activeWorkspaceChannel.channelId}
                    inModal
                    onClose={() => setChannelSettingsOpen(false)}
                  />
                </div>
              </div>
            )}

            {channelTab === "overview" && result && (
              <>
                <ChannelCommandCenter
                  channel={activeWorkspaceChannel}
                  programId={revivalProgram?.program_id}
                  autopilotStatus={autopilot.status}
                  autopilotMessage={autopilot.message}
                  currentProductionTitle={autopilot.currentTitle}
                  currentProductionJobId={autopilot.currentProductionJobId}
                  currentMediaJobId={autopilot.currentMediaJobId}
                  currentPublicationId={autopilot.currentPublicationId}
                  learningCheckpointRequired={autopilot.learningCheckpointRequired}
                  learningWaitStartedAt={autopilot.learningWaitStartedAt}
                  supervisorHeartbeatAt={autopilot.lastSupervisorHeartbeatAt}
                  executionOwner={autopilot.executionOwner}
                  onOpenTab={(tab) => setChannelTab(tab)}
                  onOpenProduction={(production) => { void openWorkspaceProduction(activeWorkspaceChannel, production); }}
                />

              </>
            )}

            {channelTab === "directions" && result && (
              <div className="channel-direction-view">
                <div className="channel-direction-view-head">
                  <button className="workspace-back-button" type="button" onClick={() => setChannelTab("overview")}>← Back to channel</button>
                  <div><span className="eyebrow">Creative strategy</span><h2>Explore a new direction</h2><p>Compare fresh opportunities without changing the channel until you choose what to do next.</p></div>
                </div>
                <RevivalProgramPanel
                  channelTitle={result.channel.title || activeWorkspaceChannel.title}
                  program={revivalProgram}
                  recovery={recoveryJob?.result ?? null}
                  recoveryStage={recoveryJob?.stage ?? null}
                  dnaReady={dnaReady}
                  recoveryReady={recoveryReady}
                  history={productionHistory}
                  pending={revivalProgramPending}
                  error={revivalProgramError}
                  lineageCheckPending={revivalLineageCheckPending}
                  restorePending={revivalRestorePending}
                  restorePhase={revivalRestorePhase}
                  onRestoreFromSavedEvidence={restoreRevivalIntelligenceFromSavedEvidence}
                  onCreate={buildRevivalProgram}
                  onUpdateCadence={changeRevivalCadence}
                  onCreateProduction={buildProductionBrief}
                  onOpenIntelligence={openRevivalPrerequisite}
                  autopilot={autopilot.recoveryJobId === recoveryJob?.job_id && autopilot.programId === revivalProgram?.program_id ? {
                    status: autopilot.status, currentTitle: autopilot.currentTitle, message: autopilot.message, attentionStage: autopilot.attentionStage,
                    completedCount: autopilot.completedRecommendationIds.length, currentRecommendationId: autopilot.currentRecommendationId,
                    completedRecommendationIds: autopilot.completedRecommendationIds,
                    blockedProductions: autopilot.blockedProductions.map((item) => ({ recommendationId: item.recommendationId, title: item.title, message: item.message, kind: item.kind, resolutionStatus: normalizeBlockedProduction(item).resolutionStatus, blocksAutonomy: blockedProductionBlocksAutonomy(item) })),
                  } : undefined}
                  onStartAutopilot={startAutopilot}
                  onRunIdeaWithAutopilot={runAutopilotForRecommendation}
                  onPauseAutopilot={pauseAutopilot}
                  onResumeAutopilot={autopilot.status === "NEEDS_ATTENTION" ? recoverAutopilotException : resumeAutopilot}
                  trendDirections={trendDirections}
                  trendPending={trendDirectionPending}
                  trendError={trendDirectionError}
                  customDirectionPending={customDirectionPending}
                  onDiscoverTrends={discoverCurrentDirections}
                  onRefineCustomDirection={refineCreatorDirection}
                  onSelectTrendDirection={produceTrendDirection}
                />
              </div>
            )}

            {channelTab === "soundtracks" && <SoundtrackLibraryPanel />}

            {channelTab === "intelligence" && result && (
              <div id="channel-intelligence" className="channel-intelligence-view">
                {dnaJob && !DNA_TERMINAL.has(dnaJob.stage) && (
                  <AiActivityState
                    title="ReviveAI is learning this channel"
                    message="Analyzing creative patterns and building a reusable Content DNA profile."
                    steps={[
                      { label: "Channel evidence loaded", state: "done" },
                      { label: "Finding recurring creative patterns", state: "active" },
                      { label: "Building Content DNA", state: "waiting" },
                    ]}
                    compact
                  />
                )}
                {recoveryJob && !RECOVERY_TERMINAL.has(recoveryJob.stage) && (
                  <AiActivityState
                    title="ReviveAI is building strategy intelligence"
                    message="Turning channel evidence into audience, recovery, and production guidance."
                    steps={[
                      { label: "Content DNA ready", state: "done" },
                      { label: "Evaluating historical evidence", state: "active" },
                      { label: "Preparing strategic recommendations", state: "waiting" },
                    ]}
                    compact
                  />
                )}
                <div className="progressive-disclosure-note glass-card">
                  <div><span className="eyebrow">Evidence layer</span><strong>Channel intelligence stays here.</strong><small>Productions no longer sit below this report, so this view can be explored deeply without making the creator workflow hard to find.</small></div>
                </div>
                <details className="v3-overview-extras">
                  <summary>Public channel evidence and historical statistics</summary>
                  <ChannelOverview result={result} />
                </details>
                <ChannelMetricsDashboard result={result} />
                <ContentDnaPanel analysis={result} job={dnaJob} error={dnaRequestError} onBuild={buildContentDna} />
                {dnaReady && dnaJob?.result && (
                  <RecoveryIntelligencePanel
                    analysis={result}
                    dna={dnaJob.result}
                    job={recoveryJob}
                    error={recoveryRequestError}
                    onBuild={buildRecoveryIntelligence}
                    onCreateBrief={buildProductionBrief}
                    productionHistory={productionHistory}
                    productionHistoryReady={productionHistoryReady}
                    creatingRecommendationId={productionBriefJob && !PRODUCTION_TERMINAL.has(productionBriefJob.stage) ? selectedRecommendationId : null}
                  />
                )}
                <VideoLibrary videos={result.videos} metrics={result.metrics} />
              </div>
            )}

            {!result && channelTab !== "productions" && channelTab !== "soundtracks" && channelTab !== "autonomy" && (
              <section className="workspace-reconnect-card glass-card" role="status">
                <div className="workspace-reconnect-icon"><RotateCcw size={20} aria-hidden="true" /></div>
                <div>
                  <span className="eyebrow">Saved channel · intelligence reconnect required</span>
                  <h2>Your productions are safe.</h2>
                  <p>{workspaceRestoreError || "The channel intelligence snapshot is not available in this backend session. Refresh it once to restore Overview and Intelligence."}</p>
                  <button className="primary-button" type="button" onClick={() => refreshSavedChannel(activeWorkspaceChannel)}><RotateCcw size={16} /> Refresh channel intelligence</button>
                </div>
              </section>
            )}

            {channelTab === "autonomy" && (
              <>
                {(() => {
                  const programReady = Boolean(revivalProgram && recoveryJob?.stage === "COMPLETED" && recoveryJob.result && revivalProgram.recovery_job_id === recoveryJob.job_id);
                  const supervisorReady = autopilotHydrated && !autopilotPersistenceError;
                  const channelReady = Boolean(activeWorkspaceChannel && revivalProgram);
                  const canStart = Boolean(programReady && supervisorReady && channelReady);
                  const isIdle = autopilot.status === "IDLE" || autopilot.status === "COMPLETED";
                  const isRunning = autopilot.status === "RUNNING" || autopilot.status === "WAITING_FOR_LEARNING";
                  const isPaused = autopilot.status === "PAUSED";
                  const needsAttention = autopilot.status === "NEEDS_ATTENTION";
                  const waitingApproval = autopilot.status === "WAITING_FOR_FINAL_APPROVAL";
                  const campaignCount = revivalProgram?.ideas.length ?? 0;
                  const completed = autopilot.completedRecommendationIds.length;
                  const blocked = blockingAutopilotProductions(autopilot.blockedProductions).length;
                  const currentStatus = needsAttention ? "Needs attention" : isPaused ? "Paused" : isRunning ? "Running" : waitingApproval ? "Awaiting approval" : autopilot.status === "COMPLETED" ? "Completed" : "Idle";
                  const currentAction = needsAttention ? "Resolve the exception and retry" : isPaused ? "Resume from existing checkpoints" : isRunning ? "Autopilot is working on the current campaign" : waitingApproval ? "Review and approve the finished video" : "Review your campaign, then start autonomy";
                  const textMuted = { color: "#a9b6cf", fontSize: 13, lineHeight: 1.5 };
                  const check = (ok: boolean, label: string) => (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: ok ? "#7de6bd" : "#f4c778", fontSize: 12, fontWeight: 650 }}>
                      {ok ? <ShieldCheck size={15} /> : <CircleAlert size={15} />}{label}
                    </span>
                  );
                  return (
                    <section aria-label="Autonomy command center" style={{ marginBottom: 16, overflow: "hidden", border: "1px solid rgba(150,150,213,.24)", borderRadius: 18, background: "linear-gradient(115deg,rgba(36,33,73,.92),rgba(17,27,47,.97) 60%,rgba(18,42,46,.83))" }}>
                      <div style={{ padding: "23px 25px", display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 20 }}>
                        <div style={{ flex: "1 1 400px", minWidth: 0 }}>
                          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                            <span style={{ color: "#b8adff", fontWeight: 800, fontSize: 11, letterSpacing: 1.2, textTransform: "uppercase", display: "inline-flex", gap: 6, alignItems: "center" }}><Bot size={15} /> Autonomy command center</span>
                            <span style={{ fontSize: 11, border: "1px solid rgba(170,160,230,.32)", borderRadius: 99, padding: "3px 10px", color: needsAttention ? "#ffd399" : isRunning ? "#7de6bd" : "#c4c6e9" }}>{currentStatus}</span>
                          </div>
                          <h2 style={{ margin: "11px 0 7px", fontSize: "clamp(22px,2.4vw,30px)", lineHeight: 1.2 }}>{isRunning ? "Your campaign is in motion" : isPaused ? "Your campaign is paused safely" : needsAttention ? "Your campaign needs attention" : waitingApproval ? "A finished video needs your approval" : "Your channel, one connected workflow"}</h2>
                          <p style={{ ...textMuted, margin: 0, maxWidth: 600 }}>{currentAction}. ReviveAI plans, creates, checks quality, prepares publishing, and learns from releases. Final approval and publishing follow the backend autonomy policy.</p>
                          <div style={{ display: "flex", gap: 15, flexWrap: "wrap", marginTop: 15 }}>
                            {check(programReady, programReady ? "Revival Program ready" : "Revival Program missing")}
                            {check(supervisorReady, supervisorReady ? "Supervisor connected" : "Supervisor unavailable")}
                            <span style={{ color: "#c7bbff", fontSize: 12, display: "inline-flex", alignItems: "center", gap: 6 }}><Bot size={15} /> Backend-controlled approval policy</span>
                          </div>
                        </div>
                        <div style={{ width: 240, maxWidth: "100%", display: "grid", alignContent: "center", gap: 9 }}>
                          {isIdle && <button className="primary-button" disabled={!canStart} type="button" onClick={() => { setAutonomyPreflightConfirmed(false); setAutonomyStartConfirmOpen(true); }} style={{ justifyContent: "center", padding: "14px", borderRadius: 11 }}><Play size={17} /> {autopilot.status === "COMPLETED" ? "Start new campaign" : "Start full autonomy"}</button>}
                          {isRunning && <button className="secondary-button" type="button" onClick={pauseAutopilot} style={{ justifyContent: "center", padding: "13px" }}><Pause size={16} /> Pause automation</button>}
                          {isPaused && <button className="primary-button" type="button" onClick={resumeAutopilot} style={{ justifyContent: "center", padding: "13px" }}><Play size={16} /> Resume automation</button>}
                          {autopilot.scope === "PRODUCTION" && Boolean((autopilot as AutopilotSession & {campaignArchiveId?: string}).campaignArchiveId) && ["PAUSED", "COMPLETED", "IDLE"].includes(autopilot.status) && <button className="secondary-button" type="button" onClick={() => { void restoreArchivedCampaign(); }}>Restore paused campaign</button>}
                          {needsAttention && <button className="primary-button" type="button" onClick={() => { void recoverAutopilotException(); }} style={{ justifyContent: "center", padding: "13px" }}><RotateCcw size={16} /> Retry after fix</button>}
                          {waitingApproval && <span style={{ ...textMuted, textAlign: "center" }}>Open the pending production to approve its final video.</span>}
                          {isIdle && <span style={{ color: "#a8b4ce", fontSize: 11, textAlign: "center" }}>Starts a campaign, never resumes a paused run</span>}
                        </div>
                      </div>
                      <div style={{ borderTop: "1px solid rgba(157,154,216,.17)", background: "rgba(6,15,30,.24)", padding: "17px 25px 19px" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "center", flexWrap: "wrap", marginBottom: 14 }}>
                          <div><span style={{ color: "#aebce0", fontWeight: 750, fontSize: 11, letterSpacing: 1, textTransform: "uppercase" }}>Campaign overview</span><div style={{ marginTop: 5, fontWeight: 750 }}>{activeWorkspaceChannel?.title || "Select a channel"}<span style={{ color: "#a4b4cf", fontWeight: 450 }}> · {campaignCount} planned ideas</span></div></div>
                          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                            <span style={{ color: "#aab7d1", fontSize: 12 }}>Session completed: <strong style={{ color: "#e8eaff" }}>{completed}</strong></span>
                            <span style={{ color: "#aab7d1", fontSize: 12 }}>Blocking: <strong style={{ color: blocked ? "#ffd399" : "#e8eaff" }}>{blocked}</strong></span>
                            <span style={{ color: "#aab7d1", fontSize: 12 }}>Current: <strong style={{ color: "#e8eaff" }}>{autopilot.currentTitle || "None"}</strong></span>
                          </div>
                        </div>
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(175px,1fr))", gap: 9 }}>
                          {([ ["01", "Plan", "Select channel-fit ideas"], ["02", "Create", "Build video and audio"], ["03", "Review", "AI quality + delivery checks"], ["04", "Publish & learn", "Release and measure"] ] as const).map(([n, t, d]) => <div key={n} style={{ border: "1px solid rgba(168,162,228,.18)", borderRadius: 10, padding: "11px 13px", background: "rgba(25,31,57,.67)" }}><div style={{ color: "#b8adff", fontSize: 11, fontWeight: 800 }}>{n} / {t}</div><div style={{ color: "#aebbd2", fontSize: 12, marginTop: 4 }}>{d}</div></div>)}
                        </div>
                        {revivalProgram && revivalProgram.ideas.length > 0 && (
                          <details style={{ marginTop: 14, border: "1px solid rgba(168,162,228,.24)", borderRadius: 12, background: "rgba(13,23,42,.6)" }}>
                            <summary style={{ cursor: "pointer", padding: "13px 15px", color: "#dedaff", fontWeight: 750, fontSize: 13 }}>
                              View campaign plan · {revivalProgram.ideas.length} actual video ideas
                            </summary>
                            <div style={{ padding: "0 13px 13px", display: "grid", gap: 9 }}>
                              <p style={{ ...textMuted, margin: "0 2px 5px" }}>Ideas are listed in the planned production order. Completed session items are marked separately from the saved idea status. Expanding an idea shows its creative direction.</p>
                              {(() => {
                                const ideasById = new Map(revivalProgram.ideas.map(idea => [idea.idea_id, idea]));
                                const orderedIds = [...revivalProgram.weekly_slate]
                                  .sort((a, b) => a.week - b.week || a.slot - b.slot)
                                  .map(slot => slot.idea_id);
                                const orderedIdeas = Array.from(new Set([...orderedIds, ...revivalProgram.ideas.map(idea => idea.idea_id)]))
                                  .map(id => ideasById.get(id))
                                  .filter((idea): idea is (typeof revivalProgram.ideas)[number] => Boolean(idea));
                                const blockedIds = new Set(blockingAutopilotProductions(autopilot.blockedProductions).map(item => item.recommendationId));
                                return orderedIdeas.map((idea, index) => {
                                  const complete = autopilot.completedRecommendationIds.includes(idea.recommendation_id);
                                  const active = autopilot.currentRecommendationId === idea.recommendation_id && isRunning;
                                  const blockedIdea = blockedIds.has(idea.recommendation_id);
                                  const label = blockedIdea ? "Needs attention" : active ? "In progress" : complete ? "Completed this session" : idea.status === "PUBLISHED" ? "Published (saved)" : idea.status === "READY" ? "Ready (saved)" : idea.status === "IN_PRODUCTION" ? "In production (saved)" : "Planned";
                                  const color = blockedIdea ? "#ffcf87" : active ? "#a99aff" : complete || idea.status === "PUBLISHED" ? "#7de6bd" : "#b6c3df";
                                  return (
                                    <details key={idea.idea_id} style={{ border: "1px solid rgba(168,162,228,.18)", borderRadius: 10, padding: "10px 12px", background: "rgba(28,35,64,.72)" }}>
                                      <summary style={{ cursor: "pointer", display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: 9 }}>
                                        <span style={{ fontWeight: 750, fontSize: 13, flex: "1 1 220px" }}>{String(index + 1).padStart(2, "0")}. {idea.title}</span>
                                        <span style={{ fontSize: 11, color, fontWeight: 700 }}>{label}</span>
                                      </summary>
                                      <div style={{ paddingTop: 11, display: "grid", gap: 8, fontSize: 12, color: "#b9c7e1", lineHeight: 1.6 }}>
                                        <div><strong style={{ color: "#ede9ff" }}>Concept:</strong> {idea.concept || "Not provided"}</div>
                                        <div><strong style={{ color: "#ede9ff" }}>Opening hook:</strong> {idea.hook || "Not provided"}</div>
                                        <div><strong style={{ color: "#ede9ff" }}>Format:</strong> {idea.format || "Not specified"} · <strong style={{ color: "#ede9ff" }}>Lane:</strong> {idea.lane} · <strong style={{ color: "#ede9ff" }}>Evidence fit:</strong> {idea.evidence_fit_score}%</div>
                                        {idea.why_now && <div><strong style={{ color: "#ede9ff" }}>Why now:</strong> {idea.why_now}</div>}
                                        {!complete && !blockedIdea && (
                                          <button type="button" className="primary-button"
                                            disabled={!autopilotHydrated || Boolean(autopilotPersistenceError) || autopilot.scope !== "CAMPAIGN" || !["IDLE", "PAUSED"].includes(autopilot.status) || !(autopilot.recoveryJobId || (recoveryJob?.stage === "COMPLETED" && recoveryJob.result))}
                                            title={!autopilotHydrated ? "Waiting for the saved Autopilot state" : autopilotPersistenceError ? "Resolve the Autopilot synchronization error first" : autopilot.scope !== "CAMPAIGN" ? "A one-video trial is already active" : !["IDLE", "PAUSED"].includes(autopilot.status) ? `Autopilot is ${autopilot.status.toLowerCase()}; pause or finish the active run first` : !(autopilot.recoveryJobId || (recoveryJob?.stage === "COMPLETED" && recoveryJob.result)) ? "Complete Recovery Intelligence before starting a trial" : "Start one controlled video; automatic publishing must be disabled on the backend"}
                                            onClick={() => setSingleTrialConfirmation({ recommendationId: idea.recommendation_id, title: idea.title })}>
                                            <Play size={14} /> Run this idea with Autopilot (one video)
                                          </button>
                                        )}
                                      </div>
                                    </details>
                                  );
                                });
                              })()}
                            </div>
                          </details>
                        )}
                        {!programReady && <p style={{ color: "#f2cb89", fontSize: 12, margin: "12px 0 0" }}>Open Directions to restore or create the Revival Program before starting.</p>}
                      </div>
                      {isIdle && autonomyStartConfirmOpen && (
                        <div role="dialog" aria-modal="true" aria-label="Start autonomy preflight" style={{ padding: "19px 25px", borderTop: "1px solid rgba(170,163,238,.35)", background: "rgba(18,20,47,.98)" }}>
                          <h3 style={{ margin: "0 0 10px", fontSize: 17 }}>Confirm campaign preflight</h3>
                          <p style={{ ...textMuted, margin: "0 0 12px" }}>You are starting {campaignCount} planned ideas for <strong>{activeWorkspaceChannel?.title || "the selected channel"}</strong>. This is a new start, not a resume. AI generation can incur provider costs and publishing follows the existing backend configuration.</p>
                          <div style={{ display: "grid", gap: 7, marginBottom: 12 }}>
                            {check(programReady, "Program matches selected recovery")}
                            {check(supervisorReady, "Backend supervisor state is available")}
                            {check(channelReady, "Channel and campaign selected")}
                            <span style={{ color: "#b7c3dc", fontSize: 12 }}>YouTube connection and live publishing safety settings are shown in the monitoring cards below; review them before continuing.</span>
                          </div>
                          <label style={{ display: "flex", gap: 9, alignItems: "flex-start", fontSize: 12, color: "#d5def0", cursor: "pointer", marginBottom: 16 }}><input type="checkbox" checked={autonomyPreflightConfirmed} onChange={(e) => setAutonomyPreflightConfirmed(e.target.checked)} style={{ marginTop: 2 }} />I reviewed the campaign ideas, YouTube connection and publishing settings, and understand that starting autonomy may incur generation costs and publish videos according to backend policy.</label>
                          <div style={{ display: "flex", justifyContent: "flex-end", flexWrap: "wrap", gap: 10 }}><button type="button" className="secondary-button" onClick={() => setAutonomyStartConfirmOpen(false)}>Cancel</button><button className="primary-button" type="button" disabled={!canStart || !autonomyPreflightConfirmed} onClick={() => { setAutonomyStartConfirmOpen(false); setAutonomyPreflightConfirmed(false); startAutopilot(); }}><Play size={15} /> Confirm & start campaign</button></div>
                        </div>
                      )}
                    </section>
                  );
                })()}
                <AutonomousOperationsConsole
                embeddedControls
                status={autopilot.status}
                message={autopilot.message}
                currentTitle={autopilot.currentTitle}
                heartbeatAt={autopilot.lastSupervisorHeartbeatAt}
                startedAt={autopilot.startedAt}
                blockedCount={blockingAutopilotProductions(autopilot.blockedProductions).length}
                archivedCount={archivedAutopilotProductions(autopilot.blockedProductions).length}
                completedCount={autopilot.completedRecommendationIds.length}
                onPause={pauseAutopilot}
                onResume={
                  autopilot.status === "NEEDS_ATTENTION"
                    ? recoverAutopilotException
                    : resumeAutopilot
                }
              />
              </>
            )}

            {channelTab === "costs" && <ProductionCostDashboard cacheKey={currentUser.uid} />}

            {channelTab === "productions" && (
              <>
                <YouTubePublishingQueue program={revivalProgram} />
                <ChannelProductionsPanel
                  channel={activeWorkspaceChannel}
                  onOpenProduction={(production) => { void openWorkspaceProduction(activeWorkspaceChannel, production); }}
                  onNewProduction={result ? openNewProductionFromChannel : () => refreshSavedChannel(activeWorkspaceChannel)}
                />
              </>
            )}
          </section>
        )}

        {!workflowRestorePending && activeWorkspaceChannel && workspaceView === "production" && !productionBriefJob && (
          <section className="production-restore-failure glass-card" role="alert">
            <AlertTriangle size={26} aria-hidden="true" />
            <div>
              <span className="eyebrow">Production restore</span>
              <h2>We couldn't reopen this production.</h2>
              <p>{workspaceRestoreError || "The saved Production Brief could not be loaded."}</p>
              {legacyAdoptionStatus?.eligible && legacyAdoptionStatus.legacy_items > 0 && (
                <div className="legacy-adoption-callout">
                  <ShieldCheck size={20} aria-hidden="true" />
                  <div>
                    <strong>Legacy workspace found</strong>
                    <span>
                      {legacyAdoptionStatus.legacy_productions > 0
                        ? `${legacyAdoptionStatus.legacy_productions} pre-isolation production${legacyAdoptionStatus.legacy_productions === 1 ? "" : "s"} can be copied into this authenticated workspace.`
                        : "Pre-isolation ReviveAI data can be copied into this authenticated workspace."}
                    </span>
                    <small>The original legacy files remain untouched as rollback copies.</small>
                  </div>
                </div>
              )}
              {legacyAdoptionError && <div className="legacy-adoption-error" role="status">{legacyAdoptionError}</div>}
              <div className="production-restore-actions">
                <button className="secondary-button" type="button" onClick={() => { setWorkspaceView("channel"); setActiveProductionId(null); setChannelTab("overview"); window.scrollTo({ top: 0, behavior: "smooth" }); }}>← Back to Lifecycle</button>
                {activeWorkspaceProduction && legacyAdoptionStatus?.eligible && legacyAdoptionStatus.legacy_items > 0 && (
                  <button
                    className="primary-button"
                    type="button"
                    disabled={legacyAdoptionPending}
                    onClick={() => { void adoptLegacyWorkspaceAndRetry(activeWorkspaceChannel, activeWorkspaceProduction); }}
                  >
                    {legacyAdoptionPending ? <LoaderCircle className="spin" size={16} /> : <ShieldCheck size={16} />}
                    {legacyAdoptionPending ? "Recovering workspace…" : "Recover legacy workspace & reopen"}
                  </button>
                )}
                {activeWorkspaceProduction && !(legacyAdoptionStatus?.eligible && legacyAdoptionStatus.legacy_items > 0) && (
                  <button className="primary-button" type="button" onClick={() => { void openWorkspaceProduction(activeWorkspaceChannel, activeWorkspaceProduction); }}><RotateCcw size={16} /> Retry</button>
                )}
                <button className="secondary-button" type="button" onClick={() => { setWorkspaceView("channel"); setActiveProductionId(null); setChannelTab("productions"); }}>Back to productions</button>
              </div>
            </div>
          </section>
        )}

        {!workflowRestorePending && activeWorkspaceChannel && workspaceView === "production" && productionBriefJob && (
          <section className={`production-workspace ${autopilotOwnsCurrentProduction ? "autopilot-owned" : ""} ${finalApprovalMode ? "final-approval-mode" : ""}`}>
            <nav className="production-lifecycle-breadcrumb" aria-label="Production location">
              <button type="button" onClick={() => returnFromProduction("overview")}>{activeWorkspaceChannel.title}</button>
              <span aria-hidden="true">/</span>
              <button type="button" onClick={() => returnFromProduction()}>{productionReturnLocation === "workspace" ? "Workspace" : productionReturnLocation === "productions" ? "Productions" : productionReturnLocation === "autonomy" ? "Autonomy" : productionReturnLocation === "intelligence" ? "Intelligence" : productionReturnLocation === "directions" ? "Explore ideas" : productionReturnLocation === "soundtracks" ? "Soundtracks" : productionReturnLocation === "costs" ? "Production costs" : "Overview"}</button>
              <span aria-hidden="true">/</span>
              <span aria-current="page">{visibleProductionTitle}</span>
            </nav>
            <div className="production-workspace-heading">
              <div>
                <span className="eyebrow">Create · {workspaceStageLabel}</span>
                <h1>{visibleProductionTitle}</h1>
                <p>{finalVideoHumanApproved && deliveryPackage ? "Approved video and delivery package ready for publishing preparation." : deliveryPackage ? "Delivery package created. ReviveAI will complete eligible AI approvals and schedule publishing automatically when autonomy is enabled." : "Your work is saved. Continue from the current production step, or return to your channel lifecycle."}</p>
              </div>
              <div className="production-heading-actions">
                <button className="secondary-button" type="button" onClick={() => returnFromProduction()}>← Back to {productionReturnLocation === "workspace" ? "workspace" : productionReturnLocation === "productions" ? "productions" : productionReturnLocation === "autonomy" ? "autonomy" : "channel"}</button>
                {!finalVideoHumanApproved && (autopilotOwnsCurrentProduction ? (
                  <button className="secondary-button production-autopilot-control" type="button" onClick={takeControlOfCurrentProduction}>
                    <Hand size={16} /> Take control
                  </button>
                ) : (
                  <button
                    className="primary-button production-autopilot-control"
                    type="button"
                    disabled={singleTrialSubmitting || !autopilotHydrated || !recoveryJob?.result || recoveryJob.stage !== "COMPLETED"}
                    onClick={() => {
                      if (!productionBriefJob) return;
                      setSavedProductionAutopilotConfirmation({
                        productionId: productionBriefJob.job_id,
                        title: productionBriefJob.result?.creative_direction?.working_title || productionBriefJob.source_snapshot.recommendation.title,
                        switching: Boolean(autopilot.currentProductionJobId && autopilot.currentProductionJobId !== productionBriefJob.job_id),
                      });
                    }}
                    title={!recoveryJob?.result || recoveryJob.stage !== "COMPLETED" ? "Restore Recovery Intelligence before starting AI Autopilot." : "Delegate this production to AI Autopilot and continue from its current stage"}
                  >
                    <Bot size={16} /> Run with AI Autopilot
                  </button>
                ))}
                {productionReturnLocation !== "productions" && <button className="secondary-button" type="button" onClick={() => returnFromProduction("productions")}>All productions</button>}
              </div>
            </div>

            {/* This diagnostic recovery action must not disappear because a creator-loaded
                production differs from the active server checkpoint. The click handler
                re-reads the authoritative session and validates both IDs before POST. */}
            {normalizeProductionTitle(visibleProductionTitle) === "the tiny symphony conductor"
              && productionBriefJob.stage === "FAILED"
              && (
              <section className="glass-card" style={{ padding: 17, marginBottom: 18, border: "1px solid rgba(170,151,255,.32)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
                  <div style={{ display: "grid", gap: 5 }}>
                    <span className="eyebrow">One-time recovery · No regeneration</span>
                    <strong>Replacement brief already exists</strong>
                    <small>Reconnect the saved replacement brief to AI Autopilot. No Gemini generation is requested by this action.</small>
                  </div>
                  <button className="primary-button" type="button" disabled={briefReconcilePending}
                    onClick={() => { setBriefReconcileError(null); setBriefReconcileConfirmOpen(true); }}>
                    <ShieldCheck size={16} /> Reconnect existing brief
                  </button>
                </div>
                {briefReconcileError && <p role="alert" style={{ color: "#f3b7b7", marginBottom: 0 }}>{briefReconcileError}</p>}
              </section>
            )}

            {approvedAudioMaster?.result?.delivery_video?.asset_url && (
              <section className="glass-card" aria-label="Finished production video" style={{ padding: 16, marginBottom: 18 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
                  <div><span className="eyebrow">FINISHED VIDEO</span><h2 style={{ margin: "6px 0" }}>Watch your production</h2>
                    <p style={{ margin: 0, opacity: .8 }}>Preview is available independently of approval and publishing status.</p></div>
                  <a className="secondary-button" href={audioAssetUrl(approvedAudioMaster.result.delivery_video.asset_url)} target="_blank" rel="noopener noreferrer">Open video</a>
                </div>
                <video controls playsInline preload="metadata" style={{ display: "block", width: "100%", maxHeight: 480, background: "#080b14", borderRadius: 12 }} src={audioAssetUrl(approvedAudioMaster.result.delivery_video.asset_url)} />
              </section>
            )}

            {autopilot.currentRecommendationId === productionBriefJob.recommendation_id && autopilot.status !== "IDLE" && (
              <AutopilotLiveMonitor
                title={visibleProductionTitle}
                status={autopilot.status}
                message={autopilot.message}
                attentionStage={autopilot.attentionStage}
                currentStartedAt={autopilot.currentStartedAt}
                activityStartedAt={autopilot.updatedAt}
                productionJob={productionBriefJob}
                mediaJob={mediaStudioJob}
                assemblyJob={finalAssemblyJob}
                audioJob={audioFinishingJob || approvedAudioMaster}
                qc={deliveryQcReport}
                deliveryPackageReady={Boolean(deliveryPackage)}
                publishingDraft={publishingDraft}
                publishingPackaged={publishingPackaged}
                finalHumanApproved={finalVideoHumanApproved}
                onPause={pauseAutopilot}
                onResume={resumeAutopilot}
                onRecover={recoverAutopilotException}
                recoveryPending={autopilotRecoveryPending}
                watchdogStatus={autopilotWatchdog.status}
                watchdogMessage={autopilotWatchdog.message}
              />
            )}

            {!finalApprovalMode && autopilotOwnsCurrentProduction && autopilotProductionPanel && (
              <div className={autopilot.status === "NEEDS_ATTENTION" ? "autopilot-attention-workspace" : "autopilot-review-workspace"}>
                {autopilotProductionPanel}
              </div>
            )}

            {finalApprovalMode ? (
              <div className="final-approval-handoff">
                {productionDeliverPanel}
              </div>
            ) : autopilotOwnsCurrentProduction ? null : (
              <GuidedProductionWorkspace
                title={visibleProductionTitle}
                subtitle={workspaceStageLabel}
                stages={guidedProductionStages}
                completed={finalVideoHumanApproved}
              />
            )}
          </section>
        )}
      </main>

      {savedProductionAutopilotConfirmation && (
        <div className="revive-confirm-backdrop" role="presentation"
          onMouseDown={() => { if (!singleTrialSubmitting) setSavedProductionAutopilotConfirmation(null); }}>
          <section className="revive-confirm-dialog" role="alertdialog" aria-modal="true"
            aria-labelledby="saved-production-autopilot-title" aria-describedby="saved-production-autopilot-description"
            onMouseDown={(event) => event.stopPropagation()}
            onKeyDown={(event) => { if (event.key === "Escape" && !singleTrialSubmitting) { event.stopPropagation(); setSavedProductionAutopilotConfirmation(null); } }}
            style={{ width: "min(500px, calc(100vw - 32px))", padding: 24, display: "grid", gap: 17, boxSizing: "border-box" }}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 13 }}>
              <div style={{ display: "grid", placeItems: "center", width: 42, height: 42, flexShrink: 0, borderRadius: 13,
                background: "rgba(139, 111, 255, .18)", border: "1px solid rgba(171, 154, 255, .33)", color: "#c8b7ff" }}>
                <Bot size={21} aria-hidden="true" />
              </div>
              <div style={{ display: "grid", gap: 6, flex: 1, minWidth: 0 }}>
                <span className="eyebrow">ReviveAI · AI Autopilot</span>
                <h2 id="saved-production-autopilot-title" style={{ margin: 0, fontSize: 21, lineHeight: 1.25 }}>
                  {savedProductionAutopilotConfirmation.switching ? "Switch autonomous production?" : "Run this production autonomously?"}
                </h2>
              </div>
              <button type="button" className="secondary-button" aria-label="Close confirmation" disabled={singleTrialSubmitting}
                onClick={() => setSavedProductionAutopilotConfirmation(null)} style={{ padding: "7px 11px", minWidth: 0 }}>✕</button>
            </div>
            <div id="saved-production-autopilot-description" style={{ display: "grid", gap: 12, color: "#b9c4e1", lineHeight: 1.6 }}>
              <div style={{ padding: "12px 14px", background: "rgba(135, 115, 239, .10)", border: "1px solid rgba(166, 151, 255, .25)", borderRadius: 11 }}>
                <span style={{ display: "block", color: "#aeadde", fontSize: 11, fontWeight: 750, textTransform: "uppercase", letterSpacing: ".08em" }}>Selected production</span>
                <strong style={{ display: "block", marginTop: 4, color: "#f2efff", fontSize: 15, overflowWrap: "anywhere" }}>{savedProductionAutopilotConfirmation.title}</strong>
              </div>
              <p style={{ margin: 0 }}>
                ReviveAI will delegate planning, visual generation, audio, quality reviews and eligible YouTube publishing to the backend Autopilot.
              </p>
              {savedProductionAutopilotConfirmation.switching && (
                <div role="note" style={{ display: "flex", gap: 10, padding: "11px 12px", borderRadius: 10,
                  border: "1px solid rgba(244, 191, 111, .36)", background: "rgba(244, 191, 111, .08)", color: "#f3d7a7", fontSize: 12.5 }}>
                  <AlertTriangle size={17} style={{ flexShrink: 0, marginTop: 2 }} aria-hidden="true" />
                  <span>The current Autopilot session will be archived. Existing productions, generated assets and checkpoints will be preserved.</span>
                </div>
              )}
              <div role="note" style={{ display: "flex", gap: 10, padding: "11px 12px", borderRadius: 10,
                border: "1px solid rgba(166, 151, 255, .25)", background: "rgba(135, 115, 239, .08)", color: "#c9c0f6", fontSize: 12.5 }}>
                <ShieldCheck size={17} style={{ flexShrink: 0, marginTop: 2 }} aria-hidden="true" />
                <span><strong>Cost and publishing notice:</strong> AI generation may incur charges up to your configured limits. Automatic YouTube publishing may make this video public after mandatory quality gates pass.</span>
              </div>
            </div>
            {savedProductionStartError && (
              <p role="alert" style={{ margin: 0, padding: "11px 13px", borderRadius: 10,
                border: "1px solid rgba(245, 132, 146, .4)", background: "rgba(160, 55, 83, .12)",
                color: "#ffd0d7", fontSize: 13, lineHeight: 1.5 }}>
                {savedProductionStartError}
              </p>
            )}
            <div className="revive-confirm-actions" style={{ display: "flex", justifyContent: "flex-end", gap: 10, flexWrap: "wrap" }}>
              <button className="secondary-button" type="button" disabled={singleTrialSubmitting}
                onClick={() => setSavedProductionAutopilotConfirmation(null)}>Cancel</button>
              <button className="primary-button" type="button" disabled={singleTrialSubmitting || savedProductionAutopilotConfirmation.productionId !== productionBriefJob?.job_id}
                onClick={() => { void startSavedProductionAutopilot(); }}>
                {singleTrialSubmitting ? <LoaderCircle className="spinner" size={16} aria-hidden="true" /> : <Bot size={16} aria-hidden="true" />}
                {singleTrialSubmitting ? "Starting…" : savedProductionAutopilotConfirmation.switching ? "Archive & start Autopilot" : "Start AI Autopilot"}
              </button>
            </div>
          </section>
        </div>
      )}

      {briefReconcileConfirmOpen && (
        <div className="revive-confirm-backdrop" role="presentation" onMouseDown={() => { if (!briefReconcilePending) setBriefReconcileConfirmOpen(false); }}>
          <section className="revive-confirm-dialog" role="alertdialog" aria-modal="true"
            aria-labelledby="brief-reconcile-title" aria-describedby="brief-reconcile-description"
            onMouseDown={(event) => event.stopPropagation()}
            onKeyDown={(event) => { if (event.key === "Escape" && !briefReconcilePending) setBriefReconcileConfirmOpen(false); }}
            style={{ width: "min(490px, calc(100vw - 32px))", padding: 24, display: "grid", gap: 17 }}>
            <div style={{ display: "flex", gap: 13, alignItems: "flex-start" }}>
              <div style={{ display: "grid", placeItems: "center", width: 42, height: 42, flexShrink: 0, borderRadius: 13,
                background: "rgba(139,111,255,.18)", color: "#c8b7ff", border: "1px solid rgba(171,154,255,.33)" }}><ShieldCheck size={21} /></div>
              <div><span className="eyebrow">ReviveAI · Safe recovery</span>
                <h2 id="brief-reconcile-title" style={{ margin: "6px 0", fontSize: 21 }}>Reconnect existing production brief?</h2></div>
            </div>
            <div id="brief-reconcile-description" style={{ display: "grid", gap: 12, color: "#b9c4e1", lineHeight: 1.6 }}>
              <p style={{ margin: 0 }}>The Tiny Symphony Conductor already has a replacement production brief. ReviveAI will adopt that saved job and resume the backend supervisor.</p>
              <div style={{ padding: 12, borderRadius: 10, background: "rgba(135,115,239,.10)", border: "1px solid rgba(166,151,255,.25)" }}>
                <span className="eyebrow">Existing replacement</span>
                <code style={{ display: "block", color: "#f2efff", overflowWrap: "anywhere", marginTop: 5 }}>production_e75711ad5c094141aa87354b6422ef20</code>
              </div>
              <p style={{ margin: 0, fontSize: 13 }}>This reconciliation does not generate another brief or clear historical retry counts. Once resumed, later autonomous stages may incur generation costs and publish according to your channel settings.</p>
              {briefReconcileError && <p role="alert" style={{ color: "#f3b7b7", margin: 0 }}>{briefReconcileError}</p>}
            </div>
            <div className="revive-confirm-actions" style={{ display: "flex", justifyContent: "flex-end", gap: 10, flexWrap: "wrap" }}>
              <button type="button" className="secondary-button" disabled={briefReconcilePending} onClick={() => setBriefReconcileConfirmOpen(false)}>Cancel</button>
              <button type="button" className="primary-button" disabled={briefReconcilePending} onClick={() => { void reconcileExistingProductionBrief(); }}>
                {briefReconcilePending ? <LoaderCircle className="spinner" size={16} /> : <ShieldCheck size={16} />}
                {briefReconcilePending ? "Reconciling…" : "Reconnect saved brief"}
              </button>
            </div>
          </section>
        </div>
      )}

      {singleTrialConfirmation && (
        <div className="revive-confirm-backdrop" role="presentation"
          onMouseDown={() => { if (!singleTrialSubmitting) setSingleTrialConfirmation(null); }}>
          <section className="revive-confirm-dialog" role="alertdialog" aria-modal="true"
            aria-labelledby="single-trial-confirm-title" aria-describedby="single-trial-confirm-description"
            onMouseDown={(event) => event.stopPropagation()}
            onKeyDown={(event) => { if (event.key === "Escape" && !singleTrialSubmitting) { event.stopPropagation(); setSingleTrialConfirmation(null); } }}
            style={{ width: "min(480px, calc(100vw - 32px))", padding: 24, display: "grid", gap: 17, boxSizing: "border-box" }}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 13 }}>
              <div style={{ display: "grid", placeItems: "center", width: 42, height: 42, flexShrink: 0, borderRadius: 13,
                background: "rgba(139, 111, 255, .18)", border: "1px solid rgba(171, 154, 255, .33)", color: "#c8b7ff" }}>
                <Bot size={21} aria-hidden="true" />
              </div>
              <div style={{ display: "grid", gap: 6, flex: 1, minWidth: 0 }}>
                <span className="eyebrow">ReviveAI · Controlled Autopilot trial</span>
                <h2 id="single-trial-confirm-title" style={{ margin: 0, fontSize: 21, lineHeight: 1.25 }}>Start one autonomous video?</h2>
              </div>
              <button type="button" className="secondary-button" aria-label="Close confirmation" disabled={singleTrialSubmitting}
                onClick={() => setSingleTrialConfirmation(null)} style={{ padding: "7px 11px", minWidth: 0 }}>✕</button>
            </div>
            <div id="single-trial-confirm-description" style={{ display: "grid", gap: 12, color: "#b9c4e1", lineHeight: 1.6 }}>
              <div style={{ padding: "12px 14px", background: "rgba(135, 115, 239, .10)", border: "1px solid rgba(166, 151, 255, .25)", borderRadius: 11 }}>
                <span style={{ display: "block", color: "#aeadde", fontSize: 11, fontWeight: 750, textTransform: "uppercase", letterSpacing: ".08em" }}>Selected production</span>
                <strong style={{ display: "block", marginTop: 4, color: "#f2efff", fontSize: 15, overflowWrap: "anywhere" }}>{singleTrialConfirmation.title}</strong>
              </div>
              <p style={{ margin: 0 }}>ReviveAI will start <strong style={{ color: "#f2efff" }}>one autonomous production</strong> and archive your current campaign state for restoration afterward.</p>
              <div role="note" style={{ display: "flex", gap: 10, padding: "11px 12px", borderRadius: 10,
                border: "1px solid rgba(244, 191, 111, .36)", background: "rgba(244, 191, 111, .08)", color: "#f3d7a7", fontSize: 12.5 }}>
                <AlertTriangle size={17} style={{ flexShrink: 0, marginTop: 2 }} aria-hidden="true" />
                <span><strong>Publishing safety:</strong> Automatic YouTube publishing must be disabled in the backend. The server enforces this requirement before starting.</span>
              </div>
            </div>
            <div className="revive-confirm-actions" style={{ display: "flex", justifyContent: "flex-end", gap: 10, flexWrap: "wrap" }}>
              <button className="secondary-button" type="button" disabled={singleTrialSubmitting}
                onClick={() => setSingleTrialConfirmation(null)}>Cancel</button>
              <button className="primary-button" type="button" disabled={singleTrialSubmitting}
                onClick={() => { void startSelectedTrial(singleTrialConfirmation.recommendationId, singleTrialConfirmation.title); }}>
                {singleTrialSubmitting ? <LoaderCircle className="spinner" size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}
                {singleTrialSubmitting ? "Starting…" : "Start one video"}
              </button>
            </div>
          </section>
        </div>
      )}

      {finalApprovalDialog && (
        <div className="revive-confirm-backdrop" role="presentation" onMouseDown={() => { if (!finalHumanApprovalPending) setFinalApprovalDialog(null); }}>
          <section className="revive-confirm-dialog" role="dialog" aria-modal="true"
            aria-labelledby="final-creator-approval-title" aria-describedby="final-creator-approval-description"
            onMouseDown={event => event.stopPropagation()}
            style={{ width: "min(480px, calc(100vw - 32px))", padding: 24, display: "grid", gap: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
              <div style={{ display: "grid", gap: 7 }}>
                <span className="eyebrow">ReviveAI · Creator approval</span>
                <h2 id="final-creator-approval-title" style={{ margin: 0 }}>
                  {finalApprovalDialog === "OVERRIDE" ? "Approve despite AI warnings?" : "Approve finished video?"}
                </h2>
              </div>
              <button type="button" className="secondary-button" aria-label="Close approval confirmation"
                disabled={finalHumanApprovalPending} onClick={() => setFinalApprovalDialog(null)}
                style={{ padding: "7px 11px", minWidth: 0 }}>✕</button>
            </div>
            <p id="final-creator-approval-description" style={{ margin: 0, color: "#b9c4e1", lineHeight: 1.6 }}>
              {finalApprovalDialog === "OVERRIDE"
                ? "You are accepting the finished video's creative-quality differences. ReviveAI will retain the original AI findings and record your explicit decision."
                : "Record your approval of this finished video so it can proceed to YouTube publishing. This action does not upload or publish the video."}
            </p>
            {finalApprovalDialog === "OVERRIDE" && (
              <div style={{ display: "grid", gap: 9 }}>
                {finalHumanOverrideReason && <div role="note" style={{ padding: 12, border: "1px solid rgba(246,185,107,.40)", background: "rgba(246,185,107,.08)", borderRadius: 10, fontSize: 13, lineHeight: 1.5 }}>
                  <strong style={{ display: "block", marginBottom: 4, color: "#ffd397" }}>AI finding</strong>
                  {finalHumanOverrideReason}
                </div>}
                <label htmlFor="final-human-override-note" style={{ fontSize: 13, fontWeight: 600 }}>Reason for overriding (required)</label>
                <textarea id="final-human-override-note" rows={3} maxLength={1000} value={finalOverrideNote}
                  onChange={event => setFinalOverrideNote(event.target.value)}
                  disabled={finalHumanApprovalPending}
                  style={{ width: "100%", boxSizing: "border-box", borderRadius: 10, border: "1px solid rgba(150,160,208,.42)", background: "#151c32", padding: 12, color: "#f3f2ff", font: "inherit", resize: "vertical" }} />
              </div>
            )}
            <div className="revive-confirm-actions" style={{ justifyContent: "flex-end", gap: 10, flexWrap: "wrap" }}>
              <button type="button" className="secondary-button" disabled={finalHumanApprovalPending}
                onClick={() => setFinalApprovalDialog(null)}>Cancel</button>
              <button type="button" className="primary-button"
                disabled={finalHumanApprovalPending || (finalApprovalDialog === "OVERRIDE" && !finalOverrideNote.trim())}
                onClick={() => {
                  const method = finalApprovalDialog;
                  const reason = finalOverrideNote.trim();
                  if (method === "OVERRIDE" && !reason) return;
                  setFinalApprovalDialog(null);
                  void approveFinalVideoAsHuman(method === "OVERRIDE" ? reason : undefined);
                }}>
                {finalApprovalDialog === "OVERRIDE" ? "Confirm human override" : "Approve finished video"}
              </button>
            </div>
          </section>
        </div>
      )}

      {manageChannelsOpen && workspaceView === "workspace" && (
        <div className="revive-confirm-backdrop" role="presentation" onMouseDown={() => setManageChannelsOpen(false)}>
          <section className="revive-confirm-dialog" role="dialog" aria-modal="true"
            aria-labelledby="manage-channels-title" onMouseDown={(event) => event.stopPropagation()}
            style={{ width: "min(650px, calc(100vw - 32px))", maxHeight: "85vh", overflowY: "auto", padding: 24 }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
              <div>
                <span className="eyebrow">Workspace administration</span>
                <h2 id="manage-channels-title" style={{ margin: "6px 0" }}>Manage channels</h2>
                <p style={{ margin: 0, opacity: .78 }}>Open a workspace or remove a saved channel. Creative directions are managed inside each channel.</p>
              </div>
              <button className="secondary-button" type="button" aria-label="Close channel management"
                onClick={() => setManageChannelsOpen(false)}>Close</button>
            </div>
            <div style={{ display: "grid", gap: 9, marginTop: 20 }}>
              {workspace.channels.map((channel) => (
                <div key={channel.channelId} style={{ display: "flex", alignItems: "center", gap: 12,
                  padding: "12px", border: "1px solid rgba(151,160,206,.20)", borderRadius: 12 }}>
                  {channel.thumbnailUrl ? <img src={channel.thumbnailUrl} alt="" style={{ width: 36, height: 36, objectFit: "cover", borderRadius: 9 }} />
                    : <span className="workspace-channel-management-avatar">{channel.title.slice(0, 1).toUpperCase()}</span>}
                  <span style={{ display: "grid", gap: 3, flex: 1, minWidth: 0 }}>
                    <strong style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{channel.title}</strong>
                    <small style={{ opacity: .72 }}>{channel.handle || "YouTube channel"}</small>
                  </span>
                  <button className="secondary-button" type="button" onClick={() => {
                    setManageChannelsOpen(false); void openWorkspaceChannel(channel);
                  }}>Open</button>
                  <button className="workspace-remove-channel-button" type="button" onClick={() => {
                    setManageChannelsOpen(false); removeSavedChannel(channel);
                  }}><Trash2 size={15} /> Remove</button>
                </div>
              ))}
            </div>
            <p style={{ fontSize: 12, opacity: .7, marginTop: 16 }}>Removal affects the saved workspace list, not the YouTube channel itself.</p>
          </section>
        </div>
      )}

      {channelPendingRemoval && (
        <div className="revive-confirm-backdrop" role="presentation" onMouseDown={() => setChannelPendingRemoval(null)}>
          <section
            className="revive-confirm-dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="remove-channel-title"
            aria-describedby="remove-channel-description"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="revive-confirm-icon"><Trash2 size={20} /></div>
            <div className="revive-confirm-copy">
              <span className="eyebrow">Workspace channel</span>
              <h2 id="remove-channel-title">Remove {channelPendingRemoval.title}?</h2>
              <p id="remove-channel-description">
                This channel will be removed from your ReviveAI workspace list. You can add and analyze the same YouTube channel again later.
              </p>
            </div>
            <div className="revive-confirm-actions">
              <button className="secondary-button" type="button" onClick={() => setChannelPendingRemoval(null)}>Cancel</button>
              <button className="revive-confirm-remove" type="button" onClick={confirmRemoveSavedChannel}>
                <Trash2 size={16} /> Remove channel
              </button>
            </div>
          </section>
        </div>
      )}


      <footer>
        <span>ReviveAI · Creator Workspace</span>
        <span>{workspaceView === "workspace" ? "Private creator workspace" : workspaceView === "production" ? workspaceStageLabel : workspaceView === "channel" ? "Channel intelligence + productions" : "Add YouTube channel"}</span>
      </footer>
    </div>
  );


}

export default function App() {
  const { user, loading, error } = useAuth();
  const [adminAllowed, setAdminAllowed] = useState(false);
  const [adminView, setAdminView] = useState(false);
  useEffect(() => {
    if (!user) { setAdminAllowed(false); setAdminView(false); return; }
    let active = true;
    fetch(`${API_BASE_URL}/api/v1/admin/me`, { credentials: "include" })
      .then(response => { if (active) setAdminAllowed(response.ok); })
      .catch(() => { if (active) setAdminAllowed(false); });
    return () => { active = false; };
  }, [user?.uid]);
  if (loading) return <AuthLoadingScreen />;
  if (!user) return <SignInPage serviceError={error} />;
  if (adminView && adminAllowed) return <PlatformAdminConsole onBack={() => setAdminView(false)} />;
  return <>
    {adminAllowed && <button type="button" onClick={() => setAdminView(true)} style={{ position: "fixed", right: 18, bottom: 18, zIndex: 2000, border: "1px solid #6454b9", borderRadius: 12, padding: "12px 16px", background: "#292247", color: "#eee8ff", cursor: "pointer" }}>Platform Administration</button>}
    <CreatorApp key={user.uid} />
  </>;
}