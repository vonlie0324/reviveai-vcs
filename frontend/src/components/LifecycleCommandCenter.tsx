import { useState } from "react";
import { ArrowRight, Bot, BrainCircuit, Check, CircleAlert, Clapperboard, LoaderCircle, RadioTower, Plus, FolderOpen } from "lucide-react";
import "./LifecycleCommandCenter.css";
import type { WorkspaceProduction } from "../workspace";
import type { NextContentRecommendation } from "../types";
import { formatRelativeWorkspaceTime } from "../workspace";

type StageId = "learn" | "understand" | "create" | "publish" | "improve";
type StageState = "complete" | "current" | "available" | "pending";
interface Stage { id: StageId; title: string; description: string; action: string; }
const stages: Stage[] = [
  { id: "learn", title: "Learn", description: "Understand your channel from public YouTube evidence.", action: "View channel evidence" },
  { id: "understand", title: "Understand", description: "Build Content DNA and turn it into creative intelligence.", action: "Open intelligence" },
  { id: "create", title: "Create", description: "Turn channel intelligence into video productions.", action: "Open production workspace" },
  { id: "publish", title: "Publish", description: "Prepare, review, schedule and deliver your videos to YouTube.", action: "Open publishing workspace" },
  { id: "improve", title: "Improve", description: "Review performance and use the findings in the next production.", action: "Review learning and intelligence" },
];

interface Props {
  channelReady: boolean;
  dnaReady: boolean;
  intelligenceReady: boolean;
  dnaBusy?: boolean;
  intelligenceBusy?: boolean;
  productionCount: number;
  productions?: WorkspaceProduction[];
  /** IDs whose final video approval and delivery package were verified in the active backend session. */
  verifiedPublishReadyIds?: string[];
  onOpenProduction?: (production: WorkspaceProduction) => void;
  onNewProduction?: () => void;
  recommendations?: NextContentRecommendation[];
  onCreateBrief?: (recommendation: NextContentRecommendation) => void;
  briefBusy?: boolean;
  briefError?: string | null;
  autonomyStatus?: string;
  onStage: (stage: StageId) => void;
  onContinue: () => void;
  onAutonomy: () => void;
  onBuildDna: () => void;
  canStartDna: boolean;
  onBuildIntelligence: () => void;
  dnaStage?: string | null;
  intelligenceStage?: string | null;
  dnaError?: string | null;
  intelligenceError?: string | null;
}

