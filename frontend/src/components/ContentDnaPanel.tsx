import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  BadgeCheck,
  BrainCircuit,
  BarChart3,
  ChevronRight,
  Clock3,
  CircleCheckBig,
  Eye,
  Fingerprint,
  Gauge,
  Image as ImageIcon,
  Layers3,
  Network,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Tags,
  UsersRound,
  Wand2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type {
  AnalysisResult,
  CharacterInsight,
  ContentDnaJob,
  ContentDnaResult,
  EvidenceMetrics,
  GroupInsight,
  VideoSnapshot,
} from "../types";

interface ContentDnaPanelProps {
  analysis: AnalysisResult;
  job: ContentDnaJob | null;
  error: string | null;
  onBuild: () => void;
}

type DnaTab = "overview" | "themes" | "characters" | "patterns";

type EvidenceSelection = {
  kind: "theme" | "character" | "story" | "visual" | "association";
  title: string;
  description: string;
  evidence_video_ids: string[];
  evidence: EvidenceMetrics;
  aliases?: string[];
  roles?: string[];
};

const DNA_TERMINAL = new Set(["COMPLETED", "FAILED"]);

export function ContentDnaPanel({ analysis, job, error, onBuild }: ContentDnaPanelProps) {
  const running = Boolean(job && !DNA_TERMINAL.has(job.stage));

  if (!job) {
    return <DnaGate analysis={analysis} error={error} onBuild={onBuild} />;
  }

  if (job.stage === "FAILED") {
    return <DnaFailure job={job} onRetry={onBuild} />;
  }

  if (running) {
    return <DnaProgress job={job} />;
  }

  if (job.stage === "COMPLETED" && job.result) {
    return <DnaDashboard result={job.result} analysis={analysis} />;
  }

  return null;
}

function DnaGate({ analysis, error, onBuild }: { analysis: AnalysisResult; error: string | null; onBuild: () => void }) {
  return (
    <section className="dna-section" id="content-dna">
      <article className="dna-gate glass-card">
        <div className="dna-gate-copy">
          <div className="layer-badge ai"><Sparkles size={15} /> AI interpretation layer</div>
          <span className="eyebrow">Milestone 1C.7 · Content DNA</span>
          <h2>We know how the channel performed. Now let Gemini understand what the content means.</h2>
          <p>
            ReviveAI starts with a representative, recency-weighted sample from {analysis.summary.retrieved_videos} public videos so your first Content DNA is ready much sooner. It then connects those content patterns back to the evidence layer you already verified.
          </p>

          <div className="dna-method-chips">
            <span><Eye size={15} /> Multimodal thumbnails</span>
            <span><ShieldCheck size={15} /> Performance hidden from Gemini</span>
            <span><Network size={15} /> Evidence-linked insights</span>
            <span><Gauge size={15} /> Fast DNA sampling</span>
          </div>

          {error && (
            <div className="dna-inline-error" role="alert">
              <AlertTriangle size={18} />
              <div>
                <strong>Content DNA is not ready to start</strong>
                <span>{error}</span>
              </div>
            </div>
          )}

          <button type="button" className="primary-button dna-build-button" onClick={onBuild}>
            <Wand2 size={18} /> Build Content DNA <ChevronRight size={17} />
          </button>
        </div>

        <div className="dna-gate-proof">
          <div className="proof-head">
            <span>Evidence ready</span>
            <CircleCheckBig size={22} />
          </div>
          <ProofMetric label="Public videos" value={formatInteger(analysis.summary.retrieved_videos)} helper="ready for classification" />
          <ProofMetric label="Channel median" value={`${formatViews(analysis.metrics.views.median)} views`} helper="kept outside Gemini prompts" />
          <ProofMetric label="Exceptional set" value={`${tierCount(analysis, "exceptional")} videos`} helper="connected only after classification" />
          <div className="blind-analysis-note">
            <Fingerprint size={18} />
            <div>
              <strong>Blind content analysis</strong>
              <span>Gemini never receives views, likes, comments, or performance tiers while classifying content.</span>
            </div>
          </div>
        </div>
      </article>
    </section>
  );
}

type RecentProgressItem = {
  video_id: string;
  title: string;
  thumbnail_url?: string | null;
  themes: string[];
  confidence: number;
  visual_evidence_available: boolean;
};

