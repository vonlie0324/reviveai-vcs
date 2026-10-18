import { Check, LoaderCircle, Sparkles } from "lucide-react";

export type AiActivityStep = { label: string; state: "done" | "active" | "waiting" };

type Props = {
  title: string;
  message: string;
  steps?: AiActivityStep[];
  compact?: boolean;
};

export function AiActivityState({ title, message, steps = [], compact = false }: Props) {
  return (
    <section className={`ai-activity-state${compact ? " compact" : ""}`} role="status" aria-live="polite" aria-busy="true">
      <div className="ai-activity-orbit" aria-hidden="true"><Sparkles size={18} /><span /></div>
      <div className="ai-activity-copy">
        <strong>{title}</strong>
        <p>{message}</p>
        {steps.length > 0 && <div className="ai-activity-steps">
          {steps.map((step) => <div key={step.label} className={`ai-activity-step ${step.state}`}>
            <span className="ai-activity-step-icon" aria-hidden="true">
              {step.state === "done" ? <Check size={13} /> : step.state === "active" ? <LoaderCircle className="spin" size={13} /> : <span className="ai-activity-dot" />}
            </span>
            <span>{step.label}</span>
          </div>)}
        </div>}
      </div>
      <div className="ai-activity-shimmer" aria-hidden="true" />
    </section>
  );
}
