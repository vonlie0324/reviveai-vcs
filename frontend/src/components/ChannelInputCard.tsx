import { ArrowRight, Check, Link2, ShieldCheck, Youtube } from "lucide-react";
import { FormEvent } from "react";

interface Props {
  url: string;
  onUrlChange: (value: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
  context?: "first" | "add" | "refresh";
}

export function ChannelInputCard({ url, onUrlChange, onSubmit, disabled, context = "add" }: Props) {
  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit();
  }

  const isRefresh = context === "refresh";
  const isFirst = context === "first";

  return (
    <section className="input-card glass-card first-workspace-input-card">
      <div className="input-icon" aria-hidden="true">
        <Youtube size={22} />
      </div>
      <div className="input-copy">
        <span className="eyebrow">{isRefresh ? "Refresh channel evidence" : "Start with evidence"}</span>
        <h2>{isRefresh ? "Reconnect this saved channel" : "Paste any YouTube link"}</h2>
        <p>
          {isRefresh
            ? "ReviveAI will rebuild the public channel snapshot without changing any saved production."
            : "Use a channel, video, or Short URL. ReviveAI resolves the channel and analyzes its public archive before AI interpretation begins."}
        </p>
      </div>

      <form className="url-form" onSubmit={submit}>
        <div className="url-field-wrap">
          <Link2 size={19} aria-hidden="true" />
          <input
            value={url}
            onChange={(event) => onUrlChange(event.target.value)}
            placeholder="https://youtube.com/@yourchannel"
            autoComplete="off"
            aria-label="YouTube channel or video URL"
            autoFocus={isFirst}
          />
        </div>
        <button className="primary-button" type="submit" disabled={disabled || !url.trim()}>
          {isRefresh ? "Refresh intelligence" : "Analyze channel"}
          <ArrowRight size={18} aria-hidden="true" />
        </button>
      </form>

      {!isRefresh && (
        <div className="onboarding-steps" aria-label="What happens next">
          <span><b>1</b><small>Resolve channel</small></span>
          <span><b>2</b><small>Analyze archive</small></span>
          <span><b>3</b><small>Start creating</small></span>
        </div>
      )}

      <div className="supported-row" aria-label="Supported YouTube link formats">
        <span>@handle</span>
        <span>Channel URL</span>
        <span>Video URL</span>
        <span>Short URL</span>
      </div>

      <div className="input-trust-note">
        {isRefresh ? <Check size={14} aria-hidden="true" /> : <ShieldCheck size={14} aria-hidden="true" />}
        <span>{isRefresh ? "Saved productions remain unchanged." : "No YouTube account connection required. Public data only; saved work stays private to your signed-in workspace."}</span>
      </div>
    </section>
  );
}