function DnaProgress({ job }: { job: ContentDnaJob }) {
  const steps = [
    ["PREPARING_EVIDENCE", "Prepare evidence"],
    ["ANALYZING_VIDEOS", "Understand videos"],
    ["SYNTHESIZING_DNA", "Build channel DNA"],
    ["CONNECTING_PERFORMANCE", "Connect evidence"],
  ] as const;
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const stageIndex = Math.max(0, steps.findIndex(([key]) => key === job.stage));
  const analyzed = Number(job.detail.videos_analyzed ?? job.progress_current ?? 0);
  const total = Math.max(0, Number(job.progress_total ?? 0));
  const archiveTotal = Math.max(total, Number(job.detail.archive_total ?? total));
  const fastDna = Boolean(job.detail.fast_dna) || archiveTotal > total;
  const visuals = Number(job.detail.visuals_analyzed ?? 0);
  const calls = Number(job.detail.gemini_calls ?? 0);
  const remaining = Math.max(0, Number(job.detail.videos_remaining ?? total - analyzed));
  const batchIndex = Number(job.detail.batch_index ?? 0);
  const batchTotal = Number(job.detail.batch_total ?? 0);
  const synthesisStep = Number(job.detail.synthesis_step ?? 0);
  const synthesisTotal = Math.max(1, Number(job.detail.synthesis_total ?? 4));
  const resumed = Boolean(job.detail.checkpoint_reused);
  const recentItems = parseRecentProgressItems(job.detail.recent_items);
  const overallPercent = contentDnaOverallPercent(job, analyzed, total, synthesisStep, synthesisTotal);
  const videoPercent = total ? Math.min(100, Math.round((analyzed / total) * 100)) : 0;
  const elapsedSeconds = Math.max(0, Math.floor((now - Date.parse(job.created_at)) / 1000));
  const etaSeconds = job.stage === "ANALYZING_VIDEOS" && analyzed > 0 && remaining > 0 && !resumed
    ? Math.round((elapsedSeconds / analyzed) * remaining)
    : null;

  return (
    <section className="dna-section" id="content-dna" aria-live="polite">
      <article className="dna-progress-card dna-progress-card-v2 glass-card">
        <div className="dna-progress-header">
          <div className="dna-orb" aria-hidden="true">
            <BrainCircuit size={34} />
          </div>
          <div className="dna-progress-main">
            <div className="layer-badge ai"><Sparkles size={15} /> Gemini multimodal analysis</div>
            <span className="eyebrow">Building Content DNA</span>
            <h2>{job.message}</h2>
            <p>
              {fastDna
                ? `ReviveAI selected ${formatInteger(total)} representative videos from the ${formatInteger(archiveTotal)}-video archive for a faster initial DNA. Progress advances only when real analysis completes.`
                : "ReviveAI is doing real content analysis in batches. The progress below advances only when a batch or synthesis step is actually completed."}
            </p>
          </div>
          <div className="dna-percent-card" aria-label={`${overallPercent}% complete`}>
            <strong>{overallPercent}%</strong>
            <span>overall</span>
          </div>
        </div>

        <div className="dna-overall-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={overallPercent}>
          <div className="dna-overall-progress-fill" style={{ width: `${overallPercent}%` }} />
        </div>

        <div className="dna-stage-track">
          {steps.map(([key, label], index) => {
            const state = index < stageIndex ? "done" : index === stageIndex ? "active" : "pending";
            return (
              <div className={`dna-stage-step ${state}`} key={key}>
                <span>{state === "done" ? <CircleCheckBig size={16} /> : index + 1}</span>
                <strong>{label}</strong>
              </div>
            );
          })}
        </div>

        <div className="dna-progress-metrics">
          <ProgressFact label={fastDna ? "Fast DNA sample" : "Videos understood"} value={`${formatInteger(analyzed)} / ${formatInteger(total)}`} helper={fastDna ? `${formatInteger(archiveTotal)} videos in archive` : `${videoPercent}% of archive`} />
          <ProgressFact label="Remaining" value={formatInteger(remaining)} helper={batchTotal ? `batch ${Math.max(1, batchIndex)} of ${batchTotal}` : "preparing batches"} />
          <ProgressFact label="Elapsed" value={formatDuration(elapsedSeconds)} helper={etaSeconds ? `≈ ${formatDuration(etaSeconds)} classification time left` : resumed ? "saved classifications reused" : "live runtime"} />
          <ProgressFact label="Gemini calls" value={formatInteger(calls)} helper={`${formatInteger(visuals)} thumbnails read`} />
        </div>

        {job.stage === "ANALYZING_VIDEOS" && (
          <div className="dna-live-analysis">
            <div className="dna-live-heading">
              <div>
                <span className="eyebrow"><Activity size={14} /> Live analysis</span>
                <h3>{resumed ? "Saved classifications restored" : "Latest completed batch"}</h3>
              </div>
              <span className="dna-live-status"><span /> {resumed ? "Checkpoint reused" : fastDna ? "Processing representative sample" : "Processing archive"}</span>
            </div>
            {recentItems.length ? (
              <div className="dna-live-items">
                {recentItems.map((item) => (
                  <article className="dna-live-item" key={item.video_id}>
                    <div className="dna-live-thumb">
                      {item.thumbnail_url ? <img src={item.thumbnail_url} alt="" /> : <ImageIcon size={20} />}
                    </div>
                    <div className="dna-live-copy">
                      <strong>{item.title}</strong>
                      <div className="dna-live-themes">
                        {(item.themes.length ? item.themes : ["Classification complete"]).slice(0, 2).map((theme) => <span key={theme}>{theme}</span>)}
                      </div>
                    </div>
                    <span className="dna-live-confidence">{formatPercent(item.confidence)}</span>
                  </article>
                ))}
              </div>
            ) : (
              <div className="dna-live-empty"><Clock3 size={18} /> The first batch is being prepared. Results will appear here after Gemini completes it.</div>
            )}
          </div>
        )}

        {job.stage === "SYNTHESIZING_DNA" && (
          <div className="dna-synthesis-live">
            <div className="dna-live-heading">
              <div>
                <span className="eyebrow"><Network size={14} /> Channel synthesis</span>
                <h3>Turning individual classifications into a reusable Content DNA</h3>
              </div>
              <span className="dna-live-status"><span /> {synthesisStep}/{synthesisTotal} synthesis steps complete</span>
            </div>
            <div className="dna-synthesis-steps">
              {["Identity & voice", "Themes", "Characters", "Story & visual grammar"].map((label, index) => {
                const number = index + 1;
                const state = number <= synthesisStep ? "done" : number === synthesisStep + 1 ? "active" : "pending";
                return <div key={label} className={`dna-synthesis-step ${state}`}><span>{state === "done" ? <CircleCheckBig size={15} /> : number}</span><strong>{label}</strong></div>;
              })}
            </div>
            {resumed && <div className="dna-checkpoint-note"><RefreshCw size={16} /> Video classifications were restored from the previous run, so ReviveAI skipped reprocessing the archive.</div>}
          </div>
        )}

        <div className="dna-progress-trust dna-progress-trust-wide">
          <ShieldCheck size={20} />
          <div>
            <strong>Performance firewall active</strong>
            <span>View counts and performance tiers are not included in Gemini classification prompts. They are connected only after Content DNA is complete.</span>
          </div>
        </div>
      </article>
    </section>
  );
}

