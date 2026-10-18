import {
  Archive,
  Captions,
  CheckCircle2,
  Download,
  FileJson2,
  FileText,
  Image as ImageIcon,
  LoaderCircle,
  Music2,
  PackageCheck,
  ShieldCheck,
  Video,
} from "lucide-react";
import { deliveryPackageAssetUrl } from "../api";
import type { DeliveryPackage, DeliveryPackageAsset } from "../types";

interface Props {
  deliveryPackage: DeliveryPackage | null;
  pending: boolean;
  resumePending?: boolean;
  error: string | null;
  audioVersion: number;
  history?: DeliveryPackage[];
  onCreate: () => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function AssetIcon({ asset }: { asset: DeliveryPackageAsset }) {
  if (asset.kind === "MASTER_VIDEO") return <Video size={16} />;
  if (asset.kind === "CAPTIONS_SRT" || asset.kind === "CAPTIONS_VTT") return <Captions size={16} />;
  if (asset.kind === "THUMBNAIL") return <ImageIcon size={16} />;
  if (asset.kind === "MUSIC_ATTRIBUTION") return <Music2 size={16} />;
  if (asset.kind === "PRODUCTION_SUMMARY" || asset.kind === "DELIVERY_QC") return <FileJson2 size={16} />;
  return <FileText size={16} />;
}

export function DeliveryPackagePanel({ deliveryPackage, pending, resumePending = false, error, audioVersion, history = [], onCreate }: Props) {
  if (!deliveryPackage) {
    return (
      <section className="delivery-package-section" id="delivery-package">
        <article className="delivery-package-gate glass-card">
          <div className="delivery-package-gate-icon"><Archive size={27} /></div>
          <div>
            <div className="layer-badge package"><PackageCheck size={15} /> Delivery Package</div>
            <span className="eyebrow">Milestone M2C.4 · Audio master v{audioVersion}</span>
            <h2>Package the verified master for handoff.</h2>
            <p>
              ReviveAI will bundle the approved MP4, captions, thumbnail, publishing copy, music rights record,
              production metadata, and the exact QC report that cleared this audio version.
            </p>
            <div className="delivery-package-lock-note"><ShieldCheck size={16} /><span>The verified visual and audio masters are copied only. Package creation never regenerates media.</span></div>
            <button className="primary-button delivery-package-create" onClick={onCreate} disabled={pending || resumePending}>
              {pending ? <><LoaderCircle className="spinner" size={17} /> Creating delivery package…</> : resumePending ? <><LoaderCircle className="spinner" size={17} /> Checking for saved package…</> : <><Archive size={17} /> Create delivery package</>}
            </button>
            {error && <div className="delivery-package-error" role="alert">{error}</div>}
          </div>
        </article>
        {history.length > 0 && (
          <article className="delivery-package-history glass-card">
            <div className="delivery-package-assets-head"><div><span className="eyebrow">Previous exports</span><h3>Delivery package history</h3></div><span>{history.length} saved package{history.length === 1 ? "" : "s"}</span></div>
            <div className="delivery-package-history-list">
              {history.map((item) => (
                <div className="delivery-package-history-row" key={item.package_id}>
                  <div><strong>Package v{item.package_version}</strong><span>Audio master v{item.audio_version} · {new Date(item.generated_at).toLocaleString()}</span></div>
                  <a className="secondary-button" href={deliveryPackageAssetUrl(item.zip_asset.asset_url)} download><Download size={15} /> Download</a>
                </div>
              ))}
            </div>
          </article>
        )}
      </section>
    );
  }

  const zipUrl = deliveryPackageAssetUrl(deliveryPackage.zip_asset.asset_url);
  return (
    <section className="delivery-package-section" id="delivery-package">
      <article className="delivery-package-ready glass-card">
        <div className="delivery-package-ready-head">
          <div>
            <div className="layer-badge package"><PackageCheck size={15} /> Delivery Package</div>
            <span className="eyebrow">Milestone {deliveryPackage.publishing_draft_id ? "M2C.5" : "M2C.4"} · Package v{deliveryPackage.package_version}</span>
            <h2>{deliveryPackage.publishing_draft_id ? "Publishing bundle ready" : "Delivery bundle ready"}</h2>
            <p>Audio master v{deliveryPackage.audio_version}, QC report {deliveryPackage.qc_report_id}{deliveryPackage.publishing_draft_version ? `, and publishing draft v${deliveryPackage.publishing_draft_version}` : ""} are locked into this package lineage.</p>
          </div>
          <div className="delivery-package-ready-badge"><CheckCircle2 size={22} /><span>Ready</span></div>
        </div>

        <div className="delivery-package-lineage">
          <div><span>Audio master</span><strong>v{deliveryPackage.audio_version}</strong></div>
          <div><span>Package</span><strong>v{deliveryPackage.package_version}</strong></div>
          <div><span>Files</span><strong>{deliveryPackage.assets.length}</strong></div>
          <div><span>ZIP size</span><strong>{formatBytes(deliveryPackage.zip_asset.size_bytes)}</strong></div>
        </div>

        <a className="primary-button delivery-package-download" href={zipUrl} download>
          <Download size={17} /> Download delivery package .ZIP
        </a>
        {error && <div className="delivery-package-error" role="alert">{error}</div>}
      </article>

      <article className="delivery-package-assets glass-card">
        <div className="delivery-package-assets-head">
          <div><span className="eyebrow">Package contents</span><h3>Individual delivery files</h3></div>
          <span>{deliveryPackage.root_folder_name}</span>
        </div>
        <div className="delivery-package-asset-list">
          {deliveryPackage.assets.map((asset) => (
            <div className="delivery-package-asset" key={asset.key}>
              <div className="delivery-package-asset-icon"><AssetIcon asset={asset} /></div>
              <div className="delivery-package-asset-copy">
                <strong>{asset.label}</strong>
                <span>{asset.filename} · {formatBytes(asset.size_bytes)}</span>
              </div>
              <a className="secondary-button" href={deliveryPackageAssetUrl(asset.asset_url)} download title={`Download ${asset.label}`}>
                <Download size={15} /> Download
              </a>
            </div>
          ))}
        </div>
      </article>

      {history.length > 1 && (
        <article className="delivery-package-history glass-card">
          <div className="delivery-package-assets-head"><div><span className="eyebrow">Version history</span><h3>Previous delivery packages</h3></div><span>Packages are never overwritten</span></div>
          <div className="delivery-package-history-list">
            {history.filter((item) => item.package_id !== deliveryPackage.package_id).map((item) => (
              <div className="delivery-package-history-row" key={item.package_id}>
                <div><strong>Package v{item.package_version}</strong><span>Audio master v{item.audio_version} · {new Date(item.generated_at).toLocaleString()}</span></div>
                <a className="secondary-button" href={deliveryPackageAssetUrl(item.zip_asset.asset_url)} download><Download size={15} /> Download</a>
              </div>
            ))}
          </div>
        </article>
      )}

      <div className="delivery-package-methodology"><ShieldCheck size={14} /><span>{deliveryPackage.methodology_notice}</span></div>
    </section>
  );
}
