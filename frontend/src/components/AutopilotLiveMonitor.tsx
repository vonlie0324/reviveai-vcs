import {
  Activity,
  Bot,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Film,
  LoaderCircle,
  Pause,
  Play,
  Radio,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type {
  AudioFinishingJob,
  DeliveryQcReport,
  FinalAssemblyJob,
  MediaStudioJob,
  ProductionBriefJob,
  PublishingDraft,
} from "../types";

type AutopilotUiStatus = "RUNNING" | "PAUSED" | "NEEDS_ATTENTION" | "WAITING_FOR_FINAL_APPROVAL" | "WAITING_FOR_LEARNING" | "COMPLETED" | "IDLE";
type WatchdogStatus = "IDLE" | "CHECKING" | "RECOVERED" | "WAITING";

type AttentionStage =
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

interface Props {
  title: string;
  status: AutopilotUiStatus;
  message: string;
  attentionStage?: AttentionStage;
  currentStartedAt?: string | null;
  activityStartedAt?: string | null;
  productionJob: ProductionBriefJob | null;
  mediaJob: MediaStudioJob | null;
  assemblyJob: FinalAssemblyJob | null;
  audioJob: AudioFinishingJob | null;
  qc: DeliveryQcReport | null;
  deliveryPackageReady: boolean;
  publishingDraft: PublishingDraft | null;
  publishingPackaged: boolean;
  finalHumanApproved: boolean;
  onPause: () => void;
  onResume: () => void;
  onRecover?: () => void | Promise<void>;
  recoveryPending?: boolean;
  watchdogStatus?: WatchdogStatus;
  watchdogMessage?: string;
}

type ActivityId =
  | "PLAN_BUILD"
  | "PLAN_REVIEW"
  | "REFERENCE_GENERATE"
  | "REFERENCE_REVIEW"
  | "KEYFRAMES_GENERATE"
  | "KEYFRAMES_REVIEW"
  | "CLIPS_GENERATE"
  | "CLIPS_REVIEW"
  | "ASSEMBLY_RENDER"
  | "ASSEMBLY_REVIEW"
  | "AUDIO_RENDER"
  | "AUDIO_REVIEW"
  | "DELIVERY_QC"
  | "DELIVERY_PACKAGE"
  | "PUBLISHING_GENERATE"
  | "PUBLISHING_REVIEW"
  | "FINAL_PACKAGE"
  | "FINAL_HUMAN";

interface ActivitySpec {
  id: ActivityId;
  label: string;
  helper: string;
  expectedSeconds: number;
  phase: "Plan" | "Visuals" | "Audio" | "AI review" | "Your approval";
}

function objectDetail(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

function aiDecisionPassed(value: unknown): boolean {
  return String(objectDetail(value).decision || "").toUpperCase() === "PASS";
}

function parseTime(value?: string | null): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function clamp(value: number, min = 0, max = 1): number {
  return Math.max(min, Math.min(max, value));
}

function humanDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) return remainingSeconds ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
}

function compactDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  if (seconds < 45) return "<1 min";
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
}

function etaRange(seconds: number): string {
  if (seconds <= 20) return "Less than 1 min remaining";
  const low = Math.max(1, Math.floor((seconds * 0.72) / 60));
  const high = Math.max(low + 1, Math.ceil((seconds * 1.35) / 60));
  if (high < 60) return `About ${low}–${high} min remaining`;
  const lowHours = Math.max(1, Math.floor(low / 60));
  const highHours = Math.max(lowHours, Math.ceil(high / 60));
  return lowHours === highHours ? `About ${lowHours} hr remaining` : `About ${lowHours}–${highHours} hr remaining`;
}

function ago(seconds: number): string {
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${Math.round(seconds)} sec ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  return `${Math.floor(seconds / 3600)} hr ago`;
}

function progressRatio(current?: number | null, total?: number | null): number | null {
  if (!total || total <= 0 || current == null) return null;
  return clamp(current / total, 0, 0.98);
}

