import {
  AlertTriangle,
  BadgeCheck,
  BookOpenText,
  BrainCircuit,
  Check,
  ChevronRight,
  CircleCheckBig,
  Clapperboard,
  Copy,
  FileText,
  Film,
  Image,
  ListChecks,
  History,
  MessageSquareText,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Target,
  WandSparkles,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import type { ProductionBriefHistoryEntry, ProductionBriefJob, ProductionBriefResult, StoryboardShot } from "../types";

type BriefTab = "brief" | "storyboard" | "publish" | "evidence";

interface ProductionBriefPanelProps {
  job: ProductionBriefJob | null;
  history: ProductionBriefHistoryEntry[];
  error: string | null;
  onRetry: () => void;
  onApprove: () => void;
  onKeepOriginalDirection: () => void;
  onAcceptAdaptation: () => void;
  onOpenHistory: (jobId: string) => void;
  onStartMediaStudio: () => void;
}

const TERMINAL = new Set(["COMPLETED", "FAILED"]);

export function ProductionBriefPanel({ job, history, error, onRetry, onApprove, onKeepOriginalDirection, onAcceptAdaptation, onOpenHistory, onStartMediaStudio }: ProductionBriefPanelProps) {
  if (!job) return <ProductionBriefGate error={error} history={history} onOpenHistory={onOpenHistory} />;
  if (job.stage === "FAILED") return <ProductionBriefFailure job={job} onRetry={onRetry} />;
  if (!TERMINAL.has(job.stage)) return <ProductionBriefProgress job={job} />;
  if (job.stage === "COMPLETED" && job.result) {
    return <ProductionBriefDashboard job={job} result={job.result} history={history} onOpenHistory={onOpenHistory} onRetry={onRetry} onApprove={onApprove} onKeepOriginalDirection={onKeepOriginalDirection} onAcceptAdaptation={onAcceptAdaptation} onStartMediaStudio={onStartMediaStudio} />;
  }
  return null;
}

function ProductionBriefGate({ error, history, onOpenHistory }: { error: string | null; history: ProductionBriefHistoryEntry[]; onOpenHistory: (jobId: string) => void }) {
  return (
    <section className="production-section" id="production-studio">
      <article className="production-gate glass-card">
        <div className="production-gate-icon"><Clapperboard size={26} /></div>
        <div>
          <div className="layer-badge production"><WandSparkles size={15} /> Content creation layer</div>
          <span className="eyebrow">Milestone 2A.7 · Direction Fidelity Lock</span>
          <h2>Select a Recovery Plan direction to turn it into a production-ready brief.</h2>
          <p>
            Use <strong>Create production brief</strong> on any Recovery Plan recommendation. ReviveAI will preserve the approved direction, lock production continuity, and create a review-ready storyboard and publishing package.
          </p>
          <div className="production-gate-points">
            <span><ShieldCheck size={16} /> Human-selected direction</span>
            <span><Target size={16} /> Idea-specific Content DNA</span>
            <span><Film size={16} /> Shot-by-shot execution plan</span>
          </div>
          {error && <div className="dna-inline-error" role="alert"><AlertTriangle size={17} /><div><strong>Production Studio is not ready</strong><span>{error}</span></div></div>}
        </div>
      </article>
      <ProductionHistory history={history} onOpen={onOpenHistory} />
    </section>
  );
}

function ProductionBriefProgress({ job }: { job: ProductionBriefJob }) {
  const steps = [
    ["PREPARING_CONTEXT", "Lock direction"],
    ["BUILDING_CREATIVE_DIRECTION", "Creative brief"],
    ["BUILDING_STORYBOARD_OUTLINE", "Shot plan"],
    ["BUILDING_STORYBOARD_PROMPTS", "Prompt pack"],
    ["BUILDING_PUBLISHING_PACKAGE", "Publish package"],
  ] as const;
  const stageIndex = Math.max(0, steps.findIndex(([key]) => key === job.stage));
  const percent = Math.min(96, Math.round(((job.progress_current + 0.35) / Math.max(1, job.progress_total)) * 100));
  const calls = Number(job.detail.gemini_calls ?? 0);
  const shots = Number(job.detail.storyboard_shots ?? 0);
  const title = String(job.detail.recommendation_title ?? "Selected recovery direction");

  return (
    <section className="production-section" id="production-studio" aria-live="polite">
      <article className="production-progress glass-card">
        <div className="production-progress-head">
          <div className="production-progress-icon"><BrainCircuit size={31} /></div>
          <div className="production-progress-copy">
            <div className="layer-badge production"><Sparkles size={15} /> Gemini Creative Director</div>
            <span className="eyebrow">Building production brief</span>
            <h2>{job.message}</h2>
            <p>{title}</p>
          </div>
          <div className="production-progress-percent"><strong>{percent}%</strong><span>overall</span></div>
        </div>
        <div className="production-progress-bar"><span style={{ width: `${percent}%` }} /></div>
        <div className="production-stage-grid">
          {steps.map(([key, label], index) => {
            const state = index < stageIndex ? "done" : index === stageIndex ? "active" : "pending";
            return <div className={`production-stage ${state}`} key={key}><span>{state === "done" ? <CircleCheckBig size={15} /> : index + 1}</span><strong>{label}</strong></div>;
          })}
        </div>
        <div className="production-live-grid">
          <ProductionLiveFact label="Gemini calls" value={String(calls)} helper="small structured passes" />
          <ProductionLiveFact label="Storyboard" value={shots ? `${shots} shots` : "Building"} helper="outline and prompts are separate passes" />
          <ProductionLiveFact label="Resume protection" value={job.detail.checkpoint_available || job.detail.resumed_from_checkpoint ? "Saved" : "Active"} helper="completed M2A stages are checkpointed" />
          <ProductionLiveFact label="Creative firewall" value="Active" helper="no view counts in writing prompts" />
        </div>
        <div className="production-trust-note"><ShieldCheck size={18} /><span>Historic performance stays outside the creative-writing prompts. The selected M1D direction and relevant Content DNA guide the brief instead.</span></div>
      </article>
    </section>
  );
}

function ProductionBriefFailure({ job, onRetry }: { job: ProductionBriefJob; onRetry: () => void }) {
  return (
    <section className="production-section" id="production-studio">
      <article className="production-failure glass-card" role="alert">
        <AlertTriangle size={28} />
        <div>
          <span className="eyebrow">Production brief paused</span>
          <h2>ReviveAI could not finish this production pass.</h2>
          <p>{job.error || "The production brief could not be completed."}</p>
          <p className="production-failure-helper">Your Recovery Intelligence direction is unchanged. Completed M2A stages are checkpointed, so retry resumes from the latest successful production stage instead of starting over.</p>
          <button className="secondary-button" onClick={onRetry}><RefreshCw size={16} /> Retry production brief</button>
        </div>
      </article>
    </section>
  );
}

function ProductionBriefDashboard({
  job,
  result,
  onRetry,
  onApprove,
  onKeepOriginalDirection,
  onAcceptAdaptation,
  onStartMediaStudio,
  history,
  onOpenHistory,
}: {
  job: ProductionBriefJob;
  result: ProductionBriefResult;
  history: ProductionBriefHistoryEntry[];
  onOpenHistory: (jobId: string) => void;
  onRetry: () => void;
  onApprove: () => void;
  onKeepOriginalDirection: () => void;
  onAcceptAdaptation: () => void;
  onStartMediaStudio: () => void;
}) {
  const [tab, setTab] = useState<BriefTab>("brief");
  const approved = result.review_status === "APPROVED";
  const consistencyPass = result.consistency_report.status === "PASS";
  const fidelityStatus = result.direction_fidelity.status;
  const fidelityReady = fidelityStatus === "PASS" || fidelityStatus === "ADAPTATION_ACCEPTED";
  const approvalReady = consistencyPass && fidelityReady;
  const fidelityIssues = result.direction_fidelity.blocking_issues.length;

  return (
    <section className="production-section production-ready" id="production-studio">
      <div className="production-title-row">
        <div>
          <div className="layer-badge production"><Clapperboard size={15} /> Production Studio</div>
          <span className="eyebrow">Milestone 2A.7 complete · Media-ready</span>
          <h2>From recovery idea to production-ready brief.</h2>
          <p>The selected M1D direction is now translated into a creative north star, storyboard, generation prompts, and publishing package.</p>
        </div>
        <div className={`production-review-status ${approved ? "approved" : approvalReady ? "review" : "blocked"}`}>
          {approved ? <CircleCheckBig size={17} /> : approvalReady ? <ListChecks size={17} /> : <AlertTriangle size={17} />}
          <div>
            <strong>{approved ? "Approved" : fidelityStatus === "REVIEW_REQUIRED" ? "Direction fidelity review" : consistencyPass ? "Needs human review" : "Consistency review required"}</strong>
            <span>{approved ? "Ready for the next creation stage" : fidelityStatus === "REVIEW_REQUIRED" ? `${fidelityIssues} source detail${fidelityIssues === 1 ? "" : "s"} changed — review before approval` : fidelityStatus === "ADAPTATION_ACCEPTED" ? "Creative adaptation accepted — final approval required" : consistencyPass ? "Direction fidelity and identity locks passed" : "Resolve consistency blockers before approval"}</span>
          </div>
        </div>
      </div>

      <ProductionHero result={result} />

      <div className="production-action-row">
        <button className="secondary-button" onClick={onRetry}><RefreshCw size={16} /> Regenerate brief</button>
        {fidelityStatus === "REVIEW_REQUIRED" && !approved && (
          <>
            <button className="secondary-button fidelity-keep" onClick={onKeepOriginalDirection}><ShieldCheck size={16} /> Keep original direction</button>
            <button className="secondary-button fidelity-accept" onClick={onAcceptAdaptation}><Check size={16} /> Accept creative adaptation</button>
          </>
        )}
        {!approved ? (
          <button className="primary-button production-approve" onClick={onApprove} disabled={!approvalReady} title={!consistencyPass ? "Resolve Production Identity consistency blockers before approval." : !fidelityReady ? "Review the Direction Fidelity changes before approval." : undefined}>
            {approvalReady ? <BadgeCheck size={17} /> : <AlertTriangle size={17} />}
            {approvalReady ? "Approve production brief" : !fidelityReady ? "Direction review required" : "Consistency blockers detected"}
          </button>
        ) : (
          <div className="production-approved-chip"><Check size={16} /> Approval recorded</div>
        )}
      </div>

      <ProductionHistory history={history} currentJobId={job.job_id} onOpen={onOpenHistory} />

      <nav className="production-tabs" aria-label="Production brief views">
        {(["brief", "storyboard", "publish", "evidence"] as BriefTab[]).map((item) => (
          <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>
            <span /> {item === "brief" ? "Creative brief" : item === "storyboard" ? "Storyboard" : item === "publish" ? "Publishing" : "Evidence anchor"}
          </button>
        ))}
      </nav>

      {tab === "brief" && <CreativeBriefView result={result} />}
      {tab === "storyboard" && <StoryboardView result={result} />}
      {tab === "publish" && <PublishingView result={result} />}
      {tab === "evidence" && <ProductionEvidenceView result={result} />}

      <div className="production-methodology"><ShieldCheck size={19} /><div><strong>Creative draft, not auto-publish.</strong><span>{result.methodology_notice}</span></div></div>
      <div className="production-next-lock"><WandSparkles size={18} /><div><strong>Next: M2B visual reference studio</strong><span>{approved ? "Create a canonical character reference and storyboard keyframes from this approved Production Identity before animation." : !fidelityReady ? "Review the source-direction change before approval and media generation." : consistencyPass ? "Approve this fidelity-checked brief before ReviveAI generates media assets." : "Resolve Production Identity consistency blockers before approval and media generation."}</span></div>{approved ? <button className="media-inline-launch" onClick={onStartMediaStudio}><Image size={15} /> Start M2B.1.2</button> : <span className="locked">Locked</span>}</div>
      <span className="production-job-id">Brief {job.job_id.slice(-8)} · {result.model} · {result.gemini_calls} Gemini calls</span>
    </section>
  );
}

function ProductionHero({ result }: { result: ProductionBriefResult }) {
  const brief = result.creative_direction;
  return (
    <article className="production-hero glass-card">
      <div className="production-hero-main">
        <span className="eyebrow">Creative north star</span>
        <h3>{brief.working_title}</h3>
        <p className="production-promise">{brief.one_sentence_promise}</p>
        <div className="production-hero-meta">
          <span><Film size={15} /> {brief.target_duration_seconds}s target</span>
          <span><Clapperboard size={15} /> {brief.format}</span>
          <span><MessageSquareText size={15} /> {brief.tone.slice(0, 3).join(" · ")}</span>
          <span><ShieldCheck size={15} /> {brief.production_identity.character_name} locked</span>
          <span><Target size={15} /> {brief.production_identity.subject_count} subject{brief.production_identity.subject_count === 1 ? "" : "s"} locked</span>
        </div>
      </div>
      <aside className="production-hook-card">
        <span>Opening hook</span>
        <strong>“{brief.opening_hook}”</strong>
        <em>{brief.setting}</em>
      </aside>
    </article>
  );
}

function CreativeBriefView({ result }: { result: ProductionBriefResult }) {
  const brief = result.creative_direction;
  return (
    <div className="production-view">
      <div className="production-view-heading"><div><span className="eyebrow">Creative direction</span><h3>What are we making, and what must stay consistent?</h3></div><p>One reviewed brief becomes the source of truth for future image/video generation.</p></div>
      <ProductionIdentityPanel result={result} />
      <DirectionFidelityPanel result={result} />
      <div className="production-brief-grid">
        <ProductionBriefCard icon={<Target size={19} />} label="Creative objective" value={brief.creative_objective} />
        <ProductionBriefCard icon={<BookOpenText size={19} />} label="Narrative arc" value={brief.narrative_arc} />
        <ProductionBriefCard icon={<Sparkles size={19} />} label="Character direction" value={brief.character_direction} />
        <ProductionBriefCard icon={<Image size={19} />} label="Setting" value={brief.setting} />
      </div>
      <div className="production-list-grid">
        <ProductionListCard title="Continuity lock" icon={<ShieldCheck size={18} />} items={brief.continuity_rules} />
        <ProductionListCard title="Avoid" icon={<AlertTriangle size={18} />} items={brief.avoid} />
        <ProductionListCard title="Asset checklist" icon={<ListChecks size={18} />} items={brief.asset_checklist} wide />
      </div>
      <ConsistencyLockPanel result={result} />
    </div>
  );
}

function StoryboardView({ result }: { result: ProductionBriefResult }) {
  const usedFallbackPrompts = result.storyboard.prompt_generation_mode === "deterministic_fallback";
  return (
    <div className="production-view">
      <div className="production-view-heading"><div><span className="eyebrow">Shot plan</span><h3>{result.storyboard.shots.length} shots · ~{formatDuration(result.storyboard.estimated_duration_seconds)}</h3></div><p>Generation prompts are draft inputs for the next media-generation milestone.</p></div>
      {usedFallbackPrompts && (
        <div className="production-prompt-fallback" role="status">
          <AlertTriangle size={17} />
          <div><strong>Prompt enrichment used a safe fallback.</strong><span>The shot outline was generated by Gemini, but media prompts were assembled deterministically from that approved outline after prompt enrichment could not complete. Review them before M2B.</span></div>
        </div>
      )}
      <div className="storyboard-list">
        {result.storyboard.shots.map((shot) => <StoryboardCard key={shot.shot_number} shot={shot} />)}
      </div>
    </div>
  );
}

function StoryboardCard({ shot }: { shot: StoryboardShot }) {
  const [copied, setCopied] = useState(false);
  async function copyPrompt() {
    try {
      await navigator.clipboard.writeText(shot.generation_prompt);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  }
  return (
    <article className="storyboard-card glass-card">
      <div className="storyboard-number"><span>{String(shot.shot_number).padStart(2, "0")}</span><em>{shot.duration_seconds}s</em></div>
      <div className="storyboard-content">
        <span className="storyboard-purpose">{shot.purpose}</span>
        <h4>{shot.visual_action}</h4>
        <div className="storyboard-detail-grid">
          <div><span>Camera</span><strong>{shot.camera_direction}</strong></div>
          <div><span>On-screen text</span><strong>{shot.on_screen_text || "None"}</strong></div>
          <div><span>Voice / dialogue</span><strong>{shot.voiceover_or_dialogue || "None"}</strong></div>
        </div>
        <div className="storyboard-prompt"><div><span>Generation prompt</span><button onClick={copyPrompt}>{copied ? <Check size={14} /> : <Copy size={14} />} {copied ? "Copied" : "Copy"}</button></div><p>{shot.generation_prompt}</p></div>
      </div>
    </article>
  );
}

function PublishingView({ result }: { result: ProductionBriefResult }) {
  const publishing = result.publishing;
  return (
    <div className="production-view">
      <div className="production-view-heading"><div><span className="eyebrow">Review-ready copy</span><h3>Publishing package</h3></div><p>Draft copy stays editable by the creator before anything is published.</p></div>
      <ConsistencyLockPanel result={result} compact />
      <div className="publishing-grid">
        <PublishingCard label="YouTube title" value={publishing.youtube_title} />
        <PublishingCard label="Description" value={publishing.description} large />
        <PublishingCard label="Social caption" value={publishing.social_caption} large />
        <PublishingCard label="Thumbnail concept" value={publishing.thumbnail_concept} />
        <PublishingCard label="Audio direction" value={publishing.audio_direction} />
        <PublishingCard label="Accessibility alt text" value={publishing.accessibility_alt_text} />
      </div>
      <div className="publishing-bottom-grid">
        <article className="publishing-list glass-card"><span className="eyebrow">Hashtags</span><div className="publishing-hashtags">{publishing.hashtags.map((item) => <span key={item}>{item}</span>)}</div></article>
        <article className="publishing-list glass-card"><span className="eyebrow">Human review checklist</span><ul>{publishing.review_notes.map((item) => <li key={item}><Check size={14} /> {item}</li>)}</ul></article>
      </div>
    </div>
  );
}

function ProductionEvidenceView({ result }: { result: ProductionBriefResult }) {
  const rec = result.selected_recommendation;
  return (
    <div className="production-view">
      <div className="production-view-heading"><div><span className="eyebrow">Creative firewall</span><h3>What evidence selected the direction?</h3></div><p>These metrics explain the M1D choice; they were not shown to Gemini while writing the brief.</p></div>
      <div className="production-evidence-banner"><ShieldCheck size={19} /><span>{result.creative_firewall_notice}</span></div>
      <article className="source-snapshot-card glass-card">
        <div><span className="eyebrow">Immutable source direction snapshot</span><h4>{result.source_snapshot.recommendation.title}</h4><p>{result.source_snapshot.recommendation.concept}</p></div>
        <div className="source-snapshot-meta">
          <span><ShieldCheck size={14} /> Captured {formatTimestamp(result.source_snapshot.captured_at)}</span>
          <span>Source hash {result.source_snapshot.source_hash}</span>
          <span>{result.source_snapshot.channel_title}</span>
        </div>
      </article>

      <div className="production-evidence-grid">
        <article className="production-evidence-card glass-card">
          <span className="eyebrow">Selected direction</span>
          <h4>{rec.title}</h4><p>{rec.concept}</p>
          <div className="production-evidence-chips"><span>{rec.evidence_strength === "STRONG" ? "Strong evidence" : rec.evidence_strength === "SUPPORTED" ? "Supported direction" : "Exploratory"}</span><span>{rec.novelty_label}</span></div>
        </article>
        <article className="production-evidence-card glass-card">
          <span className="eyebrow">Idea-specific Content DNA</span>
          <div className="production-signal-list">{result.evidence_anchor.map((signal) => <div key={`${signal.kind}-${signal.name}`}><strong>{signal.name}</strong><span>{kindLabel(signal.kind)} · {signal.evidence.video_count} videos</span><em>{formatRatio(signal.evidence.relative_to_channel_median)}</em></div>)}</div>
        </article>
      </div>
      {result.closest_archive_matches.length > 0 && <article className="production-archive-check glass-card"><span className="eyebrow">Closest archive concepts</span><p>Used to reduce accidental repetition, not as templates to copy.</p><div>{result.closest_archive_matches.map((match) => <a key={match.video.video_id} href={match.video.watch_url} target="_blank" rel="noreferrer">{match.video.thumbnail_url && <img src={match.video.thumbnail_url} alt="" />}<span><strong>{match.video.title}</strong><em>{match.similarity_label}</em></span><ChevronRight size={14} /></a>)}</div></article>}
    </div>
  );
}

function ProductionIdentityPanel({ result }: { result: ProductionBriefResult }) {
  const identity = result.creative_direction.production_identity;
  return (
    <article className="production-identity glass-card">
      <div className="production-identity-head">
        <div><span className="eyebrow">Production identity</span><h4>{identity.character_name}</h4><p>Canonical source of truth for character continuity in M2A and future media generation.</p></div>
        <span className="identity-lock-chip"><ShieldCheck size={15} /> Identity locked</span>
      </div>
      <div className="production-identity-grid">
        <IdentityFact label="Subject" value={identity.species_or_subject} />
        <IdentityFact label="Subject count" value={String(identity.subject_count)} />
        <IdentityFact label="Supporting subjects" value={identity.supporting_subjects.join(" · ") || "None"} />
        <IdentityFact label="Appearance" value={identity.appearance} />
        <IdentityFact label="Wardrobe" value={identity.wardrobe} />
        <IdentityFact label="Personality" value={identity.personality.join(" · ") || "Not specified"} />
        <IdentityFact label="Primary prop" value={identity.primary_prop} />
        <IdentityFact label="Setting anchor" value={identity.setting_anchor} />
        <IdentityFact label="Lighting" value={identity.lighting_style} />
        <IdentityFact label="Anatomy rule" value={identity.anatomy_rule} wide />
      </div>
    </article>
  );
}

function IdentityFact({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return <div className={`identity-fact ${wide ? "wide" : ""}`}><span>{label}</span><strong>{value}</strong></div>;
}

function DirectionFidelityPanel({ result }: { result: ProductionBriefResult }) {
  const report = result.direction_fidelity;
  const passed = report.status === "PASS";
  const accepted = report.status === "ADAPTATION_ACCEPTED";
  const review = report.status === "REVIEW_REQUIRED";
  return (
    <article className={`direction-fidelity glass-card ${passed ? "pass" : accepted ? "accepted" : "review"}`}>
      <div className="direction-fidelity-head">
        <div>
          {passed ? <CircleCheckBig size={20} /> : accepted ? <BadgeCheck size={20} /> : <AlertTriangle size={20} />}
          <div>
            <span className="eyebrow">Direction fidelity lock</span>
            <h4>{passed ? "Approved M1D direction preserved" : accepted ? "Creative adaptation explicitly accepted" : "The brief changed a source detail"}</h4>
          </div>
        </div>
        <span className={`direction-fidelity-status ${passed ? "pass" : accepted ? "accepted" : "review"}`}>{passed ? "PASS" : accepted ? "ADAPTATION ACCEPTED" : "REVIEW REQUIRED"}</span>
      </div>
      <div className="direction-fidelity-source">
        <span>Approved source direction</span>
        <strong>{report.contract.source_title}</strong>
        <p>{report.contract.source_concept}</p>
      </div>
      <div className="direction-fidelity-grid">
        {report.checks.map((check) => (
          <div className={`direction-fidelity-check ${check.status.toLowerCase()}`} key={check.key}>
            <div className="direction-fidelity-check-top"><strong>{check.label}</strong><span>{check.status}</span></div>
            <div className="direction-fidelity-compare"><div><em>Source</em><span>{check.source_value}</span></div><div><em>Brief</em><span>{check.brief_value}</span></div></div>
            <p>{check.detail}</p>
          </div>
        ))}
      </div>
      {review && <div className="direction-fidelity-note"><AlertTriangle size={16} /><span>Approval is locked until you regenerate with the original direction preserved or explicitly accept this creative adaptation.</span></div>}
      {accepted && <div className="direction-fidelity-note accepted"><BadgeCheck size={16} /><span>The creator explicitly accepted this adaptation. Final production approval is still required.</span></div>}
    </article>
  );
}

function ConsistencyLockPanel({ result, compact = false }: { result: ProductionBriefResult; compact?: boolean }) {
  const report = result.consistency_report;
  const passed = report.status === "PASS";
  return (
    <article className={`consistency-lock glass-card ${passed ? "pass" : "review"} ${compact ? "compact" : ""}`}>
      <div className="consistency-lock-head">
        <div>{passed ? <CircleCheckBig size={19} /> : <AlertTriangle size={19} />}<div><span className="eyebrow">Consistency lock</span><h4>{passed ? "Production identity is internally consistent" : "Consistency review required"}</h4></div></div>
        <span className={`consistency-status ${passed ? "pass" : "review"}`}>{passed ? "PASS" : "REVIEW REQUIRED"}</span>
      </div>
      {!compact && <div className="consistency-check-grid">{report.checks.map((check) => <div className={`consistency-check ${check.status.toLowerCase()}`} key={check.key}><span>{check.status === "PASS" ? <Check size={14} /> : <AlertTriangle size={14} />}</span><div><strong>{check.label}</strong><em>{check.detail}</em></div></div>)}</div>}
      {compact && <p>{passed ? "Character name, setting, primary prop, storyboard timing, generation prompts, and anatomy rules passed the deterministic consistency checks." : report.blocking_issues[0] || "Resolve the consistency blockers before approval."}</p>}
      {!compact && report.anchors && <div className="consistency-anchor-row"><span>Semantic anchors</span><em>Setting: {report.anchors.setting_terms.join(" · ") || "—"}</em><em>Prop: {report.anchors.primary_prop_terms.join(" · ") || "—"}</em></div>}
      {report.warnings.length > 0 && !compact && <div className="consistency-warnings"><strong>Review notes</strong>{report.warnings.map((item) => <span key={item}>{item}</span>)}</div>}
    </article>
  );
}

function ProductionHistory({ history, currentJobId, onOpen }: { history: ProductionBriefHistoryEntry[]; currentJobId?: string; onOpen: (jobId: string) => void }) {
  if (!history.length) return null;
  return (
    <details className="production-history glass-card">
      <summary><span><History size={16} /> Saved production briefs</span><em>{history.length} saved</em></summary>
      <div className="production-history-list">
        {history.slice(0, 8).map((entry) => {
          const active = entry.job_id === currentJobId;
          return (
            <button key={entry.job_id} className={active ? "active" : ""} onClick={() => onOpen(entry.job_id)} disabled={active}>
              <span>{entry.source_snapshot.recommendation.title}</span>
              <strong>{entry.working_title || (entry.stage === "FAILED" ? "Paused brief" : "Production brief")}</strong>
              <em>{formatTimestamp(entry.captured_at)} · {entry.review_status === "APPROVED" ? "Approved" : entry.stage === "COMPLETED" ? "Review ready" : entry.stage.toLowerCase().replace(/_/g, " ")}</em>
            </button>
          );
        })}
      </div>
      <p className="production-history-note">Each saved brief keeps an immutable copy of the exact M1D direction selected at creation time, even if Recovery Intelligence is generated again later.</p>
    </details>
  );
}

function formatTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
}

function ProductionBriefCard({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <article className="production-brief-card glass-card"><span>{icon}</span><div><em>{label}</em><strong>{value}</strong></div></article>;
}
function ProductionListCard({ title, icon, items, wide = false }: { title: string; icon: ReactNode; items: string[]; wide?: boolean }) {
  return <article className={`production-list-card glass-card ${wide ? "wide" : ""}`}><div className="production-list-title">{icon}<strong>{title}</strong></div><ul>{items.map((item) => <li key={item}><span />{item}</li>)}</ul></article>;
}
function PublishingCard({ label, value, large = false }: { label: string; value: string; large?: boolean }) {
  return <article className={`publishing-card glass-card ${large ? "large" : ""}`}><span>{label}</span><p>{value}</p></article>;
}
function ProductionLiveFact({ label, value, helper }: { label: string; value: string; helper: string }) {
  return <div className="production-live-fact"><span>{label}</span><strong>{value}</strong><em>{helper}</em></div>;
}
function kindLabel(kind: string) { return kind === "story_pattern" ? "Story pattern" : kind === "visual_pattern" ? "Visual pattern" : kind.charAt(0).toUpperCase() + kind.slice(1); }
function formatRatio(value?: number | null) { return value == null ? "—" : `${value.toFixed(1)}× median`; }
function formatDuration(value: number) { return value < 60 ? `${Math.round(value)}s` : `${Math.floor(value / 60)}m ${Math.round(value % 60)}s`; }