function DnaFailure({ job, onRetry }: { job: ContentDnaJob; onRetry: () => void }) {
  const total = Number(job.progress_total ?? 0);
  const processed = Number(job.progress_current ?? 0);
  const synthesisStarted = Number(job.detail.synthesis_step ?? 0) >= 0 && processed >= total && total > 0;
  const error = job.error || "Content DNA could not be completed.";

  return (
    <section className="dna-section" id="content-dna">
      <article className="dna-failure glass-card" role="alert">
        <div className="dna-failure-icon"><AlertTriangle size={25} /></div>
        <div>
          <span className="eyebrow">Content DNA paused</span>
          <h2>Gemini could not finish this pass, but you can resume safely.</h2>
          <p>{error}</p>
          {synthesisStarted && (
            <div className="dna-failure-checkpoint">
              <CircleCheckBig size={17} />
              <div>
                <strong>{formatInteger(processed)} video classifications are reusable</strong>
                <span>Your completed classifications are checkpointed on disk. M1C.7 reuses the M1C.6 stage checkpoints and also checkpoints each completed synthesis stage, so Resume continues from the first unfinished step instead of repeating successful work.</span>
              </div>
            </div>
          )}
          <button type="button" className="secondary-button" onClick={onRetry}><RefreshCw size={16} /> Resume Content DNA</button>
        </div>
      </article>
    </section>
  );
}