function maxTimestamp(values: Array<string | null | undefined>): number | null {
  let latest: number | null = null;
  for (const value of values) {
    const parsed = parseTime(value);
    if (parsed != null && (latest == null || parsed > latest)) latest = parsed;
  }
  return latest;
}

function buildActivities(requiredShots: number): ActivitySpec[] {
  const shots = Math.max(1, requiredShots || 1);
  return [
    { id: "PLAN_BUILD", label: "Building production plan", helper: "Creative direction, storyboard, prompts, and initial publishing intent", expectedSeconds: 110, phase: "Plan" },
    { id: "PLAN_REVIEW", label: "Reviewing plan + text fidelity", helper: "Independent AI critic checks recovery direction and production consistency", expectedSeconds: 35, phase: "Plan" },
    { id: "REFERENCE_GENERATE", label: "Generating visual identity reference", helper: "Creating the canonical character reference used by every scene", expectedSeconds: 80, phase: "Visuals" },
    { id: "REFERENCE_REVIEW", label: "Reviewing visual identity", helper: "AI critic compares the reference with locked identity and historical evidence", expectedSeconds: 35, phase: "Visuals" },
    { id: "KEYFRAMES_GENERATE", label: "Generating storyboard keyframes", helper: `Creating ${shots} scene${shots === 1 ? "" : "s"} from the approved visual identity`, expectedSeconds: Math.max(110, shots * 34), phase: "Visuals" },
    { id: "KEYFRAMES_REVIEW", label: "Reviewing storyboard fidelity", helper: "Checking character continuity, action, framing, props, and setting", expectedSeconds: Math.max(55, shots * 14), phase: "Visuals" },
    { id: "CLIPS_GENERATE", label: "Animating scenes with Veo", helper: `Generating motion for ${shots} scene${shots === 1 ? "" : "s"}; this is usually the longest step`, expectedSeconds: Math.max(220, shots * 65), phase: "Visuals" },
    { id: "CLIPS_REVIEW", label: "Reviewing motion fidelity", helper: "AI critic checks each clip and regenerates only failed scenes", expectedSeconds: Math.max(70, shots * 18), phase: "Visuals" },
    { id: "ASSEMBLY_RENDER", label: "Assembling visual master", helper: "Combining approved clips, timing, and captions into one silent master", expectedSeconds: 85, phase: "Visuals" },
    { id: "ASSEMBLY_REVIEW", label: "Reviewing visual master", helper: "Checking sequence, captions, continuity, and render integrity", expectedSeconds: 35, phase: "Visuals" },
    { id: "AUDIO_RENDER", label: "Creating voice + soundtrack", helper: "Synthesizing narration and mixing music, ambience, and ducking", expectedSeconds: 150, phase: "Audio" },
    { id: "AUDIO_REVIEW", label: "Listening to the audio master", helper: "AI critic checks narration clarity, music balance, ambience, and mix quality", expectedSeconds: 50, phase: "Audio" },
    { id: "DELIVERY_QC", label: "Running technical delivery QC", helper: "Checking decode, duration, resolution, codecs, loudness, silence, captions, and rights", expectedSeconds: 40, phase: "AI review" },
    { id: "DELIVERY_PACKAGE", label: "Creating delivery package", helper: "Packaging the verified master and delivery assets", expectedSeconds: 30, phase: "AI review" },
    { id: "PUBLISHING_GENERATE", label: "Generating publishing copy", helper: "Preparing YouTube, TikTok, and Instagram copy", expectedSeconds: 45, phase: "AI review" },
    { id: "PUBLISHING_REVIEW", label: "Reviewing publishing text", helper: "AI critic checks titles, captions, hashtags, accessibility text, and factual consistency", expectedSeconds: 45, phase: "AI review" },
    { id: "FINAL_PACKAGE", label: "Preparing final approval package", helper: "Adding AI-reviewed publishing copy to the final delivery package", expectedSeconds: 25, phase: "AI review" },
    { id: "FINAL_HUMAN", label: "Final video ready", helper: "The finished picture + sound is waiting for your approval", expectedSeconds: 0, phase: "Your approval" },
  ];
}

