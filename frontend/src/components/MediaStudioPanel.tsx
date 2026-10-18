import {
  AlertTriangle,
  BadgeCheck,
  Check,
  CircleAlert,
  CircleCheckBig,
  Eye,
  ExternalLink,
  Film,
  PlayCircle,
  Video,
  Image as ImageIcon,
  Images,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  WandSparkles,
} from "lucide-react";
import { useState } from "react";
import { mediaAssetUrl } from "../api";
import type { ClipOperation, KeyframeFidelityReport, MediaAsset, MediaStudioJob, ProductionBriefJob, ProductionIdentity, ShotOperation, StoryboardShot, VideoClipAsset, VideoGenerationCharge } from "../types";

interface MediaStudioPanelProps {
  productionJob: ProductionBriefJob | null;
  job: MediaStudioJob | null;
  error: string | null;
  resumePending?: boolean;
  onStart: () => void;
  onApproveReference: () => void;
  onRegenerateReference: () => void;
  onApproveKeyframe: (shotNumber: number) => void;
  onRegenerateKeyframe: (shotNumber: number) => void;
  onReviewAllKeyframes: () => void;
  onReviewKeyframe: (shotNumber: number) => void;
  onAcceptKeyframeAdaptation: (shotNumber: number) => void;
  onStartAnimation: () => void;
  onApproveClip: (shotNumber: number) => void;
  onRegenerateClip: (shotNumber: number) => void;
}

const RUNNING = new Set(["QUEUED", "GENERATING_REFERENCE", "GENERATING_KEYFRAMES", "REVIEWING_KEYFRAME_FIDELITY"]);

export function MediaStudioPanel(props: MediaStudioPanelProps) {
  const { productionJob, job } = props;
  const approvedBrief = productionJob?.stage === "COMPLETED" && productionJob.result?.review_status === "APPROVED";
  if (!approvedBrief && !job) return null;

  if (!job) return <MediaStudioGate {...props} />;
  if (job.stage === "FAILED") return <MediaStudioFailure {...props} />;
  if (RUNNING.has(job.stage)) return <MediaStudioProgress job={job} />;
  if (job.stage === "AWAITING_REFERENCE_APPROVAL") return <ReferenceReview {...props} />;
  if (job.stage === "GENERATING_CLIPS" || job.stage === "AWAITING_CLIP_REVIEW" || job.stage === "READY_FOR_ASSEMBLY") return <ClipStudio {...props} />;
  if (job.stage === "AWAITING_KEYFRAME_REVIEW" || job.stage === "READY_FOR_ANIMATION") return <KeyframeStudio {...props} />;
  return null;
}

function MediaStudioGate({ productionJob, error, resumePending = false, onStart }: MediaStudioPanelProps) {
  const result = productionJob?.result;
  if (!result) return null;
  const identity = result.creative_direction.production_identity;
  return (
    <section className="media-studio-section" id="media-studio">
      <article className="media-gate glass-card">
        <div className="media-gate-icon"><ImageIcon size={28} /></div>
        <div className="media-gate-copy">
          <div className="layer-badge media"><WandSparkles size={15} /> Visual creation layer</div>
          <span className="eyebrow">Milestone 2B.1.2 · Visual Reference & Keyframe Fidelity Studio</span>
          <h2>Lock the character visually, then verify every planned shot.</h2>
          <p>
            Generate one canonical reference for <strong>{identity.character_name}</strong>, approve it, create storyboard keyframes, then review whether each image actually matches its approved shot composition before Veo animation.
          </p>
          <div className="media-gate-points">
            <span><ShieldCheck size={16} /> Approved M2A source only</span>
            <span><ImageIcon size={16} /> Canonical identity reference</span>
            <span><Eye size={16} /> Shot-fidelity review</span>
            <span><Film size={16} /> {result.storyboard.shots.length} storyboard keyframes</span>
          </div>
          <button className="primary-button media-start-button" onClick={onStart} disabled={resumePending}>
            {resumePending ? <><RefreshCw size={17} className="media-spin" /> Checking saved Media Studio…</> : <><Sparkles size={17} /> Start visual reference studio</>}
          </button>
          {resumePending && <div className="media-resume-note"><ShieldCheck size={16} /><span>Looking for an existing M2B job for this approved production brief. ReviveAI will reopen it instead of creating duplicate media.</span></div>}
          {error && <div className="dna-inline-error" role="alert"><AlertTriangle size={17} /><div><strong>Media Studio could not start</strong><span>{error}</span></div></div>}
        </div>
      </article>
    </section>
  );
}

