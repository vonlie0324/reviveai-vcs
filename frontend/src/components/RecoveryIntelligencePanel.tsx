import {
  AlertTriangle,
  ArchiveRestore,
  ArrowUpRight,
  BadgeCheck,
  BrainCircuit,
  ChevronRight,
  CircleCheckBig,
  Compass,
  Fingerprint,
  Gauge,
  History,
  Lightbulb,
  RefreshCw,
  SearchCheck,
  ShieldCheck,
  Sparkles,
  Target,
  WandSparkles,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type {
  AnalysisResult,
  ArchiveMatch,
  ContentDnaResult,
  ContentGapOpportunity,
  NextContentRecommendation,
  RecoveryJob,
  RecoveryResult,
  RecoverySignal,
  ProductionBriefHistoryEntry,
  RevivalOpportunity,
} from "../types";

interface RecoveryIntelligencePanelProps {
  analysis: AnalysisResult;
  dna: ContentDnaResult;
  job: RecoveryJob | null;
  error: string | null;
  onBuild: () => void;
  onCreateBrief: (item: NextContentRecommendation) => void;
  creatingRecommendationId?: string | null;
  productionHistory: ProductionBriefHistoryEntry[];
  productionHistoryReady: boolean;
}

type RecoveryTab = "plan" | "gaps" | "revivals" | "signals";
type DetailSelection =
  | { kind: "recommendation"; item: NextContentRecommendation }
  | { kind: "gap"; item: ContentGapOpportunity }
  | { kind: "revival"; item: RevivalOpportunity };

const TERMINAL = new Set(["COMPLETED", "FAILED"]);

export function RecoveryIntelligencePanel({ analysis, dna, job, error, onBuild, onCreateBrief, creatingRecommendationId = null, productionHistory, productionHistoryReady }: RecoveryIntelligencePanelProps) {
  if (!job) return <RecoveryGate analysis={analysis} dna={dna} error={error} onBuild={onBuild} />;
  if (job.stage === "FAILED") return <RecoveryFailure job={job} onRetry={onBuild} />;
  if (!TERMINAL.has(job.stage)) return <RecoveryProgress job={job} />;
  if (job.stage === "COMPLETED" && job.result) return <RecoveryDashboard result={job.result} recoveryJobId={job.job_id} productionHistory={productionHistory} productionHistoryReady={productionHistoryReady} onCreateBrief={onCreateBrief} creatingRecommendationId={creatingRecommendationId} />;
  return null;
}

function RecoveryGate({ analysis, dna, error, onBuild }: { analysis: AnalysisResult; dna: ContentDnaResult; error: string | null; onBuild: () => void }) {
  const strongest = useMemo(() => strongestSignals(dna), [dna]);
  return (
    <section className="recovery-section" id="recovery-intelligence">
      <article className="recovery-gate glass-card">
        <div className="recovery-gate-main">
          <div className="layer-badge recovery"><Compass size={15} /> Recovery strategy layer</div>
          <span className="eyebrow">Milestone 1D.4 · Recovery Intelligence</span>
          <h2>Turn channel history into an evidence-backed comeback plan.</h2>
          <p>
            ReviveAI will look for adjacent content gaps, strong archive concepts worth revisiting, and specific next-content directions—without treating historical correlation as a guarantee.
          </p>
          <div className="recovery-method-row">
            <span><Fingerprint size={15} /> Content DNA ready</span>
            <span><Gauge size={15} /> M1B evidence attached</span>
            <span><SearchCheck size={15} /> Archive novelty checked</span>
          </div>
          {error && (
            <div className="dna-inline-error" role="alert">
              <AlertTriangle size={18} />
              <div><strong>Recovery Intelligence is not ready to start</strong><span>{error}</span></div>
            </div>
          )}
          <button type="button" className="primary-button recovery-build-button" onClick={onBuild}>
            <WandSparkles size={18} /> Build Recovery Intelligence <ChevronRight size={17} />
          </button>
        </div>
        <aside className="recovery-gate-proof">
          <span className="eyebrow">Evidence entering M1D</span>
          <h3>{analysis.channel.title}</h3>
          <p>{dna.identity.summary}</p>
          <div className="recovery-proof-grid">
            <ProofCell label="Archive" value={`${analysis.summary.retrieved_videos} videos`} />
            <ProofCell label="Themes" value={`${dna.themes.length}`} />
            <ProofCell label="Characters" value={`${dna.characters.length}`} />
            <ProofCell label="Patterns" value={`${dna.story_patterns.length + dna.visual_patterns.length}`} />
          </div>
          <div className="recovery-preview-signals">
            <span>Signals already visible</span>
            {strongest.slice(0, 3).map((item) => (
              <div key={`${item.kind}-${item.name}`}><strong>{item.name}</strong><em>{formatRatio(item.ratio)}</em></div>
            ))}
          </div>
        </aside>
      </article>
    </section>
  );
}

function RecoveryProgress({ job }: { job: RecoveryJob }) {
  const steps = [
    ["PREPARING_SIGNALS", "Prepare signals"],
    ["DISCOVERING_GAPS", "Discover gaps"],
    ["FINDING_REVIVALS", "Find revivals"],
    ["BUILDING_RECOMMENDATIONS", "Build next moves"],
    ["VALIDATING_EVIDENCE", "Validate evidence"],
  ] as const;
  const stageIndex = Math.max(0, steps.findIndex(([key]) => key === job.stage));
  const percent = job.stage === "VALIDATING_EVIDENCE" ? 95 : Math.min(92, Math.round(((job.progress_current + 0.35) / Math.max(1, job.progress_total)) * 100));
  const calls = Number(job.detail.gemini_calls ?? 0);
  const gaps = Number(job.detail.validated_gaps ?? job.detail.content_gaps ?? 0);
  const revivals = Number(job.detail.validated_revivals ?? job.detail.revival_opportunities ?? 0);

  return (
    <section className="recovery-section" id="recovery-intelligence" aria-live="polite">
      <article className="recovery-progress-card glass-card">
        <div className="recovery-progress-head">
          <div className="recovery-progress-icon"><BrainCircuit size={32} /></div>
          <div>
            <div className="layer-badge recovery"><Sparkles size={15} /> Evidence-guided Gemini strategy</div>
            <span className="eyebrow">Building Recovery Intelligence</span>
            <h2>{job.message}</h2>
            <p>ReviveAI is generating creative directions in small passes, then checking them against the archive before they reach the dashboard.</p>
          </div>
          <div className="recovery-percent"><strong>{percent}%</strong><span>overall</span></div>
        </div>
        <div className="recovery-progress-bar"><span style={{ width: `${percent}%` }} /></div>
        <div className="recovery-stage-grid">
          {steps.map(([key, label], index) => {
            const state = index < stageIndex ? "done" : index === stageIndex ? "active" : "pending";
            return <div className={`recovery-stage ${state}`} key={key}><span>{state === "done" ? <CircleCheckBig size={15} /> : index + 1}</span><strong>{label}</strong></div>;
          })}
        </div>
        <div className="recovery-live-facts">
          <ProgressFact label="Gemini calls" value={String(calls)} helper="compact structured passes" />
          <ProgressFact label="Content gaps" value={String(gaps || "—")} helper="archive-checked" />
          <ProgressFact label="Revivals" value={String(revivals || "—")} helper="source-linked" />
          <ProgressFact label="Method" value="Evidence first" helper="no performance guarantee" />
        </div>
        <div className="recovery-progress-note"><ShieldCheck size={18} /><span>Historical signals guide exploration. ReviveAI does not tell Gemini that any pattern is guaranteed to perform again.</span></div>
      </article>
    </section>
  );
}

function RecoveryFailure({ job, onRetry }: { job: RecoveryJob; onRetry: () => void }) {
  return (
    <section className="recovery-section" id="recovery-intelligence">
      <article className="recovery-failure glass-card" role="alert">
        <AlertTriangle size={28} />
        <div>
          <span className="eyebrow">Recovery Intelligence paused</span>
          <h2>Gemini could not finish this recovery pass.</h2>
          <p>{job.error || "The recovery strategy could not be completed."}</p>
          <p className="recovery-failure-helper">Your M1B evidence and M1C Content DNA are unchanged. Retrying only rebuilds the M1D strategy layer.</p>
          <button className="secondary-button" onClick={onRetry}><RefreshCw size={16} /> Retry Recovery Intelligence</button>
        </div>
      </article>
    </section>
  );
}

function RecoveryDashboard({ result, recoveryJobId, productionHistory, productionHistoryReady, onCreateBrief, creatingRecommendationId }: { result: RecoveryResult; recoveryJobId: string; productionHistory: ProductionBriefHistoryEntry[]; productionHistoryReady: boolean; onCreateBrief: (item: NextContentRecommendation) => void; creatingRecommendationId: string | null }) {
  const [tab, setTab] = useState<RecoveryTab>("plan");
  const [detail, setDetail] = useState<DetailSelection | null>(null);
  const availableRecommendations = useMemo(() => productionHistoryReady ? result.recommendations.filter((item) => !productionHistory.some((entry) => {
    const old = entry.source_snapshot.recommendation;
    const normalize = (value?: string | null) => (value || "").normalize("NFKD").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    return (entry.recovery_job_id === recoveryJobId && old.recommendation_id === item.recommendation_id)
      || Boolean(item.canonical_idea_id && old.canonical_idea_id === item.canonical_idea_id)
      || Boolean(normalize(item.title) && [old.title, entry.working_title].some((title) => normalize(title) === normalize(item.title)));
  })) : [], [productionHistory, productionHistoryReady, recoveryJobId, result.recommendations]);
  const hero = availableRecommendations[0];

  return (
    <section className="recovery-section recovery-ready" id="recovery-intelligence">
      <div className="recovery-title-row">
        <div>
          <div className="layer-badge recovery"><Compass size={15} /> Recovery Intelligence</div>
          <span className="eyebrow">Milestone 1D.4 complete</span>
          <h2>Turn evidence into the next move.</h2>
          <p>Content gaps, archive revivals, and next-content directions are linked back to the signals that justify them.</p>
        </div>
        <div className="recovery-model-chip"><BrainCircuit size={16} /> {result.model}</div>
      </div>

      {!productionHistoryReady && <p role="alert">Verifying previous production history. New production is unavailable until verification succeeds.</p>}
      {productionHistoryReady && availableRecommendations.length === 0 && <p role="status">All current recommendations were previously started. Build fresh Recovery Intelligence to discover new ideas.</p>}
      {hero && <RecoveryHero item={hero} onInspect={() => setDetail({ kind: "recommendation", item: hero })} onCreate={() => onCreateBrief(hero)} isCreating={creatingRecommendationId === hero.recommendation_id} /> }

      <div className="recovery-summary-strip">
        <SummaryStat icon={<Lightbulb size={18} />} value={result.content_gaps.length} label="content gaps" helper="novelty checked" />
        <SummaryStat icon={<ArchiveRestore size={18} />} value={result.revival_opportunities.length} label="revival opportunities" helper="source linked" />
        <SummaryStat icon={<Target size={18} />} value={availableRecommendations.length} label="available directions" helper="relevance grounded + diversity capped" />
        <SummaryStat icon={<BrainCircuit size={18} />} value={result.gemini_calls} label="Gemini calls" helper="compact strategy passes" />
      </div>

      <nav className="recovery-tabs" aria-label="Recovery Intelligence views">
        {(["plan", "gaps", "revivals", "signals"] as RecoveryTab[]).map((item) => (
          <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>
            <span /> {item === "plan" ? "Recovery plan" : item === "gaps" ? "Content gaps" : item === "revivals" ? "Revive archive" : "Signal stack"}
          </button>
        ))}
      </nav>

      {tab === "plan" && <PlanView recommendations={availableRecommendations} onInspect={(item) => setDetail({ kind: "recommendation", item })} onCreateBrief={onCreateBrief} creatingRecommendationId={creatingRecommendationId} /> }
      {tab === "gaps" && <GapView items={result.content_gaps} onInspect={(item) => setDetail({ kind: "gap", item })} />}
      {tab === "revivals" && <RevivalView items={result.revival_opportunities} onInspect={(item) => setDetail({ kind: "revival", item })} />}
      {tab === "signals" && <SignalView signals={result.top_signals} />}

      <div className="recovery-methodology"><ShieldCheck size={19} /><div><strong>Recovery hypotheses, not performance promises.</strong><span>{result.methodology_notice}</span></div></div>
      {detail && <RecoveryDetailDrawer selection={detail} onClose={() => setDetail(null)} />}
    </section>
  );
}

function RecoveryHero({ item, onInspect, onCreate, isCreating }: { item: NextContentRecommendation; onInspect: () => void; onCreate: () => void; isCreating: boolean }) {
  return (
    <article className="recovery-hero glass-card">
      <div className="recovery-hero-rank">#{item.rank}</div>
      <div className="recovery-hero-copy">
        <span className="eyebrow">Recommended next direction</span>
        <h3>{item.title}</h3>
        <p className="recovery-hero-hook">“{item.hook}”</p>
        <p>{item.concept}</p>
        <div className="recovery-chip-row">
          <span className={`evidence-strength ${strengthClass(item.evidence_strength)}`}><BadgeCheck size={14} /> {strengthLabel(item.evidence_strength)}</span>
          <span className="novelty-chip"><SearchCheck size={14} /> {item.novelty_label}</span>
          <span className="format-chip">{item.format}</span>
          <span className="diversity-chip"><Target size={13} /> Diversity-aware rank</span>
        </div>
        {item.strategy_lanes.length > 0 && <div className="strategy-lane-row">{item.strategy_lanes.slice(0, 3).map((lane) => <span key={lane}>{lane}</span>)}</div>}
        {item.recommended_characters.length > 0 && <div className="recommended-character-line"><strong>Suggested character:</strong> {item.recommended_characters.join(", ")}</div>}
        <div className="recovery-hero-actions"><button className="primary-button recovery-create" onClick={onCreate} disabled={isCreating}><WandSparkles size={16} /> {isCreating ? "Building brief…" : "Create production brief"}</button><button className="secondary-button recovery-inspect" onClick={onInspect}>Inspect why this fits <ChevronRight size={16} /></button></div>
      </div>
      <div className="recovery-hero-evidence">
        <span className="eyebrow">Idea-specific evidence</span>
        {item.evidence_signals.slice(0, 4).map((signal) => <SignalMini key={`${signal.kind}-${signal.name}`} signal={signal} />)}
      </div>
    </article>
  );
}

function PlanView({ recommendations, onInspect, onCreateBrief, creatingRecommendationId }: { recommendations: NextContentRecommendation[]; onInspect: (item: NextContentRecommendation) => void; onCreateBrief: (item: NextContentRecommendation) => void; creatingRecommendationId: string | null }) {
  return (
    <div className="recovery-view">
      <div className="recovery-view-heading"><div><span className="eyebrow">30-second scan</span><h3>What should the creator try next?</h3></div><p>Directions are ranked by idea-specific evidence fit, then diversity-capped—not by predicted views.</p></div>
      <div className="recommendation-grid">
        {recommendations.map((item) => (
          <article className="recommendation-card glass-card" key={item.recommendation_id}>
            <div className="recommendation-top"><span className="recommendation-rank">#{item.rank}</span><span className={`evidence-strength ${strengthClass(item.evidence_strength)}`}>{strengthLabel(item.evidence_strength)}</span></div>
            <h4>{item.title}</h4>
            <p>{item.concept}</p>
            <div className="recommendation-signal-list">{item.evidence_signals.slice(0, 3).map((signal) => <span key={signal.name}>{signal.name} · {formatRatio(signal.evidence.relative_to_channel_median)}</span>)}</div>
            {item.strategy_lanes.length > 0 && <div className="strategy-lane-row compact">{item.strategy_lanes.slice(0, 2).map((lane) => <span key={lane}>{lane}</span>)}</div>}
            <div className="recommendation-footer">
              <div className="novelty-summary">
                <span><SearchCheck size={13} /> {item.novelty_label}</span>
                {item.closest_archive_matches[0] && <em>Closest archive match: {shortSimilarityLabel(item.closest_archive_matches[0].similarity_label)}</em>}
              </div>
              <div className="recommendation-actions"><button className="recommendation-create" onClick={() => onCreateBrief(item)} disabled={creatingRecommendationId === item.recommendation_id}><WandSparkles size={14} /> {creatingRecommendationId === item.recommendation_id ? "Building…" : "Create brief"}</button><button onClick={() => onInspect(item)}>Why this? <ChevronRight size={14} /></button></div>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function GapView({ items, onInspect }: { items: ContentGapOpportunity[]; onInspect: (item: ContentGapOpportunity) => void }) {
  return (
    <div className="recovery-view">
      <div className="recovery-view-heading"><div><span className="eyebrow">Opportunity map</span><h3>What appears underexplored?</h3></div><p>“No close match” means no close semantic match was detected in the analyzed public archive.</p></div>
      <div className="gap-grid">
        {items.map((item, index) => (
          <article className="gap-card glass-card" key={item.gap_id}>
            <div className="gap-card-head"><span>0{index + 1}</span><div className="gap-badges"><em className={gapStrengthClass(item.opportunity_strength)}>{gapStrengthLabel(item.opportunity_strength)}</em><em>{item.novelty_label}</em>{item.selected_for_recovery_plan && <em className="shared-idea-badge">Also in recovery plan</em>}</div></div>
            <h4>{item.title}</h4><p>{item.concept}</p>
            <div className="gap-why"><strong>Why it fits</strong><span>{item.why_it_fits}</span></div>
            <div className="gap-signals">{item.evidence_signals.slice(0, 3).map((signal) => <span key={signal.name}>{signal.name}</span>)}</div>
            {item.closest_archive_matches[0] && <div className="closest-match-inline"><SearchCheck size={13} /> Closest archive match: {shortSimilarityLabel(item.closest_archive_matches[0].similarity_label)}</div>}
            <button onClick={() => onInspect(item)}>Inspect novelty & evidence <ChevronRight size={15} /></button>
          </article>
        ))}
      </div>
    </div>
  );
}

function RevivalView({ items, onInspect }: { items: RevivalOpportunity[]; onInspect: (item: RevivalOpportunity) => void }) {
  return (
    <div className="recovery-view">
      <div className="recovery-view-heading"><div><span className="eyebrow">Archive mining</span><h3>What old concepts are worth revisiting?</h3></div><p>Revival means extending a historically supported archive concept—not reposting it unchanged.</p></div>
      <div className="revival-list">
        {items.map((item) => (
          <article className="revival-card glass-card" key={item.revival_id}>
            <a className="revival-source" href={item.source_video.watch_url} target="_blank" rel="noreferrer">
              {item.source_video.thumbnail_url ? <img src={item.source_video.thumbnail_url} alt="" /> : <History size={24} />}
              <div><span>Source video</span><strong>{item.source_video.title}</strong><em>{formatViews(item.source_video.views)} views · {tierLabel(item.source_video.performance_tier)}{item.source_age_days != null ? ` · ${item.source_age_days} days old` : ""}</em></div><ArrowUpRight size={16} />
            </a>
            <div className="revival-direction"><span className="eyebrow">Fresh revival angle</span><h4>{item.revival_angle}</h4><p>{item.why_revive}</p></div>
            <div className="revival-footer"><span className={`evidence-strength ${strengthClass(item.evidence_strength)}`}>{strengthLabel(item.evidence_strength)}</span><button onClick={() => onInspect(item)}>Inspect rationale <ChevronRight size={15} /></button></div>
          </article>
        ))}
      </div>
    </div>
  );
}

function SignalView({ signals }: { signals: RecoverySignal[] }) {
  return (
    <div className="recovery-view">
      <div className="recovery-view-heading"><div><span className="eyebrow">Evidence stack</span><h3>Which Content DNA signals are carrying the recovery plan?</h3></div><p>Signals are ranked with sample support in mind; a tiny high-performing sample cannot automatically dominate.</p></div>
      <div className="signal-stack-grid">
        {signals.map((signal, index) => (
          <article className="signal-stack-card glass-card" key={`${signal.kind}-${signal.name}`}>
            <div className="signal-number">{String(index + 1).padStart(2, "0")}</div>
            <span className="signal-kind">{kindLabel(signal.kind)}</span>
            <h4>{signal.name}</h4><p>{signal.description}</p>
            <div className="signal-metric-row"><strong>{formatRatio(signal.evidence.relative_to_channel_median)}</strong><span>{signal.evidence.video_count} supporting videos</span></div>
            <div className="signal-label-row"><span>{signal.evidence.performance_signal}</span><span>{signal.evidence.sample_strength}</span></div>
          </article>
        ))}
      </div>
    </div>
  );
}

function RecoveryDetailDrawer({ selection, onClose }: { selection: DetailSelection; onClose: () => void }) {
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => { document.body.style.overflow = previous; window.removeEventListener("keydown", onKey); };
  }, [onClose]);

  const content = detailContent(selection);
  return createPortal(
    <div className="recovery-detail-layer" role="dialog" aria-modal="true" aria-label={`${content.title} rationale`}>
      <button className="recovery-detail-backdrop" aria-label="Close rationale" onClick={onClose} />
      <aside className="recovery-detail-drawer">
        <div className="recovery-detail-head"><div><span className="eyebrow">Traceable recovery rationale</span><h3>{content.title}</h3></div><button onClick={onClose} aria-label="Close"><X size={20} /></button></div>
        <p className="recovery-detail-copy">{content.description}</p>
        <div className="recovery-detail-badges">
          <span className={`evidence-strength ${content.badgeClass}`}>{content.badgeLabel}</span>
          {content.novelty && <span className="novelty-chip"><SearchCheck size={13} /> {content.novelty}</span>}
          {content.matches[0] && <span className="closest-match-chip">Closest archive match: {shortSimilarityLabel(content.matches[0].similarity_label)}</span>}
        </div>
        <section className="recovery-detail-section"><span className="eyebrow">Why ReviveAI surfaced this</span><p>{content.why}</p></section>
        {content.strategyLanes.length > 0 && <section className="recovery-detail-section"><span className="eyebrow">Strategy lanes</span><div className="strategy-lane-row detail">{content.strategyLanes.map((lane) => <span key={lane}>{lane}</span>)}</div>{content.diversityNote && <p className="diversity-note">{content.diversityNote}</p>}</section>}
        <section className="recovery-detail-section"><span className="eyebrow">Idea-specific evidence</span><p className="evidence-grounding-copy">Only Content DNA signals that are semantically relevant to this exact concept are shown here.</p><div className="recovery-detail-signals">{content.signals.map((signal) => <SignalMini key={`${signal.kind}-${signal.name}`} signal={signal} />)}</div></section>
        {content.matches.length > 0 && <section className="recovery-detail-section"><span className="eyebrow">Closest archive concepts</span><div className="recovery-match-list">{content.matches.map((match) => <ArchiveMatchRow key={match.video.video_id} match={match} />)}</div></section>}
        {selection.kind === "revival" && <section className="recovery-detail-section"><span className="eyebrow">Source evidence</span><ArchiveVideoRow video={selection.item.source_video} /></section>}
        <div className="recovery-detail-note"><ShieldCheck size={17} /><span>These are evidence-backed creative hypotheses. Historical associations do not guarantee future performance.</span></div>
      </aside>
    </div>,
    document.body,
  );
}

function detailContent(selection: DetailSelection) {
  if (selection.kind === "recommendation") return {
    title: selection.item.title, description: selection.item.concept,
    badgeLabel: strengthLabel(selection.item.evidence_strength), badgeClass: strengthClass(selection.item.evidence_strength),
    novelty: selection.item.novelty_label, why: selection.item.why_this_fits,
    signals: selection.item.evidence_signals, matches: selection.item.closest_archive_matches,
    strategyLanes: selection.item.strategy_lanes, diversityNote: selection.item.diversity_note,
  };
  if (selection.kind === "gap") return {
    title: selection.item.title, description: selection.item.concept,
    badgeLabel: gapStrengthLabel(selection.item.opportunity_strength), badgeClass: gapStrengthClass(selection.item.opportunity_strength),
    novelty: selection.item.novelty_label, why: selection.item.why_it_fits,
    signals: selection.item.evidence_signals, matches: selection.item.closest_archive_matches,
    strategyLanes: [] as string[], diversityNote: "",
  };
  return {
    title: selection.item.revival_angle, description: selection.item.source_summary,
    badgeLabel: strengthLabel(selection.item.evidence_strength), badgeClass: strengthClass(selection.item.evidence_strength),
    novelty: null, why: selection.item.why_revive, signals: selection.item.evidence_signals, matches: [] as ArchiveMatch[],
    strategyLanes: [] as string[], diversityNote: "",
  };
}

function ArchiveMatchRow({ match }: { match: ArchiveMatch }) {
  return <a className="recovery-match-row" href={match.video.watch_url} target="_blank" rel="noreferrer">{match.video.thumbnail_url ? <img src={match.video.thumbnail_url} alt="" /> : <SearchCheck size={20} />}<div><strong>{match.video.title}</strong><span>{match.similarity_label} · {formatViews(match.video.views)} views</span></div><ArrowUpRight size={14} /></a>;
}
function ArchiveVideoRow({ video }: { video: RevivalOpportunity["source_video"] }) {
  return <a className="recovery-match-row" href={video.watch_url} target="_blank" rel="noreferrer">{video.thumbnail_url ? <img src={video.thumbnail_url} alt="" /> : <ArchiveRestore size={20} />}<div><strong>{video.title}</strong><span>{formatViews(video.views)} views · {tierLabel(video.performance_tier)}</span></div><ArrowUpRight size={14} /></a>;
}

function SignalMini({ signal }: { signal: RecoverySignal }) {
  return <div className="signal-mini"><div><strong>{signal.name}</strong><span>{kindLabel(signal.kind)} · {signal.evidence.video_count} videos</span></div><em>{formatRatio(signal.evidence.relative_to_channel_median)}</em></div>;
}
function ProofCell({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }
function ProgressFact({ label, value, helper }: { label: string; value: string; helper: string }) { return <div className="recovery-progress-fact"><span>{label}</span><strong>{value}</strong><em>{helper}</em></div>; }
function SummaryStat({ icon, value, label, helper }: { icon: ReactNode; value: number; label: string; helper: string }) { return <div className="recovery-summary-stat"><span>{icon}</span><div><strong>{value}</strong><em>{label}</em><small>{helper}</small></div></div>; }

function strongestSignals(dna: ContentDnaResult) {
  const rows: { kind: string; name: string; ratio: number }[] = [];
  const add = (kind: string, items: { name: string; evidence: { relative_to_channel_median?: number | null; video_count: number } }[]) => items.forEach((item) => { if ((item.evidence.relative_to_channel_median ?? 0) > 0 && item.evidence.video_count >= 3) rows.push({ kind, name: item.name, ratio: item.evidence.relative_to_channel_median ?? 0 }); });
  add("theme", dna.themes); add("character", dna.characters); add("pattern", dna.story_patterns); add("pattern", dna.visual_patterns);
  return rows.sort((a, b) => b.ratio - a.ratio);
}
function kindLabel(kind: string) { return kind === "story_pattern" ? "Story pattern" : kind === "visual_pattern" ? "Visual pattern" : kind.charAt(0).toUpperCase() + kind.slice(1); }
function strengthClass(value: string) { const v = value.toUpperCase(); return v === "STRONG" ? "strong" : v === "SUPPORTED" ? "supported" : "exploratory"; }
function strengthLabel(value: string) { const v = value.toUpperCase(); return v === "STRONG" ? "Strong evidence" : v === "SUPPORTED" ? "Supported direction" : "Exploratory"; }
function gapStrengthClass(value: string) { const v = value.toUpperCase(); return v === "EVIDENCE_BACKED_GAP" ? "strong" : v === "ADJACENT_OPPORTUNITY" ? "supported" : "exploratory"; }
function gapStrengthLabel(value: string) { const v = value.toUpperCase(); return v === "EVIDENCE_BACKED_GAP" ? "Evidence-backed gap" : v === "ADJACENT_OPPORTUNITY" ? "Adjacent opportunity" : "Emerging opportunity"; }
function shortSimilarityLabel(value: string) { return value === "Close archive match" ? "Close" : value === "Related archive concept" ? "Related" : "Loose"; }
function formatRatio(value?: number | null) { return value == null ? "—" : `${value.toFixed(1)}× median`; }
function formatViews(value?: number | null) { if (value == null) return "—"; return new Intl.NumberFormat("en-US", { notation: value >= 10000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(value); }
function tierLabel(value: string) { return value === "low" ? "Lower quartile" : value.charAt(0).toUpperCase() + value.slice(1); }