function DnaDashboard({ result, analysis }: { result: ContentDnaResult; analysis: AnalysisResult }) {
  const [tab, setTab] = useState<DnaTab>("overview");
  const [evidenceSelection, setEvidenceSelection] = useState<EvidenceSelection | null>(null);
  const channelMedian = analysis.metrics.views.median;
  const strongestThemes = useMemo(
    () => [...result.themes]
      .filter((theme) => theme.evidence.video_count >= 3 && theme.evidence.relative_to_channel_median != null)
      .sort((a, b) => (b.evidence.relative_to_channel_median || 0) - (a.evidence.relative_to_channel_median || 0))
      .slice(0, 3),
    [result.themes],
  );

  const inspectGroup = (group: GroupInsight, kind: EvidenceSelection["kind"] = "theme") => {
    setEvidenceSelection({
      kind,
      title: group.name,
      description: group.description,
      evidence_video_ids: group.evidence_video_ids,
      evidence: group.evidence,
    });
  };

  const inspectCharacter = (character: CharacterInsight) => {
    setEvidenceSelection({
      kind: "character",
      title: character.name,
      description: character.description,
      evidence_video_ids: character.evidence_video_ids,
      evidence: character.evidence,
      aliases: character.aliases,
      roles: character.roles,
    });
  };

  return (
    <section className="dna-section dna-ready" id="content-dna">
      <div className="dna-section-heading">
        <div>
          <div className="layer-badge ai"><Sparkles size={15} /> AI interpretation layer</div>
          <span className="eyebrow">Milestone 1C.7 complete</span>
          <h2>Content DNA</h2>
          <p>Gemini understood the content first. ReviveAI then attached verified performance evidence afterward.</p>
        </div>
        <div className="dna-model-chip"><BrainCircuit size={16} /> {result.model}</div>
      </div>

      <article className="dna-identity-hero glass-card">
        <div className="dna-identity-main">
          <span className="dna-kicker">{analysis.channel.title}</span>
          <h3>{result.identity.primary_niche}</h3>
          <p>{result.identity.summary}</p>
          <div className="identity-confidence" title="Model-estimated confidence based on consistency across the analyzed archive; not a measured audience metric.">
            <BadgeCheck size={16} /> AI confidence <strong>{confidenceBand(result.identity.confidence)}</strong>
          </div>
        </div>
        <div className="dna-identity-stats">
          <DnaStat icon={<Layers3 size={18} />} label="Videos classified" value={`${result.videos_classified}`} helper={`${result.unclassified_videos} unclassified`} />
          <DnaStat icon={<ImageIcon size={18} />} label="Visual evidence" value={`${result.visuals_analyzed}`} helper={`${result.metadata_only_videos} metadata-only`} />
          <DnaStat icon={<Network size={18} />} label="Recurring themes" value={`${result.themes.length}`} helper="evidence-linked" />
          <DnaStat icon={<UsersRound size={18} />} label="Characters" value={`${result.characters.length}`} helper="channel universe" />
        </div>
      </article>

      <div className="dna-method-ribbon">
        <div><span>1</span><strong>Classify blind</strong><small>No performance data</small></div>
        <ChevronRight size={18} />
        <div><span>2</span><strong>Synthesize DNA</strong><small>Normalize recurring patterns</small></div>
        <ChevronRight size={18} />
        <div><span>3</span><strong>Connect evidence</strong><small>Backend joins M1B.2 metrics</small></div>
      </div>

      <nav className="dna-tabs" aria-label="Content DNA sections">
        {([
          ["overview", "Overview"],
          ["themes", "Themes"],
          ["characters", "Characters"],
          ["patterns", "Patterns"],
        ] as Array<[DnaTab, string]>).map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={tab === key ? "active" : undefined}
            aria-pressed={tab === key}
            onClick={() => setTab(key)}
          >
            <span className="tab-dot" /> {label}
          </button>
        ))}
      </nav>

      {tab === "overview" && (
        <div className="dna-tab-panel">
          <div className="identity-grid">
            <IdentityFact label="Content promise" value={result.identity.content_promise} />
            <IdentityFact label="Dominant format" value={result.identity.dominant_format} />
            <IdentityFact label="Language style" value={result.identity.language_style} />
            <IdentityFact label="Analysis coverage" value={`${result.videos_classified}/${result.video_classifications.length} videos`} />
          </div>

          <div className="dna-overview-grid">
            <article className="dna-card glass-card">
              <div className="dna-card-heading">
                <div>
                  <span className="eyebrow">Voice & tone</span>
                  <h3>How this channel communicates</h3>
                </div>
                <Tags size={19} />
              </div>
              <div className="tone-list">
                {result.voice_tone.slice(0, 6).map((tone) => (
                  <div className="tone-row" key={tone.label}>
                    <div className="tone-row-copy">
                      <strong>{tone.label}</strong>
                      <span>{tone.explanation}</span>
                    </div>
                    <div className="tone-confidence" title={`Internal model confidence: ${formatPercent(tone.confidence)}. Shown as a qualitative band to avoid implying calibrated probability.`}>
                      <span>{confidenceSignalLabel(tone.confidence)}</span>
                      <div aria-hidden="true"><i style={{ width: `${Math.round(tone.confidence * 100)}%` }} /></div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="ai-estimate-note">Signal labels are model estimates, not calibrated probabilities or measured audience metrics.</div>
            </article>

            <article className="dna-card glass-card">
              <div className="dna-card-heading">
                <div>
                  <span className="eyebrow">Observed associations</span>
                  <h3>Patterns worth investigating</h3>
                </div>
                <BarChart3 size={19} />
              </div>
              <div className="association-list">
                {(strongestThemes.length ? strongestThemes : result.themes.slice(0, 3)).map((theme) => (
                  <AssociationRow key={theme.name} group={theme} channelMedian={channelMedian} onInspect={() => inspectGroup(theme, "association")} />
                ))}
              </div>
              <div className="association-caution">
                <ShieldCheck size={15} /> Historical association only. ReviveAI does not claim these patterns caused the views.
              </div>
            </article>
          </div>

          <article className="methodology-card glass-card">
            <div className="methodology-icon"><Fingerprint size={23} /></div>
            <div>
              <span className="eyebrow">Why this is explainable</span>
              <h3>Content understanding and performance measurement stay separate.</h3>
              <p>{result.methodology_notice}</p>
            </div>
            <div className="methodology-mini-stats">
              <span><strong>{result.gemini_calls}</strong> Gemini calls</span>
              <span><strong>{result.visuals_analyzed}</strong> thumbnails read</span>
            </div>
          </article>
        </div>
      )}

      {tab === "themes" && (
        <div className="dna-tab-panel">
          <PanelIntro icon={<Network size={20} />} eyebrow="Theme map" title="Recurring subjects, connected to measured performance" text="Gemini defines the themes; ReviveAI calculates the numbers. Themes are non-exclusive, so one video can support multiple themes." />
          <div className="nonexclusive-note"><Layers3 size={15} /><span><strong>Overlapping classification:</strong> theme counts are not intended to sum to the 89-video archive total.</span></div>
          <div className="theme-grid">
            {result.themes.map((theme) => <GroupCard key={theme.name} group={theme} onInspect={() => inspectGroup(theme, "theme")} />)}
          </div>
        </div>
      )}

      {tab === "characters" && (
        <div className="dna-tab-panel">
          <PanelIntro icon={<UsersRound size={20} />} eyebrow="Character universe" title="Who keeps appearing in the channel?" text="Character names are used only when public text or thumbnails support them. Roles are consolidated across appearances." />
          {result.characters.length ? (
            <div className="character-grid">
              {result.characters.map((character) => <CharacterCard key={character.name} character={character} onInspect={() => inspectCharacter(character)} />)}
            </div>
          ) : (
            <EmptyDnaState title="No recurring named characters were confidently identified." />
          )}
        </div>
      )}

      {tab === "patterns" && (
        <div className="dna-tab-panel">
          <PanelIntro icon={<Fingerprint size={20} />} eyebrow="Story & visual grammar" title="The repeatable formulas behind the archive" text="These are recurring, non-exclusive structures and visible motifs. One video can support several patterns; none imply audience preference by themselves." />
          <div className="nonexclusive-note"><Layers3 size={15} /><span><strong>Overlapping classification:</strong> story and visual pattern counts can overlap across the same source videos.</span></div>
          <div className="patterns-columns">
            <PatternColumn title="Story patterns" icon={<Layers3 size={18} />} groups={result.story_patterns} kind="story" onInspect={inspectGroup} />
            <PatternColumn title="Visual patterns" icon={<Eye size={18} />} groups={result.visual_patterns} kind="visual" onInspect={inspectGroup} />
          </div>
        </div>
      )}

      {evidenceSelection && (
        <EvidenceDrawer
          selection={evidenceSelection}
          analysis={analysis}
          onClose={() => setEvidenceSelection(null)}
        />
      )}
    </section>
  );
}
function ProofMetric({ label, value, helper }: { label: string; value: string; helper: string }) {
  return <div className="proof-metric"><span>{label}</span><strong>{value}</strong><small>{helper}</small></div>;
}

function ProgressFact({ label, value, helper }: { label: string; value: string; helper?: string }) {
  return <div><span>{label}</span><strong>{value}</strong>{helper ? <small>{helper}</small> : null}</div>;
}

function DnaStat({ icon, label, value, helper }: { icon: ReactNode; label: string; value: string; helper: string }) {
  return (
    <div className="dna-stat">
      <div className="dna-stat-icon">{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{helper}</small>
    </div>
  );
}

function IdentityFact({ label, value }: { label: string; value: string }) {
  return <div className="identity-fact"><span>{label}</span><strong>{value}</strong></div>;
}

function AssociationRow({ group, channelMedian, onInspect }: { group: GroupInsight; channelMedian?: number | null; onInspect: () => void }) {
  const evidence = group.evidence;
  return (
    <div className="association-row">
      <div>
        <strong>{group.name}</strong>
        <span>{evidence.video_count} supporting videos · {evidence.performance_signal}</span>
        <small className={`sample-strength ${sampleStrengthClass(evidence.sample_strength)}`}>{evidence.sample_strength}</small>
      </div>
      <div className="association-metric">
        <strong>{formatViews(evidence.median_views)}</strong>
        <span>{formatRatio(evidence.relative_to_channel_median)} median</span>
      </div>
      <MiniEvidenceStrip videos={evidence.sample_videos.slice(0, 3)} />
      <button type="button" className="inspect-evidence-button compact" onClick={onInspect}>View evidence</button>
      {channelMedian ? <span className="sr-only">Channel median {channelMedian} views.</span> : null}
    </div>
  );
}

function GroupCard({ group, onInspect }: { group: GroupInsight; onInspect: () => void }) {
  return (
    <article className="group-card glass-card">
      <div className="group-card-head">
        <div>
          <div className="signal-stack">
            <span className={`signal-pill ${signalClass(group.evidence.performance_signal)}`}>{group.evidence.performance_signal}</span>
            <span className={`sample-strength ${sampleStrengthClass(group.evidence.sample_strength)}`}>{group.evidence.sample_strength}</span>
          </div>
          <h3>{group.name}</h3>
        </div>
        <div className="group-count"><strong>{group.evidence.video_count}</strong><span>videos</span></div>
      </div>
      <p>{group.description}</p>
      <div className="group-metrics">
        <MetricCell label="Median views" value={formatViews(group.evidence.median_views)} />
        <MetricCell label="vs channel median" value={formatRatio(group.evidence.relative_to_channel_median)} />
        <MetricCell label="Exceptional" value={`${group.evidence.exceptional_count}`} />
        <MetricCell label="Typical" value={`${group.evidence.typical_count}`} />
      </div>
      {group.evidence.exceptional_vs_typical_lift != null && (
        <div className="lift-note"><Gauge size={15} /> Appears {formatRatio(group.evidence.exceptional_vs_typical_lift)} more often in the exceptional set than the typical set.</div>
      )}
      <EvidenceStrip videos={group.evidence.sample_videos} />
      <button type="button" className="inspect-evidence-button" onClick={onInspect}>Inspect all {group.evidence.video_count} supporting videos <ChevronRight size={14} /></button>
    </article>
  );
}

function CharacterCard({ character, onInspect }: { character: CharacterInsight; onInspect: () => void }) {
  return (
    <article className="character-card glass-card">
      <div className="character-head">
        <div className="character-avatar"><UsersRound size={20} /></div>
        <div>
          <h3>{character.name}</h3>
          <span>{character.evidence.video_count} appearances identified</span>
        </div>
      </div>
      <p>{character.description}</p>
      {character.aliases.length > 0 && (
        <div className="character-aliases"><span>Also seen as</span><strong>{character.aliases.slice(0, 3).join(", ")}</strong></div>
      )}
      {character.roles.length > 0 && (
        <div className="role-chips">{character.roles.slice(0, 6).map((role) => <span key={role}>{role}</span>)}</div>
      )}
      <div className="character-performance">
        <MetricCell label="Median views" value={formatViews(character.evidence.median_views)} />
        <MetricCell label="Channel baseline" value={formatRatio(character.evidence.relative_to_channel_median)} />
      </div>
      <div className="character-signal-row">
        <span className={`sample-strength ${sampleStrengthClass(character.evidence.sample_strength)}`}>{character.evidence.sample_strength}</span>
        <span className={`signal-pill ${signalClass(character.evidence.performance_signal)}`}>{character.evidence.performance_signal}</span>
      </div>
      <EvidenceStrip videos={character.evidence.sample_videos} />
      <button type="button" className="inspect-evidence-button" onClick={onInspect}>Inspect character evidence <ChevronRight size={14} /></button>
    </article>
  );
}

function PatternColumn({ title, icon, groups, kind, onInspect }: { title: string; icon: ReactNode; groups: GroupInsight[]; kind: "story" | "visual"; onInspect: (group: GroupInsight, kind: EvidenceSelection["kind"]) => void }) {
  return (
    <article className="pattern-column glass-card">
      <div className="pattern-column-head"><div className="metric-icon">{icon}</div><h3>{title}</h3></div>
      <div className="pattern-list">
        {groups.map((group) => (
          <div className="pattern-item" key={group.name}>
            <div className="pattern-copy">
              <strong>{group.name}</strong>
              <span>{group.description}</span>
              <div className="pattern-signal-row">
                <small className={`sample-strength ${sampleStrengthClass(group.evidence.sample_strength)}`}>{group.evidence.sample_strength}</small>
                <small className={`signal-pill ${signalClass(group.evidence.performance_signal)}`}>{group.evidence.performance_signal}</small>
              </div>
            </div>
            <div className="pattern-stats">
              <span>{group.evidence.video_count} videos</span>
              <strong>{formatRatio(group.evidence.relative_to_channel_median)} median</strong>
            </div>
            <MiniEvidenceStrip videos={group.evidence.sample_videos.slice(0, 3)} />
            <button type="button" className="inspect-evidence-icon" onClick={() => onInspect(group, kind)} aria-label={`Inspect evidence for ${group.name}`} title="Inspect evidence"><ChevronRight size={15} /></button>
          </div>
        ))}
      </div>
    </article>
  );
}

function EvidenceDrawer({ selection, analysis, onClose }: { selection: EvidenceSelection; analysis: AnalysisResult; onClose: () => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };

    const scrollY = window.scrollY;
    const body = document.body;
    const html = document.documentElement;
    const previousBody = {
      overflow: body.style.overflow,
      position: body.style.position,
      top: body.style.top,
      width: body.style.width,
    };
    const previousHtmlOverflow = html.style.overflow;

    // iOS and several mobile browsers can still scroll the page when only
    // overflow:hidden is applied. Pinning the body preserves the current
    // scroll position and makes the modal evidence surface own the viewport.
    body.style.overflow = "hidden";
    body.style.position = "fixed";
    body.style.top = `-${scrollY}px`;
    body.style.width = "100%";
    html.style.overflow = "hidden";
    body.classList.add("evidence-modal-open");

    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      body.classList.remove("evidence-modal-open");
      body.style.overflow = previousBody.overflow;
      body.style.position = previousBody.position;
      body.style.top = previousBody.top;
      body.style.width = previousBody.width;
      html.style.overflow = previousHtmlOverflow;
      window.scrollTo(0, scrollY);
    };
  }, [onClose]);

  const videos = supportingVideos(selection.evidence_video_ids, analysis);
  const evidence = selection.evidence;

  return createPortal(
    <div className="evidence-drawer-layer" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <aside className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-drawer-title">
        <div className="evidence-drawer-head">
          <div>
            <span className="eyebrow">Traceable evidence</span>
            <h3 id="evidence-drawer-title">{selection.title}</h3>
          </div>
          <button type="button" className="evidence-drawer-close" onClick={onClose} autoFocus aria-label="Close evidence drawer"><X size={19} /></button>
        </div>

        <p className="evidence-drawer-description">{selection.description}</p>
        {selection.aliases?.length ? (
          <div className="evidence-aliases"><span>Canonical identity aliases</span><strong>{selection.aliases.slice(0, 4).join(", ")}</strong></div>
        ) : null}
        {selection.roles?.length ? <div className="role-chips evidence-drawer-roles">{selection.roles.slice(0, 8).map((role) => <span key={role}>{role}</span>)}</div> : null}

        <div className="evidence-trust-row">
          <span className={`sample-strength ${sampleStrengthClass(evidence.sample_strength)}`}>{evidence.sample_strength}</span>
          <span className={`signal-pill ${signalClass(evidence.performance_signal)}`}>{evidence.performance_signal}</span>
        </div>

        <div className="evidence-drawer-metrics">
          <MetricCell label="Supporting videos" value={`${evidence.video_count}`} />
          <MetricCell label="Median views" value={formatViews(evidence.median_views)} />
          <MetricCell label="vs channel median" value={formatRatio(evidence.relative_to_channel_median)} />
        </div>

        <div className="evidence-tier-summary">
          <div><span className="tier-dot exceptional" /><strong>{evidence.exceptional_count}</strong><small>Exceptional</small></div>
          <div><span className="tier-dot strong" /><strong>{evidence.strong_count}</strong><small>Strong</small></div>
          <div><span className="tier-dot typical" /><strong>{evidence.typical_count}</strong><small>Typical</small></div>
          <div><span className="tier-dot low" /><strong>{evidence.lower_quartile_count}</strong><small>Lower quartile</small></div>
        </div>

        <div className="evidence-drawer-note"><ShieldCheck size={15} /><span>Performance is attached after Gemini classification. This is historical association, not evidence that the content pattern caused the views.</span></div>

        <div className="evidence-drawer-list-head">
          <div><span className="eyebrow">Supporting archive</span><h4>{videos.length} source videos</h4></div>
          <span>Sorted by public lifetime views</span>
        </div>
        <div className="evidence-drawer-list">
          {videos.map(({ video, tier }) => {
            const thumb = video.thumbnails.medium || video.thumbnails.high || video.thumbnails.default;
            return (
              <a className="evidence-drawer-video" href={video.watch_url} target="_blank" rel="noreferrer" key={video.video_id}>
                <div className="evidence-drawer-thumb">{thumb ? <img src={thumb} alt="" loading="lazy" /> : <ImageIcon size={20} />}</div>
                <div className="evidence-drawer-video-copy">
                  <strong>{video.title}</strong>
                  <span>{formatViews(video.view_count)} views · <i className={`evidence-tier-text ${tier}`}>{tierLabel(tier)}</i></span>
                </div>
                <ArrowUpRight size={15} />
              </a>
            );
          })}
        </div>
      </aside>
    </div>,
    document.body,
  );
}