function MediaStudioProgress({ job }: { job: MediaStudioJob }) {
  const referencePhase = job.stage === "QUEUED" || job.stage === "GENERATING_REFERENCE";
  const fidelityPhase = job.stage === "REVIEWING_KEYFRAME_FIDELITY" || job.detail.current_task === "fidelity_review";
  const currentShot = Number(job.detail.current_shot ?? 0);
  const keyframeCount = job.result?.required_keyframes ?? 0;
  const label = referencePhase
    ? "Creating canonical character reference"
    : fidelityPhase
      ? currentShot ? `Reviewing storyboard fidelity for shot ${currentShot}` : "Reviewing storyboard fidelity"
      : currentShot
        ? `Creating storyboard keyframe ${currentShot} of ${keyframeCount}`
        : "Creating storyboard keyframes";
  const total = Math.max(1, job.progress_total);
  const percent = referencePhase ? 18 : Math.min(94, Math.max(28, Math.round((job.progress_current / total) * 100)));
  return (
    <section className="media-studio-section" id="media-studio" aria-live="polite">
      <article className="media-progress glass-card">
        <div className="media-progress-head">
          <div className="media-progress-icon"><WandSparkles size={30} /></div>
          <div>
            <div className="layer-badge media"><Sparkles size={15} /> Google image generation + Gemini visual review</div>
            <span className="eyebrow">Building visual continuity and shot fidelity</span>
            <h2>{label}</h2>
            <p>{job.result?.source_snapshot.working_title || "Approved production brief"}</p>
          </div>
          <div className="media-progress-percent"><strong>{percent}%</strong><span>stage progress</span></div>
        </div>
        <div className="media-progress-bar"><span style={{ width: `${percent}%` }} /></div>
        <div className="media-progress-steps four">
          <div className={referencePhase ? "active" : "done"}><span>{referencePhase ? "1" : <Check size={14} />}</span><strong>Character reference</strong></div>
          <div className={!referencePhase && !fidelityPhase ? "active" : referencePhase ? "pending" : "done"}><span>{referencePhase ? "2" : fidelityPhase ? <Check size={14} /> : "2"}</span><strong>Storyboard keyframes</strong></div>
          <div className={fidelityPhase ? "active" : referencePhase ? "pending" : "pending"}><span>3</span><strong>Fidelity review</strong></div>
          <div className="pending"><span>4</span><strong>Human approval</strong></div>
        </div>
        <div className="media-trust-note"><ShieldCheck size={18} /><span>Visual fidelity review is an AI-assisted review aid, not a calibrated score. The creator remains the final approver and can regenerate a mismatched shot or explicitly accept an adaptation.</span></div>
      </article>
    </section>
  );
}

function MediaStudioFailure(props: MediaStudioPanelProps) {
  const { job, onRegenerateReference, onApproveReference } = props;
  if (!job) return null;
  const canRetryKeyframes = Boolean(job.result?.reference_approved && job.result.reference_asset);
  return (
    <section className="media-studio-section" id="media-studio">
      <article className="media-failure glass-card" role="alert">
        <AlertTriangle size={28} />
        <div>
          <span className="eyebrow">Media generation paused</span>
          <h2>ReviveAI could not finish this visual pass.</h2>
          <p>{job.error || "The generated media pass did not complete."}</p>
          <p>Your approved M2A brief remains unchanged. {canRetryKeyframes ? "The approved character reference is still reusable." : "Retry only the character reference generation."}</p>
          <button className="secondary-button" onClick={canRetryKeyframes ? onApproveReference : onRegenerateReference}><RefreshCw size={16} /> {canRetryKeyframes ? "Retry keyframes" : "Retry reference"}</button>
        </div>
      </article>
    </section>
  );
}

