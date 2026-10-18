import { useState } from "react";
import { recoverMissingSqueakerAudio } from "./api";

/** Temporary development control. Delete after audio v2 has been verified. */
export default function DevAudioRecoveryButton() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  if (!import.meta.env.DEV) return null;

  const run = async () => {
    if (busy) return;
    if (!window.confirm(
      "Recover The Case of the Missing Squeaker?\n\n" +
      "This creates ONE new audio-finishing job using the approved visual assembly. " +
      "Google Cloud TTS/audio processing may incur charges. It does not generate Veo clips or publish the video."
    )) return;

    setBusy(true);
    setMessage("Checking original job and creating audio v2…");
    try {
      const job = await recoverMissingSqueakerAudio();
      const result = `Created audio v${job.version_number}: ${job.job_id} (${job.stage})`;
      setMessage(result);
      console.info("[DevAudioRecovery] New audio job", job);
    } catch (error) {
      const result = error instanceof Error ? error.message : String(error);
      setMessage(`Recovery stopped: ${result}`);
      console.error("[DevAudioRecovery]", error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside style={{position:"fixed",right:16,bottom:16,zIndex:9999,maxWidth:340,padding:12,
      background:"#fff",border:"1px solid #a3a3a3",borderRadius:12,
      boxShadow:"0 8px 24px rgba(0,0,0,0.15)",fontFamily:"sans-serif",fontSize:12,color:"#222"}}>
      <div style={{fontWeight:700,marginBottom:8}}>DEV ONLY · Audio recovery</div>
      <button type="button" onClick={run} disabled={busy}
        style={{background:busy?"#aaa":"#2563eb",color:"white",border:0,borderRadius:8,
          padding:"9px 12px",cursor:busy?"not-allowed":"pointer",fontWeight:600}}>
        {busy ? "Creating…" : "Recover Missing Squeaker Audio"}
      </button>
      {message && <div role="status" style={{marginTop:8,overflowWrap:"anywhere",lineHeight:1.5}}>{message}</div>}
    </aside>
  );
}