function PanelIntro({ icon, eyebrow, title, text }: { icon: ReactNode; eyebrow: string; title: string; text: string }) {
  return (
    <div className="dna-panel-intro">
      <div className="panel-intro-icon">{icon}</div>
      <div><span className="eyebrow">{eyebrow}</span><h3>{title}</h3><p>{text}</p></div>
    </div>
  );
}

function EvidenceStrip({ videos }: { videos: EvidenceMetrics["sample_videos"] }) {
  if (!videos.length) return <div className="no-evidence-strip">No source thumbnails available.</div>;
  return (
    <div className="evidence-strip">
      {videos.map((video) => (
        <a href={video.watch_url} target="_blank" rel="noreferrer" key={video.video_id} title={`${video.title} · ${formatViews(video.views)} views`}>
          {video.thumbnail_url ? <img src={video.thumbnail_url} alt="" loading="lazy" /> : <div className="evidence-thumb-placeholder" />}
          <span className={`evidence-tier-dot ${video.performance_tier}`} />
          <ArrowUpRight size={13} />
        </a>
      ))}
    </div>
  );
}

function MiniEvidenceStrip({ videos }: { videos: EvidenceMetrics["sample_videos"] }) {
  if (!videos.length) return null;
  return (
    <div className="mini-evidence-strip" aria-label="Supporting videos">
      {videos.map((video) => (
        <a href={video.watch_url} target="_blank" rel="noreferrer" key={video.video_id} title={video.title}>
          {video.thumbnail_url ? <img src={video.thumbnail_url} alt="" loading="lazy" /> : <span />}
        </a>
      ))}
    </div>
  );
}

