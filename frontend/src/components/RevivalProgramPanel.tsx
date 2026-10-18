import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CalendarClock,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronRight,
  Compass,
  Flame,
  Gauge,
  Layers3,
  LoaderCircle,
  Pause,
  Play,
  Sparkles,
  Target,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import "./RevivalProgramPanel.css";
import { AdaptiveLearningPanel } from "./AdaptiveLearningPanel";
import type {
  NextContentRecommendation,
  ProductionBriefHistoryEntry,
  RecoveryJobStage,
  RecoveryResult,
  RevivalCadenceIntensity,
  RevivalProgram,
  RevivalProgramIdea,
  TrendDirection,
  TrendDirectionSet,
} from "../types";

interface Props {
  channelTitle: string;
  program: RevivalProgram | null;
  recovery: RecoveryResult | null;
  recoveryStage?: RecoveryJobStage | null;
  dnaReady: boolean;
  recoveryReady: boolean;
  history: ProductionBriefHistoryEntry[];
  pending: boolean;
  error: string | null;
  lineageCheckPending?: boolean;
  restorePending?: boolean;
  restorePhase?: "CONTENT_DNA" | "RECOVERY" | null;
  onRestoreFromSavedEvidence?: () => void;
  onCreate: () => void;
  onUpdateCadence: (intensity: RevivalCadenceIntensity) => void;
  onCreateProduction: (item: NextContentRecommendation) => void;
  onOpenIntelligence: (target: "dna" | "recovery") => void;
  autopilot?: {
    status: "IDLE" | "RUNNING" | "PAUSED" | "NEEDS_ATTENTION" | "WAITING_FOR_FINAL_APPROVAL" | "WAITING_FOR_LEARNING" | "COMPLETED";
    currentTitle: string | null;
    currentRecommendationId: string | null;
    message: string;
    attentionStage: string | null;
    completedCount: number;
    completedRecommendationIds: string[];
    blockedProductions: Array<{
      recommendationId: string;
      title: string;
      message: string;
      kind: "INFRASTRUCTURE" | "CONTENT" | "TECHNICAL";
      resolutionStatus?: "RETRYABLE" | "ARCHIVED" | "BLOCKING" | null;
      blocksAutonomy?: boolean | null;
    }>;
  };
  onStartAutopilot?: () => void;
  onRunIdeaWithAutopilot?: (recommendationId: string) => void;
  onPauseAutopilot?: () => void;
  onResumeAutopilot?: () => void;
  trendDirections?: TrendDirectionSet | null;
  trendPending?: boolean;
  trendError?: string | null;
  customDirectionPending?: boolean;
  onDiscoverTrends?: () => void;
  onRefineCustomDirection?: (idea: string) => void;
  onSelectTrendDirection?: (direction: TrendDirection) => void;
}

const CADENCE_OPTIONS: Array<{
  value: RevivalCadenceIntensity;
  label: string;
  detail: string;
  posts: string;
}> = [
  { value: "AUTO", label: "Adaptive", detail: "ReviveAI balances channel evidence, freshness, and backlog.", posts: "Recommended" },
  { value: "SUSTAINABLE", label: "Sustainable", detail: "Lower production load and more breathing room.", posts: "2 / week" },
  { value: "BALANCED", label: "Balanced", detail: "A steady content cadence with regular testing.", posts: "3 / week" },
  { value: "ACCELERATED", label: "Accelerated", detail: "Faster experimentation when production capacity allows.", posts: "5 / week" },
  { value: "DAILY_SPRINT", label: "Daily sprint", detail: "An intensive short test, not an automatic 30-day commitment.", posts: "7 / week" },
];

function laneLabel(lane: RevivalProgramIdea["lane"]) {
  if (lane === "CORE") return "Core";
  if (lane === "ADJACENT") return "Adjacent";
  return "Experiment";
}

function PrerequisiteStep({ complete, active, label }: { complete: boolean; active?: boolean; label: string }) {
  return (
    <div className={`revival-prereq-step ${complete ? "is-complete" : active ? "is-active" : ""}`}>
      <span>{complete ? <Check size={14} aria-hidden="true" /> : <span className="revival-prereq-dot" />}</span>
      <strong>{label}</strong>
    </div>
  );
}

