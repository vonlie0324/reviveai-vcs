import { BadgeCheck, Bot, CheckCircle2, Film, LoaderCircle, ShieldCheck } from "lucide-react";
import { audioAssetUrl } from "../api";
import type {
  AudioFinishingJob,
  DeliveryPackage,
  DeliveryQcReport,
  FinalAssemblyJob,
  MediaStudioJob,
  ProductionBriefJob,
  PublishingDraft,
} from "../types";

interface Props {
  productionJob: ProductionBriefJob;
  mediaJob: MediaStudioJob;
  assemblyJob: FinalAssemblyJob | null;
  audioJob: AudioFinishingJob;
  qc: DeliveryQcReport;
  deliveryPackage: DeliveryPackage;
  publishingDraft: PublishingDraft;
  pending?: boolean;
  error?: string | null;
  onApprove: () => void;
}

function detailObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

function isHumanApproved(job: AudioFinishingJob): boolean {
  return detailObject(job.detail).human_final_approved === true;
}

function aiDecisionPassed(value: unknown): boolean {
  return String(detailObject(value).decision || "").toUpperCase() === "PASS";
}

function mediaReviewSummary(job: MediaStudioJob) {
  const detail = detailObject(job.detail);
  const referenceOk = Boolean(
    job.result?.reference_approved
    && String(detail.reference_approval_actor || "").toUpperCase() === "AI"
    && aiDecisionPassed(detail.reference_ai_review ?? detail.ai_reference_review)
  );
  const keyframeActors = detailObject(detail.keyframe_approval_actor);
  const salvagedKeyframes = detailObject(detail.ai_salvaged_keyframes);
  const keyframeSalvaged = Object.values(salvagedKeyframes).some((value) => String(detailObject(value).outcome || "").toUpperCase() === "AI_SALVAGED");
  const keyframesOk = Boolean(
    job.result
    && job.result.required_keyframes > 0
    && job.result.keyframes.length >= job.result.required_keyframes
    && job.result.keyframes.every((asset) => {
      const salvage = detailObject(salvagedKeyframes[String(asset.shot_number)]);
      const salvagePassed = String(salvage.outcome || "").toUpperCase() === "AI_SALVAGED"
        && asset.fidelity_report?.status === "ADAPTATION_ACCEPTED"
        && asset.fidelity_report.creator_override === false;
      return asset.review_status === "APPROVED"
        && (asset.fidelity_report?.status === "PASS" || salvagePassed)
        && String(keyframeActors[String(asset.shot_number)] || "").toUpperCase() === "AI";
    })
  );
  const clipActors = detailObject(detail.clip_approval_actor);
  const clipReviews = detailObject(detail.ai_clip_reviews);
  const salvagedClips = detailObject(detail.ai_salvaged_clips);
  const motionSalvaged = Object.values(salvagedClips).some((value) => String(detailObject(value).outcome || "").toUpperCase() === "AI_SALVAGED");
  const motionOk = Boolean(
    job.result
    && job.result.required_clips > 0
    && job.result.video_clips.length >= job.result.required_clips
    && job.result.video_clips.every((clip) =>
      clip.review_status === "APPROVED"
      && String(clipActors[String(clip.shot_number)] || "").toUpperCase() === "AI"
      && aiDecisionPassed(clipReviews[String(clip.shot_number)])
    )
  );
  return { referenceOk, keyframesOk, motionOk, keyframeSalvaged, motionSalvaged };
}