function MetricCell({ label, value }: { label: string; value: string }) {
  return <div className="metric-cell"><span>{label}</span><strong>{value}</strong></div>;
}

function EmptyDnaState({ title }: { title: string }) {
  return <div className="dna-empty glass-card"><UsersRound size={24} /><strong>{title}</strong><span>ReviveAI will keep this empty instead of inventing unsupported identities.</span></div>;
}

function tierCount(analysis: AnalysisResult, key: string): number {
  return analysis.metrics.performance_tiers.find((tier) => tier.key === key)?.count || 0;
}

function formatViews(value?: number | null): string {
  if (value == null) return "—";
  return Math.round(value).toLocaleString();
}

function parseRecentProgressItems(value: unknown): RecentProgressItem[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const raw = item as Record<string, unknown>;
    const videoId = typeof raw.video_id === "string" ? raw.video_id : "";
    const title = typeof raw.title === "string" ? raw.title : "Untitled video";
    if (!videoId) return [];
    return [{
      video_id: videoId,
      title,
      thumbnail_url: typeof raw.thumbnail_url === "string" ? raw.thumbnail_url : null,
      themes: Array.isArray(raw.themes) ? raw.themes.filter((theme): theme is string => typeof theme === "string") : [],
      confidence: typeof raw.confidence === "number" ? raw.confidence : 0,
      visual_evidence_available: Boolean(raw.visual_evidence_available),
    }];
  });
}