function ReferenceReview({ productionJob, job, onApproveReference, onRegenerateReference }: MediaStudioPanelProps) {
  const [showPrompt, setShowPrompt] = useState(false);
  const [selectedSourceIndex, setSelectedSourceIndex] = useState(0);
  const asset = job?.result?.reference_asset;
  const source = job?.result?.source_snapshot;
  if (!job || !asset || !source) return null;

  const identity = source.production_identity;
  const identityEvidence = source.character_identity_evidence
    ?? productionJob?.result?.character_identity_evidence
    ?? null;
  const historicalSources = identityEvidence?.source_videos ?? [];
  const safeSourceIndex = Math.min(selectedSourceIndex, Math.max(0, historicalSources.length - 1));
  const sourceVideo = historicalSources[safeSourceIndex] ?? null;
  const groundedVideoIds = new Set(asset.identity_grounding_video_ids ?? []);
  const groundingImagesSupplied = Number(asset.identity_grounding_images_supplied ?? 0);
  const groundingExpected = historicalSources.length > 0;
  const groundingMissing = groundingExpected && groundingImagesSupplied < 1;

  return (
    <section className="media-studio-section" id="media-studio">
      <div className="media-title-row">
        <div>
          <div className="layer-badge media"><ImageIcon size={15} /> Visual Reference Studio</div>
          <span className="eyebrow">Milestone 2B.1.2 · Character identity review</span>
          <h2>Compare the new reference with {identity.character_name}'s real channel history.</h2>
          <p>Historical character appearances are the physical-identity source of truth. Wardrobe, props, setting and lighting may change for the new production.</p>
        </div>
        <div className="media-review-status"><span>1 of 3</span><strong>Character reference review</strong></div>
      </div>

      {groundingMissing && (
        <article className="media-failure glass-card" role="alert" style={{ marginBottom: 16 }}>
          <AlertTriangle size={24} />
          <div>
            <span className="eyebrow">Historical identity grounding missing</span>
            <h3 style={{ margin: "4px 0 6px" }}>Do not approve this reference yet.</h3>
            <p style={{ margin: 0 }}>
              ReviveAI found {historicalSources.length} previous {identityEvidence?.character_name || identity.character_name} appearance{historicalSources.length === 1 ? "" : "s"}, but none reached the image model for this generation. Regenerate the reference so the historical images are actually used.
            </p>
          </div>
        </article>
      )}

      <article className="glass-card" style={{ padding: 18, marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap", marginBottom: 14 }}>
          <div>
            <span className="eyebrow">Historical character appearances</span>
            <h3 style={{ margin: "4px 0 0" }}>
              {identityEvidence
                ? `${identityEvidence.character_name} · ${historicalSources.length} grounded source${historicalSources.length === 1 ? "" : "s"}`
                : `No Content DNA identity evidence resolved for ${identity.character_name}`}
            </h3>
          </div>
          {historicalSources.length > 1 && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }} aria-label="Historical character appearances">
              {historicalSources.slice(0, 6).map((video, index) => (
                <button
                  key={`${video.video_id}-${index}`}
                  type="button"
                  className={index === safeSourceIndex ? "primary-button" : "secondary-button"}
                  onClick={() => setSelectedSourceIndex(index)}
                  style={{ minHeight: 34, padding: "7px 11px" }}
                  title={video.title}
                >
                  <Images size={14} /> Appearance {index + 1}
                </button>
              ))}
            </div>
          )}
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(320px, 100%), 1fr))",
            gap: 16,
            alignItems: "stretch",
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 8 }}>
              <div>
                <span className="eyebrow">Historical identity source</span>
                <strong style={{ display: "block", marginTop: 3 }}>Previous {identity.character_name} appearance</strong>
              </div>
              {sourceVideo?.watch_url && (
                <a
                  href={sourceVideo.watch_url}
                  target="_blank"
                  rel="noreferrer"
                  className="secondary-button"
                  style={{ textDecoration: "none", minHeight: 34, padding: "7px 10px" }}
                >
                  View post <ExternalLink size={14} />
                </a>
              )}
            </div>
            <div
              style={{
                position: "relative",
                aspectRatio: "4 / 5",
                borderRadius: 16,
                overflow: "hidden",
                background: "rgba(5, 9, 24, 0.72)",
                border: "1px solid rgba(148, 163, 184, 0.16)",
                display: "grid",
                placeItems: "center",
              }}
            >
              {sourceVideo?.thumbnail_url ? (
                <img
                  src={sourceVideo.thumbnail_url}
                  alt={`Historical ${identity.character_name} appearance from ${sourceVideo.title}`}
                  referrerPolicy="no-referrer"
                  style={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }}
                />
              ) : (
                <div style={{ padding: 28, textAlign: "center", maxWidth: 420 }}>
                  <Images size={34} style={{ opacity: 0.65, marginBottom: 10 }} />
                  <strong style={{ display: "block", marginBottom: 6 }}>Historical character image unavailable</strong>
                  <span style={{ opacity: 0.72 }}>
                    {identityEvidence
                      ? "Content DNA resolved the character, but no usable thumbnail was retained for visual grounding."
                      : "This production does not contain Content DNA character-identity evidence yet."}
                  </span>
                </div>
              )}
              <span
                style={{
                  position: "absolute",
                  left: 12,
                  top: 12,
                  padding: "6px 9px",
                  borderRadius: 999,
                  background: "rgba(7, 12, 28, 0.82)",
                  border: "1px solid rgba(255,255,255,0.12)",
                  fontSize: 12,
                  fontWeight: 700,
                }}
              >
                HISTORICAL APPEARANCE
              </span>
              {sourceVideo && groundedVideoIds.has(sourceVideo.video_id) && (
                <span
                  style={{
                    position: "absolute",
                    right: 12,
                    top: 12,
                    padding: "6px 9px",
                    borderRadius: 999,
                    background: "rgba(16, 120, 92, 0.88)",
                    border: "1px solid rgba(255,255,255,0.16)",
                    fontSize: 12,
                    fontWeight: 700,
                  }}
                >
                  USED FOR GENERATION
                </span>
              )}
            </div>
            <div style={{ marginTop: 10, minHeight: 48 }}>
              <strong style={{ display: "block" }}>{sourceVideo?.title || "No historical source image available"}</strong>
              <span style={{ display: "block", marginTop: 4, opacity: 0.7, fontSize: 13 }}>
                {identityEvidence?.resolved_from_content_dna
                  ? "Resolved from Content DNA character evidence — not archive-concept similarity."
                  : "No grounded recurring-character evidence was attached."}
              </span>
            </div>
          </div>

          <div style={{ minWidth: 0 }}>
            <div style={{ marginBottom: 8 }}>
              <span className="eyebrow">Generated reference</span>
              <strong style={{ display: "block", marginTop: 3 }}>Proposed identity anchor · v{asset.generation_attempt}</strong>
            </div>
            <div
              style={{
                position: "relative",
                aspectRatio: "4 / 5",
                borderRadius: 16,
                overflow: "hidden",
                background: "rgba(5, 9, 24, 0.72)",
                border: groundingMissing ? "1px solid rgba(244, 63, 94, 0.5)" : "1px solid rgba(139, 92, 246, 0.34)",
                display: "grid",
                placeItems: "center",
              }}
            >
              <img
                src={mediaAssetUrl(asset.asset_url)}
                alt={`Generated reference for ${identity.character_name}`}
                style={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }}
              />
              <span
                style={{
                  position: "absolute",
                  left: 12,
                  top: 12,
                  padding: "6px 9px",
                  borderRadius: 999,
                  background: "rgba(88, 62, 190, 0.88)",
                  border: "1px solid rgba(255,255,255,0.16)",
                  fontSize: 12,
                  fontWeight: 700,
                }}
              >
                NEW REFERENCE
              </span>
            </div>
            <div style={{ marginTop: 10, minHeight: 48 }}>
              <strong style={{ display: "block" }}>{identity.character_name}</strong>
              <span style={{ display: "block", marginTop: 4, opacity: 0.7, fontSize: 13 }}>
                {groundingImagesSupplied > 0
                  ? `Generated with ${groundingImagesSupplied} historical identity image${groundingImagesSupplied === 1 ? "" : "s"}.`
                  : groundingExpected
                    ? "Historical sources exist but were not supplied to this generation."
                    : "Generated from Production Identity text because no recurring-character visual evidence was resolved."}
              </span>
            </div>
          </div>
        </div>

        <div className="media-review-checklist" style={{ marginTop: 16 }}>
          <ShieldCheck size={18} />
          <div>
            <strong>Historical appearance wins for physical identity.</strong>
            <span>Compare fur/coat, face, muzzle, eyes, ears, proportions and other stable traits. Production text controls wardrobe, props, setting, pose and lighting; it must not turn the recurring character into a different-looking animal.</span>
          </div>
        </div>
      </article>

      <div className="media-reference-layout">
        <article className="media-reference-card glass-card">
          <div style={{ padding: "4px 2px 12px" }}>
            <span className="eyebrow">Approval decision</span>
            <h3 style={{ margin: "5px 0 5px" }}>Use this as the production identity?</h3>
            <p style={{ margin: 0, opacity: 0.76 }}>
              Regenerate if {identity.character_name} is no longer visually recognizable. Approval locks this reference for all keyframes.
            </p>
          </div>
          <div className="media-reference-actions">
            <button className="secondary-button" onClick={onRegenerateReference}><RefreshCw size={16} /> Regenerate with history</button>
            <button className="primary-button" disabled={groundingMissing} onClick={onApproveReference} title={groundingMissing ? "Regenerate with historical identity grounding before approval." : undefined}>
              <BadgeCheck size={17} /> {groundingMissing ? "Grounding required" : "Approve reference"}
            </button>
          </div>
          <button className="media-prompt-toggle" onClick={() => setShowPrompt((v) => !v)}>{showPrompt ? "Hide generation prompt" : "Inspect generation prompt"}</button>
          {showPrompt && <pre className="media-prompt-preview">{asset.prompt}</pre>}
        </article>

        <article className="media-identity-review glass-card">
          <span className="eyebrow">Production styling lock</span>
          <h3>{identity.character_name}</h3>
          <p>{identityEvidence ? `Recurring character · ${identityEvidence.source_videos.length} historical appearance${identityEvidence.source_videos.length === 1 ? "" : "s"}` : identity.species_or_subject}</p>
          <div className="media-identity-facts">
            <Fact label="Production subject label" value={identity.species_or_subject} />
            <Fact label="Appearance notes" value={identity.appearance} />
            <Fact label="Wardrobe" value={identity.wardrobe} />
            <Fact label="Primary prop" value={identity.primary_prop} />
            <Fact label="Setting" value={identity.setting_anchor} />
            <Fact label="Lighting" value={identity.lighting_style} />
            <Fact label="Anatomy" value={identity.anatomy_rule} />
          </div>
          <div className="media-review-checklist">
            <ShieldCheck size={18} />
            <div>
              <strong>Physical identity precedence</strong>
              <span>If these text notes conflict with a clearly visible stable trait in the historical appearances, the historical visual evidence is authoritative.</span>
            </div>
          </div>
        </article>
      </div>
    </section>
  );
}

