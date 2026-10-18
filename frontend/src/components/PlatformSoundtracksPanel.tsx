import { FormEvent, useEffect, useRef, useState } from "react";
import { Music2, Pause, Play, RefreshCw, UploadCloud } from "lucide-react";
import { API_BASE_URL, apiFetch } from "../http";
import { PlatformLyriaBatchPanel } from "./PlatformLyriaBatchPanel";

interface Track {
  track_id: string; title: string; artist: string; status: string;
  license_name: string; license_evidence: string; attribution: string;
  created_at?: string; size_bytes?: number; duration_seconds?: number | null;
  mood?: string; requested_bpm?: number; generation_cost_estimated_usd?: number;
  generation_cost_actual_usd?: number; generation_cost_status?: string;
  rights_confirmed?: boolean; standalone_distribution_approved?: boolean; internal_video_use_approved?: boolean; internal_video_use_evidence?: string; source?: string;
}

export function PlatformSoundtracksPanel() {
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [license, setLicense] = useState("");
  const [evidence, setEvidence] = useState("");
  const [attribution, setAttribution] = useState("");
  const [rights, setRights] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editLicense, setEditLicense] = useState("");
  const [editEvidence, setEditEvidence] = useState("");
  const [editAttribution, setEditAttribution] = useState("");
  const [editConfirmed, setEditConfirmed] = useState(false);
  const [editInternal, setEditInternal] = useState(false);
  const [editInternalEvidence, setEditInternalEvidence] = useState("");
  const [backfillBusy, setBackfillBusy] = useState(false);
  const lyriaBasis = "Google Lyria 3 Clip – API-generated audio; rights review pending";
  const lyriaEvidence = "Source: Google Gemini API Additional Terms of Service\nReference: https://ai.google.dev/gemini-api/terms\n[VERIFY applicable version/date and specific permission to distribute audio to ReviveAI creators for use in videos. Replace this instruction with the verified provision or agreement reference.]";
  const isLyria = (track: Track) => track.source === "GOOGLE_LYRIA";
  const isUnverifiedTemplate = (value: string) => value.includes("[VERIFY") || value.includes("[ADD") || value.includes("REVIEW PENDING");
  function applyLyriaDefaults() {
    setEditLicense(lyriaBasis);
    setEditEvidence(lyriaEvidence);
    setEditAttribution("Generated using Google Lyria 3 (voluntary disclosure; verify attribution obligations)");
    setEditConfirmed(false);
    setEditInternal(false);
    setEditInternalEvidence("");
  }
  function editTrack(track: Track) {
    setEditing(track.track_id);
    setEditLicense(track.license_name && track.license_name !== "AI-generated; rights review required" ? track.license_name : isLyria(track) ? lyriaBasis : track.license_name || "");
    setEditEvidence(track.license_evidence || (isLyria(track) ? lyriaEvidence : ""));
    setEditAttribution(track.attribution || (isLyria(track) ? "Generated using Google Lyria 3 (voluntary disclosure; verify attribution obligations)" : ""));
    setEditConfirmed(Boolean(track.standalone_distribution_approved));
    setEditInternal(Boolean(track.internal_video_use_approved));
    setEditInternalEvidence(track.internal_video_use_evidence || "");
    setError("");
  }
  async function saveMetadata(track: Track) {
    if (busy || (editConfirmed && (editEvidence.trim().length < 8 || isUnverifiedTemplate(editEvidence))) || (editInternal && (editInternalEvidence.trim().length < 8 || isUnverifiedTemplate(editInternalEvidence)))) return;
    setBusy(true); setError("");
    try {
      const response = await apiFetch(`${API_BASE_URL}/api/v1/admin/soundtracks/${encodeURIComponent(track.track_id)}/metadata`, {
        method: "PATCH", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({license_name: editLicense, license_evidence: editEvidence,
          attribution: editAttribution, rights_confirmed: editConfirmed,
          standalone_distribution_approved: editConfirmed,
          internal_video_use_approved: editInternal,
          internal_video_use_evidence: editInternalEvidence}),
      });
      if (!response.ok) throw new Error(`Metadata update failed (HTTP ${response.status}): ${await response.text()}`);
      setEditing(null); await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Metadata update failed"); }
    finally {setBusy(false);}
  }
  async function backfill() {
    if (backfillBusy || busy) return;
    setBackfillBusy(true); setError("");
    try {
      const response = await apiFetch(`${API_BASE_URL}/api/v1/admin/soundtracks/backfill-metadata`, {method: "POST"});
      if (!response.ok) throw new Error(`Metadata enrichment failed (HTTP ${response.status}): ${await response.text()}`);
      await load();
    } catch (e) {setError(e instanceof Error ? e.message : "Metadata enrichment failed");}
    finally {setBackfillBusy(false);}
  }
  const [playing, setPlaying] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const objectUrl = useRef<string | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const stop = () => { audio.current?.pause(); audio.current = null; if (objectUrl.current) URL.revokeObjectURL(objectUrl.current); objectUrl.current = null; setPlaying(null); };
  async function load() {
    setLoading(true); setError("");
    try {
      const response = await apiFetch(`${API_BASE_URL}/api/v1/admin/soundtracks`);
      if (!response.ok) throw new Error(`Soundtrack catalog unavailable (HTTP ${response.status})`);
      const body = await response.json() as {tracks: Track[]};
      setTracks(body.tracks || []);
    } catch (e) {setError(e instanceof Error ? e.message : "Could not load soundtracks");}
    finally {setLoading(false);}
  }
  useEffect(() => {void load(); return () => {audio.current?.pause(); if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);};}, []);
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!file || !rights || busy) return;
    setBusy(true); setError("");
    const form = new FormData();
    form.set("file", file); form.set("title", title); form.set("artist", artist);
    form.set("license_name", license); form.set("license_evidence", evidence);
    form.set("attribution", attribution); form.set("rights_confirmed", "true");
    try {
      const r = await apiFetch(`${API_BASE_URL}/api/v1/admin/soundtracks`, {method: "POST", body: form});
      if (!r.ok) throw new Error(`Upload failed (HTTP ${r.status}): ${await r.text()}`);
      setTitle(""); setArtist(""); setLicense(""); setEvidence(""); setAttribution(""); setRights(false); setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      await load();
    } catch(e) {setError(e instanceof Error ? e.message : "Upload failed");}
    finally {setBusy(false);}
  }
  async function change(track: Track, status: string) {
    if (busy) return;
    if (status === "PUBLISHED" && !window.confirm(`Publish “${track.title}” for all ReviveAI users? Verify redistribution rights first.`)) return;
    if (status === "RETIRED" && !window.confirm(`Retire “${track.title}”? It will no longer be selectable by users.`)) return;
    setBusy(true); setError("");
    try {
      const r = await apiFetch(`${API_BASE_URL}/api/v1/admin/soundtracks/${encodeURIComponent(track.track_id)}/status`, {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({status})});
      if (!r.ok) throw new Error(`Update failed (HTTP ${r.status}): ${await r.text()}`);
      await load();
    } catch(e) {setError(e instanceof Error ? e.message : "Update failed");}
    finally {setBusy(false);}
  }
  async function preview(track: Track) {
    if (playing === track.track_id) {stop(); return;}
    stop(); setError("");
    try {
      const r = await apiFetch(`${API_BASE_URL}/api/v1/admin/soundtracks/${encodeURIComponent(track.track_id)}/preview`);
      if (!r.ok) throw new Error(`Preview unavailable (HTTP ${r.status})`);
      const url = URL.createObjectURL(await r.blob()); objectUrl.current = url;
      const player = new Audio(url); audio.current = player; player.onended = stop;
      await player.play(); setPlaying(track.track_id);
    } catch(e) {stop(); setError(e instanceof Error ? e.message : "Preview failed");}
  }
  return <section className="revai-admin-surface">
    <div className="revai-admin-toolbar"><div className="revai-admin-section-title"><Music2 size={18}/> Platform soundtracks</div><button className="revai-admin-button" disabled={loading} onClick={() => void load()}><RefreshCw size={15}/> Refresh</button></div>
    <p className="revai-admin-notice">Upload licensed music as a private draft. Only tracks approved and published here become available to all authenticated ReviveAI creators. Personal soundtrack collections are unchanged.</p>
    {error && <p className="revai-admin-error" role="alert">{error}</p>}
    <PlatformLyriaBatchPanel />
    <div className="revai-admin-music-layout">
      <form className="revai-admin-music-upload" onSubmit={e => void upload(e)}>
        <h3><UploadCloud size={18}/> Upload platform music</h3>
        <label>Audio file (MP3, WAV, M4A · 25 MB max)<input ref={fileInput} type="file" accept=".mp3,.wav,.m4a" required onChange={e => setFile(e.target.files?.[0] || null)}/></label>
        <label>Track title<input maxLength={160} required value={title} onChange={e => setTitle(e.target.value)}/></label>
        <label>Artist<input maxLength={160} value={artist} onChange={e => setArtist(e.target.value)}/></label>
        <label>License or rights basis<input maxLength={160} required value={license} onChange={e => setLicense(e.target.value)} placeholder="Owned composition / distribution license"/></label>
        <label>License evidence / reference<textarea required minLength={8} maxLength={2000} rows={3} value={evidence} onChange={e => setEvidence(e.target.value)} placeholder="Document ID, contractual rights, or applicable license terms"/></label>
        <label>Attribution text, if required<textarea maxLength={1000} rows={2} value={attribution} onChange={e => setAttribution(e.target.value)}/></label>
        <label className="revai-admin-music-rights"><input type="checkbox" checked={rights} onChange={e => setRights(e.target.checked)}/> I confirm ReviveAI is authorized to host and distribute this track for creators' videos.</label>
        <button className="revai-admin-button" disabled={busy || !rights || !file || !title.trim() || !license.trim() || evidence.trim().length < 8}>{busy ? "Processing…" : "Upload as draft"}</button>
      </form>
      <div className="revai-admin-music-catalog"><div style={{display:"flex",justifyContent:"space-between",alignItems:"center",gap:12,flexWrap:"wrap"}}><h3>Catalog ({tracks.length})</h3><button type="button" className="revai-admin-button" disabled={backfillBusy || busy} onClick={() => void backfill()}>{backfillBusy ? "Enriching…" : "Enrich existing metadata"}</button></div>
        {loading && <p>Loading tracks…</p>}
        {!loading && tracks.length === 0 && <p>No platform tracks yet. Upload your first licensed soundtrack.</p>}
        {tracks.map(track => <article className="revai-admin-music-track" key={track.track_id}>
          <div className="revai-admin-music-track-top"><button className="revai-admin-button" title="Preview track" onClick={() => void preview(track)}>{playing === track.track_id ? <Pause size={16}/> : <Play size={16}/>}</button><div><strong>{track.title}</strong><small>{track.artist || "Unknown artist"}</small></div><span className="revai-admin-music-status">{track.status.replace(/_/g, " ")}</span></div>
          <div style={{display:"flex",flexWrap:"wrap",gap:12,marginTop:10,fontSize:12,color:"#bac7e5"}}>
            <span>Duration: <strong>{typeof track.duration_seconds === "number" ? `${track.duration_seconds.toFixed(1)}s` : "Not measured"}</strong></span>
            <span>Mood: <strong>{track.mood || "Unspecified"}</strong></span>
            <span>Tempo: <strong>{track.requested_bpm ? `${track.requested_bpm} BPM (requested)` : "Unspecified"}</strong></span>
            <span>Cost: <strong>{typeof track.generation_cost_actual_usd === "number" ? `$${track.generation_cost_actual_usd.toFixed(2)} actual` : typeof track.generation_cost_estimated_usd === "number" ? `$${track.generation_cost_estimated_usd.toFixed(2)} est.` : "Not tracked"}</strong></span>
          </div>
          <div style={{fontSize:12,color:"#adbbd8",marginTop:8}}>
            Video-use review: {track.internal_video_use_approved ? "Approved" : "Pending"}
            {" · "}Standalone distribution: {track.standalone_distribution_approved ? "Approved" : "Not approved"}
            {track.license_evidence && <span> · Policy notes saved</span>}
          </div>
          {editing === track.track_id && <div style={{display:"grid",gap:16,marginTop:14,padding:16,border:"1px solid #465274",borderRadius:12,background:"rgba(26,37,66,.65)"}}>
            <div style={{display:"flex",justifyContent:"space-between",gap:12,alignItems:"center",flexWrap:"wrap"}}>
              <div><strong style={{fontSize:15}}>Rights & metadata review</strong><p style={{margin:"4px 0 0",fontSize:12,color:"#b5c3df"}}>Save policy notes separately; approvals require verified permissions.</p></div>
              {isLyria(track) && <button type="button" className="revai-admin-button" onClick={applyLyriaDefaults} disabled={busy}>Restore Lyria defaults</button>}
            </div>
            <div style={{padding:"9px 12px",background:"rgba(98,118,160,.12)",borderRadius:8,fontSize:12,color:"#c5d1e9"}}>
              You can save reference notes without approving either use. Each permission must be independently verified before approval.
            </div>
            <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(min(100%,260px),1fr))",gap:12}}>
              <label style={{display:"grid",gap:6,fontSize:12}}>Rights basis
                <input style={{width:"100%",minWidth:0,boxSizing:"border-box",padding:"11px 12px",borderRadius:8,background:"#101a30",color:"#f5f7ff",border:"1px solid #586787"}} maxLength={160} value={editLicense} onChange={e => {setEditLicense(e.target.value);setEditConfirmed(false);}} />
              </label>
              <label style={{display:"grid",gap:6,fontSize:12}}>Attribution (optional)
                <input style={{width:"100%",minWidth:0,boxSizing:"border-box",padding:"11px 12px",borderRadius:8,background:"#101a30",color:"#f5f7ff",border:"1px solid #586787"}} maxLength={1000} value={editAttribution} onChange={e => {setEditAttribution(e.target.value);setEditConfirmed(false);}} />
              </label>
            </div>
            <label style={{display:"grid",gap:6,fontSize:12}}>Supporting license or policy evidence
              <textarea style={{width:"100%",minWidth:0,boxSizing:"border-box",padding:"12px",borderRadius:8,background:"#101a30",color:"#f5f7ff",border:"1px solid #586787",lineHeight:1.5,resize:"vertical"}} rows={5} maxLength={2000} value={editEvidence} onChange={e => {setEditEvidence(e.target.value);setEditConfirmed(false);}} placeholder="Reference, version/date, specific authorization, and reviewed permitted use" />
            </label>
            {isUnverifiedTemplate(editEvidence) && <p style={{margin:0,fontSize:12,color:"#f0c784"}}>The evidence contains a verification placeholder. Replace it with an actual reviewed policy provision or agreement reference before saving.</p>}
            <div style={{display:"grid",gap:12}}>
              <div style={{padding:12,border:"1px solid #455575",borderRadius:9,display:"grid",gap:10}}>
                <strong>1. Use in ReviveAI-produced videos</strong>
                <p style={{margin:0,fontSize:12,color:"#b5c3df"}}>Internal video assembly only. Approval does not enable creator downloads or shared catalog publication.</p>
                <label style={{display:"grid",gap:6,fontSize:12}}>Evidence supporting this permission
                  <textarea rows={2} style={{width:"100%",boxSizing:"border-box",padding:10,background:"#101a30",color:"#f5f7ff",border:"1px solid #586787",borderRadius:8}} value={editInternalEvidence} onChange={e => {setEditInternalEvidence(e.target.value);setEditInternal(false);}} placeholder="Reviewed contract/policy provision and date (optional until approving)"/>
                </label>
                <label style={{display:"flex",gap:9,alignItems:"flex-start",fontSize:12}}><input type="checkbox" checked={editInternal} onChange={e => setEditInternal(e.target.checked)}/> I verified permission for ReviveAI to incorporate this soundtrack into videos.</label>
              </div>
              <div style={{padding:12,border:"1px solid #455575",borderRadius:9,display:"grid",gap:10}}>
                <strong>2. Standalone distribution to creators</strong>
                <p style={{margin:0,fontSize:12,color:"#b5c3df"}}>Required for “Publish to all users.” Verify permission to supply reusable audio files to third-party creators.</p>
                <label style={{display:"flex",gap:9,alignItems:"flex-start",fontSize:12}}><input type="checkbox" checked={editConfirmed} onChange={e => setEditConfirmed(e.target.checked)}/> I verified standalone audio redistribution rights for the shared creator catalog.</label>
              </div>
            </div>
            <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
              <button type="button" className="revai-admin-button" disabled={busy || editLicense.trim().length < 3 || (editEvidence.trim().length > 0 && editEvidence.trim().length < 8) || (editConfirmed && (editEvidence.trim().length < 8 || isUnverifiedTemplate(editEvidence))) || (editInternal && (editInternalEvidence.trim().length < 8 || isUnverifiedTemplate(editInternalEvidence)))} onClick={() => void saveMetadata(track)}>{editConfirmed || editInternal ? "Save notes & approvals" : "Save review notes"}</button>
              <button type="button" className="revai-admin-button" onClick={() => setEditing(null)}>Cancel</button>
            </div>
          </div>}
          <div className="revai-admin-music-actions">
            {(track.status === "DRAFT" || track.status === "PENDING_REVIEW") && <button className="revai-admin-button" disabled={busy} onClick={() => editing === track.track_id ? setEditing(null) : editTrack(track)}>{editing === track.track_id ? "Close rights editor" : "Edit rights & metadata"}</button>}
            {track.status === "DRAFT" && <button className="revai-admin-button" disabled={busy} onClick={() => void change(track, "PENDING_REVIEW")}>Submit for review</button>}
            {track.status === "PENDING_REVIEW" && <button className="revai-admin-button" disabled={busy || !track.standalone_distribution_approved || !track.license_evidence?.trim()} title={!track.standalone_distribution_approved ? "Standalone distribution rights approval required" : "Publish"} onClick={() => void change(track, "PUBLISHED")}>Publish to all users</button>}
            {track.status !== "RETIRED" && <button className="revai-admin-button" disabled={busy} onClick={() => void change(track, "RETIRED")}>Retire</button>}
          </div>
        </article>)}
      </div>
    </div>
  </section>;
}
