import { AlertTriangle, BadgeCheck, Captions, Check, Download, Film, Music2, PlayCircle, ShieldCheck, Sparkles } from "lucide-react";
import { assemblyAssetUrl } from "../api";
import type { FinalAssemblyJob, MediaStudioJob } from "../types";

interface Props {
  mediaJob: MediaStudioJob | null;
  job: FinalAssemblyJob | null;
  error: string | null;
  resumePending?: boolean;
  onStart: () => void;
  onApprove: () => void;
}

const RUNNING = new Set(["QUEUED", "PREPARING", "RENDERING"]);

export function FinalAssemblyPanel({ mediaJob, job, error, resumePending = false, onStart, onApprove }: Props) {
  const ready = mediaJob?.stage === "READY_FOR_ASSEMBLY" && Boolean(mediaJob.result?.assembly_ready);
  if (!ready && !job) return null;

  if (!job) return <AssemblyGate mediaJob={mediaJob} error={error} resumePending={resumePending} onStart={onStart} />;
  if (RUNNING.has(job.stage)) return <AssemblyProgress job={job} />;
  if (job.stage === "FAILED") return <AssemblyFailure job={job} error={error} onStart={onStart} />;
  if ((job.stage === "COMPLETED" || job.stage === "DELIVERED") && job.result) {
    return <AssemblyReview job={job} onApprove={onApprove} />;
  }
  return null;
}

function AssemblyGate({ mediaJob, error, resumePending, onStart }: { mediaJob: MediaStudioJob | null; error: string | null; resumePending: boolean; onStart: () => void }) {
  const result = mediaJob?.result;
  if (!result) return null;
  return (
    <section className="assembly-section" id="final-assembly">
      <article className="assembly-gate glass-card">
        <div className="assembly-gate-icon"><Film size={28} /></div>
        <div>
          <div className="layer-badge media"><Sparkles size={15} /> Final assembly layer</div>
          <span className="eyebrow">Milestone M2C.1.2 · Final Assembly Studio</span>
          <h2>Turn the approved Veo shots into one review-ready Short.</h2>
          <p>
            ReviveAI trims each approved clip to the storyboard timing, normalizes the portrait master, sequences the shots, burns approved on-screen text, and preserves the publishing package for delivery.
          </p>
          <div className="assembly-gate-points">
            <span><ShieldCheck size={16} /> {result.approved_clips}/{result.required_clips} Veo clips approved</span>
            <span><Film size={16} /> Exact storyboard timing</span>
            <span><Captions size={16} /> Title-safe on-screen text</span>
            <span><Music2 size={16} /> Audio direction retained for final mix</span>
          </div>
          <button className="primary-button" onClick={onStart} disabled={resumePending}>
            {resumePending ? <><Film size={17} /> Checking saved final assembly…</> : <><PlayCircle size={17} /> Build final Short</>}
          </button>
          {resumePending && <div className="media-resume-note"><ShieldCheck size={16} /><span>Checking whether this approved Media Studio job already has an M2C render. Existing final-review or approved masters are reopened automatically.</span></div>}
          {error && <div className="dna-inline-error" role="alert"><AlertTriangle size={17} /><div><strong>Assembly could not start</strong><span>{error}</span></div></div>}
        </div>
      </article>
    </section>
  );
}

function AssemblyProgress({ job }: { job: FinalAssemblyJob }) {
  const total = Math.max(1, job.progress_total);
  const pct = Math.max(8, Math.min(96, Math.round((job.progress_current / total) * 100)));
  const currentShot = Number(job.detail.current_shot ?? 0);
  return (
    <section className="assembly-section" id="final-assembly" aria-live="polite">
      <article className="assembly-progress glass-card">
        <div className="assembly-progress-head">
          <div className="assembly-gate-icon"><Film size={28} /></div>
          <div>
            <div className="layer-badge media"><Sparkles size={15} /> Deterministic final assembly</div>
            <span className="eyebrow">Milestone M2C.1.2</span>
            <h2>{job.message}</h2>
            <p>{currentShot ? `Rendering shot ${currentShot} without touching the approved source clips.` : "Preparing the approved clip sequence."}</p>
          </div>
          <div className="assembly-percent"><strong>{pct}%</strong><span>render progress</span></div>
        </div>
        <div className="media-progress-bar"><span style={{ width: `${pct}%` }} /></div>
        <div className="assembly-progress-steps">
          <div className={job.stage === "PREPARING" ? "active" : "done"}><span>{job.stage === "PREPARING" ? "1" : <Check size={14} />}</span><strong>Prepare clips</strong></div>
          <div className={job.stage === "RENDERING" ? "active" : job.stage === "PREPARING" ? "pending" : "done"}><span>2</span><strong>Trim + sequence</strong></div>
          <div className="pending"><span>3</span><strong>Preview + review</strong></div>
        </div>
      </article>
    </section>
  );
}