function aiPlanDone(job: ProductionBriefJob | null): boolean {
  if (!job?.result) return false;
  const detail = objectDetail(job.detail);
  const review = objectDetail(detail.ai_plan_review);
  const reviewIsCurrent = String(detail.ai_plan_review_for_generated_at || "") === job.result.generated_at;
  return job.stage === "COMPLETED"
    && job.result.review_status === "APPROVED"
    && String(detail.approval_actor || "").toUpperCase() === "AI"
    && reviewIsCurrent
    && review.decision === "PASS";
}

function referenceAiDone(job: MediaStudioJob | null): boolean {
  if (!job?.result?.reference_asset || !job.result.reference_approved) return false;
  const detail = objectDetail(job.detail);
  return String(detail.reference_approval_actor || "").toUpperCase() === "AI"
    && aiDecisionPassed(detail.reference_ai_review ?? detail.ai_reference_review);
}

function keyframesAiDone(job: MediaStudioJob | null): boolean {
  if (!job?.result || job.result.required_keyframes <= 0) return false;
  const detail = objectDetail(job.detail);
  const actors = objectDetail(detail.keyframe_approval_actor);
  const salvaged = objectDetail(detail.ai_salvaged_keyframes);
  return job.result.keyframes.length >= job.result.required_keyframes
    && job.result.keyframes.every((asset) => {
      const salvage = objectDetail(salvaged[String(asset.shot_number)]);
      const salvagePassed = String(salvage.outcome || "").toUpperCase() === "AI_SALVAGED"
        && asset.fidelity_report?.status === "ADAPTATION_ACCEPTED"
        && asset.fidelity_report.creator_override === false;
      return asset.review_status === "APPROVED"
        && (asset.fidelity_report?.status === "PASS" || salvagePassed)
        && String(actors[String(asset.shot_number)] || "").toUpperCase() === "AI";
    });
}

function clipsAiDone(job: MediaStudioJob | null): boolean {
  if (!job?.result || job.result.required_clips <= 0) return false;
  const detail = objectDetail(job.detail);
  const actors = objectDetail(detail.clip_approval_actor);
  const reviews = objectDetail(detail.ai_clip_reviews);
  return job.result.video_clips.length >= job.result.required_clips
    && job.result.video_clips.every((clip) =>
      clip.review_status === "APPROVED"
      && String(actors[String(clip.shot_number)] || "").toUpperCase() === "AI"
      && aiDecisionPassed(reviews[String(clip.shot_number)])
    );
}

function assemblyMatchesMedia(assembly: FinalAssemblyJob | null, media: MediaStudioJob | null): boolean {
  if (!assembly?.result || !media?.result) return false;
  const clips = new Map(media.result.video_clips.map((clip) => [clip.shot_number, clip.asset_id]));
  return assembly.result.timeline.length === media.result.required_clips
    && assembly.result.timeline.every((item) => clips.get(item.shot_number) === item.source_clip_asset_id);
}

function assemblyAiDone(job: FinalAssemblyJob | null, mediaJob: MediaStudioJob | null): boolean {
  if (!job?.result) return false;
  const detail = objectDetail(job.detail);
  return job.stage === "DELIVERED"
    && job.result.review_status === "APPROVED"
    && String(detail.approval_actor || "").toUpperCase() === "AI"
    && aiDecisionPassed(detail.ai_visual_master_review)
    && assemblyMatchesMedia(job, mediaJob);
}

function audioAiDone(job: AudioFinishingJob | null, assemblyJob: FinalAssemblyJob | null): boolean {
  if (!job?.result) return false;
  const detail = objectDetail(job.detail);
  return job.stage === "DELIVERED"
    && job.result.review_status === "APPROVED"
    && String(detail.approval_actor || "").toUpperCase() === "AI"
    && aiDecisionPassed(detail.ai_audio_review)
    && Boolean(assemblyJob?.job_id && job.assembly_job_id === assemblyJob.job_id);
}

