import type { ReactNode } from "react";
import { ArrowRight, BarChart3, BrainCircuit, FolderKanban, Plus, Sparkles } from "lucide-react";
import type { WorkspaceChannel, WorkspaceProduction } from "../workspace";
import { formatRelativeWorkspaceTime, getUniqueWorkspaceProductions } from "../workspace";

interface Props {
  channel: WorkspaceChannel;
  dnaReady: boolean;
  recoveryReady: boolean;
  onOpenTab: (tab: "overview" | "intelligence" | "productions") => void;
  onOpenProduction: (production: WorkspaceProduction) => void;
  revivalProgramSlot?: ReactNode;
}

export function ChannelWorkspaceHome({ channel, dnaReady, recoveryReady, onOpenTab, onOpenProduction, revivalProgramSlot }: Props) {
  const productions = getUniqueWorkspaceProductions(channel.productions);
  const recent = productions.slice(0, 4);

  return (
    <section className="channel-workspace-home">
      <div className="channel-home-grid">
        <button className="channel-home-card glass-card" type="button" onClick={() => onOpenTab("intelligence")}>
          <span className="channel-home-icon"><BarChart3 size={19} /></span>
          <small>Channel intelligence</small>
          <strong>Evidence-backed performance</strong>
          <p>The deterministic channel report is saved behind this view instead of expanding every production screen.</p>
          <span className="channel-home-action">Open intelligence <ArrowRight size={15} /></span>
        </button>

        <button className="channel-home-card glass-card" type="button" onClick={() => onOpenTab("intelligence")}>
          <span className="channel-home-icon"><BrainCircuit size={19} /></span>
          <small>Creative intelligence</small>
          <strong>{recoveryReady ? "Recovery intelligence ready" : dnaReady ? "Content DNA available" : "Creative intelligence"}</strong>
          <p>Explore the detailed evidence and AI synthesis behind the Revival Program below. The program card guides the next required action.</p>
          <span className="channel-home-action">View intelligence details <ArrowRight size={15} /></span>
        </button>

        <button className="channel-home-card glass-card" type="button" onClick={() => onOpenTab("productions")}>
          <span className="channel-home-icon"><FolderKanban size={19} /></span>
          <small>Productions</small>
          <strong>{productions.length} saved production{productions.length === 1 ? "" : "s"}</strong>
          <p>Open a production directly at its brief, visuals, audio, QC, delivery, or publishing stage.</p>
          <span className="channel-home-action">Browse productions <ArrowRight size={15} /></span>
        </button>
      </div>

      {revivalProgramSlot}

      <div className="channel-recent-heading">
        <div>
          <span className="eyebrow">Recent productions</span>
          <h2>Keep creating</h2>
        </div>
        <button type="button" onClick={() => onOpenTab("intelligence")}><Plus size={15} /> New production</button>
      </div>

      {recent.length ? (
        <div className="channel-recent-list glass-card">
          {recent.map((production) => (
            <button type="button" key={production.id} onClick={() => onOpenProduction(production)}>
              <span className={`workspace-status-dot status-${production.status.toLowerCase()}`} />
              <span>
                <strong>{production.title}</strong>
                <small>{production.stageLabel} · {formatRelativeWorkspaceTime(production.updatedAt)}</small>
              </span>
              <span>{production.milestone}</span>
              <ArrowRight size={15} />
            </button>
          ))}
        </div>
      ) : (
        <div className="channel-no-production glass-card">
          <Sparkles size={20} />
          <div>
            <strong>No production brief yet</strong>
            <span>Open Intelligence, choose a Recovery direction, and create your first production brief.</span>
          </div>
        </div>
      )}
    </section>
  );
}
