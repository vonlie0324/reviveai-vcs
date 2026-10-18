import {
  Check,
  ChevronRight,
  CircleAlert,
  CircleDot,
  LockKeyhole,
  Route,
  Sparkles,
} from "lucide-react";

export type CreatorJourneyStepStatus = "COMPLETE" | "CURRENT" | "REVIEW" | "BLOCKED" | "LOCKED";

export interface CreatorJourneyStep {
  id: string;
  label: string;
  shortLabel: string;
  milestone: string;
  detail: string;
  targetId?: string | null;
  status: CreatorJourneyStepStatus;
}

interface CreatorJourneyProps {
  steps: CreatorJourneyStep[];
  currentStepId: string;
  continueLabel: string;
  complete: boolean;
}

function scrollToTarget(targetId?: string | null) {
  if (!targetId) return;
  document.getElementById(targetId)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function StatusGlyph({ status }: { status: CreatorJourneyStepStatus }) {
  if (status === "COMPLETE") return <Check size={13} aria-hidden="true" />;
  if (status === "BLOCKED") return <CircleAlert size={13} aria-hidden="true" />;
  if (status === "REVIEW") return <CircleDot size={13} aria-hidden="true" />;
  if (status === "LOCKED") return <LockKeyhole size={12} aria-hidden="true" />;
  return <Sparkles size={13} aria-hidden="true" />;
}

export function CreatorJourney({ steps, currentStepId, continueLabel, complete }: CreatorJourneyProps) {
  const completeCount = steps.filter((step) => step.status === "COMPLETE").length;
  const current = steps.find((step) => step.id === currentStepId) ?? steps[steps.length - 1];
  const progress = Math.round((completeCount / steps.length) * 100);

  return (
    <nav className="creator-journey glass-card" aria-label="ReviveAI creator journey">
      <div className="creator-journey-head">
        <div className="creator-journey-title">
          <span className="creator-journey-icon"><Route size={17} aria-hidden="true" /></span>
          <div>
            <span className="eyebrow">M2D · Creator journey</span>
            <strong>{complete ? "Delivery workflow complete" : current.label}</strong>
            <small>{complete ? "Your approved master, delivery package, and publishing copy are ready." : current.detail}</small>
          </div>
        </div>

        <div className="creator-journey-actions">
          <div className="creator-journey-progress" aria-label={`${completeCount} of ${steps.length} stages complete`}>
            <span>{completeCount}/{steps.length}</span>
            <div className="creator-journey-progress-track" aria-hidden="true">
              <i style={{ width: `${progress}%` }} />
            </div>
          </div>
          <button
            className="creator-journey-continue"
            type="button"
            disabled={!current?.targetId}
            onClick={() => scrollToTarget(current?.targetId)}
          >
            {continueLabel}
            <ChevronRight size={15} aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="creator-journey-steps" role="list">
        {steps.map((step, index) => {
          const navigable = Boolean(step.targetId) && step.status !== "LOCKED";
          return (
            <button
              key={step.id}
              className={`creator-journey-step status-${step.status.toLowerCase()} ${step.id === currentStepId ? "is-current" : ""}`}
              type="button"
              role="listitem"
              disabled={!navigable}
              onClick={() => scrollToTarget(step.targetId)}
              title={step.detail}
              aria-current={step.id === currentStepId ? "step" : undefined}
            >
              <span className="creator-journey-step-index">{index + 1}</span>
              <span className="creator-journey-step-copy">
                <small>{step.milestone}</small>
                <strong>{step.shortLabel}</strong>
              </span>
              <span className="creator-journey-step-status"><StatusGlyph status={step.status} /></span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