function publishingAiDone(draft: PublishingDraft | null): boolean {
  return Boolean(draft?.status === "APPROVED" && (draft.generation_note || "").includes("[AI_REVIEW_APPROVED]"));
}

function activeClipReviewOperation(job: MediaStudioJob | null): Record<string, unknown> | null {
  if (!job) return null;
  const operations = objectDetail(objectDetail(job.detail).ai_clip_review_operations);
  for (const raw of Object.values(operations)) {
    const operation = objectDetail(raw);
    if (String(operation.status || "").toUpperCase() === "RUNNING") return operation;
  }
  return null;
}

function allAiReviewGatesPassed(props: Props): boolean {
  return aiPlanDone(props.productionJob)
    && referenceAiDone(props.mediaJob)
    && keyframesAiDone(props.mediaJob)
    && clipsAiDone(props.mediaJob)
    && assemblyAiDone(props.assemblyJob, props.mediaJob)
    && audioAiDone(props.audioJob, props.assemblyJob)
    && props.qc?.overall_status === "READY"
    && props.deliveryPackageReady
    && publishingAiDone(props.publishingDraft)
    && props.publishingPackaged;
}

function currentActivityId(props: Props): ActivityId {
  const {
    status,
    attentionStage,
    productionJob,
    mediaJob,
    assemblyJob,
    audioJob,
    qc,
    deliveryPackageReady,
    publishingDraft,
    publishingPackaged,
    finalHumanApproved,
  } = props;

  if (finalHumanApproved || allAiReviewGatesPassed(props)) return "FINAL_HUMAN";
  if (!productionJob || productionJob.stage !== "COMPLETED") return "PLAN_BUILD";
  if (!aiPlanDone(productionJob)) return "PLAN_REVIEW";
  if (!mediaJob || ["QUEUED", "GENERATING_REFERENCE"].includes(mediaJob.stage)) return "REFERENCE_GENERATE";
  if (!referenceAiDone(mediaJob)) return "REFERENCE_REVIEW";
  if (mediaJob.stage === "GENERATING_KEYFRAMES") return "KEYFRAMES_GENERATE";
  if (!keyframesAiDone(mediaJob)) return "KEYFRAMES_REVIEW";
  if (mediaJob.stage === "GENERATING_CLIPS" || mediaJob.result?.video_clips.length !== mediaJob.result?.required_clips) return "CLIPS_GENERATE";
  if (!clipsAiDone(mediaJob) || mediaJob.stage !== "READY_FOR_ASSEMBLY") return "CLIPS_REVIEW";
  if (!assemblyJob || ["QUEUED", "PREPARING", "RENDERING"].includes(assemblyJob.stage)) return "ASSEMBLY_RENDER";
  if (!assemblyAiDone(assemblyJob, mediaJob)) return "ASSEMBLY_REVIEW";
  if (!audioJob || ["QUEUED", "PREPARING", "SYNTHESIZING_VOICE", "BUILDING_MIX", "RENDERING"].includes(audioJob.stage)) return "AUDIO_RENDER";
  if (!audioAiDone(audioJob, assemblyJob)) return "AUDIO_REVIEW";
  if (!qc || qc.overall_status !== "READY") return "DELIVERY_QC";
  if (!deliveryPackageReady) return "DELIVERY_PACKAGE";
  if (!publishingDraft) return "PUBLISHING_GENERATE";
  if (!publishingAiDone(publishingDraft)) return "PUBLISHING_REVIEW";
  if (!publishingPackaged) return "FINAL_PACKAGE";
  return "FINAL_HUMAN";
}

