import {
  Check,
  CheckCircle2,
  Clipboard,
  FilePenLine,
  Instagram,
  LoaderCircle,
  LockKeyhole,
  PackagePlus,
  RefreshCw,
  Save,
  Send,
  ShieldCheck,
  Sparkles,
  Youtube,
} from "lucide-react";
import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import type { DeliveryPackage, PublishingDraft, PublishingDraftContent } from "../types";

type Platform = "youtube" | "tiktok" | "instagram";

interface Props {
  draft: PublishingDraft | null;
  history: PublishingDraft[];
  deliveryPackage: DeliveryPackage;
  deliveryPackageHistory: DeliveryPackage[];
  resumePending?: boolean;
  action?: "GENERATE" | "SAVE" | "REGENERATE" | "APPROVE" | "PACKAGE" | "FORK" | null;
  error: string | null;
  onGenerate: () => void;
  onSave: (content: PublishingDraftContent) => void;
  onRegenerate: (fields: string[]) => void;
  onApprove: () => void;
  onAddToPackage: () => void;
  onContinueToYouTube: () => void;
  finalVideoApproved: boolean;
  onGoToFinalApproval: () => void;
  onFork: () => void;
  onOpenVersion: (draft: PublishingDraft) => void;
}

const platformFields: Record<Platform, string[]> = {
  youtube: ["youtube.title", "youtube.description", "youtube.hashtags", "youtube.tags", "youtube.thumbnail_text_suggestions"],
  tiktok: ["tiktok.hook", "tiktok.caption", "tiktok.hashtags", "tiktok.cta"],
  instagram: ["instagram.caption_short", "instagram.caption_long", "instagram.hashtags", "instagram.alt_text", "instagram.cta"],
};

function cloneContent(content: PublishingDraftContent): PublishingDraftContent {
  return JSON.parse(JSON.stringify(content)) as PublishingDraftContent;
}

function csvToList(value: string): string[] {
  return value.split(/[\n,]+/).map((item) => item.trim()).filter(Boolean);
}

function hashtagToList(value: string): string[] {
  return value.split(/[\s,]+/).map((item) => item.trim()).filter(Boolean);
}

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }
  return (
    <button className="publishing-inline-button" onClick={copy} type="button">
      {copied ? <Check size={14} /> : <Clipboard size={14} />} {copied ? "Copied" : label}
    </button>
  );
}

function FieldHeader({
  label,
  onRegenerate,
  disabled,
  locked = false,
}: {
  label: string;
  onRegenerate: () => void;
  disabled: boolean;
  locked?: boolean;
}) {
  return (
    <div className="publishing-field-head">
      <label>{label}</label>
      {locked ? (
        <span className="publishing-field-lock"><LockKeyhole size={12} /> Approved version</span>
      ) : (
        <button className="publishing-field-regenerate" onClick={onRegenerate} disabled={disabled} type="button" title={`Regenerate ${label}`}>
          <RefreshCw size={13} /> Regenerate
        </button>
      )}
    </div>
  );
}