function KeyframeStudio({ job, onApproveKeyframe, onRegenerateKeyframe, onReviewAllKeyframes, onReviewKeyframe, onAcceptKeyframeAdaptation, onStartAnimation }: MediaStudioPanelProps) {
  if (!job?.result?.reference_asset) return null;
  const result = job.result;
  const ready = job.stage === "READY_FOR_ANIMATION" && result.animation_ready;
  const missingReview = result.keyframes.filter((asset) => !asset.fidelity_report).length;
  const needsCorrection = result.keyframes.filter((asset) => asset.fidelity_report?.status === "REVIEW_REQUIRED").length;
  const activeOperations = Object.values(result.shot_operations ?? {}).filter((operation) => operation.status === "REGENERATING" || operation.status === "FIDELITY_REVIEW");
  const reference = result.reference_asset!;
  const identity = result.source_snapshot.production_identity;
  const shotsByNumber = new Map<number, StoryboardShot>(result.source_snapshot.storyboard.shots.map((shot) => [shot.shot_number, shot]));
  return (
    <section className="media-studio-section media-keyframe-ready" id="media-studio">
      <div className="media-title-row">
        <div><div className="layer-badge media"><Film size={15} /> Keyframe Fidelity Studio</div><span className="eyebrow">Milestone 2B.1.2 {ready ? "complete" : "· Shot review"}</span><h2>{ready ? "Visual continuity and storyboard fidelity approved." : "Verify each frame actually matches the planned shot."}</h2><p>{ready ? "Every keyframe passed or received an explicit human adaptation decision, then was human-approved." : "Shot-level regeneration stays local: approved or passing frames remain visible while only the selected shot is corrected."}</p></div>
        <div className={`media-ready-status ${ready ? "ready" : "review"}`}>{ready ? <CircleCheckBig size={18} /> : <Eye size={18} />}<div><strong>{ready ? "Ready for M2B.2" : `${result.approved_keyframes}/${result.required_keyframes} human-approved`}</strong><span>{ready ? "Animation gate unlocked" : `${result.fidelity_passed_keyframes}/${result.required_keyframes} fidelity-cleared`}</span></div></div>
      </div>
      <article className="media-reference-strip glass-card">
        <img src={mediaAssetUrl(reference.asset_url)} alt="Approved character reference" />
        <div><span className="eyebrow">Approved identity anchor</span><h3>{identity.character_name}</h3><p>Every keyframe below was generated with this image attached as the visual identity source.</p></div>
        <span className="media-approved-badge"><Check size={14} /> Approved</span>
      </article>
      {activeOperations.length > 0 && (
        <article className="media-local-operation-summary glass-card" aria-live="polite">
          <RefreshCw size={19} className="media-spin" />
          <div><strong>{activeOperations.length} shot{activeOperations.length === 1 ? " is" : "s are"} updating locally.</strong><span>Other keyframes stay visible and keep their review/approval state.</span></div>
        </article>
      )}
      {(missingReview > 0 || needsCorrection > 0) && (
        <article className="media-fidelity-summary glass-card">
          <div className="media-fidelity-summary-icon"><Eye size={20} /></div>
          <div>
            <span className="eyebrow">Storyboard fidelity gate</span>
            <h3>{missingReview > 0 ? `${missingReview} shot${missingReview === 1 ? "" : "s"} still need fidelity review.` : `${needsCorrection} shot${needsCorrection === 1 ? "" : "s"} need a creator decision.`}</h3>
            <p>ReviveAI checks identity, wardrobe, setting, props, required action, camera framing, and camera angle. It does not use a numeric confidence score.</p>
          </div>
          {missingReview > 0 && <button className="secondary-button" onClick={onReviewAllKeyframes}><Eye size={16} /> Review missing shots</button>}
        </article>
      )}
      <div className="media-keyframe-grid">
        {result.keyframes.map((asset) => {
          const shotNumber = asset.shot_number || 0;
          const shot = shotsByNumber.get(shotNumber);
          const operation = result.shot_operations?.[String(shotNumber)] ?? null;
          return <KeyframeCard
            key={asset.asset_id}
            asset={asset}
            shot={shot}
            identity={identity}
            operation={operation}
            onApprove={() => onApproveKeyframe(shotNumber)}
            onRegenerate={() => onRegenerateKeyframe(shotNumber)}
            onReview={() => onReviewKeyframe(shotNumber)}
            onAcceptAdaptation={() => onAcceptKeyframeAdaptation(shotNumber)}
          />;
        })}
      </div>
      <div className="media-methodology"><ShieldCheck size={19} /><div><strong>Reference-first generation + shot-fidelity review + localized correction.</strong><span>{result.methodology_notice}</span></div></div>
      <div className={`media-next-stage ${ready ? "ready" : "locked"}`}><WandSparkles size={19} /><div><strong>Next: M2B.2 Veo animation</strong><span>{ready ? "Animate each approved keyframe into its matching shot while keeping clip review/regeneration local to that shot." : "Animation stays locked until every shot has a fidelity decision and human image approval."}</span></div>{ready ? <button className="primary-button" onClick={onStartAnimation}><PlayCircle size={16} /> Animate approved shots</button> : <span>Locked</span>}</div>
    </section>
  );
}