export function LifecycleCommandCenter({ channelReady, dnaReady, intelligenceReady, dnaBusy, intelligenceBusy, productionCount, productions = [], verifiedPublishReadyIds = [], onOpenProduction, onNewProduction, recommendations = [], onCreateBrief, briefBusy = false, briefError, autonomyStatus, onStage, onContinue, onAutonomy, onBuildDna, canStartDna, onBuildIntelligence, dnaStage, intelligenceStage, dnaError, intelligenceError }: Props) {
  const productionReady = dnaReady && intelligenceReady;
  const recentProductions = [...productions].sort((a,b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt)).slice(0,4);
  const publishReadyProductions = recentProductions.filter(p => verifiedPublishReadyIds.includes(p.id));
  const unfinishedProductions = recentProductions.filter(p => !verifiedPublishReadyIds.includes(p.id));
  const priorityProduction = unfinishedProductions.find(p => p.status === "REVIEW" || p.status === "BLOCKED") ?? unfinishedProductions[0];
  const next: StageId = !channelReady ? "learn" : !dnaReady || !intelligenceReady ? "understand" : priorityProduction || !publishReadyProductions.length ? "create" : "publish";
  const [selected, setSelected] = useState<StageId | null>(null);
  const [selectedRecommendationId, setSelectedRecommendationId] = useState<string | null>(null);
  const [inspectedProductionId, setInspectedProductionId] = useState<string | null>(null);
  const active = selected ?? next;
  const recommendedIdeas = [...recommendations].sort((a,b) => a.rank - b.rank);
  const chosenIdea = recommendedIdeas.find((item) => item.recommendation_id === selectedRecommendationId) ?? recommendedIdeas[0];
  const inspectedProduction = recentProductions.find(item => item.id === inspectedProductionId) ?? priorityProduction ?? publishReadyProductions[0];
  // These are persisted workspace stages, not fabricated progress percentages.
  const productionStages = ["BRIEF", "VISUALS", "VISUAL_MASTER", "AUDIO", "QC", "DELIVERY", "PUBLISHING"] as const;
  const productionStageLabels: Record<(typeof productionStages)[number], string> = {
    BRIEF: "Brief", VISUALS: "Visuals", VISUAL_MASTER: "Visual master", AUDIO: "Audio", QC: "Quality review", DELIVERY: "Delivery", PUBLISHING: "Publishing"
  };

  const currentStage = stages.find((stage) => stage.id === active)!;
  const currentProductionNeedsReview = active === "create" && priorityProduction?.status === "REVIEW";
  const centerStatus = currentProductionNeedsReview ? "NEEDS YOUR REVIEW" : active === "create" && priorityProduction ? "PRODUCTION IN PROGRESS" : null;
  const centerMilestone = active === "create" && priorityProduction ? priorityProduction.stageLabel : null;
  const isExploring = active !== next;
  const autonomyActive = autonomyStatus === "RUNNING";
  const understandBusy = (dnaBusy && !dnaReady) || (intelligenceBusy && dnaReady && !intelligenceReady);
  const processingLabel = dnaBusy && !dnaReady ? "Building Content DNA" : intelligenceBusy && !intelligenceReady ? "Generating intelligence" : null;
  const processingStage = dnaBusy && !dnaReady ? dnaStage : intelligenceStage;
  const processingDescription = processingStage && !["STARTED", "RUNNING", "PENDING", "QUEUED"].includes(processingStage.toUpperCase())
    ? `Backend status: ${processingStage.replace(/_/g, " ").toLowerCase()}`
    : "Waiting for the next backend update";

  const states: Record<StageId, StageState> = {
    learn: channelReady ? "complete" : "current",
    understand: intelligenceReady && dnaReady ? "complete" : channelReady ? "current" : "pending",
    create: productionReady ? (priorityProduction || !publishReadyProductions.length ? "current" : "complete") : "pending",
    publish: productionReady && publishReadyProductions.length ? "available" : "pending",
    improve: intelligenceReady && dnaReady ? "available" : "pending",
  };
  const readiness = [channelReady, dnaReady, intelligenceReady].filter(Boolean).length;
  const nextMessage = !channelReady ? "Analyze your channel to get started." : !dnaReady ? "Build Content DNA to capture your channel's creative identity." : !intelligenceReady ? "Generate intelligence from your Content DNA." : priorityProduction ? `${priorityProduction.title} — ${priorityProduction.stageLabel}.` : publishReadyProductions.length ? "An approved video is ready for publishing preparation." : "You're ready to create your first video.";
  const nextLabel = !channelReady ? "Continue channel setup" : !dnaReady ? "Build Content DNA" : !intelligenceReady ? "Generate intelligence" : priorityProduction ? "Continue production" : publishReadyProductions.length ? "Prepare for publishing" : "Create your first video";
  // SVG stages are keyboard accessible; fallback buttons remain for small screens.
  return (
    <section className={`lcc glass-card ${understandBusy ? "lcc--working" : ""}`} aria-label="ReviveAI lifecycle command center">
      <div className="lcc-heading">
        <div><span className="eyebrow">Your creator lifecycle</span><h2>Your content lifecycle</h2><p>Select a stage to explore, or follow the next recommended action.</p></div>
        <span className="lcc-readiness">{readiness === 3 ? `${productionCount} saved production${productionCount === 1 ? "" : "s"}` : `Setup ${readiness} of 3 ready`}</span>
      </div>
      <div className="lcc-layout">
        <div className="lcc-cycle-wrap">
          <svg className="lcc-cycle" viewBox="0 0 440 420" role="img" aria-label="Five-stage lifecycle: Learn, Understand, Create, Publish, Improve. Improve feeds back into Create.">
            <circle cx="220" cy="210" r="144" className="lcc-track" />
            {stages.map((stage, index) => {
              const mid = -90 + index * 72;
              const rad = (mid * Math.PI) / 180;
              const x = 220 + 144 * Math.cos(rad);
              const y = 210 + 144 * Math.sin(rad);
              const start = ((mid - 25) * Math.PI) / 180;
              const end = ((mid + 25) * Math.PI) / 180;
              const d = `M${220 + 144 * Math.cos(start)} ${210 + 144 * Math.sin(start)} A144 144 0 0 1 ${220 + 144 * Math.cos(end)} ${210 + 144 * Math.sin(end)}`;
              return <g key={stage.id} className="lcc-stage-target" role="button" tabIndex={0} aria-label={`Explore ${stage.title} stage: ${states[stage.id]}`} aria-pressed={active === stage.id} onClick={() => setSelected(stage.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelected(stage.id); } }}>
                <path d={d} className={`lcc-segment lcc-segment--${states[stage.id]} ${active === stage.id ? "lcc-segment--selected" : ""} ${stage.id === "understand" && understandBusy ? "lcc-segment--working" : ""}`} />
                <circle cx={x} cy={y} r="34" className={`lcc-node lcc-node--${states[stage.id]} ${active === stage.id ? "lcc-node--selected" : ""} ${stage.id === "understand" && understandBusy ? "lcc-node--working" : ""}`} />
                <text x={x} y={y - 2} textAnchor="middle" className="lcc-node-number">{states[stage.id] === "complete" ? "✓" : index + 1}</text>
                <text x={x} y={y + 14} textAnchor="middle" className="lcc-node-label">{stage.title.toUpperCase()}</text>
              </g>;
            })}
            <circle cx="220" cy="210" r="89" className="lcc-core" />
            <text x="220" y="178" textAnchor="middle" className="lcc-center-small">{centerStatus ?? (understandBusy && active === "understand" ? "WORKING ON" : isExploring ? "EXPLORING" : "NEXT STEP")}</text>
            <text x="220" y="207" textAnchor="middle" className="lcc-center-title">{currentStage.title.toUpperCase()}</text>
            <text x="220" y="227" textAnchor="middle" className="lcc-center-subtitle">{centerMilestone ? centerMilestone.length > 28 ? `${centerMilestone.slice(0, 25)}…` : centerMilestone : understandBusy && active === "understand" ? "Processing…" : autonomyActive ? "Autonomy active" : "Guided mode"}</text>
            <text x="220" y="254" textAnchor="middle" className="lcc-center-foot">↻ CREATE · PUBLISH · IMPROVE</text>
          </svg>
          <div className="lcc-stage-buttons" aria-label="Explore lifecycle stages">
            {stages.map((stage) => <button key={stage.id} className={active === stage.id ? "is-selected" : ""} type="button" aria-pressed={active === stage.id} onClick={() => setSelected(stage.id)}>{states[stage.id] === "complete" && <Check size={12} />}{stage.title}</button>)}
          </div>
        </div>
        <div className="lcc-details">
          {active === "create" ? (
            <div className="lcc-next lcc-create lcc-create-compact" aria-label="Create video productions">
              <div className="lcc-compact-top"><span className="eyebrow">Create · Your next action</span><span className="lcc-compact-badge">{inspectedProduction ? inspectedProduction.status === "REVIEW" ? "Needs review" : inspectedProduction.status : productionReady ? "Ready" : "Setup needed"}</span></div>
              {!productionReady ? <>
                <h3>Complete your creative foundation</h3>
                <p>Finish Content DNA and Creative Intelligence before creating videos.</p>
                <button className="primary-button" type="button" onClick={() => setSelected("understand")}>Continue Understand <ArrowRight size={16}/></button>
              </> : inspectedProduction ? <>
                <h3 className="lcc-compact-title">{inspectedProduction.title}</h3>
                <p className="lcc-compact-milestone">{inspectedProduction.stageLabel} · {inspectedProduction.milestone}</p>
                <div className="lcc-compact-progress" aria-label={`Current saved production stage: ${inspectedProduction.stageLabel}`}>
                  <div className="lcc-compact-progress-heading"><strong>Production checkpoint</strong><span>{productionStageLabels[inspectedProduction.stage as keyof typeof productionStageLabels] ?? inspectedProduction.stageLabel}</span></div>
                  <div className="lcc-compact-bars" aria-hidden="true">{productionStages.map(stage => <span key={stage} className={stage === inspectedProduction.stage ? "is-active" : ""}/>)}</div>
                  <small>Current stage only; earlier stages are not assumed complete.</small>
                </div>
                <button className="primary-button lcc-compact-primary" type="button" onClick={() => onOpenProduction?.(inspectedProduction)} disabled={!onOpenProduction}>{inspectedProduction.status === "REVIEW" ? "Review production" : verifiedPublishReadyIds.includes(inspectedProduction.id) ? "Open approved video" : "Continue production"}<ArrowRight size={16}/></button>
                <details className="lcc-compact-disclosure"><summary>Production details and other actions</summary>
                  <div className="lcc-compact-extra">
                    <div className="lcc-productions-heading"><strong>Saved productions</strong><span>{productionCount} total</span></div>
                    {recentProductions.map(p => <button key={p.id} type="button" className="lcc-production-row" onClick={() => setInspectedProductionId(p.id)} aria-pressed={inspectedProduction.id === p.id}><span className="lcc-production-info"><strong>{p.title}</strong><small>{p.stageLabel} · {formatRelativeWorkspaceTime(p.updatedAt)}</small></span><ArrowRight size={14}/></button>)}
                    <ol className="lcc-track-steps">{productionStages.map(stage => <li key={stage} className={`lcc-track-step ${inspectedProduction.stage === stage ? "is-current" : ""}`} aria-current={inspectedProduction.stage === stage ? "step" : undefined}><span>{productionStageLabels[stage]}</span>{inspectedProduction.stage === stage && <small>Current</small>}</li>)}</ol>
                    <button className="secondary-button" type="button" onClick={onNewProduction ?? (() => onStage("create"))}>Create another video</button>
                    <button className="secondary-button" type="button" onClick={() => onStage("create")}>All productions</button>
                    <button className="secondary-button" type="button" onClick={onNewProduction ?? (() => onStage("create"))}>Explore creative directions</button>
                  </div>
                </details>
              </> : <>
                <h3>Create your first video</h3>
                <p>Choose a direction grounded in the channel intelligence.</p>
                {recommendedIdeas.length > 0 && <div className="lcc-compact-choice"><label htmlFor="lcc-direction-select">Creative direction</label><select id="lcc-direction-select" value={chosenIdea?.recommendation_id ?? ""} disabled={briefBusy} onChange={e => setSelectedRecommendationId(e.target.value)}>{recommendedIdeas.map(idea => <option key={idea.recommendation_id} value={idea.recommendation_id}>{idea.title}</option>)}</select>{chosenIdea && <small>{chosenIdea.hook || chosenIdea.concept}</small>}</div>}
                {briefError && <p className="lcc-action-error" role="alert">{briefError}</p>}
                <button className="primary-button lcc-compact-primary" disabled={briefBusy} type="button" onClick={chosenIdea && onCreateBrief ? () => onCreateBrief(chosenIdea) : onNewProduction ?? (() => onStage("create"))}>{briefBusy ? <LoaderCircle className="lcc-spin" size={16}/> : <Plus size={16}/>} {briefBusy ? "Creating brief…" : chosenIdea && onCreateBrief ? "Create production brief" : "Explore creative directions"}<ArrowRight size={16}/></button>
                <details className="lcc-compact-disclosure"><summary>More options</summary><div className="lcc-compact-extra"><button className="secondary-button" type="button" onClick={() => onStage("create")}>All productions</button><button className="secondary-button" type="button" onClick={onNewProduction ?? (() => onStage("create"))}>Explore all directions</button></div></details>
              </>}
            </div>
          ) : active === "understand" && channelReady ? (
            <div className="lcc-next lcc-understand" aria-label="Understand channel setup">
              <span className="eyebrow">Understand · Creative foundation</span>
              <h3>Understand your channel</h3>
              <p>Build a reusable creative identity, then turn it into production recommendations. Completed steps are preserved.</p>
              <div className="lcc-checklist">
                <div className="lcc-checklist-step">
                  <span className={`lcc-step-icon ${channelReady ? "is-done" : ""}`}>{channelReady ? <Check size={17}/> : "1"}</span>
                  <div><strong>Channel evidence</strong><small>Public channel analysis saved</small></div>
                  <span className="lcc-step-status">Complete</span>
                </div>
                <div className="lcc-checklist-step">
                  <span className={`lcc-step-icon ${dnaReady ? "is-done" : ""}`}>{dnaReady ? <Check size={17}/> : "2"}</span>
                  <div><strong>Content DNA</strong><small>Creative identity, formats and recurring patterns</small></div>
                  <span className="lcc-step-status">{dnaReady ? "Complete" : dnaBusy ? <span className="lcc-inline-busy"><LoaderCircle size={12} aria-hidden="true"/> Processing</span> : dnaStage === "FAILED" ? "Failed" : "To do"}</span>
                </div>
                <div className="lcc-checklist-step">
                  <span className={`lcc-step-icon ${intelligenceReady ? "is-done" : ""}`}>{intelligenceReady ? <Check size={17}/> : "3"}</span>
                  <div><strong>Creative intelligence</strong><small>Production opportunities grounded in the channel evidence</small></div>
                  <span className="lcc-step-status">{intelligenceReady ? "Complete" : intelligenceBusy ? <span className="lcc-inline-busy"><LoaderCircle size={12} aria-hidden="true"/> Processing</span> : intelligenceStage === "FAILED" ? "Failed" : "To do"}</span>
                </div>
              </div>
              {dnaError && !dnaReady && <p role="alert" className="lcc-action-error">{dnaError}</p>}
              {intelligenceError && dnaReady && !intelligenceReady && <p role="alert" className="lcc-action-error">{intelligenceError}</p>}
              <div className="lcc-actions">
                {!dnaReady ? <button className="primary-button" disabled={Boolean(dnaBusy)} type="button" onClick={canStartDna ? onBuildDna : () => onStage("understand")}>{!canStartDna ? "Restore channel analysis" : dnaBusy ? "Building Content DNA…" : dnaStage === "FAILED" ? "Retry Content DNA" : "Build Content DNA"}<ArrowRight size={16}/></button>
                  : !intelligenceReady ? <button className="primary-button" disabled={Boolean(intelligenceBusy)} type="button" onClick={onBuildIntelligence}>{intelligenceBusy ? "Generating intelligence…" : intelligenceStage === "FAILED" ? "Retry intelligence" : "Generate intelligence"}<ArrowRight size={16}/></button>
                  : <button className="primary-button" type="button" onClick={() => onStage("create")}>Continue to Create<ArrowRight size={16}/></button>}
                <button className="secondary-button" type="button" onClick={() => onStage("understand")}>View detailed intelligence<ArrowRight size={16}/></button>
              </div>
              {processingLabel && <div className="lcc-live-job" role="status" aria-live="polite" aria-atomic="true">
                <div className="lcc-live-job-heading"><span className="lcc-live-dot" aria-hidden="true"/><strong>{processingLabel}</strong><span className="lcc-live-tag">In progress</span></div>
                <div className="lcc-indeterminate" aria-hidden="true"><span/></div>
                <p>{processingDescription}. You can safely leave this workspace; ReviveAI will retain the job state.</p>
                <span className="lcc-live-hint">Activity indicator only — actual completion percentage is not available.</span>
              </div>}
            </div>
          ) : (
            <div className="lcc-next">
              <span className="eyebrow">{isExploring ? `Exploring · ${currentStage.title}` : "Recommended next action"}</span>
              <h3>{isExploring ? currentStage.title : nextMessage}</h3>
              <p>{active === "publish" && !publishReadyProductions.length ? "Publishing will unlock after final video approval and a verified delivery package. Saving a brief does not make a video ready." : currentStage.description}</p>
              <span className={`lcc-state lcc-state--${states[active]}`}>{states[active] === "complete" ? "Completed" : states[active] === "current" ? "Next step" : states[active] === "available" ? "Available" : "Prerequisites pending"}</span>
              <div className="lcc-actions">
                <button className="primary-button" type="button" onClick={() => (active === "publish" && !publishReadyProductions.length && priorityProduction && onOpenProduction) ? onOpenProduction(priorityProduction) : isExploring ? onStage(active) : onContinue()}>{active === "publish" && !publishReadyProductions.length ? (priorityProduction ? "Finish production first" : "Create a video first") : isExploring ? currentStage.action : nextLabel}<ArrowRight size={16}/></button>
                {isExploring && <button type="button" className="secondary-button" onClick={() => setSelected(null)}>Back to next step</button>}
              </div>
            </div>
          )}
          <div className="lcc-autonomy"><Bot size={21}/><div><strong>{autonomyActive ? "Autonomy running" : "Automate this lifecycle"}</strong><p>{autonomyActive ? "View the supervisor and publishing activity." : "Optional: connect YouTube and configure approvals, cadence and budget."}</p></div><button type="button" className="secondary-button" onClick={onAutonomy}>{autonomyActive ? "Monitor" : "Set up"}<ArrowRight size={14}/></button></div>
        </div>
      </div>
      <div className="lcc-bottom"><span><BrainCircuit size={15}/> Evidence and intelligence</span><span><Clapperboard size={15}/> {productionCount} saved production{productionCount === 1 ? "" : "s"}</span><span><RadioTower size={15}/> Publishing and learning</span><span><CircleAlert size={15}/> Publishing status is tracked per video</span></div>
    </section>
  );
}
