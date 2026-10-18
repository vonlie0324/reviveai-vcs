import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Download,
  FileCheck2,
  Info,
  PackageCheck,
  PlayCircle,
  RefreshCcw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { audioAssetUrl } from "../api";
import type {
  AudioFinishingJob,
  DeliveryQcCheck,
  DeliveryQcCheckStatus,
  DeliveryQcReport,
} from "../types";

interface Props {
  audioJob: AudioFinishingJob;
  report: DeliveryQcReport | null;
  pending: boolean;
  resumePending?: boolean;
  error: string | null;
  onRun: () => void;
  packageReady?: boolean;
  packagePending?: boolean;
  onCreatePackage?: () => void;
  acknowledgmentPending?: boolean;
  onAcknowledge?: (reportId: string) => void;
}

const STATUS_ORDER: Record<DeliveryQcCheckStatus, number> = {
  FAIL: 0,
  WARN: 1,
  PASS: 2,
  INFO: 3,
};

function StatusIcon({ status }: { status: DeliveryQcCheckStatus }) {
  if (status === "PASS") return <CheckCircle2 size={16} />;
  if (status === "WARN") return <AlertTriangle size={16} />;
  if (status === "FAIL") return <XCircle size={16} />;
  return <Info size={16} />;
}

function statusCopy(report: DeliveryQcReport) {
  if (report.overall_status === "READY") {
    return {
      title: "Ready for delivery",
      copy: "All blocking delivery checks passed. This approved master is technically ready for packaging and export.",
    };
  }
  if (report.overall_status === "REVIEW") {
    return {
      title: "Ready with review notes",
      copy: "No blocking failure was found, but one or more warnings should be reviewed by the creator before export.",
    };
  }
  return {
    title: "Delivery blocked",
    copy: "At least one blocking check failed. Resolve the failed item before treating this master as delivery-ready.",
  };
}

function groupStatus(checks: DeliveryQcCheck[]): DeliveryQcCheckStatus {
  if (checks.some((item) => item.status === "FAIL")) return "FAIL";
  if (checks.some((item) => item.status === "WARN")) return "WARN";
  if (checks.some((item) => item.status === "PASS")) return "PASS";
  return "INFO";
}