function KeyframeCard({ asset, shot, identity, operation, onApprove, onRegenerate, onReview, onAcceptAdaptation }: { asset: MediaAsset; shot?: StoryboardShot; identity: ProductionIdentity; operation?: ShotOperation | null; onApprove: () => void; onRegenerate: () => void; onReview: () => void; onAcceptAdaptation: () => void }) {
  const approved = asset.review_status === "APPROVED";
  const report = asset.fidelity_report;
  const reviewRequired = report?.status === "REVIEW_REQUIRED";
  const adaptationAccepted = report?.status === "ADAPTATION_ACCEPTED";
  const fidelityCleared = report?.status === "PASS" || adaptationAccepted;
  const busy = operation?.status === "REGENERATING" || operation?.status === "FIDELITY_REVIEW";
  const failed = operation?.status === "FAILED";
  const updated = operation?.status === "READY" && operation.updated_asset_id === asset.asset_id;
  const operationLabel = operation?.status === "FIDELITY_REVIEW" ? "Reviewing updated shot" : "Regenerating shot";
  return (
    <article className={`media-keyframe-card glass-card ${approved ? "approved" : ""} ${reviewRequired ? "fidelity-review" : fidelityCleared ? "fidelity-pass" : "fidelity-missing"} ${busy ? "shot-busy" : ""} ${failed ? "shot-failed" : ""}`}>
      <div className="media-keyframe-image">
        <img src={mediaAssetUrl(asset.asset_url)} alt={`Storyboard shot ${asset.shot_number}`} />
        <span>SHOT {String(asset.shot_number || 0).padStart(2, "0")}</span>
        <b className="media-version-badge">v{asset.generation_attempt}</b>
        {approved && !busy && <em><Check size={13} /> Approved</em>}
        {busy && (
          <div className="media-shot-busy-overlay" role="status" aria-live="polite">
            <RefreshCw size={24} className="media-spin" />
            <strong>{operationLabel} {String(asset.shot_number || 0).padStart(2, "0")}</strong>
            <span>{operation?.status === "FIDELITY_REVIEW" ? "New keyframe generated. Checking fidelity now…" : "Applying only the requested shot correction…"}</span>
            <div className="media-preserve-row"><small>Preserving</small><span>{identity.character_name}</span><span>wardrobe</span><span>setting</span><span>primary prop</span></div>
          </div>
        )}
      </div>
      <div className="media-keyframe-copy"><span className="eyebrow">{shot?.purpose || "Storyboard keyframe"}</span><h3>{shot?.visual_action || "Generated from approved storyboard"}</h3><p>{shot?.camera_direction}</p></div>
      {updated && <div className="media-shot-operation-state ready"><CircleCheckBig size={16} /><div><strong>Updated keyframe ready · v{asset.generation_attempt}</strong><span>Only this shot changed. Review the new fidelity result and approve when ready.</span></div></div>}
      {failed && <div className="media-shot-operation-state failed"><AlertTriangle size={16} /><div><strong>Shot regeneration failed</strong><span>{operation?.error || "The previous keyframe was preserved."}</span></div><button className="secondary-button" onClick={onRegenerate}><RefreshCw size={14} /> Retry this shot</button></div>}
      <FidelityReview report={report} onReview={onReview} />
      {reviewRequired && !busy && !failed && (
        <div className="media-fidelity-actions">
          <button className="secondary-button fidelity-regenerate" onClick={onRegenerate}><RefreshCw size={15} /> Regenerate to match shot</button>
          <button className="secondary-button fidelity-accept" onClick={onAcceptAdaptation}><BadgeCheck size={15} /> Accept adaptation</button>
        </div>
      )}
      <div className="media-keyframe-actions">
        {!reviewRequired && !busy && !failed && <button className="secondary-button" onClick={onRegenerate}><RefreshCw size={15} /> Regenerate</button>}
        <button className="primary-button" disabled={busy || approved || !fidelityCleared} onClick={onApprove}>{busy ? <RefreshCw size={15} className="media-spin" /> : approved ? <Check size={15} /> : <BadgeCheck size={15} />} {busy ? "Updating this shot" : approved ? "Approved" : !report ? "Review first" : reviewRequired ? "Resolve fidelity" : "Approve frame"}</button>
      </div>
    </article>
  );
}