function contentDnaOverallPercent(job: ContentDnaJob, analyzed: number, total: number, synthesisStep: number, synthesisTotal: number) {
  if (job.stage === "QUEUED") return 1;
  if (job.stage === "PREPARING_EVIDENCE") return 4;
  if (job.stage === "ANALYZING_VIDEOS") {
    const ratio = total > 0 ? analyzed / total : 0;
    return Math.min(75, Math.round(5 + ratio * 70));
  }
  if (job.stage === "SYNTHESIZING_DNA") {
    return Math.min(95, Math.round(75 + (synthesisStep / Math.max(1, synthesisTotal)) * 20));
  }
  if (job.stage === "CONNECTING_PERFORMANCE") return 98;
  if (job.stage === "COMPLETED") return 100;
  return Math.min(99, Math.max(0, Math.round((analyzed / Math.max(1, total)) * 75)));
}

function formatDuration(totalSeconds: number) {
  const seconds = Math.max(0, Math.round(totalSeconds));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  if (minutes < 60) return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return mins ? `${hours}h ${mins}m` : `${hours}h`;
}

function formatInteger(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return Math.round(value).toLocaleString();
}

function formatRatio(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value >= 10) return `${value.toFixed(0)}×`;
  return `${value.toFixed(1)}×`;
}

