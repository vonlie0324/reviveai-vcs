import {
  Bot,
  CheckCircle2,
  CircleDashed,
  Film,
  Headphones,
  LoaderCircle,
  MessageSquareText,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type {
  AudioFinishingJob,
  DeliveryQcReport,
  FinalAssemblyJob,
  MediaStudioJob,
  ProductionBriefJob,
  PublishingDraft,
} from "../types";

type AutopilotUiStatus = "RUNNING" | "PAUSED" | "NEEDS_ATTENTION" | "WAITING_FOR_FINAL_APPROVAL" | "WAITING_FOR_LEARNING" | "COMPLETED" | "IDLE";

interface Props {
  title: string;
  status: AutopilotUiStatus;
  message: string;
  attentionStage?: string | null;
  productionJob: ProductionBriefJob | null;
  mediaJob: MediaStudioJob | null;
  assemblyJob: FinalAssemblyJob | null;
  audioJob: AudioFinishingJob | null;
  qc: DeliveryQcReport | null;
  publishingDraft: PublishingDraft | null;
  publishingPackaged: boolean;
  finalHumanApproved: boolean;
}

type StepState = "DONE" | "SALVAGED" | "ACTIVE" | "WAITING" | "BLOCKED";

function detail(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

function aiActor(job: { detail?: Record<string, unknown> | null } | null): boolean {
  return Boolean(job && String(detail(job.detail).approval_actor || "").toUpperCase() === "AI");
}

function aiDecisionPassed(value: unknown): boolean {
  return String(detail(value).decision || "").toUpperCase() === "PASS";
}

function assemblyMatchesMedia(assemblyJob: FinalAssemblyJob | null, mediaJob: MediaStudioJob | null): boolean {
  if (!assemblyJob?.result || !mediaJob?.result) return false;
  const clips = new Map(mediaJob.result.video_clips.map((clip) => [clip.shot_number, clip.asset_id]));
  return assemblyJob.result.timeline.length === mediaJob.result.required_clips
    && assemblyJob.result.timeline.every((item) => clips.get(item.shot_number) === item.source_clip_asset_id);
}

function Step({ label, helper, state }: { label: string; helper: string; state: StepState }) {
  return (
    <div className={`autopilot-review-step state-${state.toLowerCase()}`}>
      <span className="autopilot-review-step-icon">
        {state === "DONE" ? <CheckCircle2 size={17} /> : state === "SALVAGED" ? <Sparkles size={17} /> : state === "ACTIVE" ? <LoaderCircle className="spinner" size={17} /> : <CircleDashed size={17} />}
      </span>
      <div><strong>{label}</strong><small>{helper}</small></div>
      <em>{state === "DONE" ? "AI passed" : state === "SALVAGED" ? "AI salvaged" : state === "ACTIVE" ? "Working" : state === "BLOCKED" ? "Paused" : "Queued"}</em>
    </div>
  );
}

export function AutopilotProductionPanel({
  title,
  status,
  message,
  attentionStage,
  productionJob,
  mediaJob,
  assemblyJob,
  audioJob,
  qc,
  publishingDraft,
  publishingPackaged,
  finalHumanApproved,
}: Props) {
  const planDetail = detail(productionJob?.detail);
  const planReview = detail(planDetail.ai_plan_review);
  const planReviewCurrent = Boolean(productionJob?.result && String(planDetail.ai_plan_review_for_generated_at || "") === productionJob.result.generated_at);
  const planDone = productionJob?.stage === "COMPLETED"
    && productionJob.result?.review_status === "APPROVED"
    && String(planDetail.approval_actor || "").toUpperCase() === "AI"
    && planReviewCurrent
    && planReview.decision === "PASS";

  const mediaDetail = detail(mediaJob?.detail);
  const referenceDone = Boolean(
    mediaJob?.result?.reference_approved
    && String(mediaDetail.reference_approval_actor || "").toUpperCase() === "AI"
    && aiDecisionPassed(mediaDetail.reference_ai_review ?? mediaDetail.ai_reference_review)
  );
  const keyframeActors = detail(mediaDetail.keyframe_approval_actor);
  const salvagedKeyframes = detail(mediaDetail.ai_salvaged_keyframes);
  const keyframeSalvaged = Object.values(salvagedKeyframes).some((value) => String(detail(value).outcome || "").toUpperCase() === "AI_SALVAGED");
  const keyframesDone = Boolean(
    mediaJob?.result
    && mediaJob.result.required_keyframes > 0
    && mediaJob.result.keyframes.length >= mediaJob.result.required_keyframes
    && mediaJob.result.keyframes.every((asset) => {
      const salvage = detail(salvagedKeyframes[String(asset.shot_number)]);
      const salvagePassed = String(salvage.outcome || "").toUpperCase() === "AI_SALVAGED"
        && asset.fidelity_report?.status === "ADAPTATION_ACCEPTED"
        && asset.fidelity_report.creator_override === false;
      return asset.review_status === "APPROVED"
        && (asset.fidelity_report?.status === "PASS" || salvagePassed)
        && String(keyframeActors[String(asset.shot_number)] || "").toUpperCase() === "AI";
    })
  );
  const clipActors = detail(mediaDetail.clip_approval_actor);
  const clipReviews = detail(mediaDetail.ai_clip_reviews);
  const salvagedClips = detail(mediaDetail.ai_salvaged_clips);
  const motionSalvaged = Object.values(salvagedClips).some((value) => String(detail(value).outcome || "").toUpperCase() === "AI_SALVAGED");
  const motionDone = Boolean(
    mediaJob?.result
    && mediaJob.result.required_clips > 0
    && mediaJob.result.video_clips.length >= mediaJob.result.required_clips
    && mediaJob.result.video_clips.every((clip) =>
      clip.review_status === "APPROVED"
      && String(clipActors[String(clip.shot_number)] || "").toUpperCase() === "AI"
      && aiDecisionPassed(clipReviews[String(clip.shot_number)])
    )
  );
  const visualMasterDetail = detail(assemblyJob?.detail);
  const visualMasterDone = Boolean(
    assemblyJob?.stage === "DELIVERED"
    && assemblyJob.result?.review_status === "APPROVED"
    && aiActor(assemblyJob)
    && aiDecisionPassed(visualMasterDetail.ai_visual_master_review)
    && assemblyMatchesMedia(assemblyJob, mediaJob)
  );
  const visualIdentityDone = referenceDone && keyframesDone;
  const motionAndMasterDone = motionDone && visualMasterDone;
  const audioDetail = detail(audioJob?.detail);
  const audioDone = Boolean(
    audioJob?.stage === "DELIVERED"
    && audioJob.result?.review_status === "APPROVED"
    && aiActor(audioJob)
    && aiDecisionPassed(audioDetail.ai_audio_review)
    && assemblyJob?.job_id === audioJob.assembly_job_id
  );
  const qcDone = qc?.overall_status === "READY";
  const copyDone = publishingDraft?.status === "APPROVED" && (publishingDraft.generation_note || "").includes("[AI_REVIEW_APPROVED]") && publishingPackaged;
  const hardFailure = status === "NEEDS_ATTENTION" && attentionStage === "FAILURE";
  const effectiveMessage = /human-approved/i.test(message || "") && !motionDone
    ? "AI motion fidelity review is validating the current animated shots before assembly."
    : message;

  const states: StepState[] = [
    planDone ? "DONE" : hardFailure ? "BLOCKED" : "ACTIVE",
    visualIdentityDone ? (keyframeSalvaged ? "SALVAGED" : "DONE") : !planDone ? "WAITING" : hardFailure ? "BLOCKED" : "ACTIVE",
    motionAndMasterDone ? (motionSalvaged ? "SALVAGED" : "DONE") : !visualIdentityDone ? "WAITING" : hardFailure ? "BLOCKED" : "ACTIVE",
    audioDone ? "DONE" : !motionAndMasterDone ? "WAITING" : hardFailure ? "BLOCKED" : "ACTIVE",
    qcDone ? "DONE" : !audioDone ? "WAITING" : hardFailure ? "BLOCKED" : "ACTIVE",
    copyDone ? "DONE" : !qcDone ? "WAITING" : hardFailure ? "BLOCKED" : "ACTIVE",
  ];

  // Keep only the earliest incomplete stage visually active. Later stages stay queued.
  const isCompleteState = (value: StepState) => value === "DONE" || value === "SALVAGED";
  const firstIncomplete = states.findIndex((item) => !isCompleteState(item));
  if (firstIncomplete >= 0) {
    for (let index = firstIncomplete + 1; index < states.length; index += 1) {
      if (!isCompleteState(states[index])) states[index] = "WAITING";
    }
  }

  return (
    <section className="autopilot-review-panel" aria-live="polite">
      <article className="autopilot-review-hero glass-card">
        <div className="autopilot-review-hero-icon"><Bot size={24} /></div>
        <div className="autopilot-review-hero-copy">
          <div className="layer-badge autopilot"><Sparkles size={14} /> AI Production Assistant</div>
          <span className="eyebrow">Delegated production · intermediate reviews handled by AI</span>
          <h2>{title}</h2>
          <p>{effectiveMessage}</p>
          <div className="autopilot-review-trust"><ShieldCheck size={15} /><span>No intermediate creative approval is required from you. ReviveAI automatically escalates from correction to alternate generation, shot replan, and safe fallback; your creative approval remains reserved for the finished video.</span></div>
        </div>
        <div className={`autopilot-review-live status-${status.toLowerCase().replace(/_/g, "-")}`}>
          {status === "RUNNING"
            ? <LoaderCircle className="spinner" size={18} />
            : status === "WAITING_FOR_FINAL_APPROVAL" || attentionStage === "FINAL_VIDEO"
              ? <Film size={18} />
              : status === "WAITING_FOR_LEARNING"
                ? <Sparkles size={18} />
                : <Bot size={18} />}
          <span>{status === "RUNNING"
            ? "AI working"
            : status === "WAITING_FOR_FINAL_APPROVAL" || attentionStage === "FINAL_VIDEO"
              ? "Waiting for your approval"
              : status === "WAITING_FOR_LEARNING"
                ? "Learning before next production"
                : status.replace(/_/g, " ").toLowerCase()}</span>
        </div>
      </article>

      <article className="autopilot-review-checklist glass-card">
        <div className="autopilot-review-checklist-head">
          <div><span className="eyebrow">AI review trail</span><h3>What your assistant is checking</h3></div>
          {finalHumanApproved && <span className="autopilot-final-approved-chip"><CheckCircle2 size={14} /> Final human approval recorded</span>}
        </div>
        <div className="autopilot-review-steps">
          <Step label="Plan + text fidelity" helper="Recovery direction, production consistency, storyboard, and copy intent" state={states[0]} />
          <Step label="Visual identity" helper="Canonical reference and storyboard keyframes checked for identity and continuity" state={states[1]} />
          <Step label="Motion + visual master" helper="Veo clips and the assembled visual master checked against the approved storyboard" state={states[2]} />
          <Step label="Voice + soundtrack" helper="Narration intelligibility, music balance, ambience, and ducking" state={states[3]} />
          <Step label="Technical delivery QC" helper="Decode, duration, resolution, codecs, loudness, silence, captions, and rights" state={states[4]} />
          <Step label="Publishing text" helper="Title, descriptions, captions, hashtags, accessibility text, and factual consistency" state={states[5]} />
        </div>
        <div className="autopilot-review-footer">
          <MessageSquareText size={16} />
          <span>{hardFailure ? "A hard technical exception stopped automatic progress. Creative visual failures are recovered autonomously before ReviveAI asks for help." : copyDone && !finalHumanApproved ? "All AI reviews passed. Your final video review is next." : "The assistant regenerates only the failed layer when possible, preserving work that already passed."}</span>
        </div>
      </article>
    </section>
  );
}