function FidelityReview({ report, onReview }: { report?: KeyframeFidelityReport | null; onReview: () => void }) {
  if (!report) {
    return (
      <div className="media-fidelity-panel missing">
        <div><Eye size={17} /><div><strong>Fidelity review required</strong><span>This keyframe predates M2B.1.2 or its automatic review did not complete.</span></div></div>
        <button className="secondary-button" onClick={onReview}><Eye size={15} /> Run review</button>
      </div>
    );
  }
  const review = report.status === "REVIEW_REQUIRED";
  const accepted = report.status === "ADAPTATION_ACCEPTED";
  return (
    <div className={`media-fidelity-panel ${review ? "review" : accepted ? "accepted" : "pass"}`}>
      <div className="media-fidelity-title">
        {review ? <CircleAlert size={18} /> : <CircleCheckBig size={18} />}
        <div><span className="eyebrow">Keyframe fidelity review</span><strong>{review ? "Storyboard mismatch needs review" : accepted ? "Creative adaptation accepted" : "Matches approved shot"}</strong></div>
        <span className="media-fidelity-pill">{review ? "REVIEW" : accepted ? "ACCEPTED" : "PASS"}</span>
      </div>
      <div className="media-fidelity-checks">
        {report.checks.map((check) => <span key={check.key} className={check.status === "PASS" ? "pass" : "review"}>{check.status === "PASS" ? <Check size={12} /> : <AlertTriangle size={12} />}{check.label}</span>)}
      </div>
      {review && report.issues.length > 0 && <ul className="media-fidelity-issues">{report.issues.map((issue, index) => <li key={`${issue}-${index}`}>{issue}</li>)}</ul>}
      {review && report.corrective_instruction && <div className="media-correction-note"><strong>Targeted correction</strong><span>{report.corrective_instruction}</span></div>}
      <p className="media-fidelity-method">AI-assisted review aid; no numeric score is used. Human review remains authoritative.</p>
    </div>
  );
}

