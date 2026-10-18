import { useEffect, useRef, useState } from "react";
import { API_BASE_URL, apiFetch } from "../http";

interface MusicTrack { index: number; title: string; category: string; status: string; track_id?: string | null; error?: string; attempt_id?: string; resolution_reason?: string; }
interface MusicBatch { batch_id: string; count: number; model: string; estimated_max_cost_usd: number; created_at: string; }
interface BatchDetail { batch: MusicBatch; tracks: MusicTrack[]; }
const base = `${API_BASE_URL}/api/v1/admin/music-batches`;

export function PlatformLyriaBatchPanel() {
  const [count, setCount] = useState(3);
  const [batch, setBatch] = useState<BatchDetail | null>(null);
  const [batchList, setBatchList] = useState<MusicBatch[]>([]);
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [skipIndex, setSkipIndex] = useState<number | null>(null);
  const [skipReason, setSkipReason] = useState("");
  const [error, setError] = useState("");
  const stopRef = useRef(false);
  const busyRef = useRef(false);
  async function json(url: string, init?: RequestInit) {
    const res = await apiFetch(url, init);
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${(await res.text()).slice(0, 350)}`);
    return res.json();
  }
  async function refreshList() {
    try { const result = await json(base); setBatchList(result.batches || []); }
    catch (e) { setError(String(e)); }
  }
  useEffect(() => { void refreshList(); return () => { stopRef.current = true; }; }, []);
  async function open(id: string) {
    if (busyRef.current) return;
    setError("");
    try { setBatch(await json(`${base}/${encodeURIComponent(id)}`)); }
    catch (e) { setError(String(e)); }
  }
  async function create() {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setError("");
    try {
      const result = await json(base, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({count}) });
      setBatch(result); await refreshList();
    } catch (e) { setError(String(e)); }
    finally { busyRef.current = false; setBusy(false); }
  }
  async function next(): Promise<boolean> {
    if (busyRef.current || !batch) return false;
    busyRef.current = true; setBusy(true); setError("");
    try { setBatch(await json(`${base}/${encodeURIComponent(batch.batch.batch_id)}/generate-next`, {method:"POST"})); return true; }
    catch (e) {
      setError(`${String(e)}. Check the batch before any further generation.`);
      try { setBatch(await json(`${base}/${encodeURIComponent(batch.batch.batch_id)}`)); } catch { /* original error remains */ }
      return false;
    } finally { busyRef.current = false; setBusy(false); }
  }
  async function skipFailed() {
    if (!batch || skipIndex === null || busyRef.current || running || skipReason.trim().length < 12) return;
    const track = batch.tracks.find(t => t.index === skipIndex);
    if (!track || track.status !== "NEEDS_ATTENTION") return;
    if (!window.confirm(`Skip the failed attempt for “${track.title}”? This will preserve its error and possible provider charge. It will NOT regenerate this track.`)) return;
    busyRef.current = true; setBusy(true); setError("");
    try {
      const updated = await json(`${base}/${encodeURIComponent(batch.batch.batch_id)}/tracks/${skipIndex}/skip`, {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({reason: skipReason.trim()}),
      }) as BatchDetail;
      setBatch(updated); setSkipIndex(null); setSkipReason("");
    } catch (e) {
      setError(String(e));
      try { setBatch(await json(`${base}/${encodeURIComponent(batch.batch.batch_id)}`)); } catch { /* preserve primary error */ }
    } finally { busyRef.current = false; setBusy(false); }
  }
  async function runRemaining() {
    if (!batch || busyRef.current || running || attention) return;
    stopRef.current = false;
    setRunning(true);
    const id = batch.batch.batch_id;
    // Sequential requests: one provider charge at a time, halt immediately on uncertain error.
    for (let i = 0; i < pending && !stopRef.current; i++) {
      if (busyRef.current) break;
      busyRef.current = true; setBusy(true);
      try {
        const updated = await json(`${base}/${encodeURIComponent(id)}/generate-next`, {method:"POST"}) as BatchDetail;
        if (stopRef.current) break;
        setBatch(updated);
      } catch (e) {
        setError(`${String(e)}. Generation stopped; inspect the batch before resuming.`);
        try { setBatch(await json(`${base}/${encodeURIComponent(id)}`)); } catch { /* preserve error */ }
        break;
      } finally { busyRef.current = false; setBusy(false); }
    }
    setRunning(false);
  }
  const pending = batch?.tracks.filter(t => t.status === "PENDING").length ?? 0;
  const attention = batch?.tracks.some(t => t.status === "NEEDS_ATTENTION" || t.status === "RUNNING") ?? false;
  return <section className="revai-admin-music-batch" style={{marginBottom: 24, padding: 16, border:"1px solid #36415d",borderRadius:12}}>
    <h3>Generate soundtracks with Google Lyria</h3>
    <p className="revai-admin-notice">Create 3, 10, or 30 distinct instrumental clips. Each generation is a separate paid API request. New music stays in Draft; publication requires rights and quality review.</p>
    {error && <p className="revai-admin-error" role="alert">{error}</p>}
    <div style={{display:"flex",alignItems:"center",gap:12,flexWrap:"wrap"}}>
      <label>Batch size <select value={count} disabled={busy || running} onChange={e=>setCount(Number(e.target.value))}><option value={3}>3 (smoke test)</option><option value={10}>10 (pilot)</option><option value={30}>30 (full pilot)</option></select></label>
      <span>Estimated generation cost: ${(count * 0.04).toFixed(2)} USD</span>
      <button className="revai-admin-button" onClick={()=>void create()} disabled={busy || running}>Create batch plan</button>
    </div>
    {batchList.length > 0 && <div style={{marginTop:12}}><label>Existing batches <select value={batch?.batch.batch_id || ""} onChange={e => void open(e.target.value)} disabled={busy || running}><option value="">Select a batch</option>{batchList.map(b=><option value={b.batch_id} key={b.batch_id}>{b.batch_id.slice(0,18)} · {b.count} tracks</option>)}</select></label></div>}
    {batch && <div style={{marginTop:16}}>
      <strong>{batch.batch.count}-track batch</strong> · {pending} pending · {batch.tracks.filter(t=>t.status==="DRAFT").length} drafts
      {attention && <p className="revai-admin-error">One or more attempts are unresolved. Investigate provider usage and saved assets before proceeding. Automatic retry is disabled.</p>}
      <div style={{display:"flex",gap:8,flexWrap:"wrap",marginTop:8}}>
        <button className="revai-admin-button" disabled={busy || running || pending===0 || attention} onClick={()=>void next()}>{busy ? "Generating…" : "Generate next track"}</button>
        <button className="revai-admin-button" disabled={busy || running || pending===0 || attention} onClick={()=>void runRemaining()}>Generate remaining (sequential)</button>
        {running && <button className="revai-admin-button" onClick={()=>{stopRef.current=true;}}>Stop after current track</button>}
        <button className="revai-admin-button" disabled={busy || running} onClick={()=>void open(batch.batch.batch_id)}>Refresh</button>
      </div>
      <p style={{fontSize:12,opacity:.8}}>Generate remaining makes one request per track, sequentially, while this page stays open. Closing the page stops new requests; in-flight requests may still incur charges. A timeout is not retried automatically. Refresh the catalog to see drafts.</p>
      {batch.tracks.some(t => t.status === "NEEDS_ATTENTION") && <div style={{marginTop:12,padding:12,border:"1px solid #9e7745",borderRadius:8}}>
        <strong>Failed attempt recovery</strong>
        <p style={{fontSize:12}}>Skipping is an administrative acknowledgment, not a retry or a claim that the provider did not charge. Confirm any generated assets and provider usage before proceeding.</p>
        <label>Failed track <select value={skipIndex ?? ""} disabled={busy || running} onChange={e => {setSkipIndex(e.target.value ? Number(e.target.value) : null);setSkipReason("");}}>
          <option value="">Select failed track</option>
          {batch.tracks.filter(t=>t.status==="NEEDS_ATTENTION").map(t=><option key={t.index} value={t.index}>{t.index}. {t.title}</option>)}
        </select></label>
        {skipIndex !== null && <div style={{marginTop:8}}>
          <label style={{display:"block"}}>Investigation / skip reason
            <textarea style={{display:"block",width:"100%",boxSizing:"border-box",marginTop:6}} rows={3} maxLength={1000} value={skipReason} onChange={e=>setSkipReason(e.target.value)} placeholder="Explain the failed attempt, asset checks, and why skipping is safe" />
          </label>
          <button className="revai-admin-button" disabled={busy || running || skipReason.trim().length < 12} onClick={()=>void skipFailed()}>Skip failed attempt after investigation</button>
        </div>}
      </div>}
      <div style={{maxHeight:320,overflowY:"auto",marginTop:10}}>{batch.tracks.map(t=><div key={t.index} style={{padding:"7px 0",borderBottom:"1px solid #36415d",display:"flex",justifyContent:"space-between",gap:12}}><span>{String(t.index).padStart(2,"0")}. {t.title} <small>· {t.category}</small></span><strong>{t.status.replace(/_/g, " ")}</strong></div>)}</div>
    </div>}
  </section>;
}