export function FinalDeliveryQcPanel({
  audioJob,
  report,
  pending,
  resumePending = false,
  error,
  onRun,
  packageReady = false,
  packagePending = false,
  onCreatePackage,
  acknowledgmentPending = false,
  onAcknowledge,
}: Props) {
  const result = audioJob.result;
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => { setConfirmed(false); }, [report?.report_id]);
  const grouped = useMemo(() => {
    const groups = new Map<string, DeliveryQcCheck[]>();
    for (const check of report?.checks ?? []) {
      const bucket = groups.get(check.category) ?? [];
      bucket.push(check);
      groups.set(check.category, bucket);
    }
    for (const checks of groups.values()) {
      checks.sort((a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status] || a.label.localeCompare(b.label));
    }
    return [...groups.entries()];
  }, [report]);

  useEffect(() => {
    if (report && report.overall_status !== "READY") setDetailsOpen(true);
  }, [report?.report_id, report?.overall_status]);

  if (!result) return null;
  const videoUrl = audioAssetUrl(result.delivery_video.asset_url);

  if (!report) {
    return (
      <section className="delivery-qc-section" id="final-delivery-qc">
        <article className="delivery-qc-gate glass-card">
          <div className="delivery-qc-gate-media">
            <video controls playsInline preload="metadata" src={videoUrl} />
          </div>
          <div className="delivery-qc-gate-copy">
            <div className="layer-badge qc"><ShieldCheck size={15} /> Final Delivery QC</div>
            <span className="eyebrow">Milestone M2C.3 · Delivery readiness</span>
            <h2>Verify the approved master before export.</h2>
            <p>
              ReviveAI will inspect the final container, decode integrity, duration, portrait resolution, codecs, loudness, peak safety,
              long silence, audio/video alignment, narration completion, captions, rights metadata, attribution, and approved visual-master lineage.
            </p>
            <div className="delivery-qc-lock-note">
              <FileCheck2 size={16} />
              <span>This is an inspection only. No visual or audio asset is regenerated.</span>
            </div>
            <button className="primary-button delivery-qc-run" onClick={onRun} disabled={pending || resumePending}>
              {pending ? <><Activity className="spinner" size={17} /> Running final delivery check…</> : resumePending ? <><Activity className="spinner" size={17} /> Checking for saved QC…</> : <><Activity size={17} /> Run final delivery check</>}
            </button>
            {error && <div className="delivery-qc-error" role="alert"><AlertTriangle size={16} /><span>{error}</span></div>}
          </div>
        </article>
      </section>
    );
  }

  const status = statusCopy(report);
  const ready = report.overall_status === "READY" || (report.overall_status === "REVIEW" && Boolean(report.human_acknowledgment?.report_id === report.report_id && report.human_acknowledgment?.audio_version === report.audio_version && report.fail_count === 0));

  function previewMaster() {
    if (!detailsOpen) setDetailsOpen(true);
    window.setTimeout(() => document.getElementById("delivery-qc-player")?.scrollIntoView({ behavior: "smooth", block: "center" }), 60);
  }

  function packageAction() {
    if (packageReady) {
      document.getElementById("delivery-package")?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    onCreatePackage?.();
  }

  return (
    <section className="delivery-qc-section" id="final-delivery-qc">
      <article className={`delivery-qc-summary glass-card status-${report.overall_status.toLowerCase()}`}>
        <div className="delivery-qc-summary-head">
          <div>
            <div className="layer-badge qc"><ShieldCheck size={15} /> Final Delivery QC</div>
            <span className="eyebrow">Milestone M2C.3 · Audio master v{report.audio_version}</span>
            <h2>{status.title}</h2>
            <p>{status.copy}</p>
          </div>
          <div className={`delivery-qc-verdict status-${report.overall_status.toLowerCase()}`}>
            {report.overall_status === "BLOCKED" ? <XCircle size={24} /> : report.overall_status === "REVIEW" ? <AlertTriangle size={24} /> : <CheckCircle2 size={24} />}
            <span>{report.overall_status === "BLOCKED" ? "Blocked" : report.overall_status === "REVIEW" ? "Review" : "Ready"}</span>
          </div>
        </div>

        <div className="delivery-qc-stats">
          <div><strong>{report.pass_count}</strong><span>Passed</span></div>
          <div><strong>{report.warn_count}</strong><span>Warnings</span></div>
          <div><strong>{report.fail_count}</strong><span>Failures</span></div>
          <div><strong>v{report.audio_version}</strong><span>Audio master</span></div>
        </div>

        <div className="delivery-qc-category-strip">
          {grouped.map(([category, checks]) => {
            const status = groupStatus(checks);
            return (
              <div className={`delivery-qc-category-chip status-${status.toLowerCase()}`} key={category}>
                <StatusIcon status={status} />
                <span>{category}</span>
                <strong>{checks.filter((item) => item.status === "PASS").length}/{checks.length}</strong>
              </div>
            );
          })}
        </div>

        {report.overall_status === "REVIEW" && !ready && report.fail_count === 0 && (
          <div className="delivery-qc-review-acknowledgment" style={{ padding: 16, margin: "12px 0", border: "1px solid #a97935", borderRadius: 12, display: "grid", gap: 12 }}>
            <strong>Review warning before continuing to Publishing</strong>
            <p style={{ margin: 0 }}>The automated QC warning remains recorded. Watch the full delivery master and verify the flagged items before continuing.</p>
            <label style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
              <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
              <span>I reviewed the complete final master and verified the reported warnings, including caption and narration synchronization.</span>
            </label>
            <button className="primary-button" disabled={!confirmed || acknowledgmentPending || !onAcknowledge} onClick={() => onAcknowledge?.(report.report_id)}>
              {acknowledgmentPending ? "Saving acknowledgment…" : "Approve review notes and continue"}
            </button>
          </div>
        )}
        {report.overall_status === "REVIEW" && ready && <p role="status" style={{ color: "#7dd9b3" }}>Creator review saved for this QC report. The warning remains on record; you may continue to packaging.</p>}
        <div className="delivery-qc-actions">
          <button className="secondary-button" onClick={previewMaster}><PlayCircle size={16} /> Preview final master</button>
          <a className="secondary-button" href={videoUrl} download><Download size={16} /> Download master</a>
          {ready && onCreatePackage && (
            <button className="primary-button delivery-qc-package-button" onClick={packageAction} disabled={packagePending}>
              {packagePending ? <><Activity className="spinner" size={16} /> Creating package…</> : packageReady ? <><PackageCheck size={16} /> View delivery package</> : <><PackageCheck size={16} /> Create delivery package</>}
            </button>
          )}
          <button className="secondary-button" onClick={onRun} disabled={pending}>
            {pending ? <><Activity className="spinner" size={16} /> Checking…</> : <><RefreshCcw size={16} /> Rerun QC</>}
          </button>
          <button className="secondary-button delivery-qc-detail-toggle" onClick={() => setDetailsOpen((value) => !value)} aria-expanded={detailsOpen}>
            <ChevronDown size={16} className={detailsOpen ? "open" : ""} /> {detailsOpen ? "Hide detailed QC" : "View detailed QC"}
          </button>
        </div>
        {error && <div className="delivery-qc-error" role="alert"><AlertTriangle size={16} /><span>{error}</span></div>}
      </article>

      {detailsOpen && (
        <div className="delivery-qc-details-wrap">
          <div className="delivery-qc-grid">
            <article className="delivery-qc-player glass-card" id="delivery-qc-player">
              <video controls playsInline preload="metadata" src={videoUrl} />
              <div className="delivery-qc-player-meta">
                <div><span>Approved delivery master</span><strong>Audio master v{report.audio_version}</strong></div>
                <div><span>QC generated</span><strong>{new Date(report.generated_at).toLocaleString()}</strong></div>
              </div>
            </article>

            <div className="delivery-qc-check-groups">
              {grouped.map(([category, checks]) => {
                const attention = checks.some((item) => item.status === "FAIL" || item.status === "WARN");
                const status = groupStatus(checks);
                return (
                  <details className={`delivery-qc-check-group glass-card status-${status.toLowerCase()}`} key={category} open={attention}>
                    <summary className="delivery-qc-check-group-head">
                      <span className="delivery-qc-check-group-label"><StatusIcon status={status} /> {category}</span>
                      <span className="delivery-qc-check-group-meta"><small>{checks.length} check{checks.length === 1 ? "" : "s"}</small><ChevronDown size={15} /></span>
                    </summary>
                    <div className="delivery-qc-check-list">
                      {checks.map((check) => (
                        <div className={`delivery-qc-check status-${check.status.toLowerCase()}`} key={check.key}>
                          <div className="delivery-qc-check-icon"><StatusIcon status={check.status} /></div>
                          <div className="delivery-qc-check-copy">
                            <div className="delivery-qc-check-title-row">
                              <strong>{check.label}</strong>
                              <span>{check.status}</span>
                            </div>
                            <p>{check.summary}</p>
                            {(check.metric || check.expected) && (
                              <div className="delivery-qc-check-metrics">
                                {check.metric && <span><small>Measured</small>{check.metric}</span>}
                                {check.expected && <span><small>Expected</small>{check.expected}</span>}
                              </div>
                            )}
                            {check.detail && <small className="delivery-qc-detail">{check.detail}</small>}
                          </div>
                        </div>
                      ))}
                    </div>
                  </details>
                );
              })}
            </div>
          </div>

          <div className="delivery-qc-methodology">
            <ShieldCheck size={14} />
            <span>{report.methodology_notice}</span>
          </div>
        </div>
      )}
    </section>
  );
}