function ClipStudio({ job, onApproveClip, onRegenerateClip }: MediaStudioPanelProps) {
  const result = job?.result;
  if (!job || !result) return null;
  const shotsByNumber = new Map(result.source_snapshot.storyboard.shots.map((shot) => [shot.shot_number, shot]));
  const clipsByShot = new Map(result.video_clips.map((clip) => [clip.shot_number, clip]));
  const operations = result.clip_operations ?? {};
  const charges = result.video_generation_charges ?? [];
  const assemblyReady = result.assembly_ready;
  const totalEstimatedCost = charges.reduce((sum, charge) => sum + Number(charge.estimated_cost_usd || 0), 0);
  const initialEstimatedCost = charges.filter((charge) => charge.generation_attempt === 1).reduce((sum, charge) => sum + Number(charge.estimated_cost_usd || 0), 0);
  const regenerationEstimatedCost = Math.max(0, totalEstimatedCost - initialEstimatedCost);
  const submittedAttempts = charges.filter((charge) => charge.status !== "CLAIMED").length;
  return (
    <section className="media-studio-section media-clip-studio" id="media-studio">
      <div className="media-title-row">
        <div>
          <div className="layer-badge media"><Video size={15} /> Veo animation layer</div>
          <span className="eyebrow">Milestone 2B.2.1 · Shot Animation & Clip Review</span>
          <h2>Animate each approved frame, then review clips shot by shot.</h2>
          <p>Each clip starts from its approved keyframe. Regenerating one clip leaves every other clip visible and preserves its review state.</p>
        </div>
        <div className={`media-ready-status ${assemblyReady ? "ready" : "review"}`}><Film size={18} /><div><strong>{assemblyReady ? "Ready for M2C" : `${result.approved_clips}/${result.required_clips} clips approved`}</strong><span>{assemblyReady ? "Assembly gate unlocked" : job.stage === "GENERATING_CLIPS" ? "Veo is generating locally per shot" : "Human clip review required"}</span></div></div>
      </div>
      <article className="media-animation-trust glass-card">
        <ShieldCheck size={19} />
        <div><strong>Keyframe-to-video continuity.</strong><span>Veo receives the approved keyframe as the starting image plus the matching storyboard action/camera direction. Audio is disabled by default so M2C can add one coherent soundtrack later.</span></div>
      </article>
      <article className="media-cost-summary glass-card" aria-label="Estimated Veo generation cost">
        <div className="media-cost-summary-head">
          <div>
            <span className="eyebrow">Estimated AI generation cost</span>
            <strong>${totalEstimatedCost.toFixed(2)}</strong>
            <small>Production total across all recorded Veo attempts</small>
          </div>
          <div className="media-cost-model">{result.video_model || "Veo"}</div>
        </div>
        <div className="media-cost-metrics">
          <div><span>Initial generation</span><strong>${initialEstimatedCost.toFixed(2)}</strong></div>
          <div><span>Regenerations / retries</span><strong>${regenerationEstimatedCost.toFixed(2)}</strong></div>
          <div><span>Recorded attempts</span><strong>{charges.length}</strong></div>
          <div><span>Provider submissions</span><strong>{submittedAttempts}</strong></div>
        </div>
        <div className="media-cost-notice">
          <CircleAlert size={16} />
          <span>Estimate only. It includes retained retry/regeneration attempts; Google Cloud Billing remains authoritative for invoiced cost.</span>
        </div>
      </article>
      <div className="media-clip-grid">
        {result.source_snapshot.storyboard.shots.map((shot) => {
          const clip = clipsByShot.get(shot.shot_number);
          const operation = operations[String(shot.shot_number)] as ClipOperation | undefined;
          const keyframe = result.keyframes.find((asset) => asset.shot_number === shot.shot_number);
          const shotCharges = charges.filter((charge) => charge.shot_number === shot.shot_number);
          return <ClipCard key={shot.shot_number} shot={shot} clip={clip} operation={operation} charges={shotCharges} keyframe={keyframe} onApprove={() => onApproveClip(shot.shot_number)} onRegenerate={() => onRegenerateClip(shot.shot_number)} />;
        })}
      </div>
      <div className="media-methodology"><ShieldCheck size={19} /><div><strong>Human clip approval remains authoritative.</strong><span>Generated durations follow Veo-supported 4/6/8-second lengths; M2C will trim approved clips back to the storyboard timing during final assembly.</span></div></div>
      <div className={`media-next-stage ${assemblyReady ? "ready" : "locked"}`}><Film size={19} /><div><strong>Next: M2C final assembly</strong><span>{assemblyReady ? "Trim clips to storyboard timing, combine them in sequence, then add captions/audio from the approved publishing package." : "Assembly stays locked until every animated shot is human-approved."}</span></div><span>{assemblyReady ? "Ready" : "Locked"}</span></div>
    </section>
  );
}

