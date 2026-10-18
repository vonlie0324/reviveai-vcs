import { Check, LoaderCircle } from "lucide-react";
import type { AnalysisJob, JobStage } from "../types";

const steps: Array<{ stage: JobStage; label: string }> = [
  { stage: "RESOLVING_CHANNEL", label: "Resolve channel" },
  { stage: "READING_UPLOADS", label: "Read public upload history" },
  { stage: "FETCHING_VIDEO_DETAILS", label: "Fetch video details" },
  { stage: "COMPUTING_METRICS", label: "Compute evidence-backed metrics" },
  { stage: "PREPARING_SNAPSHOT", label: "Prepare channel intelligence" },
];

const stageOrder: JobStage[] = [
  "QUEUED",
  "RESOLVING_CHANNEL",
  "READING_UPLOADS",
  "FETCHING_VIDEO_DETAILS",
  "COMPUTING_METRICS",
  "PREPARING_SNAPSHOT",
  "COMPLETED",
];

function indexOf(stage: JobStage) {
  return stageOrder.indexOf(stage);
}

export function ProgressTimeline({ job }: { job: AnalysisJob }) {
  const current = indexOf(job.stage);
  const discovered = Number(job.detail?.videos_discovered ?? 0);
  const loaded = Number(job.detail?.videos_loaded ?? 0);

  return (
    <section className="progress-card glass-card" aria-live="polite">
      <div className="progress-heading">
        <div>
          <span className="eyebrow">Live channel analysis</span>
          <h2>{job.message}</h2>
        </div>
        <LoaderCircle className="spinner" size={24} aria-hidden="true" />
      </div>

      <div className="progress-steps">
        {steps.map((step) => {
          const stepIndex = indexOf(step.stage);
          const complete = current > stepIndex;
          const active = current === stepIndex;
          return (
            <div className={`progress-step ${complete ? "complete" : ""} ${active ? "active" : ""}`} key={step.stage}>
              <div className="step-dot">
                {complete ? <Check size={14} /> : <span />}
              </div>
              <span>{step.label}</span>
            </div>
          );
        })}
      </div>

      {(discovered > 0 || loaded > 0) && (
        <div className="live-detail">
          {discovered > 0 && <span>{discovered.toLocaleString()} uploads discovered</span>}
          {loaded > 0 && <span>{loaded.toLocaleString()} video records loaded</span>}
        </div>
      )}
    </section>
  );
}
