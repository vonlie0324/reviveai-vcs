import { useEffect, useMemo, useRef, useState } from "react";
import { API_BASE_URL, apiFetch } from "../http";
import { InfinityLoader } from "./InfinityLoader";

type Gender = "MALE" | "FEMALE";
type Policy = {
  max_final_video_duration_seconds: number;
  max_total_production_cost_usd: string;
  publish_interval_hours: number;
  narrator_gender: Gender;
  narrator_voice_name: string;
  auto_accept_safe_adaptations: boolean;
  max_keyframe_attempts: number;
  autonomous_publishing_enabled: boolean;
  isolate_failed_productions: boolean;
};
type Voice = { name: string; gender: Gender };
type CostEstimate = { recommended_budget_usd: number; worst_case_video_only_usd: number; components: { label: string; usd: number; basis: string }[] };
const base = `${API_BASE_URL}/api/v1/youtube/channel-policies`;
async function message(response: Response) {
  const data = await response.json().catch(() => ({}));
  return typeof data.detail === "string" ? data.detail : `Request failed (${response.status})`;
}
const field: React.CSSProperties = { display: "grid", gap: 5, color: "#e5e9ff", fontSize: 13 };
const input: React.CSSProperties = { background: "#202943", border: "1px solid #455170", borderRadius: 8, color: "white", padding: "10px", width: "100%", boxSizing: "border-box" };
const modalSurface: React.CSSProperties = { background: "linear-gradient(180deg, rgba(28,34,58,.98), rgba(19,24,43,.98))", border: "1px solid rgba(122, 133, 182, 0.35)", borderRadius: 18, color: "#fff", boxShadow: "0 24px 80px rgba(0,0,0,.55)" };

const VOICE_HINTS: Record<string, string> = {
  Kore: "Warm and polished — good for premium lifestyle storytelling.",
  Aoede: "Bright and friendly — good for welcoming explainers and upbeat intros.",
  Puck: "Youthful and playful — good for energetic and fun short-form videos.",
  Leda: "Calm and confident — good for clear educational narration.",
  Zephyr: "Light and energetic — good for fast, trendy content.",
  Umbriel: "Smooth and balanced — good for general-purpose narration.",
  Fenrir: "Bold and authoritative — good for punchy hooks and strong delivery.",
  Orus: "Steady and informative — good for explainers and reviews.",
  Charon: "Deep and composed — good for dramatic or cinematic reads.",
  Autonoe: "Clear and conversational — good for natural channel voiceovers.",
};

function friendlyVoiceName(name: string) {
  return name.replace(/^en-US-(?:Chirp3-HD-)?/, "");
}

function describeVoice(voice: Voice | undefined) {
  if (!voice) return "Select a narrator voice, then preview it to hear how it fits your channel personality.";
  const friendly = friendlyVoiceName(voice.name);
  const hinted = VOICE_HINTS[friendly];
  if (hinted) return hinted;
  const genderText = voice.gender === "FEMALE" ? "Female" : "Male";
  return `${genderText} English narrator — clear studio-style delivery for general voiceover use.`;
}