function AssemblyFailure({ job, error, onStart }: { job: FinalAssemblyJob; error: string | null; onStart: () => void }) {
  return (
    <section className="assembly-section" id="final-assembly">
      <article className="media-failure glass-card" role="alert">
        <AlertTriangle size={28} />
        <div>
          <span className="eyebrow">Final assembly paused</span>
          <h2>ReviveAI could not finish the final Short.</h2>
          <p>{job.error || "The deterministic render did not complete."}</p>
          {error && <p>{error}</p>}
          <p>Your four approved Veo clips remain unchanged. Retry starts a new assembly job from the same approved sources.</p>
          <button className="secondary-button" onClick={onStart}>Retry final assembly</button>
        </div>
      </article>
    </section>
  );
}

function AssemblyReview({ job, onApprove }: { job: FinalAssemblyJob; onApprove: () => void }) {
  const result = job.result!;
  const approved = result.review_status === "APPROVED" || job.stage === "DELIVERED";
  return (
    <section className="assembly-section" id="final-assembly">
      <div className="assembly-title-row">
        <div>
          <div className="layer-badge media"><Film size={15} /> Final Assembly Studio</div>
          <span className="eyebrow">Milestone M2C.1.2 · {approved ? "Visual master approved" : "Final visual review"}</span>
          <h2>{result.working_title}</h2>
          <p>{result.total_duration_seconds.toFixed(1)}s portrait master assembled from human-approved Veo clips.</p>
        </div>
        <div className={`assembly-status ${approved ? "approved" : "review"}`}>
          {approved ? <BadgeCheck size={19} /> : <PlayCircle size={19} />}
          <div><strong>{approved ? "Visual master approved" : "Needs human review"}</strong><span>{approved ? "Ready for audio finishing" : "Watch the visual master before approval"}</span></div>
        </div>
      </div>

      <div className="assembly-review-layout">
        <article className="assembly-player-card glass-card">
          <video controls playsInline src={assemblyAssetUrl(result.final_video.asset_url)} />
          <div className="assembly-player-actions">
            <a className="secondary-button assembly-download" href={assemblyAssetUrl(result.final_video.asset_url)} download={result.final_video.filename}><Download size={16} /> Download MP4</a>
            {result.subtitles && <a className="secondary-button assembly-download" href={assemblyAssetUrl(result.subtitles.asset_url)} download={result.subtitles.filename}><Captions size={16} /> Download SRT</a>}
            {!approved && <button className="primary-button" onClick={onApprove}><BadgeCheck size={17} /> Approve visual master</button>}
          </div>
        </article>

        <article className="assembly-summary glass-card">
          <span className="eyebrow">Render summary</span>
          <div className="assembly-summary-grid">
            <Fact label="Final duration" value={`${result.total_duration_seconds.toFixed(1)}s`} />
            <Fact label="Approved source clips" value={`${result.timeline.length}`} />
            <Fact label="On-screen text" value={result.captions_burned_in ? "Burned in" : "Not burned"} />
            <Fact label="Audio master" value="Silent compatibility track" />
          </div>
          <div className="assembly-audio-note"><Music2 size={17} /><div><strong>Audio direction preserved</strong><span>{result.publishing.audio_direction}</span></div></div>
        </article>
      </div>

      <article className="assembly-timeline glass-card">
        <div className="assembly-section-head"><div><span className="eyebrow">Final timeline</span><h3>Exact storyboard trims</h3></div><span>{result.timeline.length} shots · {result.total_duration_seconds.toFixed(1)}s</span></div>
        <div className="assembly-timeline-grid">
          {result.timeline.map((item) => (
            <div className="assembly-shot" key={item.shot_number}>
              <div className="assembly-shot-number">{String(item.shot_number).padStart(2, "0")}</div>
              <div><strong>{item.output_duration_seconds.toFixed(1)}s final</strong><span>Veo source {item.source_duration_seconds}s · v{item.source_generation_attempt}</span>{item.on_screen_text && <p>Text: {item.on_screen_text}</p>}</div>
            </div>
          ))}
        </div>
      </article>

      <article className="assembly-publishing glass-card">
        <div className="assembly-section-head"><div><span className="eyebrow">Delivery package</span><h3>Copy-ready publishing metadata</h3></div></div>
        <div className="assembly-publish-grid">
          <CopyBlock label="YouTube title" value={result.publishing.youtube_title} />
          <CopyBlock label="Description" value={result.publishing.description} />
          <CopyBlock label="Social caption" value={result.publishing.social_caption} />
          <CopyBlock label="Thumbnail concept" value={result.publishing.thumbnail_concept} />
        </div>
        <div className="assembly-hashtags">{result.publishing.hashtags.map((tag) => <span key={tag}>{tag}</span>)}</div>
      </article>

      <div className="assembly-methodology"><ShieldCheck size={18} /><span>{result.methodology_notice}</span></div>
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="assembly-fact"><span>{label}</span><strong>{value}</strong></div>;
}

function CopyBlock({ label, value }: { label: string; value: string }) {
  return <div className="assembly-copy-block"><span>{label}</span><p>{value}</p></div>;
}