export function FinalHumanReviewPanel({
  productionJob,
  mediaJob,
  assemblyJob,
  audioJob,
  qc,
  deliveryPackage,
  publishingDraft,
  pending = false,
  error = null,
  onApprove,
}: Props) {
  if (!audioJob.result) return null;

  const approved = isHumanApproved(audioJob);
  const planDetail = detailObject(productionJob.detail);
  const planAiReviewed = productionJob.result?.review_status === "APPROVED"
    && String(planDetail.approval_actor || "").toUpperCase() === "AI"
    && String(planDetail.ai_plan_review_for_generated_at || "") === productionJob.result?.generated_at
    && aiDecisionPassed(planDetail.ai_plan_review);
  const mediaSummary = mediaReviewSummary(mediaJob);
  const visualDetail = detailObject(assemblyJob?.detail);
  const visualActor = String(visualDetail.approval_actor ?? "");
  const visualAiReviewed = visualActor.toUpperCase() === "AI" && aiDecisionPassed(visualDetail.ai_visual_master_review);
  const visualSalvaged = visualDetail.ai_salvaged_visual_master === true || String(detailObject(visualDetail.ai_visual_master_review).outcome || "").toUpperCase() === "AI_SALVAGED";
  const audioDetail = detailObject(audioJob.detail);
  const audioActor = String(audioDetail.approval_actor ?? "");
  const audioAiReviewed = audioActor.toUpperCase() === "AI" && aiDecisionPassed(audioDetail.ai_audio_review);
  const audioSalvaged = audioDetail.ai_salvaged_audio_master === true || String(detailObject(audioDetail.ai_audio_review).outcome || "").toUpperCase() === "AI_SALVAGED";
  const videoUrl = audioAssetUrl(audioJob.result.delivery_video.asset_url);
  const publishingAiReviewed = publishingDraft.status === "APPROVED" && (publishingDraft.generation_note || "").includes("[AI_REVIEW_APPROVED]");
  const publishingSalvaged = (publishingDraft.generation_note || "").includes("[AI_SALVAGED]");

  return (
    <section className="final-human-review-section" id="final-human-review">
      <article className={`final-human-review-card glass-card ${approved ? "is-approved" : ""}`}>
        <div className="final-human-review-head">
          <div>
            <div className="layer-badge autopilot"><Bot size={15} /> AI production complete</div>
            <span className="eyebrow">One human decision · final video</span>
            <h2>{approved ? "Final video approved" : "Your final video is ready"}</h2>
            <p>
              ReviveAI has already reviewed the visual continuity, animation, audio mix, technical delivery checks,
              and publishing copy. This is the only approval Autopilot asks from you.
            </p>
          </div>
          <div className={`final-human-review-status ${approved ? "approved" : "ready"}`}>
            {approved ? <BadgeCheck size={22} /> : <Film size={22} />}
            <div>
              <strong>{approved ? "Human approved" : "Ready for your review"}</strong>
              <span>{approved ? "This production can move forward." : "Watch the finished picture + sound."}</span>
            </div>
          </div>
        </div>

        <div className="final-human-review-layout">
          <article className="final-human-review-player">
            <video controls playsInline preload="metadata" src={videoUrl} />
            {!approved && (
              <button className="primary-button final-human-approve" type="button" onClick={onApprove} disabled={pending}>
                {pending ? <LoaderCircle className="spinner" size={17} /> : <BadgeCheck size={17} />}
                {pending ? "Recording final approval…" : "Approve final video"}
              </button>
            )}
            {approved && <div className="final-human-approved-note"><CheckCircle2 size={17} /> Final human approval recorded</div>}
            {error && <div className="publishing-error" role="alert">{error}</div>}
          </article>

          <aside className="final-human-review-summary">
            <span className="eyebrow">AI review trail</span>
            <ReviewRow label="Plan + text fidelity" ok={planAiReviewed} value={planAiReviewed ? "AI reviewed" : "Not verified"} />
            <ReviewRow label="Visual identity" ok={mediaSummary.referenceOk && mediaSummary.keyframesOk} value={mediaSummary.referenceOk && mediaSummary.keyframesOk ? (mediaSummary.keyframeSalvaged ? "AI salvaged + reviewed" : "AI reviewed") : "Not verified"} />
            <ReviewRow label="Motion fidelity" ok={mediaSummary.motionOk} value={mediaSummary.motionOk ? (mediaSummary.motionSalvaged ? "AI salvaged fallback" : "AI reviewed") : "Not verified"} />
            <ReviewRow label="Visual master" ok={visualAiReviewed} value={visualAiReviewed ? (visualSalvaged ? "AI salvaged + reviewed" : "AI reviewed") : "Not verified"} />
            <ReviewRow label="Audio master" ok={audioAiReviewed} value={audioAiReviewed ? (audioSalvaged ? "AI salvaged + reviewed" : "AI reviewed") : "Not verified"} />
            <ReviewRow label="Delivery QC" ok={qc.overall_status === "READY" || (qc.overall_status === "REVIEW" && qc.fail_count === 0 && qc.human_acknowledgment?.report_id === qc.report_id)} value={qc.overall_status === "REVIEW" && qc.human_acknowledgment?.report_id === qc.report_id ? "REVIEW · Creator acknowledged" : qc.overall_status} />
            <ReviewRow label="Publishing copy" ok={publishingAiReviewed} value={publishingAiReviewed ? (publishingSalvaged ? "AI salvaged + reviewed" : "AI reviewed") : publishingDraft.status} />
            <ReviewRow label="Delivery package" ok={deliveryPackage.publishing_draft_id === publishingDraft.draft_id} value={`v${deliveryPackage.package_version}`} />
            <div className="final-human-review-trust">
              <ShieldCheck size={16} />
              <span>Intermediate AI approvals are recorded separately from this final human approval.</span>
            </div>
          </aside>
        </div>
      </article>
    </section>
  );
}

function ReviewRow({ label, ok, value }: { label: string; ok: boolean; value: string }) {
  return (
    <div className={`final-human-review-row ${ok ? "pass" : "review"}`}>
      <span>{ok ? <CheckCircle2 size={15} /> : <ShieldCheck size={15} />}</span>
      <div><strong>{label}</strong><small>{value}</small></div>
    </div>
  );
}
