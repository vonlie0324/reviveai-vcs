import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, AlertTriangle, LoaderCircle, RefreshCw, ShieldCheck } from "lucide-react";
import {
  aiReviewAudioFinishing,
  aiReviewPublishingDraft,
  getAudioFinishingJob,
  getLatestDeliveryPackage,
  getPublishingDrafts,
} from "../api";

/** Temporary dev-only checkpoint repair; intentionally scoped to ONE recovery. */
const AUDIO_ID = "audio_92d788728faf41a78c20d7cc5e19c35d";
const DRAFT_ID = "publishing_8bce387ccdec472abaf0f94a2224a6c9";
const PACKAGE_ID = "deliverypkg_0cf6523ec2fd4cac8311e370efb2d95a";

type RecordLike = Record<string, unknown>;
function object(value: unknown): RecordLike {
  return value && typeof value === "object" ? value as RecordLike : {};
}
function decision(value: unknown) { return String(object(value).decision || "MISSING").toUpperCase(); }
function outcome(value: unknown) { return String(object(value).outcome || "").toUpperCase(); }
function errorMessage(error: unknown) { return error instanceof Error ? error.message : String(error); }

type Checkpoint = {
  audioStage: string;
  audioActor: string;
  audioDecision: string;
  audioOriginal: string;
  audioOutcome: string;
  audioSummary: string;
  draftStatus: string;
  draftMarker: boolean;
  draftSalvaged: boolean;
  packageMatches: boolean;
  ready: boolean;
};