function formatPercent(value?: number | null): string {
  if (value == null) return "—";
  return `${Math.round(value * 100)}%`;
}

function confidenceBand(value?: number | null): string {
  if (value == null) return "Unknown";
  if (value >= 0.85) return "High";
  if (value >= 0.65) return "Moderate";
  return "Low";
}

function confidenceSignalLabel(value?: number | null): string {
  const band = confidenceBand(value);
  if (band === "High") return "Strong signal";
  if (band === "Moderate") return "Moderate signal";
  if (band === "Low") return "Tentative signal";
  return "Unknown";
}

function sampleStrengthClass(value: string): string {
  if (value.startsWith("Broad")) return "broad";
  if (value.startsWith("Developing")) return "developing";
  if (value.startsWith("Emerging")) return "emerging";
  return "limited";
}

function supportingVideos(ids: string[], analysis: AnalysisResult): Array<{ video: VideoSnapshot; tier: string }> {
  const wanted = new Set(ids);
  return analysis.videos
    .filter((video) => wanted.has(video.video_id))
    .map((video) => ({ video, tier: videoPerformanceTier(video, analysis) }))
    .sort((a, b) => (b.video.view_count || 0) - (a.video.view_count || 0));
}

function videoPerformanceTier(video: VideoSnapshot, analysis: AnalysisResult): string {
  const views = video.view_count;
  const { p25, p75, p90 } = analysis.metrics.views;
  if (views == null || p25 == null || p75 == null || p90 == null) return "unknown";
  if (views >= p90) return "exceptional";
  if (views >= p75) return "strong";
  if (views >= p25) return "typical";
  return "low";
}

function tierLabel(tier: string): string {
  if (tier === "low") return "Lower quartile";
  if (tier === "exceptional") return "Exceptional";
  if (tier === "strong") return "Strong";
  if (tier === "typical") return "Typical";
  return "Unknown tier";
}

function signalClass(signal: string): string {
  if (signal.startsWith("Above")) return "positive";
  if (signal.startsWith("Below")) return "negative";
  if (signal.startsWith("Near")) return "neutral";
  return "limited";
}
