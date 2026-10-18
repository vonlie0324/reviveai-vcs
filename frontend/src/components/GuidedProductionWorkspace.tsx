import { Check, ChevronDown, ChevronRight, Circle, SlidersHorizontal, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

export type GuidedStageId = "idea" | "create" | "finish" | "deliver";

export interface GuidedStage {
  id: GuidedStageId;
  label: string;
  description: string;
  complete: boolean;
  available: boolean;
  node: ReactNode;
}

interface Props {
  title: string;
  subtitle: string;
  stages: GuidedStage[];
  completed: boolean;
}

function nextStage(stages: GuidedStage[]): GuidedStage {
  return stages.find((stage) => stage.available && !stage.complete) ?? stages.filter((stage) => stage.available).slice(-1)[0] ?? stages[0];
}

export function GuidedProductionWorkspace({ title, subtitle, stages, completed }: Props) {
  const focus = useMemo(() => nextStage(stages), [stages]);
  const [mode, setMode] = useState<"CREATOR" | "ADVANCED">("CREATOR");
  const [openStage, setOpenStage] = useState<GuidedStageId | null>(null);
  const goToStage = (id: GuidedStageId) => {
    if (openStage === id) {
      document.getElementById(`guided-stage-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      setOpenStage(id);
    }
  };
  useEffect(() => {
    if (!openStage) return;
    document.getElementById(`guided-stage-${openStage}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [openStage]);

  if (mode === "ADVANCED") {
    return (
      <section className="guided-production-shell is-advanced">
        <div className="guided-mode-bar glass-card">
          <div><span className="eyebrow">Advanced production view</span><strong>All production details are visible.</strong></div>
          <button className="secondary-button" type="button" onClick={() => setMode("CREATOR")}><Sparkles size={15} /> Creator mode</button>
        </div>
        <div className="guided-advanced-panels">{stages.map((stage) => <div key={stage.id}>{stage.node}</div>)}</div>
      </section>
    );
  }

  return (
    <section className="guided-production-shell">
      <article className="guided-focus-card glass-card">
        <div className="guided-focus-copy">
          <span className="eyebrow">Creator mode</span>
          <h2>{completed ? "Your video is ready." : focus.label}</h2>
          <p>{completed ? "The production is complete. Start from the final result, and open production details only when you need them." : focus.description}</p>
          <div className="guided-stage-strip" aria-label="Production progress">
            {stages.map((stage, index) => (
              <button
                type="button"
                key={stage.id}
                disabled={!stage.available}
                className={`${stage.complete ? "complete" : focus.id === stage.id ? "current" : "future"}`}
                onClick={() => goToStage(stage.id)}
              >
                <span>{stage.complete ? <Check size={14} /> : <Circle size={12} />}</span>
                <b>{index + 1}</b>
                <strong>{stage.label.replace(/^\d+\s*/, "")}</strong>
              </button>
            ))}
          </div>
        </div>
        <div className="guided-focus-actions">
          {!completed && (
            <button className="primary-button" type="button" onClick={() => goToStage(focus.id)}>
              {focus.id === "deliver" ? "Continue final review" : "Continue"} <ChevronRight size={16} />
            </button>
          )}
          {completed && (
            <button className="primary-button" type="button" onClick={() => goToStage("deliver")}>
              View final result <ChevronRight size={16} />
            </button>
          )}
          <button className="guided-advanced-toggle" type="button" onClick={() => setMode("ADVANCED")}><SlidersHorizontal size={15} /> Advanced</button>
        </div>
      </article>

      <div className="guided-stage-accordion">
        {stages.map((stage, index) => (
          <section id={`guided-stage-${stage.id}`} className={`guided-stage-section ${openStage === stage.id ? "is-open" : ""}`} key={stage.id}>
            <button
              className="guided-stage-summary"
              type="button"
              disabled={!stage.available}
              onClick={() => setOpenStage((current) => current === stage.id ? null : stage.id)}
              aria-expanded={openStage === stage.id}
            >
              <span className={`guided-stage-number ${stage.complete ? "complete" : focus.id === stage.id ? "current" : ""}`}>{stage.complete ? <Check size={14} /> : index + 1}</span>
              <span><strong>{stage.label}</strong><small>{stage.complete ? "Complete" : stage.description}</small></span>
              <ChevronDown size={17} />
            </button>
            {openStage === stage.id && <div className="guided-stage-content">{stage.node}</div>}
          </section>
        ))}
      </div>
    </section>
  );
}