export function DevRecoveredReviewPanel() {
  const [data, setData] = useState<Checkpoint | null>(null);
  const [busy, setBusy] = useState<"refresh" | "audio" | "draft" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async (): Promise<Checkpoint> => {
    const [audio, drafts, delivery] = await Promise.all([
      getAudioFinishingJob(AUDIO_ID),
      getPublishingDrafts(AUDIO_ID),
      getLatestDeliveryPackage(AUDIO_ID),
    ]);
    const draft = drafts.find((item) => item.draft_id === DRAFT_ID);
    if (!draft) throw new Error("Approved publishing draft not found for the recovered audio v2.");
    const a = object(audio);
    const details = object(a.detail);
    const review = object(details.ai_audio_review);
    const d = object(draft);
    const record = object(delivery);
    const packageMatches = record.package_id === PACKAGE_ID &&
      record.audio_job_id === AUDIO_ID && record.publishing_draft_id === DRAFT_ID;
    if (!packageMatches) throw new Error("Latest delivery package does not match the locked recovery package/draft. No review was run.");
    const result = object(a.result);
    const audioDecision = decision(review);
    const audioActor = String(details.approval_actor || "MISSING");
    const draftMarker = String(d.generation_note || "").includes("[AI_REVIEW_APPROVED]");
    const next: Checkpoint = {
      audioStage: String(a.stage || "MISSING"),
      audioActor,
      audioDecision,
      audioOriginal: String(review.original_decision || ""),
      audioOutcome: outcome(review),
      audioSummary: String(review.summary || ""),
      draftStatus: String(d.status || "MISSING"),
      draftMarker,
      draftSalvaged: String(d.generation_note || "").includes("[AI_SALVAGED]"),
      packageMatches,
      ready: a.stage === "DELIVERED" && result.review_status === "APPROVED" &&
        audioActor === "AI" && audioDecision === "PASS" &&
        d.status === "APPROVED" && draftMarker && packageMatches,
    };
    setData(next);
    return next;
  }, []);

  useEffect(() => {
    if (!import.meta.env.DEV) return;
    let active = true;
    void refresh().catch((caught) => { if (active) setError(errorMessage(caught)); });
    return () => { active = false; };
  }, [refresh]);

  async function runAudio() {
    if (!data || data.audioStage !== "DELIVERED" || !data.packageMatches || busy) return;
    if (!window.confirm("Run independent AI listening review for EXISTING recovered audio v2? The backend has regeneration disabled. This is NOT final approval or YouTube upload.")) return;
    setBusy("audio"); setError(null); setNotice(null);
    try {
      const result = await aiReviewAudioFinishing(AUDIO_ID);
      if (result.job_id !== AUDIO_ID) throw new Error(`Unexpected audio version returned: ${result.job_id}. Stop and inspect.`);
      const checked = await refresh();
      setNotice(checked.audioOutcome === "AI_SALVAGED"
        ? `Audio AI reviewer requested changes (${checked.audioOriginal || "non-PASS"}); backend retained the approved master using AI_SALVAGED. Review the finding before final approval.`
        : checked.audioDecision === "PASS" ? "Independent AI audio review passed on the existing v2 master." : "AI audio review completed without a passing decision. Inspect the record.");
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(null); }
  }

  async function runDraft() {
    if (!data || !data.packageMatches || data.draftStatus !== "APPROVED" || data.audioDecision !== "PASS" || busy) return;
    if (!window.confirm("Run AI publishing-copy review on the EXISTING approved draft? The backend has regeneration disabled. This is NOT a YouTube upload.")) return;
    setBusy("draft"); setError(null); setNotice(null);
    try {
      const result = await aiReviewPublishingDraft(DRAFT_ID);
      if (result.draft_id !== DRAFT_ID) throw new Error(`Unexpected draft returned: ${result.draft_id}. Stop and inspect.`);
      const checked = await refresh();
      setNotice(checked.draftSalvaged
        ? "Publishing critic requested changes; the original copy was retained as AI_SALVAGED. Review the content before final approval."
        : checked.draftMarker ? "AI publishing-copy review recorded on the existing approved draft." : "AI review returned, but final-approval marker is still missing. Stop and inspect.");
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(null); }
  }

  if (!import.meta.env.DEV) return null;
  return (
    <section className="glass-card" style={{ padding: 20, marginTop: 16, display: "grid", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <ShieldCheck size={19} /><strong>Recovery AI review checkpoints</strong>
        <span style={{ fontSize: 11, opacity: 0.65 }}>DEV ONLY · Missing Squeaker</span>
      </div>
      <small>This operates only on existing audio v2 and publishing draft v1. No automatic final approval, uploading, or Autopilot actions.</small>
      {error && <div className="inline-error" role="alert"><AlertTriangle size={14} /> {error}</div>}
      {notice && <p role="status" style={{ margin: 0 }}>{notice}</p>}
      {data && <>
        <div><strong>Audio:</strong> {data.audioStage} · actor {data.audioActor} · AI decision {data.audioDecision}
          {data.audioOutcome === "AI_SALVAGED" && <strong> · AI_SALVAGED (original: {data.audioOriginal})</strong>}
          {data.audioSummary && <div><small>{data.audioSummary}</small></div>}
        </div>
        <div><strong>Publishing copy:</strong> {data.draftStatus} · AI marker {data.draftMarker ? "present" : "missing"}{data.draftSalvaged ? " · AI_SALVAGED" : ""}</div>
        <div><strong>Package v2:</strong> {data.packageMatches ? "verified" : "mismatch"}</div>
        {data.ready && <p style={{ margin: 0 }}><CheckCircle2 size={15} style={{ verticalAlign: "middle" }} /> Local audio/publishing review checkpoints recorded. Earlier plan/media AI gates are still validated by final approval backend.</p>}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button type="button" className="secondary-button" disabled={busy !== null} onClick={() => { setBusy("refresh"); setError(null); void refresh().catch(e => setError(errorMessage(e))).finally(() => setBusy(null)); }}>
            {busy === "refresh" ? <LoaderCircle size={14} /> : <RefreshCw size={14} />} Refresh
          </button>
          <button type="button" className="secondary-button" disabled={busy !== null || data.audioStage !== "DELIVERED" || data.audioDecision === "PASS"} onClick={() => void runAudio()}>
            {busy === "audio" ? <LoaderCircle size={14} /> : <ShieldCheck size={14} />} Run AI audio review
          </button>
          <button type="button" className="secondary-button" disabled={busy !== null || data.audioDecision !== "PASS" || data.draftStatus !== "APPROVED" || data.draftMarker} onClick={() => void runDraft()}>
            {busy === "draft" ? <LoaderCircle size={14} /> : <ShieldCheck size={14} />} Run AI publishing review
          </button>
        </div>
      </>}
    </section>
  );
}