export function PublishingAssistantPanel({
  draft,
  history,
  deliveryPackage,
  deliveryPackageHistory,
  resumePending = false,
  action = null,
  error,
  onGenerate,
  onSave,
  onRegenerate,
  onApprove,
  onAddToPackage,
  onContinueToYouTube,
  finalVideoApproved,
  onGoToFinalApproval,
  onFork,
  onOpenVersion,
}: Props) {
  const [platform, setPlatform] = useState<Platform>("youtube");
  const [content, setContent] = useState<PublishingDraftContent | null>(draft ? cloneContent(draft.content) : null);

  useEffect(() => {
    setContent(draft ? cloneContent(draft.content) : null);
  }, [draft?.draft_id]);

  const dirty = useMemo(() => Boolean(draft && content && JSON.stringify(content) !== JSON.stringify(draft.content)), [draft, content]);
  const busy = action !== null || resumePending;
  const isApproved = draft?.status === "APPROVED";
  const allDeliveryPackages = useMemo(() => {
    const byId = new Map<string, DeliveryPackage>();
    [deliveryPackage, ...deliveryPackageHistory].forEach((item) => byId.set(item.package_id, item));
    return [...byId.values()].sort((a, b) => b.package_version - a.package_version);
  }, [deliveryPackage, deliveryPackageHistory]);
  const includedPackage = useMemo(
    () => draft ? allDeliveryPackages.find((item) => item.publishing_draft_id === draft.draft_id) ?? null : null,
    [draft?.draft_id, allDeliveryPackages],
  );
  const included = Boolean(includedPackage);

  function updateSection<T extends Platform>(section: T, patch: Partial<PublishingDraftContent[T]>) {
    setContent((current) => current ? ({ ...current, [section]: { ...current[section], ...patch } }) : current);
  }

  function platformText(): string {
    if (!content) return "";
    if (platform === "youtube") {
      return [content.youtube.title, content.youtube.description, content.youtube.hashtags.join(" "), content.youtube.tags.join(", ")].filter(Boolean).join("\n\n");
    }
    if (platform === "tiktok") {
      return [content.tiktok.hook, content.tiktok.caption, content.tiktok.hashtags.join(" "), content.tiktok.cta].filter(Boolean).join("\n\n");
    }
    return [content.instagram.caption_long, content.instagram.hashtags.join(" "), content.instagram.cta, `Alt text: ${content.instagram.alt_text}`].filter(Boolean).join("\n\n");
  }

  if (!draft) {
    return (
      <section className="publishing-assistant-section" id="publishing-assistant">
        <article className="publishing-assistant-gate glass-card">
          <div className="publishing-assistant-hero-icon"><Sparkles size={27} /></div>
          <div className="publishing-assistant-gate-copy">
            <div className="layer-badge publishing"><Send size={15} /> AI Publishing Assistant</div>
            <span className="eyebrow">Milestone M2C.5 · Package v{deliveryPackage.package_version}</span>
            <h2>Prepare platform-ready copy without touching the finished video.</h2>
            <p>
              Gemini will use the approved story, narration, final-master metadata, and music-rights context to prepare editable drafts for YouTube, TikTok, and Instagram.
            </p>
            <div className="publishing-safety-note"><ShieldCheck size={16} /><span>Generation creates text only. The approved visual master, audio master, QC report, and existing delivery package remain unchanged.</span></div>
            <button className="primary-button publishing-generate-button" onClick={onGenerate} disabled={busy}>
              {busy ? <><LoaderCircle className="spinner" size={17} /> Preparing publishing draft…</> : <><Sparkles size={17} /> Generate publishing draft</>}
            </button>
            {error && <div className="publishing-error" role="alert">{error}</div>}
          </div>
        </article>
      </section>
    );
  }

  if (!content) return null;

  return (
    <section className="publishing-assistant-section" id="publishing-assistant">
      <article className="publishing-assistant-card glass-card">
        <div className="publishing-assistant-head">
          <div>
            <div className="layer-badge publishing"><Send size={15} /> AI Publishing Assistant</div>
            <div className="publishing-heading-line">
              <span className="eyebrow">Milestone M2C.5 · Draft v{draft.version_number}</span>
              {dirty && <span className="publishing-dirty-badge">Unsaved edits</span>}
            </div>
            <h2>Creator-controlled publishing copy</h2>
            <p>{isApproved ? "This approved version is locked to preserve package lineage. Create a new draft version before editing or regenerating." : "Review every field before approval. Saving or regenerating creates a new draft version; prior versions remain available."}</p>
          </div>
          <div className={`publishing-status ${draft.status.toLowerCase()}`}>
            {draft.status === "APPROVED" ? <CheckCircle2 size={18} /> : <FilePenLine size={18} />}
            <span>{draft.status === "APPROVED" ? "Approved" : "Draft"}</span>
          </div>
        </div>

        <div className="publishing-lineage-row publishing-lineage-row-five">
          <div><span>Audio master</span><strong>v{draft.audio_version}</strong></div>
          <div><span>Generated from package</span><strong>v{draft.source_package_version ?? deliveryPackage.package_version}</strong></div>
          <div><span>Draft</span><strong>v{draft.version_number}</strong></div>
          <div><span>Published into</span><strong>{includedPackage ? `Package v${includedPackage.package_version}` : "Not packaged"}</strong></div>
          <div><span>Model</span><strong>{draft.model}</strong></div>
        </div>

        {isApproved && (
          <div className="publishing-approved-banner">
            <LockKeyhole size={15} />
            <div>
              <strong>Approved draft v{draft.version_number} is immutable.</strong>
              <span>{includedPackage ? ` Its exact copy is preserved in delivery package v${includedPackage.package_version}.` : " Create a new version to make changes while this approval stays intact."}</span>
            </div>
          </div>
        )}

        <div className="publishing-toolbar">
          <div className="publishing-tabs" role="tablist" aria-label="Publishing platform">
            <button className={platform === "youtube" ? "active" : ""} onClick={() => setPlatform("youtube")}><Youtube size={16} /> YouTube</button>
            <button className={platform === "tiktok" ? "active" : ""} onClick={() => setPlatform("tiktok")}><Send size={16} /> TikTok</button>
            <button className={platform === "instagram" ? "active" : ""} onClick={() => setPlatform("instagram")}><Instagram size={16} /> Instagram</button>
          </div>
          <div className="publishing-toolbar-actions">
            <CopyButton text={platformText()} label={`Copy ${platform === "youtube" ? "YouTube" : platform === "tiktok" ? "TikTok" : "Instagram"}`} />
            {isApproved ? (
              <button className="secondary-button publishing-edit-version-button" onClick={onFork} disabled={busy}>
                {action === "FORK" ? <LoaderCircle className="spinner" size={15} /> : <FilePenLine size={15} />} Edit as new version
              </button>
            ) : (
              <button className="secondary-button" onClick={() => onRegenerate(platformFields[platform])} disabled={busy || dirty} title={dirty ? "Save or discard your manual edits before regenerating." : undefined}>
                {action === "REGENERATE" ? <LoaderCircle className="spinner" size={15} /> : <RefreshCw size={15} />} Regenerate {platform === "youtube" ? "YouTube" : platform === "tiktok" ? "TikTok" : "Instagram"}
              </button>
            )}
          </div>
        </div>

        {platform === "youtube" && (
          <div className="publishing-editor-grid">
            <div className="publishing-field full">
              <FieldHeader label="Title" onRegenerate={() => onRegenerate(["youtube.title"])} disabled={busy || dirty || isApproved} locked={isApproved} />
              <input readOnly={isApproved} value={content.youtube.title} maxLength={120} onChange={(e: ChangeEvent<HTMLInputElement>) => updateSection("youtube", { title: e.target.value })} />
              <div className="publishing-field-meta"><span>{content.youtube.title.length}/120</span><CopyButton text={content.youtube.title} /></div>
            </div>
            <div className="publishing-field full">
              <FieldHeader label="Description" onRegenerate={() => onRegenerate(["youtube.description"])} disabled={busy || dirty || isApproved} locked={isApproved} />
              <textarea readOnly={isApproved} rows={8} value={content.youtube.description} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => updateSection("youtube", { description: e.target.value })} />
              <div className="publishing-field-meta"><span>Music attribution is appended deterministically when required.</span><CopyButton text={content.youtube.description} /></div>
            </div>
            <div className="publishing-field">
              <FieldHeader label="Hashtags" onRegenerate={() => onRegenerate(["youtube.hashtags"])} disabled={busy || dirty || isApproved} locked={isApproved} />
              <input readOnly={isApproved} value={content.youtube.hashtags.join(" ")} onChange={(e: ChangeEvent<HTMLInputElement>) => updateSection("youtube", { hashtags: hashtagToList(e.target.value) })} />
            </div>
            <div className="publishing-field">
              <FieldHeader label="Search tags / keywords" onRegenerate={() => onRegenerate(["youtube.tags"])} disabled={busy || dirty || isApproved} locked={isApproved} />
              <input readOnly={isApproved} value={content.youtube.tags.join(", ")} onChange={(e: ChangeEvent<HTMLInputElement>) => updateSection("youtube", { tags: csvToList(e.target.value) })} />
            </div>
            <div className="publishing-field full">
              <FieldHeader label="Thumbnail text suggestions" onRegenerate={() => onRegenerate(["youtube.thumbnail_text_suggestions"])} disabled={busy || dirty || isApproved} locked={isApproved} />
              <input readOnly={isApproved} value={content.youtube.thumbnail_text_suggestions.join(", ")} onChange={(e: ChangeEvent<HTMLInputElement>) => updateSection("youtube", { thumbnail_text_suggestions: csvToList(e.target.value).slice(0, 3) })} />
            </div>
          </div>
        )}

        {platform === "tiktok" && (
          <div className="publishing-editor-grid">
            <div className="publishing-field full">
              <FieldHeader label="Hook" onRegenerate={() => onRegenerate(["tiktok.hook"])} disabled={busy || dirty || isApproved} locked={isApproved} />
              <input readOnly={isApproved} value={content.tiktok.hook} onChange={(e: ChangeEvent<HTMLInputElement>) => updateSection("tiktok", { hook: e.target.value })} />
            </div>
            <div className="publishing-field full">
              <FieldHeader label="Caption" onRegenerate={() => onRegenerate(["tiktok.caption"])} disabled={busy || dirty || isApproved} locked={isApproved} />
              <textarea readOnly={isApproved} rows={6} value={content.tiktok.caption} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => updateSection("tiktok", { caption: e.target.value })} />
            </div>
            <div className="publishing-field">
              <FieldHeader label="Hashtags" onRegenerate={() => onRegenerate(["tiktok.hashtags"])} disabled={busy || dirty || isApproved} locked={isApproved} />
              <input readOnly={isApproved} value={content.tiktok.hashtags.join(" ")} onChange={(e: ChangeEvent<HTMLInputElement>) => updateSection("tiktok", { hashtags: hashtagToList(e.target.value) })} />
            </div>
            <div className="publishing-field">
              <FieldHeader label="CTA" onRegenerate={() => onRegenerate(["tiktok.cta"])} disabled={busy || dirty || isApproved} locked={isApproved} />
              <input readOnly={isApproved} value={content.tiktok.cta} onChange={(e: ChangeEvent<HTMLInputElement>) => updateSection("tiktok", { cta: e.target.value })} />
            </div>
          </div>
        )}

        {platform === "instagram" && (
          <div className="publishing-editor-grid">
            <div className="publishing-field full">
              <FieldHeader label="Short caption" onRegenerate={() => onRegenerate(["instagram.caption_short"])} disabled={busy || dirty || isApproved} locked={isApproved} />
              <textarea readOnly={isApproved} rows={3} value={content.instagram.caption_short} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => updateSection("instagram", { caption_short: e.target.value })} />
            </div>
            <div className="publishing-field full">
              <FieldHeader label="Long caption" onRegenerate={() => onRegenerate(["instagram.caption_long"])} disabled={busy || dirty || isApproved} locked={isApproved} />
              <textarea readOnly={isApproved} rows={7} value={content.instagram.caption_long} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => updateSection("instagram", { caption_long: e.target.value })} />
            </div>
            <div className="publishing-field full">
              <FieldHeader label="Accessibility alt text" onRegenerate={() => onRegenerate(["instagram.alt_text"])} disabled={busy || dirty || isApproved} locked={isApproved} />
              <textarea readOnly={isApproved} rows={4} value={content.instagram.alt_text} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => updateSection("instagram", { alt_text: e.target.value })} />
            </div>
            <div className="publishing-field">
              <FieldHeader label="Hashtags" onRegenerate={() => onRegenerate(["instagram.hashtags"])} disabled={busy || dirty || isApproved} locked={isApproved} />
              <input readOnly={isApproved} value={content.instagram.hashtags.join(" ")} onChange={(e: ChangeEvent<HTMLInputElement>) => updateSection("instagram", { hashtags: hashtagToList(e.target.value) })} />
            </div>
            <div className="publishing-field">
              <FieldHeader label="CTA" onRegenerate={() => onRegenerate(["instagram.cta"])} disabled={busy || dirty || isApproved} locked={isApproved} />
              <input readOnly={isApproved} value={content.instagram.cta} onChange={(e: ChangeEvent<HTMLInputElement>) => updateSection("instagram", { cta: e.target.value })} />
            </div>
          </div>
        )}

        <div className="publishing-action-bar">
          <div className="publishing-action-left">
            {isApproved ? (
              <div className="publishing-immutable-note"><LockKeyhole size={14} /><span>Approved versions are read-only. Use <strong>Edit as new version</strong> to continue without changing this approval.</span></div>
            ) : (
              <>
                <button className="secondary-button" onClick={() => setContent(cloneContent(draft.content))} disabled={!dirty || busy}>Discard edits</button>
                <button className="secondary-button" onClick={() => onSave(content)} disabled={!dirty || busy}>
                  {action === "SAVE" ? <LoaderCircle className="spinner" size={15} /> : <Save size={15} />} Save as new version
                </button>
              </>
            )}
          </div>
          <div className="publishing-action-right">
            {!isApproved ? (
              <button className="primary-button" onClick={onApprove} disabled={busy || dirty} title={dirty ? "Save your edits as a new version before approval." : undefined}>
                {action === "APPROVE" ? <LoaderCircle className="spinner" size={16} /> : <CheckCircle2 size={16} />} Approve publishing copy
              </button>
            ) : included ? (
              <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", justifyContent: "flex-end" }}>
                <div className="publishing-package-included"><CheckCircle2 size={16} /> Included in delivery package v{includedPackage?.package_version}</div>
                {includedPackage?.package_id === deliveryPackage.package_id && (
                  <button
                    className={finalVideoApproved ? "primary-button" : "secondary-button"}
                    type="button"
                    disabled={busy}
                    onClick={finalVideoApproved ? onContinueToYouTube : onGoToFinalApproval}
                    title={finalVideoApproved ? "Go to YouTube publishing" : "Final creator approval must be completed before publishing"}
                  >
                    {finalVideoApproved ? <Youtube size={16} /> : <ShieldCheck size={16} />}
                    {finalVideoApproved ? "Continue to YouTube Publishing" : "Step 1: Review final video"}
                  </button>
                )}
              </div>
            ) : (
              <button className="primary-button" onClick={onAddToPackage} disabled={busy}>
                {action === "PACKAGE" ? <LoaderCircle className="spinner" size={16} /> : <PackagePlus size={16} />} Add approved copy to delivery package
              </button>
            )}
          </div>
        </div>
        {!isApproved && dirty && <div className="publishing-save-hint">Manual edits are local until you choose <strong>Save as new version</strong>. ReviveAI will not overwrite the currently saved draft.</div>}
        {error && <div className="publishing-error" role="alert">{error}</div>}
      </article>

      {history.length > 1 && (
        <article className="publishing-history glass-card">
          <div className="publishing-history-head"><div><span className="eyebrow">Version history</span><h3>Publishing drafts</h3></div><span>{history.length} saved version{history.length === 1 ? "" : "s"}</span></div>
          <div className="publishing-history-list">
            {history.map((item) => (
              <button key={item.draft_id} className={`publishing-history-row ${item.draft_id === draft.draft_id ? "active" : ""}`} onClick={() => onOpenVersion(item)}>
                <div><strong>Draft v{item.version_number}</strong><span>{new Date(item.updated_at).toLocaleString()} · based on package v{item.source_package_version ?? "—"}{allDeliveryPackages.find((pkg) => pkg.publishing_draft_id === item.draft_id) ? ` · packaged as v${allDeliveryPackages.find((pkg) => pkg.publishing_draft_id === item.draft_id)?.package_version}` : ""}</span></div>
                <span className={`publishing-history-status ${item.status.toLowerCase()}`}>{item.status === "APPROVED" ? <CheckCircle2 size={13} /> : <FilePenLine size={13} />}{item.status === "APPROVED" ? "Approved" : "Draft"}</span>
              </button>
            ))}
          </div>
        </article>
      )}

      <div className="publishing-methodology"><ShieldCheck size={14} /><span>{draft.generation_note} AI copy remains editable and is never auto-published.</span></div>
    </section>
  );
}
