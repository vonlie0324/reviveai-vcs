import { useEffect, useMemo, useState } from "react";
import { BrainCircuit, ChevronDown, ChevronUp, LoaderCircle, RefreshCw } from "lucide-react";
import { bootstrapRevivalLearning, getRevivalLearning } from "../api";
import { observationDecisionReady } from "../youtubePerformance";
import type { RecoveryResult, RevivalLearningWorkspace, RevivalProgram } from "../types";

export function AdaptiveLearningPanel({ program, recovery }: { program: RevivalProgram; recovery: RecoveryResult }) {
  const [workspace, setWorkspace] = useState<RevivalLearningWorkspace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(true);

  const characters = useMemo(() => Array.from(new Set(recovery.recommendations.flatMap(x => x.recommended_characters))), [recovery]);

  async function load() {
    setPending(true); setError(null);
    try {
      const result = workspace?.program_id === program.program_id ? await getRevivalLearning(program.program_id) : await bootstrapRevivalLearning({
        recovery_job_id: program.recovery_job_id,
        program_id: program.program_id,
        channel_id: program.channel_id,
        characters,
        ideas: recovery.recommendations.map(x => ({
          recommendation_id: x.recommendation_id, title: x.title, concept: x.concept,
          recommended_characters: x.recommended_characters,
        })),
      });
      setWorkspace(result as RevivalLearningWorkspace);
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to initialize adaptive learning."); }
    finally { setPending(false); }
  }

  useEffect(() => { void load(); }, [program.program_id]);

  const verifiedObservations = workspace?.observations.filter(observationDecisionReady).length ?? 0;
  const pendingObservations = (workspace?.observations.length ?? 0) - verifiedObservations;

  const decisions = workspace?.series_registry.reduce<Record<string, number>>((acc, item) => {
    acc[item.decision] = (acc[item.decision] || 0) + 1; return acc;
  }, {}) ?? {};

  return <div className="adaptive-learning-card">
    <button className="adaptive-learning-head" type="button" onClick={() => setOpen(v => !v)}>
      <span className="adaptive-learning-icon"><BrainCircuit size={18} /></span>
      <span className="adaptive-learning-copy">
        <strong>Adaptive learning loop</strong>
        <small>{pending ? "Preparing character + series memory…" : workspace?.learning_summary || "Ready to learn from publishing outcomes."}</small>
      </span>
      {pending ? <LoaderCircle className="spin" size={17} /> : open ? <ChevronUp size={17} /> : <ChevronDown size={17} />}
    </button>
    {open && <div className="adaptive-learning-body">
      {error && <div className="revival-program-error">{error}</div>}
      {workspace && <>
        <div className="adaptive-learning-stats">
          <span><b>{workspace.character_bible.length}</b> persistent characters</span>
          <span><b>{workspace.series_registry.length}</b> series hypotheses</span>
          <span><b>{verifiedObservations}</b> verified learning observations</span>
          {pendingObservations > 0 && <span><b>{pendingObservations}</b> awaiting Analytics or verification</span>}
          <span><b>{decisions.EXPAND || 0}</b> expand</span>
          <span><b>{decisions.REFINE || 0}</b> refine</span>
          <span><b>{decisions.PAUSE || 0}</b> pause</span>
        </div>
        <p className="adaptive-learning-note">The 30-day plan is now a learning program, not a frozen calendar. Verified Analytics can move a series to Expand, Refine, or Pause; subscriber conversion is weighted alongside retention, sharing, and comments. Pending evidence does not count as zero performance.</p>
        {workspace.character_bible.length > 0 && <div className="adaptive-character-row">
          {workspace.character_bible.slice(0, 6).map(c => <span key={c.character_id}>{c.name}</span>)}
        </div>}
      </>}
      <button className="secondary-button" type="button" onClick={() => void load()} disabled={pending}><RefreshCw size={15}/> Refresh learning state</button>
    </div>}
  </div>;
}