function currentActivityProgress(activityId: ActivityId, props: Props): number | null {
  const { productionJob, mediaJob, assemblyJob, audioJob } = props;
  switch (activityId) {
    case "PLAN_BUILD":
      return progressRatio(productionJob?.progress_current, productionJob?.progress_total);
    case "REFERENCE_GENERATE":
      return mediaJob?.result?.reference_asset ? 0.9 : 0.38;
    case "KEYFRAMES_GENERATE": {
      const required = mediaJob?.result?.required_keyframes || 0;
      const count = mediaJob?.result?.keyframes.length || 0;
      return required ? clamp(count / required, 0.08, 0.92) : null;
    }
    case "KEYFRAMES_REVIEW": {
      const required = mediaJob?.result?.required_keyframes || 0;
      const reviewed = mediaJob?.result?.fidelity_reviewed_keyframes || 0;
      return required ? clamp(reviewed / required, 0.08, 0.94) : null;
    }
    case "CLIPS_GENERATE": {
      const required = mediaJob?.result?.required_clips || 0;
      const count = mediaJob?.result?.video_clips.length || 0;
      return required ? clamp(count / required, 0.05, 0.9) : null;
    }
    case "CLIPS_REVIEW": {
      const required = mediaJob?.result?.required_clips || 0;
      const actors = objectDetail(objectDetail(mediaJob?.detail).clip_approval_actor);
      const reviewed = Object.values(actors).filter((value) => String(value).toUpperCase() === "AI").length;
      return required ? clamp(reviewed / required, 0.08, 0.94) : null;
    }
    case "ASSEMBLY_RENDER":
      return progressRatio(assemblyJob?.progress_current, assemblyJob?.progress_total);
    case "AUDIO_RENDER":
      return progressRatio(audioJob?.progress_current, audioJob?.progress_total);
    case "PLAN_REVIEW":
    case "REFERENCE_REVIEW":
    case "ASSEMBLY_REVIEW":
    case "AUDIO_REVIEW":
    case "DELIVERY_QC":
    case "DELIVERY_PACKAGE":
    case "PUBLISHING_GENERATE":
    case "PUBLISHING_REVIEW":
    case "FINAL_PACKAGE":
      return 0.45;
    case "FINAL_HUMAN":
      return 1;
    default:
      return null;
  }
}

function latestActivityTimestamp(props: Props): number | null {
  return maxTimestamp([
    props.productionJob?.updated_at,
    props.mediaJob?.updated_at,
    props.assemblyJob?.updated_at,
    props.audioJob?.updated_at,
    props.qc?.generated_at,
    props.publishingDraft?.updated_at,
  ]);
}