function ClipCard({ shot, clip, operation, charges, keyframe, onApprove, onRegenerate }: { shot: StoryboardShot; clip?: VideoClipAsset; operation?: ClipOperation; charges: VideoGenerationCharge[]; keyframe?: MediaAsset; onApprove: () => void; onRegenerate: () => void }) {
  const busy = operation?.status === "QUEUED" || operation?.status === "GENERATING";
  const failed = operation?.status === "FAILED";
  const budgetBlocked = operation?.status === "BUDGET_EXCEEDED";
  const approved = clip?.review_status === "APPROVED";
  const shotEstimatedCost = charges.reduce((sum, charge) => sum + Number(charge.estimated_cost_usd || 0), 0);
  const latestCharge = charges.length ? charges[charges.length - 1] : undefined;
  return (
    <article className={`media-clip-card glass-card ${approved ? "approved" : ""} ${busy ? "clip-busy" : ""} ${failed ? "clip-failed" : ""}`}>
      <div className="media-clip-visual">
        {clip ? <video src={mediaAssetUrl(clip.asset_url)} controls playsInline preload="metadata" poster={keyframe ? mediaAssetUrl(keyframe.asset_url) : undefined} /> : keyframe ? <img src={mediaAssetUrl(keyframe.asset_url)} alt={`Approved keyframe for shot ${shot.shot_number}`} /> : <div className="media-clip-placeholder"><Film size={30} /></div>}
        <span className="media-shot-chip">SHOT {String(shot.shot_number).padStart(2, "0")}</span>
        {clip && <b className="media-version-badge">v{clip.generation_attempt}</b>}
        {busy && <div className="media-clip-busy-overlay"><RefreshCw size={25} className="media-spin"/><strong>{operation?.status === "QUEUED" ? "Queued for Veo" : `Animating Shot ${shot.shot_number}`}</strong><span>The existing keyframe stays visible while this clip is generated.</span></div>}
      </div>
      <div className="media-clip-copy">
        <span className="eyebrow">{shot.purpose}</span><h3>{shot.visual_action}</h3><p>{shot.camera_direction}</p>
        <div className="media-clip-duration"><span>Storyboard {shot.duration_seconds}s</span>{clip && <span>Veo output {clip.generated_duration_seconds}s</span>}</div>
        <div className="media-clip-cost">
          <div><span>Estimated generation cost</span><strong>${shotEstimatedCost.toFixed(2)}</strong></div>
          <small>
            {charges.length
              ? `${charges.length} recorded attempt${charges.length === 1 ? "" : "s"}${latestCharge ? ` · latest ${latestCharge.status.toLowerCase()}` : ""}`
              : busy && operation?.estimated_cost_usd
                ? `Current estimate $${Number(operation.estimated_cost_usd).toFixed(2)}`
                : "No paid Veo attempt recorded yet"}
          </small>
        </div>
      </div>
      {failed && <div className="media-shot-operation-state failed"><AlertTriangle size={16}/><div><strong>Animation failed</strong><span>{operation?.error || "The previous clip/keyframe was preserved."}</span></div></div>}
      {budgetBlocked && <div className="media-shot-operation-state failed"><AlertTriangle size={16}/><div><strong>Animation paused by budget limit</strong><span>{operation?.error || "The current production can continue using available assets."}</span></div></div>}
      <div className="media-keyframe-actions">
        <button className="secondary-button" disabled={busy || (!clip && !failed && !budgetBlocked)} onClick={onRegenerate}><RefreshCw size={15}/> {failed && !clip ? "Retry animation" : clip ? "Regenerate clip" : "Waiting for clip"}</button>
        <button className="primary-button" disabled={busy || (!clip && !budgetBlocked) || approved} onClick={onApprove}>{approved ? <Check size={15}/> : <BadgeCheck size={15}/>} {approved ? "Approved" : "Approve clip"}</button>
      </div>
    </article>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}