export function ChannelAutonomySettings({ channelId, onClose, inModal = false }: { channelId: string; onClose?: () => void; inModal?: boolean }) {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [savedPolicy, setSavedPolicy] = useState<Policy | null>(null);
  const [saving, setSaving] = useState(false);
  const [previewingVoice, setPreviewingVoice] = useState<string | null>(null);
  const [voiceSearch, setVoiceSearch] = useState("");
  const [costEstimate, setCostEstimate] = useState<CostEstimate | null>(null);
  const [estimateError, setEstimateError] = useState("");
  const [showCostDetails, setShowCostDetails] = useState(false);
  const [showAllVoices, setShowAllVoices] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);
  const objectUrl = useRef<string | null>(null);
  useEffect(() => {
    let active = true;
    setPolicy(null); setError(""); setNotice("");
    Promise.all([apiFetch(`${base}/${encodeURIComponent(channelId)}`), apiFetch(`${base}/voices`)]).then(async ([p, v]) => {
      if (!p.ok) throw new Error(await message(p));
      if (!v.ok) throw new Error(await message(v));
      const payload: Policy = await p.json();
      const catalog: { voices: Voice[] } = await v.json();
      if (active) { setPolicy(payload); setSavedPolicy(payload); setVoices(catalog.voices); }
    }).catch(err => { if (active) setError(String(err.message || err)); });
    return () => {
      active = false;
      audio.current?.pause(); audio.current = null;
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = null;
    };
  }, [channelId]);
  useEffect(() => {
    if (!policy || !Number.isFinite(policy.max_final_video_duration_seconds) || !Number.isFinite(policy.max_keyframe_attempts)) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void apiFetch(`${base}/cost-estimate?duration_seconds=${policy.max_final_video_duration_seconds}&max_keyframe_attempts=${policy.max_keyframe_attempts}`, { signal: controller.signal })
        .then(async response => { if (!response.ok) throw new Error(await message(response)); return response.json() as Promise<CostEstimate>; })
        .then(estimate => { if (!controller.signal.aborted) { setCostEstimate(estimate); setEstimateError(""); } })
        .catch(() => { if (!controller.signal.aborted) { setCostEstimate(null); setEstimateError("Cost estimate unavailable"); } });
    }, 350);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [policy?.max_final_video_duration_seconds, policy?.max_keyframe_attempts]);
  const change = (patch: Partial<Policy>) => { setPolicy(old => old ? { ...old, ...patch } : old); setNotice(""); };
  const dirty = Boolean(policy && savedPolicy && JSON.stringify(policy) !== JSON.stringify(savedPolicy));
  function close() { if (dirty && !window.confirm("Discard unsaved channel settings?")) return; onClose?.(); }
  async function save() {
    if (!policy) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const r = await apiFetch(`${base}/${encodeURIComponent(channelId)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(policy) });
      if (!r.ok) throw new Error(await message(r));
      const saved: Policy = await r.json(); setPolicy(saved); setSavedPolicy(saved); setNotice("Settings saved successfully.");
    } catch (err) { setError(err instanceof Error ? err.message : "Save failed"); }
    finally { setSaving(false); }
  }
  async function preview(voiceName: string) {
    if (!policy || !voiceName) return;
    setPreviewingVoice(voiceName); setError("");
    try {
      const response = await apiFetch(`${base}/voices/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ voice_name: voiceName }) });
      if (!response.ok) throw new Error(await message(response));
      const blob = await response.blob();
      audio.current?.pause();
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      const url = URL.createObjectURL(blob); objectUrl.current = url;
      const player = new Audio(url); audio.current = player;
      await player.play();
    } catch (err) { setError(err instanceof Error ? err.message : "Preview failed"); }
    finally { setPreviewingVoice(null); }
  }
  const genders: Gender[] = ["FEMALE", "MALE"];
  const availableVoices = useMemo(() => voices.filter(v => v.gender === policy?.narrator_gender), [voices, policy?.narrator_gender]);
  const filteredVoices = useMemo(() => availableVoices.filter(voice => {
    const query = voiceSearch.trim().toLowerCase();
    return !query || friendlyVoiceName(voice.name).toLowerCase().includes(query) || describeVoice(voice).toLowerCase().includes(query);
  }), [availableVoices, voiceSearch]);
  const visibleVoices = showAllVoices ? filteredVoices : filteredVoices.slice(0, 3);
  const selectedVoice = useMemo(() => voices.find(v => v.name === policy?.narrator_voice_name), [voices, policy?.narrator_voice_name]);
  const shellStyle = inModal ? { ...modalSurface, padding: 0, display: "flex", flexDirection: "column", gap: 0, width: "min(760px, calc(100vw - 32px))", maxHeight: "min(88vh, 920px)", overflow: "hidden" } as React.CSSProperties : { padding: 20, display: "flex", flexDirection: "column", gap: 0, maxWidth: 760 } as React.CSSProperties;
  return <section className={inModal ? undefined : "glass-card"} style={shellStyle}>
    <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", padding: "18px 22px", borderBottom: "1px solid rgba(125,139,187,.25)", flexShrink: 0 }}>
      <div><h2 style={{ margin: 0 }}>Channel autonomy settings</h2><p style={{ color: "#aab7d5", marginBottom: 0 }}>Set production limits, release spacing, and a narrator voice for this channel.</p></div>
      {onClose && <button type="button" onClick={close} aria-label="Close channel autonomy settings" style={{ background: "transparent", color: "#dfe7ff", border: "1px solid rgba(159,171,220,.35)", borderRadius: 10, padding: "8px 10px", cursor: "pointer", lineHeight: 1 }}>✕</button>}
    </div>
    <div style={{ overflowY: "auto", padding: "16px 22px", display: "grid", gap: 15, minHeight: 0, flex: 1 }}>
    {!policy ? <InfinityLoader label={error || "Loading channel settings"} /> : <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px,1fr))", gap: 14 }}>
        <label style={field}>Maximum final video duration (seconds)<input style={input} type="number" min="6" max="3600" value={policy.max_final_video_duration_seconds} onChange={e => change({ max_final_video_duration_seconds: Number(e.target.value) })} /></label>
        <label style={field}>Maximum total production cost (USD)<input style={input} type="number" min="0.01" max="10000" step="0.01" value={policy.max_total_production_cost_usd} onChange={e => change({ max_total_production_cost_usd: e.target.value })} /></label>
        <label style={field}>Minimum publishing interval (hours)<input style={input} type="number" min="1" max="720" value={policy.publish_interval_hours} onChange={e => change({ publish_interval_hours: Number(e.target.value) })} /></label>
        <label style={field}>Maximum keyframe attempts<input style={input} type="number" min="1" max="5" value={policy.max_keyframe_attempts} onChange={e => change({ max_keyframe_attempts: Number(e.target.value) })} /></label>
      </div>
      <div style={{ display: "grid", gap: 8, padding: 12, border: "1px solid rgba(146,123,230,.35)", borderRadius: 12, background: "rgba(96,80,174,.13)" }}>
        <strong>Recommended budget · planning estimate</strong>
        {costEstimate ? <>
          <span style={{ fontSize: 13, color: "#dae2ff" }}>Suggested for {policy.max_final_video_duration_seconds}s: <strong>${costEstimate.recommended_budget_usd.toFixed(2)}</strong> (USD)</span>
          <span style={{ fontSize: 12, color: "#bdc9e6" }}>Your limit of ${Number(policy.max_total_production_cost_usd).toFixed(2)} is {Number(policy.max_total_production_cost_usd) < costEstimate.recommended_budget_usd ? "below" : "at or above"} the suggestion; it remains fully configurable.</span>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button type="button" onClick={() => change({ max_total_production_cost_usd: costEstimate.recommended_budget_usd.toFixed(2) })} style={{ ...input, width: "auto", cursor: "pointer", background: "#514b9e" }}>Use ${costEstimate.recommended_budget_usd.toFixed(2)}</button>
            <button type="button" onClick={() => setShowCostDetails(value => !value)} style={{ ...input, width: "auto", cursor: "pointer" }}>{showCostDetails ? "Hide" : "Show"} breakdown</button>
          </div>
          {showCostDetails && <div style={{ display: "grid", gap: 5 }}>
            {costEstimate.components.map(component => <div key={component.label} title={component.basis} style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 12, color: "#cdd6ef" }}><span>{component.label}</span><strong>${component.usd.toFixed(2)}</strong></div>)}
            <span style={{ color: "#ecd49e", fontSize: 12 }}>All-shot retry worst-case video generation: ${costEstimate.worst_case_video_only_usd.toFixed(2)}, before other services.</span>
          </div>}
          <span style={{ color: "#ecd49e", fontSize: 12 }}>Veo pricing uses configured backend rates. Other components are illustrative allowances, not live provider quotes. This estimate is not an enforced ceiling.</span>
        </> : <span style={{ fontSize: 12 }}>{estimateError || "Calculating estimate…"}</span>}
      </div>
      <div style={{ display: "grid", gap: 10, padding: 16, borderRadius: 14, background: "rgba(17,23,43,.55)", border: "1px solid rgba(110,120,166,.22)" }}><strong>Narrator voice</strong>
        <p style={{ margin: 0, color: "#9fb1d9", fontSize: 13 }}>Choose the default narrator for this channel. Use preview to hear the selected voice before saving.</p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{genders.map(g => <button key={g} type="button" aria-pressed={policy.narrator_gender === g} onClick={() => { setVoiceSearch(""); setShowAllVoices(false); change({ narrator_gender: g, narrator_voice_name: voices.find(v => v.gender === g)?.name || "" }); }} style={{ ...input, width: "auto", cursor: "pointer", background: policy.narrator_gender === g ? "#514b9e" : "#202943", paddingInline: 16 }}>{g === "FEMALE" ? "Female" : "Male"}</button>)}</div>
        <label style={field}>Find a narrator
          <input style={input} type="search" value={voiceSearch} onChange={e => { setVoiceSearch(e.target.value); setShowAllVoices(false); }} placeholder="Search voice or style (e.g., calm, lively)" />
        </label>
        <div style={{ display: "grid", gap: 8, paddingRight: 4 }} role="radiogroup" aria-label="Narrator voices">
          {visibleVoices.map(voice => {
            const chosen = voice.name === policy.narrator_voice_name;
            return <div key={voice.name} style={{ display: "flex", gap: 10, alignItems: "center", padding: "10px 12px", background: chosen ? "rgba(100,86,200,.22)" : "rgba(27,35,63,.72)", border: `1px solid ${chosen ? "#8879eb" : "rgba(130,144,197,.25)"}`, borderRadius: 11 }}>
              <button type="button" role="radio" aria-checked={chosen} onClick={() => change({ narrator_voice_name: voice.name })} style={{ background: "transparent", color: "#edf0ff", border: 0, textAlign: "left", cursor: "pointer", flex: 1, minWidth: 0, display: "flex", alignItems: "flex-start", gap: 10, padding: 0 }}>
                <span aria-hidden="true" style={{ marginTop: 2, color: chosen ? "#ada3ff" : "#91a0c2" }}>{chosen ? "◉" : "○"}</span>
                <span style={{ display: "grid", gap: 4, minWidth: 0 }}>
                  <strong style={{ fontSize: 14 }}>{friendlyVoiceName(voice.name)}</strong>
                  <span style={{ fontSize: 12, color: "#b7c4e6", lineHeight: 1.45 }}>{describeVoice(voice)}</span>
                </span>
              </button>
              <button type="button" disabled={previewingVoice !== null} onClick={() => void preview(voice.name)} aria-label={`Preview ${friendlyVoiceName(voice.name)}`} style={{ flexShrink: 0, border: "1px solid rgba(153,163,214,.45)", borderRadius: 8, padding: "8px 10px", cursor: "pointer", background: "#263253", color: "#f1f3ff", fontSize: 12 }}>
                {previewingVoice === voice.name ? <InfinityLoader inline label="Preparing" /> : "▶ Preview"}
              </button>
            </div>;
          })}
          {filteredVoices.length === 0 && <span style={{ fontSize: 13, color: "#b7c4e6" }}>No voices match your search.</span>}
        </div>
        {!showAllVoices && filteredVoices.length > 3 && <button type="button" onClick={() => setShowAllVoices(true)} style={{ ...input, cursor: "pointer", width: "auto", justifySelf: "start" }}>Show all {filteredVoices.length} voices</button>}
        {showAllVoices && filteredVoices.length > 3 && <button type="button" onClick={() => setShowAllVoices(false)} style={{ ...input, cursor: "pointer", width: "auto", justifySelf: "start" }}>Show fewer voices</button>}
        <span style={{ fontSize: 12, color: "#aab7d5" }}>Select a voice to save it. Preview plays a real sample without changing your selection.</span>
      </div>
      <label style={field}><span><input type="checkbox" checked={policy.auto_accept_safe_adaptations} onChange={e => change({ auto_accept_safe_adaptations: e.target.checked })} /> Accept safe creative adaptations automatically</span></label>
      <label style={field}><span><input type="checkbox" checked={policy.autonomous_publishing_enabled} onChange={e => change({ autonomous_publishing_enabled: e.target.checked })} /> Enable autonomous publishing after QC</span></label>
      <div style={{ display: "grid", gap: 10, padding: 16, borderRadius: 14, background: "rgba(17,23,43,.55)", border: "1px solid rgba(110,120,166,.22)" }}>
        <strong>Autonomous recovery</strong>
        <p style={{ margin: 0, color: "#aab7d5", fontSize: 13 }}>Choose what happens if a production cannot recover after its automatic retry attempts. Provider-wide failures still require attention.</p>
        <label style={{ ...field, cursor: "pointer" }}>
          <span style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <input type="checkbox" checked={policy.isolate_failed_productions ?? true} onChange={e => change({ isolate_failed_productions: e.target.checked })} />
            <span>Isolate an unrecoverable production and continue other eligible videos</span>
          </span>
        </label>
        <span style={{ fontSize: 12, color: "#b7c4e6" }}>
          {policy.isolate_failed_productions ?? true
            ? "After retries are exhausted, retain the failed production and its assets in history while the campaign moves on."
            : "After retries are exhausted, pause the campaign for manual review of the affected production."}
        </span>
        <span style={{ fontSize: 12, color: "#e9c78b" }}>Budget cap, speech fallback, and safe-adaptation automation require additional backend enforcement; changing settings here cannot guarantee uninterrupted production.</span>
      </div>
    </>}
    </div>
    <div style={{ padding: "12px 22px", borderTop: "1px solid rgba(125,139,187,.3)", background: "#141a30", flexShrink: 0, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
      <div role={error ? "alert" : "status"} aria-live="polite" style={{ flex: "1 1 180px", fontSize: 13, color: error ? "#ffc0c0" : "#a2ebbc" }}>{saving ? <InfinityLoader inline label="Saving settings" /> : error || notice || (dirty ? "Unsaved changes" : "Settings are up to date")}</div>
      <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
        {onClose && <button type="button" onClick={close} style={{ ...input, width: "auto", paddingInline: 18, cursor: "pointer", background: "rgba(40,48,77,.9)" }}>Close</button>}
        <button type="button" disabled={saving || !policy || voices.length === 0 || !dirty} onClick={() => void save()} style={{ ...input, width: "auto", cursor: "pointer", background: "#514b9e", opacity: saving || !policy || !dirty ? .6 : 1 }}>Save settings</button>
      </div>
    </div>
  </section>;
}