export function AutopilotLiveMonitor(props: Props) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const requiredShots = props.mediaJob?.result?.required_clips
    || props.mediaJob?.result?.required_keyframes
    || props.productionJob?.result?.storyboard.shots.length
    || 1;
  const activities = useMemo(() => buildActivities(requiredShots), [requiredShots]);
  const activityId = currentActivityId(props);
  const activityIndex = Math.max(0, activities.findIndex((item) => item.id === activityId));
  const current = activities[activityIndex];
  const progress = currentActivityProgress(activityId, props);
  const activeReviewOperation = activeClipReviewOperation(props.mediaJob);
  const operationStartedAt = parseTime(String(activeReviewOperation?.started_at || ""));
  const currentStarted = (activityId === "CLIPS_REVIEW" ? operationStartedAt : null)
    ?? parseTime(props.activityStartedAt)
    ?? parseTime(props.currentStartedAt)
    ?? now;
  const contentStarted = parseTime(props.currentStartedAt) ?? parseTime(props.productionJob?.created_at) ?? now;
  const activityElapsedSeconds = Math.max(0, (now - currentStarted) / 1000);
  const contentElapsedSeconds = Math.max(0, (now - contentStarted) / 1000);
  const latestActivity = latestActivityTimestamp(props) ?? currentStarted;
  const sinceActivitySeconds = Math.max(0, (now - latestActivity) / 1000);

  const expectedBefore = activities.slice(0, activityIndex).reduce((sum, item) => sum + item.expectedSeconds, 0);
  const expectedTotal = activities.slice(0, -1).reduce((sum, item) => sum + item.expectedSeconds, 0);
  const currentFraction = activityId === "FINAL_HUMAN"
    ? 1
    : progress != null
      ? clamp(progress, 0.02, 0.94)
      : clamp(activityElapsedSeconds / Math.max(1, current.expectedSeconds), 0.04, 0.82);
  const weightedProgress = activityId === "FINAL_HUMAN"
    ? 1
    : clamp((expectedBefore + current.expectedSeconds * currentFraction) / Math.max(1, expectedTotal), 0.02, 0.98);
  const percent = Math.round(weightedProgress * 100);

  const currentRemaining = activityId === "FINAL_HUMAN"
    ? 0
    : progress != null
      ? Math.max(current.expectedSeconds * 0.18, current.expectedSeconds * (1 - currentFraction))
      : activityElapsedSeconds > current.expectedSeconds
        ? current.expectedSeconds * 0.28
        : Math.max(current.expectedSeconds * 0.2, current.expectedSeconds - activityElapsedSeconds);
  const futureRemaining = activities.slice(activityIndex + 1, -1).reduce((sum, item) => sum + item.expectedSeconds, 0);
  const etaSeconds = currentRemaining + futureRemaining;
  const longRunning = props.status === "RUNNING"
    && activityId !== "FINAL_HUMAN"
    && activityElapsedSeconds > Math.max(90, current.expectedSeconds * 1.45);
  const staleCheckpoint = props.status === "RUNNING" && sinceActivitySeconds > 8 * 60;
  const reviewerHardDeadlineExceeded = props.status === "RUNNING"
    && activityId === "CLIPS_REVIEW"
    && Boolean(activeReviewOperation)
    && activityElapsedSeconds >= 8 * 60;
  const watchdogChecking = !props.finalHumanApproved && props.watchdogStatus === "CHECKING";
  const watchdogRecovered = !props.finalHumanApproved && props.watchdogStatus === "RECOVERED";
  const watchdogWaiting = !props.finalHumanApproved && props.watchdogStatus === "WAITING";
  const finalReady = allAiReviewGatesPassed(props) && !props.finalHumanApproved;
  const productionComplete = props.finalHumanApproved;
  const hardAttention = props.status === "NEEDS_ATTENTION" && !finalReady && !productionComplete;
  const effectiveMessage = activityId === "CLIPS_REVIEW" && /human-approved/i.test(props.message || "")
    ? "AI motion reviewer is validating the current animated shots before assembly."
    : props.message;

  const phaseItems = ["Plan", "Visuals", "Audio", "AI review"] as const;
  const phaseStatus = phaseItems.map((phase) => {
    if (finalReady || props.finalHumanApproved) return "done";
    const first = activities.findIndex((item) => item.phase === phase);
    const last = activities.map((item) => item.phase).lastIndexOf(phase);
    if (activityIndex > last) return "done";
    if (activityIndex >= first && activityIndex <= last) return "active";
    return "waiting";
  });

  const statusLabel = productionComplete
    ? "Complete"
    : finalReady
      ? "Waiting for your approval"
    : watchdogChecking
      ? "Recovering"
      : props.status === "RUNNING"
        ? "Working"
      : props.status === "WAITING_FOR_FINAL_APPROVAL"
        ? "Verifying final handoff"
        : props.status === "WAITING_FOR_LEARNING"
          ? "Learning before next production"
        : props.status === "PAUSED"
          ? "Paused"
          : props.status === "NEEDS_ATTENTION"
            ? "Needs attention"
            : props.status === "COMPLETED"
              ? "Complete"
              : "Idle";

  return (
    <section className={`autopilot-live-monitor glass-card status-${props.status.toLowerCase().replace(/_/g, "-")} ${finalReady ? "is-final-ready" : ""} ${productionComplete ? "is-complete" : ""}`} aria-live="polite">
      <div className="autopilot-live-head">
        <div className="autopilot-live-brand">
          <span className="autopilot-live-icon"><Bot size={22} /></span>
          <div>
            <div className="layer-badge autopilot"><Sparkles size={13} /> AI Autopilot</div>
            <strong>{productionComplete ? "Production complete" : finalReady ? "Production complete — final approval required" : hardAttention ? "Autopilot needs help" : "ReviveAI is producing your video"}</strong>
            <small>{props.title}</small>
          </div>
        </div>
        <div className="autopilot-live-actions">
          <span className={`autopilot-live-state ${productionComplete ? "completed" : finalReady ? "ready" : props.status.toLowerCase().replace(/_/g, "-")}`}>
            {productionComplete || finalReady ? <CheckCircle2 size={14} /> : props.status === "RUNNING" ? <span className="autopilot-live-dot" /> : hardAttention ? <CircleAlert size={14} /> : <Radio size={14} />}
            {statusLabel}
          </span>
          {!productionComplete && ["RUNNING", "WAITING_FOR_LEARNING"].includes(props.status) && <button type="button" className="secondary-button" onClick={props.onPause}><Pause size={15} /> Pause</button>}
          {!productionComplete && props.status === "PAUSED" && <button type="button" className="secondary-button" onClick={props.onResume}><Play size={15} /> Resume</button>}
          {hardAttention && props.onRecover && (
            <button
              type="button"
              className="primary-button autopilot-recovery-button"
              disabled={props.recoveryPending}
              onClick={() => { void props.onRecover?.(); }}
            >
              {props.recoveryPending ? <LoaderCircle className="spinner" size={15} /> : <Sparkles size={15} />}
              {props.recoveryPending ? "Starting AI recovery…" : "Retry automatic recovery"}
            </button>
          )}
        </div>
      </div>

      {!productionComplete && !finalReady && !hardAttention && (
        <>
          <div className="autopilot-live-current">
            <div className="autopilot-live-current-copy">
              <span className="eyebrow">Now · {current.phase}</span>
              <h3>{watchdogChecking ? "Recovering stalled checkpoint" : reviewerHardDeadlineExceeded ? "Reclaiming stalled AI reviewer" : current.label}</h3>
              <p>{watchdogChecking
                ? (props.watchdogMessage || "Checking durable backend state before resuming safely.")
                : reviewerHardDeadlineExceeded
                  ? "The motion reviewer exceeded the 8-minute hard deadline. ReviveAI will reclaim it automatically; a second stalled review uses the controlled-motion fallback so production can continue."
                  : effectiveMessage || current.helper}</p>
            </div>
            <div className="autopilot-live-percent"><strong>{percent}%</strong><span>estimated progress</span></div>
          </div>

          <div className="autopilot-live-progress" aria-label={`Estimated production progress ${percent}%`}>
            <span style={{ width: `${percent}%` }} />
            {props.status === "RUNNING" && <i />}
          </div>

          <div className="autopilot-live-metrics">
            <div><Clock3 size={15} /><span><strong>{props.status === "PAUSED" ? "ETA paused" : watchdogChecking || watchdogRecovered || reviewerHardDeadlineExceeded ? "Re-estimating after recovery" : staleCheckpoint ? "Automatic recovery due" : etaRange(etaSeconds)}</strong><small>{watchdogChecking ? "ReviveAI is reconciling the latest durable checkpoint" : reviewerHardDeadlineExceeded ? "The current reviewer has exceeded its hard deadline" : "Estimate updates as each AI step finishes"}</small></span></div>
            <div><LoaderCircle size={15} /><span><strong>{humanDuration(activityElapsedSeconds)} current operation</strong><small>{activeReviewOperation ? "Backend reviewer lease is active" : current.label}</small></span></div>
            <div><Activity size={15} /><span><strong>{humanDuration(contentElapsedSeconds)} production elapsed</strong><small>Total time since this Autopilot production started</small></span></div>
            <div><Radio size={15} /><span><strong>Last durable checkpoint {ago(sinceActivitySeconds)}</strong><small>{watchdogChecking ? "Automatic recovery is checking saved job state" : watchdogRecovered ? "Checkpoint recovered; production is resuming" : watchdogWaiting ? "Watchdog will check again automatically" : staleCheckpoint ? "No durable checkpoint recently" : "Backend checkpoints are updating"}</small></span></div>
          </div>

          {(longRunning || staleCheckpoint || reviewerHardDeadlineExceeded || watchdogChecking || watchdogRecovered || watchdogWaiting) && (
            <div className="autopilot-live-slow-note">
              <LoaderCircle className={props.status === "RUNNING" && !watchdogRecovered ? "spinner" : ""} size={16} />
              <span>
                <strong>{watchdogChecking ? "Automatic recovery is running." : watchdogRecovered ? "Stalled checkpoint recovered." : reviewerHardDeadlineExceeded ? "AI reviewer exceeded the hard deadline." : watchdogWaiting ? "Recovery retry is scheduled." : "This step is taking longer than the usual estimate."}</strong>
                {watchdogChecking || watchdogRecovered
                  ? ` ${props.watchdogMessage || "ReviveAI is reconciling saved backend state without skipping an AI review gate."}`
                  : reviewerHardDeadlineExceeded
                    ? " ReviveAI will reclaim this reviewer at the next watchdog pass. If the restarted reviewer also exceeds the deadline, controlled-motion salvage is used automatically and production continues."
                    : watchdogWaiting
                      ? ` ${props.watchdogMessage || "ReviveAI will retry automatic recovery; no manual action is required."}`
                      : staleCheckpoint
                        ? " No durable checkpoint has arrived recently. ReviveAI will invoke its watchdog automatically instead of waiting indefinitely."
                        : " ReviveAI is still on the same step and will update the ETA when the next checkpoint arrives."}
              </span>
            </div>
          )}
        </>
      )}

      {productionComplete && (
        <div className="autopilot-live-complete-summary">
          <div className="autopilot-live-complete-copy">
            <span className="autopilot-live-complete-icon"><CheckCircle2 size={20} /></span>
            <div>
              <strong>Final video approved.</strong>
              <small>ReviveAI finished production and AI review. Your final approval has been recorded.</small>
            </div>
          </div>
          <div className="autopilot-live-complete-metrics">
            <div><Clock3 size={15} /><span><strong>{humanDuration(contentElapsedSeconds)}</strong><small>Production time</small></span></div>
            <div><ShieldCheck size={15} /><span><strong>AI review passed</strong><small>Required review gates complete</small></span></div>
            <div><CheckCircle2 size={15} /><span><strong>Final approval received</strong><small>Human decision recorded</small></span></div>
          </div>
        </div>
      )}

      {hardAttention && (
        <div className="autopilot-live-attention">
          <CircleAlert size={19} />
          <div><strong>Automatic production stopped safely.</strong><span>{props.message}</span></div>
        </div>
      )}

      {finalReady && (
        <div className="autopilot-live-final-ready">
          <span><CheckCircle2 size={20} /></span>
          <div><strong>AI production and review are complete.</strong><small>The production is no longer running. Watch the finished picture + sound below and make the only human decision required.</small></div>
          <em>{humanDuration(contentElapsedSeconds)} elapsed</em>
        </div>
      )}

      <div className="autopilot-live-phase-rail">
        {phaseItems.map((phase, index) => {
          const state = phaseStatus[index];
          return (
            <div key={phase} className={`autopilot-live-phase ${state}`}>
              <span>{state === "done" ? <CheckCircle2 size={13} /> : state === "active" ? <LoaderCircle className={props.status === "RUNNING" ? "spinner" : ""} size={13} /> : index + 1}</span>
              <strong>{phase}</strong>
            </div>
          );
        })}
      </div>

      <div className="autopilot-live-footer">
        <ShieldCheck size={14} />
        <span>{productionComplete
          ? "Production is complete. Runtime ETA, watchdog, recovery, and active-operation indicators are closed for this video."
          : finalReady
            ? "AI review is complete. ReviveAI is waiting for your decision and will not start the next production until you approve this final video."
            : hardAttention
            ? "A hard exception stopped automatic progress. Creative visual failures normally recover automatically; use retry only when the automatic recovery call itself could not start."
            : "No action needed while Autopilot is working. Keep this tab open in the current frontend-driven version."}</span>
      </div>
    </section>
  );
}