export function RevivalProgramPanel({
  channelTitle,
  program,
  recovery,
  recoveryStage,
  dnaReady,
  recoveryReady,
  history,
  pending,
  error,
  lineageCheckPending = false,
  restorePending = false,
  restorePhase = null,
  onRestoreFromSavedEvidence,
  onCreate,
  onUpdateCadence,
  onCreateProduction,
  onOpenIntelligence,
  autopilot,
  onStartAutopilot,
  onRunIdeaWithAutopilot,
  onPauseAutopilot,
  onResumeAutopilot,
  trendDirections = null,
  trendPending = false,
  trendError = null,
  customDirectionPending = false,
  onDiscoverTrends,
  onRefineCustomDirection,
  onSelectTrendDirection,
}: Props) {
  const [customIdea, setCustomIdea] = useState("");
  const [customSubmissionStarted, setCustomSubmissionStarted] = useState(false);
  const customResultRef = useRef<HTMLDivElement | null>(null);
  const customPendingSeenRef = useRef(false);
  if (!recoveryReady || !recovery) {
    const recoveryRunning = Boolean(recoveryStage && !["COMPLETED", "FAILED"].includes(recoveryStage));
    const recoveryFailed = recoveryStage === "FAILED";
    const hasSavedProductions = history.length > 0;
    const canRestore = hasSavedProductions && !dnaReady && Boolean(onRestoreFromSavedEvidence);

    const title = lineageCheckPending
      ? "Checking your saved revival intelligence…"
      : restorePending
        ? (restorePhase === "RECOVERY" ? "Restoring Recovery Intelligence…" : "Restoring Content DNA…")
        : canRestore
          ? "Your existing productions can restore the missing intelligence."
          : !dnaReady
            ? "Complete Content DNA to unlock your 30-day plan."
            : recoveryRunning
              ? "Recovery Intelligence is building your comeback options."
              : recoveryFailed
                ? "Recovery Intelligence needs another pass."
                : "One step left before your revival plan is ready.";

    const description = lineageCheckPending
      ? "ReviveAI is checking this signed-in workspace for reusable Content DNA, Recovery Intelligence, and prior production lineage before asking you to rebuild anything."
      : restorePending
        ? "ReviveAI is rebuilding only the missing intelligence from your already-saved channel evidence. Existing productions remain untouched and YouTube is not analyzed again."
        : canRestore
          ? "The original reusable intelligence jobs are no longer available, but your saved channel report and production history are intact. Restore the missing Content DNA and Recovery Intelligence from that saved evidence—without re-fetching the YouTube archive or changing existing productions."
          : !dnaReady
            ? "ReviveAI first learns the channel's recurring themes, characters, formats, and creative identity. Then it can turn that evidence into a repeatable publishing program."
            : recoveryRunning
              ? "ReviveAI is connecting your Content DNA to evidence-backed recovery directions. You can keep this page open or return later; the result is saved to your workspace."
              : recoveryFailed
                ? "Your completed channel evidence is safe. Reopen Intelligence and retry Recovery Intelligence; you do not need to analyze the channel again."
                : "Content DNA is ready. Build Recovery Intelligence next so ReviveAI can rank repeatable directions and turn them into a four-week publishing slate.";

    const buttonLabel = lineageCheckPending
      ? "Checking saved intelligence…"
      : restorePending
        ? (restorePhase === "RECOVERY" ? "Restoring recovery…" : "Restoring Content DNA…")
        : canRestore
          ? "Restore revival intelligence"
          : !dnaReady
            ? "Build Content DNA"
            : recoveryRunning
              ? "View Recovery progress"
              : recoveryFailed
                ? "Retry Recovery Intelligence"
                : "Complete Recovery Intelligence";

    const handleAction = () => {
      if (lineageCheckPending || restorePending) return;
      if (canRestore && onRestoreFromSavedEvidence) {
        onRestoreFromSavedEvidence();
        return;
      }
      onOpenIntelligence(dnaReady ? "recovery" : "dna");
    };

    return (
      <section className="revival-program-card revival-program-prereq glass-card" aria-labelledby="revival-program-title">
        <div className="revival-program-gate-copy">
          <span className="revival-program-icon"><Compass size={20} aria-hidden="true" /></span>
          <div className="revival-prereq-copy">
            <span className="eyebrow">Channel revival · 30-day program</span>
            <h2 id="revival-program-title">{channelTitle} — 30-Day Revival</h2>
            <h3>{title}</h3>
            <p>{description}</p>
            <div className="revival-prereq-steps" aria-label="Revival program prerequisites">
              <PrerequisiteStep complete label="Channel evidence" />
              <PrerequisiteStep complete={dnaReady} active={!dnaReady} label="Content DNA" />
              <PrerequisiteStep complete={recoveryReady} active={dnaReady && !recoveryReady} label="Recovery Intelligence" />
            </div>
            {error && <div className="revival-program-error" role="alert">{error}</div>}
          </div>
        </div>
        <button
          className="primary-button"
          type="button"
          disabled={lineageCheckPending || restorePending}
          onClick={handleAction}
        >
          {(lineageCheckPending || restorePending || recoveryRunning) ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}
          {buttonLabel}
        </button>
      </section>
    );
  }

  if (!program) {
    return (
      <section className="revival-program-card glass-card" aria-labelledby="revival-program-title">
        <div className="revival-program-gate-copy">
          <span className="revival-program-icon"><CheckCircle2 size={20} aria-hidden="true" /></span>
          <div>
            <span className="eyebrow">Ready to plan · channel intelligence complete</span>
            <h2 id="revival-program-title">{channelTitle} — {recovery.strategy.mode === "SUSTAIN" ? "30-Day Content Plan" : recovery.strategy.mode === "RECOVER" ? "30-Day Recovery" : recovery.strategy.mode === "DISCOVER" ? "30-Day Discovery" : "30-Day Revival"}</h2>
            <p>{recovery.strategy.guidance}</p>
            <div className="revival-program-benefits">
              <span><Gauge size={15} /> Mode: {recovery.strategy.label}</span>
              <span><Layers3 size={15} /> Historical weight: {Math.round(recovery.strategy.historical_evidence_weight * 100)}%</span>
              <span><Target size={15} /> Fresh evidence priority: {Math.round(recovery.strategy.fresh_evidence_priority * 100)}%</span>
            </div>
            <div className="revival-program-benefits">
              <span><Layers3 size={15} /> Repeatable content pillars</span>
              <span><CalendarDays size={15} /> Adaptive publishing slate</span>
              <span><Target size={15} /> Evidence-fit priorities</span>
            </div>
            {error && <div className="revival-program-error" role="alert">{error}</div>}
          </div>
        </div>
        <button className="primary-button" type="button" disabled={pending} onClick={onCreate}>
          {pending ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}
          {pending ? "Building 30-day plan…" : `Create ${recovery.strategy.label.toLowerCase()} plan`}
        </button>
      </section>
    );
  }

  const productionIds = new Set(history.map((entry) => entry.source_snapshot.recommendation.recommendation_id));
  const firstUnstarted = program.ideas.find((idea) => !productionIds.has(idea.recommendation_id));
  const completedCount = program.ideas.filter((idea) => productionIds.has(idea.recommendation_id)).length;
  const autopilotCompletedCount = autopilot?.completedCount ?? 0;
  const autopilotCompletedIds = new Set(autopilot?.completedRecommendationIds ?? []);
  const autopilotBlockedIds = new Set((autopilot?.blockedProductions ?? []).map((item) => item.recommendationId));
  const autopilotParkedCount = autopilot?.blockedProductions.length ?? 0;
  const autopilotBlockedCount = (autopilot?.blockedProductions ?? []).filter((item) => item.blocksAutonomy === true || item.resolutionStatus === "BLOCKING").length;
  const autopilotArchivedCount = Math.max(0, autopilotParkedCount - autopilotBlockedCount);
  const hasAutopilotWork = program.ideas.length > 0 && autopilotCompletedCount < program.ideas.length;
  const nextAiCandidate = program.ideas.find((idea) =>
    !autopilotCompletedIds.has(idea.recommendation_id)
    && !autopilotBlockedIds.has(idea.recommendation_id)
    && idea.recommendation_id !== autopilot?.currentRecommendationId
  );
  const weekGroups = [1, 2, 3, 4].map((week) => ({
    week,
    slots: program.weekly_slate.filter((slot) => slot.week === week),
  })).filter((group) => group.slots.length > 0);
  const activeOption = CADENCE_OPTIONS.find((item) => item.value === program.cadence_intensity) ?? CADENCE_OPTIONS[0];
  const customDirection = trendDirections?.directions.find((direction) =>
    String(direction.lane_label || "").toUpperCase().includes("CUSTOM")
  ) ?? null;

  const standardDirections = trendDirections?.directions.filter(
    (direction) => direction.direction_id !== customDirection?.direction_id
  ) ?? [];

  const submitCustomDirection = () => {
    const idea = customIdea.trim();
    if (!onRefineCustomDirection || customDirectionPending || idea.length < 8) return;
    setCustomSubmissionStarted(true);
    onRefineCustomDirection(idea);
  };

  useEffect(() => {
    if (customDirectionPending) {
      customPendingSeenRef.current = true;
      return;
    }

    if (!customPendingSeenRef.current) return;
    customPendingSeenRef.current = false;

    if (customDirection) {
      setCustomSubmissionStarted(false);
      window.requestAnimationFrame(() => {
        customResultRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    }
  }, [customDirectionPending, customDirection?.direction_id]);

  const scheduledCount = program.weekly_slate.length;

  return (
    <section className="revival-program glass-card" id="revival-program">
      <section className="direction-studio" id="direction-studio" aria-labelledby="trend-direction-title">
        <div className="direction-studio-hero">
          <div>
            <span className="eyebrow">Direction Studio</span>
            <h2 id="trend-direction-title">Choose where to take {channelTitle} next</h2>
            <p>ReviveAI already did the analysis. Focus on the decision: choose a direction below, or bring your own idea and let AI strengthen it.</p>
          </div>
          <div className="direction-studio-ready" aria-label="Intelligence ready">
            <CheckCircle2 size={18} />
            <span><strong>Intelligence ready</strong><small>History + Content DNA + current signals</small></span>
          </div>
        </div>

        {!trendPending && (
          <div className="direction-studio-toolbar">
            <div>
              <strong>{trendDirections ? `${trendDirections.directions.length} directions ready` : "Find fresh opportunities"}</strong>
              <span>{trendDirections ? "Compare the ideas and choose what fits the channel next." : "Scan current public YouTube signals and match them against this channel's Content DNA."}</span>
            </div>
            {onDiscoverTrends && (
              <button type="button" className="secondary-button" onClick={onDiscoverTrends}>
                <Sparkles size={16}/> {trendDirections ? "Refresh directions" : "Find current opportunities"}
              </button>
            )}
          </div>
        )}

        {trendError && !customSubmissionStarted && <div className="revival-program-error" role="alert">{trendError}</div>}

        {trendPending && !trendDirections && (
          <div className="direction-studio-loading direction-studio-loading--active" role="status" aria-live="polite" aria-busy="true">
            <div className="direction-loading-spinner" aria-hidden="true"><LoaderCircle size={28}/></div>
            <div className="direction-loading-copy">
              <strong>Finding the best directions for {channelTitle}</strong>
              <span>Reviewing fresh signals and matching them against your Content DNA and historical performance.</span>
              <small>Recommendations will appear here as soon as the comparison is ready.</small>
            </div>
            <div className="direction-loading-pulse" aria-hidden="true"><span/><span/><span/></div>
          </div>
        )}

        {trendDirections && (
          <>
            <div className="direction-choice-grid">
              {standardDirections.map((direction, index) => {
                const opportunityLabel = direction.opportunity_score >= 80 ? "High opportunity" : direction.opportunity_score >= 65 ? "Promising" : "Worth testing";
                const fitLabel = direction.scores.channel_fit >= 20 ? "High fit" : direction.scores.channel_fit >= 15 ? "Good fit" : "Exploratory fit";
                const momentumLabel = direction.scores.trend_momentum >= 24 ? "Strong signal" : direction.scores.trend_momentum >= 18 ? "Rising signal" : "Early signal";
                return (
                  <article className={`direction-choice-card ${index === 0 ? "is-first" : ""}`} key={direction.direction_id}>
                    <div className="direction-choice-topline">
                      <span className="direction-choice-lane">{direction.lane_label}</span>
                      <span className="direction-choice-opportunity">{opportunityLabel}</span>
                    </div>
                    <h3>{direction.title}</h3>
                    <p className="direction-choice-concept">{direction.concept}</p>
                    <div className="direction-choice-signals" aria-label="Direction signals">
                      <span><Sparkles size={13}/> {momentumLabel}</span>
                      <span><CheckCircle2 size={13}/> {fitLabel}</span>
                      <span><Gauge size={13}/> {direction.opportunity_score}/100 opportunity</span>
                    </div>
                    <div className="direction-choice-why"><strong>Why now</strong><span>{direction.why_now}</span></div>
                    <details className="direction-evidence-details">
                      <summary>Why AI recommends this <ChevronRight size={14}/></summary>
                      <div className="direction-evidence-body">
                        <div className="direction-score-breakdown">
                          <span>Trend momentum <b>{direction.scores.trend_momentum}/30</b></span>
                          <span>Channel fit <b>{direction.scores.channel_fit}/25</b></span>
                          <span>Format momentum <b>{direction.scores.format_momentum}/20</b></span>
                          <span>Differentiation <b>{direction.scores.differentiation}/15</b></span>
                          <span>Feasibility <b>{direction.scores.feasibility}/10</b></span>
                        </div>
                        {direction.evidence.length > 0 && (
                          <div className="direction-evidence-list">
                            <strong>Fresh signals used</strong>
                            {direction.evidence.slice(0, 4).map((e) => (
                              <div className="trend-evidence" key={e.url}>
                                <span>{e.title}</span>
                                <small>{Math.round(e.views_per_day).toLocaleString()} views/day · {e.channel_title}</small>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </details>
                    {onSelectTrendDirection && (
                      <button type="button" className="primary-button direction-choice-action" onClick={() => onSelectTrendDirection(direction)}>
                        Choose this direction <ArrowRight size={15}/>
                      </button>
                    )}
                  </article>
                );
              })}
            </div>
            <small className="direction-studio-methodology">Opportunity scores help compare evidence; they are not a probability of virality. {trendDirections.methodology_notice}</small>
          </>
        )}

        <div className="direction-custom-studio">
          <div className="direction-custom-copy">
            <span className="direction-custom-icon"><Sparkles size={18}/></span>
            <div>
              <span className="eyebrow">Your idea + AI strategist</span>
              <h3>Have another direction in mind?</h3>
              <p>Describe it naturally. ReviveAI will preserve your intent, challenge weak assumptions, and suggest a stronger execution.</p>
            </div>
          </div>

          <label className="direction-custom-field">
            <span className="sr-only">Describe your direction</span>
            <textarea
              value={customIdea}
              onChange={(event) => setCustomIdea(event.target.value)}
              onKeyDown={(event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                  event.preventDefault();
                  submitCustomDirection();
                }
              }}
              placeholder="Example: A dancing corgi with two human backup dancers, using the linked reference only as inspiration."
              rows={3}
              disabled={customDirectionPending}
              aria-describedby="direction-custom-help"
            />
          </label>

          <div className="direction-custom-actions">
            <small id="direction-custom-help">
              AI develops the idea first. Nothing is added to production until you choose the resulting direction.
            </small>
            <button
              type="button"
              className="primary-button"
              disabled={customDirectionPending || customIdea.trim().length < 8 || !onRefineCustomDirection}
              onClick={submitCustomDirection}
            >
              {customDirectionPending ? <LoaderCircle className="spin" size={16}/> : <Sparkles size={16}/>}
              {customDirectionPending ? "Developing…" : "Develop with AI"}
            </button>
          </div>

          {(customDirectionPending || (customSubmissionStarted && !trendError && !customDirection)) && (
            <div className="direction-custom-feedback is-loading" role="status" aria-live="polite">
              <LoaderCircle className="spin" size={18}/>
              <div>
                <strong>Developing your direction</strong>
                <span>ReviveAI is combining your idea with the channel's Content DNA and current evidence.</span>
              </div>
            </div>
          )}

          {customSubmissionStarted && trendError && (
            <div className="direction-custom-feedback is-error" role="alert">
              <AlertTriangle size={18}/>
              <div>
                <strong>ReviveAI couldn't develop this direction</strong>
                <span>{trendError}</span>
              </div>
            </div>
          )}

          {customDirection && !customDirectionPending && (
            <div className="direction-custom-result" ref={customResultRef} aria-live="polite">
              <div className="direction-custom-result-head">
                <div>
                  <span className="eyebrow">AI-developed direction</span>
                  <h3>{customDirection.title}</h3>
                </div>
                <span className="direction-choice-opportunity">
                  {customDirection.opportunity_score >= 80 ? "High opportunity" : customDirection.opportunity_score >= 65 ? "Promising" : "Worth testing"}
                </span>
              </div>

              <p>{customDirection.concept}</p>

              <div className="direction-choice-signals" aria-label="Custom direction signals">
                <span><Sparkles size={13}/> {customDirection.scores.trend_momentum >= 24 ? "Strong signal" : customDirection.scores.trend_momentum >= 18 ? "Rising signal" : "Early signal"}</span>
                <span><CheckCircle2 size={13}/> {customDirection.scores.channel_fit >= 20 ? "High fit" : customDirection.scores.channel_fit >= 15 ? "Good fit" : "Exploratory fit"}</span>
                <span><Gauge size={13}/> {customDirection.opportunity_score}/100 opportunity</span>
              </div>

              <div className="direction-choice-why">
                <strong>AI recommendation</strong>
                <span>{customDirection.why_now}</span>
              </div>

              <div className="direction-custom-result-actions">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => {
                    setCustomIdea("");
                    setCustomSubmissionStarted(false);
                    window.requestAnimationFrame(() => {
                      document.querySelector<HTMLTextAreaElement>(".direction-custom-studio textarea")?.focus();
                    });
                  }}
                >
                  Try another idea
                </button>

                {onSelectTrendDirection && (
                  <button
                    type="button"
                    className="primary-button"
                    onClick={() => onSelectTrendDirection(customDirection)}
                  >
                    Choose this direction <ArrowRight size={15}/>
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </section>

      <details className="direction-intelligence-details">
        <summary>
          <span><Compass size={17}/><span><strong>View strategy, publishing plan & supporting intelligence</strong><small>Optional details · historical evidence, cadence, backlog and Autopilot controls</small></span></span>
          <ChevronRight size={16}/>
        </summary>
        <div className="direction-intelligence-body">
      <AdaptiveLearningPanel program={program} recovery={recovery} />
      <div className="revival-program-head">
        <div>
          <span className="eyebrow">Channel operating plan · {program.operating_mode}</span>
          <h2>{channelTitle} — {program.program_label}</h2>
          <p>{program.program_goal}</p>
          <small>{program.target_posts} evidence-backed ideas · {scheduledCount} currently scheduled · creator-controlled publishing.</small>
        </div>
        <div className="revival-program-progress">
          <strong>{completedCount}/{program.target_posts}</strong>
          <span>production records</span>
        </div>
      </div>

      <section className={`revival-autopilot-card status-${(autopilot?.status || "IDLE").toLowerCase().replace(/_/g, "-")}`} aria-label="AI Autopilot controls">
        <div className="revival-autopilot-main">
          <span className="revival-autopilot-icon"><Bot size={21} aria-hidden="true" /></span>
          <div className="revival-autopilot-copy">
            <span className="eyebrow">AI Autopilot · Delegated production</span>
            <h3>{autopilot?.status === "RUNNING"
              ? (autopilotBlockedCount > 0
                  ? `Autopilot is continuing; ${autopilotBlockedCount} blocking production${autopilotBlockedCount === 1 ? "" : "s"} need attention.`
                  : autopilotArchivedCount > 0
                    ? `Autopilot is healthy; ${autopilotArchivedCount} historical production exception${autopilotArchivedCount === 1 ? " is" : "s are"} archived.`
                    : "Your AI assistant is creating and reviewing the slate.")
              : autopilot?.status === "WAITING_FOR_FINAL_APPROVAL"
                ? "Your finished video is waiting for final approval."
              : autopilot?.status === "WAITING_FOR_LEARNING"
                ? "ReviveAI is learning from the latest release before choosing the next idea."
              : autopilot?.status === "PAUSED"
                ? "Autopilot is paused."
                : autopilot?.status === "NEEDS_ATTENTION"
                  ? (autopilot?.attentionStage === "FINAL_VIDEO" ? "Your finished video is ready for final approval." : "Autopilot paused on a production exception.")
                  : autopilot?.status === "COMPLETED"
                    ? "Autopilot finished the available slate."
                    : "Produce the campaign without clicking through every normal step."}</h3>
            <p>{autopilot?.message || "Autopilot delegates the intermediate work to AI: plan checks, visual identity, keyframes, video motion, audio mix, technical QC, and publishing text. You review only the finished picture + sound."}</p>
            {autopilot?.currentTitle && <div className="revival-autopilot-current"><span>Current production</span><strong>{autopilot.currentTitle}</strong></div>}
          </div>
        </div>
        <div className="revival-autopilot-side">
          <div className="revival-autopilot-metrics">
            <div><strong>{program.target_posts}</strong><span>planned</span></div>
            <div><strong>{autopilotCompletedCount}</strong><span>AI finished</span></div>
            <div><strong>{autopilotBlockedCount}</strong><span>needs attention</span></div>
            <div><strong>{Math.max(0, program.ideas.length - autopilotCompletedCount - autopilotParkedCount)}</strong><span>available</span></div>
          </div>
          <div className="revival-autopilot-actions">
            {(!autopilot || ["IDLE", "COMPLETED"].includes(autopilot.status)) && onStartAutopilot && (
              <button type="button" className="primary-button revival-autopilot-start" onClick={onStartAutopilot} disabled={pending || !hasAutopilotWork}>
                <Play size={16} /> {autopilot?.status === "COMPLETED" ? "Run remaining ideas" : "Start AI Autopilot"}
              </button>
            )}
            {["RUNNING", "WAITING_FOR_LEARNING"].includes(autopilot?.status || "") && onPauseAutopilot && (
              <button type="button" className="secondary-button" onClick={onPauseAutopilot}><Pause size={15} /> Pause after current action</button>
            )}
            {["PAUSED", "NEEDS_ATTENTION", "WAITING_FOR_FINAL_APPROVAL"].includes(autopilot?.status || "") && onResumeAutopilot && (
              <button type="button" className="primary-button revival-autopilot-start" onClick={onResumeAutopilot}><Play size={15} /> {autopilot?.status === "WAITING_FOR_FINAL_APPROVAL" ? "Review final video" : autopilot?.status === "NEEDS_ATTENTION" ? (autopilot.attentionStage === "FINAL_VIDEO" ? "Review final video" : "Retry blocked production") : "Resume Autopilot"}</button>
            )}
          </div>
          {autopilotParkedCount > 0 && (
            <div className="revival-autopilot-exceptions" role="status">
              <AlertTriangle size={15} />
              <div>
                <strong>{autopilotBlockedCount > 0
                  ? `${autopilotBlockedCount} blocking production issue${autopilotBlockedCount === 1 ? "" : "s"}`
                  : `${autopilotArchivedCount} historical production exception${autopilotArchivedCount === 1 ? "" : "s"} archived`}</strong>
                <span>{autopilotBlockedCount > 0
                  ? "A current infrastructure or safety issue still requires attention."
                  : "Completed work and failure history are preserved, but these old exceptions no longer block autonomous production."}</span>
              </div>
            </div>
          )}
          <small className="revival-autopilot-guardrail">AI reviewer gates are independent from generation: failed layers are regenerated automatically when possible. Public publishing is never triggered here; the only normal human approval is the finished video.</small>
        </div>
      </section>

      <section className="revival-cadence-card" aria-label="Strategy evidence freshness">
        <div className="revival-cadence-summary">
          <span className="revival-cadence-icon"><Compass size={18} /></span>
          <div>
            <span className="eyebrow">Strategy mode · {recovery.strategy.label}</span>
            <h3>{recovery.strategy.historical_confidence_label}</h3>
            <p>{recovery.strategy.reason}</p>
          </div>
          <div className="revival-cadence-recommendation">
            <small>Historical / fresh</small>
            <strong>{Math.round(program.historical_evidence_weight * 100)}% / {Math.round(program.fresh_evidence_priority * 100)}%</strong>
          </div>
        </div>
        <div className="revival-cadence-warning" role="note">
          <AlertTriangle size={16} />
          <div><strong>Freshness guardrail</strong><span>{program.evidence_freshness_note}</span></div>
        </div>
      </section>

      <section className="revival-cadence-card" aria-labelledby="revival-cadence-title">
        <div className="revival-cadence-summary">
          <span className="revival-cadence-icon"><Gauge size={18} /></span>
          <div>
            <span className="eyebrow">Publishing cadence</span>
            <h3 id="revival-cadence-title">{activeOption.label} · {program.cadence_per_week} post{program.cadence_per_week === 1 ? "" : "s"} / week</h3>
            <p>{program.schedule_rationale}</p>
          </div>
          <div className="revival-cadence-recommendation">
            <small>ReviveAI recommendation</small>
            <strong>{program.recommended_cadence_per_week}/week</strong>
          </div>
        </div>

        <div className="revival-cadence-options" role="group" aria-label="Publishing intensity">
          {CADENCE_OPTIONS.map((option) => (
            <button
              type="button"
              key={option.value}
              className={program.cadence_intensity === option.value ? "is-active" : ""}
              disabled={pending}
              onClick={() => onUpdateCadence(option.value)}
              aria-pressed={program.cadence_intensity === option.value}
            >
              <span>{option.value === "DAILY_SPRINT" ? <Zap size={14} /> : <CalendarClock size={14} />}{option.label}</span>
              <strong>{option.posts}</strong>
              <small>{option.detail}</small>
            </button>
          ))}
        </div>

        <div className="revival-cadence-evidence">
          <div>
            <span className="eyebrow">Suggested publishing days</span>
            <strong>{program.suggested_days.join(" · ") || "Flexible"}</strong>
            <small>{program.schedule_basis === "historical_activity_with_spacing" ? "Based on historically active publishing weekdays plus spacing between tests—not a performance claim about those weekdays." : "Evenly spaced because weekday history is too limited to support a stronger claim."}</small>
          </div>
          <div>
            <span className="eyebrow">Backlog capacity</span>
            <strong>{program.backlog_capacity_label}</strong>
            <small>{program.backlog_weeks_supported.toFixed(1)} weeks of current ideas at this pace.</small>
          </div>
        </div>

        {program.backlog_capacity_warning && (
          <div className="revival-cadence-warning" role="status">
            <AlertTriangle size={16} />
            <div><strong>Cadence capacity check</strong><span>{program.backlog_capacity_warning}</span></div>
          </div>
        )}

        {program.weekday_activity.some((item) => item.upload_count > 0) && (
          <details className="revival-weekday-details">
            <summary>Why these days? <ChevronRight size={14} /></summary>
            <div className="revival-weekday-grid">
              {program.weekday_activity.map((item) => (
                <div key={item.day} className={program.suggested_days.includes(item.day) ? "is-suggested" : ""}>
                  <strong>{item.day}</strong>
                  <span>{item.upload_count} historical upload{item.upload_count === 1 ? "" : "s"}</span>
                  <small>{item.share_percent}% of dated uploads</small>
                </div>
              ))}
            </div>
          </details>
        )}
        {error && <div className="revival-program-error" role="alert">{error}</div>}
      </section>

      <div className="revival-pillar-row" aria-label="Content pillars">
        {program.pillars.map((pillar) => (
          <article key={pillar.pillar_id}>
            <span><Layers3 size={15} /> Content pillar</span>
            <strong>{pillar.name}</strong>
            <small>{pillar.source_ideas.slice(0, 2).join(" · ") || "Evidence-backed repeatable territory"}</small>
          </article>
        ))}
      </div>

      <div className="revival-program-body">
        <div className="revival-weekly-plan">
          <div className="revival-section-title">
            <div><span className="eyebrow">Publishing slate</span><h3>Four weeks of consistent testing</h3></div>
            <CalendarDays size={19} />
          </div>
          <div className="revival-week-grid">
            {weekGroups.map(({ week, slots }) => (
              <article className="revival-week" key={week}>
                <header><span>Week {week}</span><small>{slots.length} post{slots.length === 1 ? "" : "s"}</small></header>
                {slots.map((slot) => {
                  const idea = program.ideas.find((item) => item.idea_id === slot.idea_id)!;
                  const started = productionIds.has(idea.recommendation_id);
                  return (
                    <div className={`revival-slot ${started ? "is-started" : ""}`} key={slot.idea_id}>
                      <span className="revival-slot-day">{slot.cadence_label}</span>
                      <div><strong>{idea.title}</strong><small>{laneLabel(idea.lane)} · {idea.evidence_fit_label}</small></div>
                      {started ? <Check size={16} aria-label="Production started" /> : null}
                    </div>
                  );
                })}
              </article>
            ))}
          </div>
        </div>

        <aside className="revival-next-card">
          <div className="revival-next-icon"><Flame size={21} /></div>
          <span className="eyebrow">Next recommended move</span>
          {firstUnstarted ? (
            <>
              <h3>{firstUnstarted.title}</h3>
              <p>{firstUnstarted.why_now}</p>
              <div className="revival-next-meta"><span>{laneLabel(firstUnstarted.lane)}</span><span>{firstUnstarted.evidence_fit_score}% evidence fit</span></div>
              <div className="revival-next-actions">
                {onRunIdeaWithAutopilot && (
                  <button className="primary-button" type="button" onClick={() => onRunIdeaWithAutopilot(firstUnstarted.recommendation_id)}>
                    <Sparkles size={16} /> Produce with AI
                  </button>
                )}
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => {
                    const recommendation = recovery.recommendations.find((item) => item.recommendation_id === firstUnstarted.recommendation_id);
                    if (recommendation) onCreateProduction(recommendation);
                  }}
                >
                  Start manually <ArrowRight size={16} />
                </button>
              </div>
            </>
          ) : nextAiCandidate ? (
            <>
              <h3>{nextAiCandidate.title}</h3>
              <p>This idea already has a saved production record. AI Autopilot can adopt it and continue from the last verified stage without creating a duplicate.</p>
              <div className="revival-next-meta"><span>{laneLabel(nextAiCandidate.lane)}</span><span>{nextAiCandidate.evidence_fit_score}% evidence fit</span></div>
              {onRunIdeaWithAutopilot && (
                <button className="primary-button" type="button" onClick={() => onRunIdeaWithAutopilot(nextAiCandidate.recommendation_id)}>
                  <Sparkles size={16} /> Continue this production with AI
                </button>
              )}
            </>
          ) : (
            <>
              <h3>{autopilotBlockedCount > 0 ? "A blocking exception remains." : autopilotArchivedCount > 0 ? "Historical exceptions are archived." : "All planned ideas have been handled."}</h3>
              <p>{autopilotBlockedCount > 0
                ? "Resolve the current blocking issue before Autopilot can safely continue."
                : autopilotArchivedCount > 0
                  ? "Those failed attempts remain in history for audit, but they do not prevent future autonomous production."
                  : "Autopilot has finished the available slate. Keep publishing consistently, then refresh channel evidence so ReviveAI can learn which pillars deserve more investment."}</p>
            </>
          )}
          <small className="revival-program-guardrail">Evidence fit guides testing; it does not predict future performance.</small>
        </aside>
      </div>

      <details className="revival-backlog-details">
        <summary>View full idea backlog <ChevronRight size={15} /></summary>
        <div className="revival-backlog-list">
          {program.ideas.map((idea) => {
            const started = productionIds.has(idea.recommendation_id);
            return (
              <article key={idea.idea_id}>
                <span className={`revival-lane lane-${idea.lane.toLowerCase()}`}>{laneLabel(idea.lane)}</span>
                <div><strong>{idea.title}</strong><small>{idea.concept}</small></div>
                <span className="revival-fit"><b>{idea.evidence_fit_score}%</b> evidence fit</span>
                {autopilotCompletedIds.has(idea.recommendation_id) ? (
                  <span className="revival-started"><Check size={14} /> AI finished</span>
                ) : autopilotBlockedIds.has(idea.recommendation_id) ? (
                  <div className="revival-backlog-actions">
                    <span className="revival-started is-attention"><AlertTriangle size={14} /> Needs attention</span>
                    {onRunIdeaWithAutopilot && (
                      <button type="button" onClick={() => onRunIdeaWithAutopilot(idea.recommendation_id)}><Sparkles size={14} /> Retry with AI</button>
                    )}
                  </div>
                ) : idea.recommendation_id === autopilot?.currentRecommendationId ? (
                  <span className="revival-started is-ai"><Sparkles size={14} /> AI working</span>
                ) : (
                  <div className="revival-backlog-actions">
                    {onRunIdeaWithAutopilot && (
                      <button type="button" onClick={() => onRunIdeaWithAutopilot(idea.recommendation_id)}><Sparkles size={14} /> Produce with AI</button>
                    )}
                    {!started && (
                      <button type="button" onClick={() => {
                        const recommendation = recovery.recommendations.find((item) => item.recommendation_id === idea.recommendation_id);
                        if (recommendation) onCreateProduction(recommendation);
                      }}>Manual <ArrowRight size={14} /></button>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      </details>
        </div>
      </details>
    </section>
  );
}
