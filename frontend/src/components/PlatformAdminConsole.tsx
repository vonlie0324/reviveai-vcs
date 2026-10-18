import { Fragment, useEffect, useState } from "react";
import { ArrowLeft, ChevronLeft, ChevronRight, RefreshCw, ShieldCheck, Users, Wallet, Music2 } from "lucide-react";
import { API_BASE_URL, apiFetch } from "../http";
import "./PlatformAdminConsole.css";
import { PlatformSoundtracksPanel } from "./PlatformSoundtracksPanel";

type AdminUser = {
  uid: string;
  email: string | null;
  display_name: string | null;
  disabled: boolean;
  email_verified: boolean;
  created_at: number | null;
  last_sign_in_at: number | null;
  platform_role: string | null;
};
type ProductionCost = {provenance?: Record<string, number>; production_id: string; production_title: string | null; transaction_count: number; actual_cost_usd: number; estimated_cost_usd: number; reserved_estimate_usd: number};
type TitleGroup = {title: string; jobs: ProductionCost[]; production_job_count: number; transaction_count: number; actual_cost_usd: number; estimated_cost_usd: number; reserved_estimate_usd: number};
type CostGroup = {owner?: {uid: string; display_name: string} | null;unique_title_count?: number; title_groups?: TitleGroup[]; provenance?: Record<string, number>; channel_title: string | null; productions: ProductionCost[]; tenant_namespace: string | null; attribution: string; channel_id: string | null; transaction_count: number; production_count: number; actual_cost_usd: number; estimated_cost_usd: number; reserved_estimate_usd: number};
type CostSummary = {owner_directory_incomplete?: boolean; owner_directory_error?: boolean; undated_transaction_count_in_scan?: number; daily_trend?: {date: string; actual_cost_usd: number; estimated_cost_usd: number; reserved_estimate_usd: number; transaction_count: number}[]; date_from?: string | null; date_to?: string | null;scope: string; currency: string; scanned_transactions: number; has_more: boolean; max_scan: number; channel_attribution_available: boolean; connection_registry_scan_incomplete: boolean; total_actual_cost_usd: number; total_estimated_cost_usd: number; total_reserved_estimate_usd: number; groups: CostGroup[]; generated_at: string};
const provenanceLabel = (raw: string) => {
  const key = raw.toUpperCase();
  if (key === "CHECKPOINT_MIGRATION:CHECKPOINT_RECOVERED") return "Recovered from historical checkpoint";
  return raw.replace(/_/g, " ").replace(":", " · ").toLowerCase();
};
const localIsoDate = (date: Date) => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`;
const datePreset = (preset: string): [string,string] => {
  const today = new Date(); const end = localIsoDate(today);
  if (preset === "all") return ["", ""];
  if (preset === "today") return [end,end];
  if (preset === "month") return [localIsoDate(new Date(today.getFullYear(),today.getMonth(),1)),end];
  const start = new Date(today); start.setDate(today.getDate()-(preset === "7" ? 6 : 29));
  return [localIsoDate(start),end];
};
const usd = (value: number) => new Intl.NumberFormat("en-US", {style: "currency", currency: "USD"}).format(value);
type UserPage = { users: AdminUser[]; next_page_token: string | null };
const dateText = (timestamp: number | null) => timestamp ? new Date(timestamp).toLocaleDateString() : "—";

export function PlatformAdminConsole({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState<"users" | "costs" | "soundtracks">("users");
  const [costs, setCosts] = useState<CostSummary | null>(null);
  const [costLoading, setCostLoading] = useState(false);
  const [costError, setCostError] = useState<string | null>(null);
  const [costReload, setCostReload] = useState(0);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [dateMode, setDateMode] = useState("all");
  const datesInvalid = Boolean(fromDate && toDate && fromDate > toDate);
  const selectDatePreset = (preset: string) => {
    setDateMode(preset);
    const [from,to] = datePreset(preset);
    setFromDate(from); setToDate(to);
  };
  const [expandedChannels, setExpandedChannels] = useState<string[]>([]);
  const [expandedTitles, setExpandedTitles] = useState<string[]>([]);
  useEffect(() => {
    if (tab !== "costs") return;
    const controller = new AbortController();
    setCostLoading(true); setCostError(null);
    const qs = new URLSearchParams({limit: "500"});
    if (fromDate) qs.set("from_date", fromDate);
    if (toDate) qs.set("to_date", toDate);
    if (datesInvalid) {setCostLoading(false); return;}
    apiFetch(`${API_BASE_URL}/api/v1/admin/costs/summary?${qs}`, {signal: controller.signal})
      .then(async response => {
        if (!response.ok) throw new Error(`Unable to load cost snapshot (HTTP ${response.status}).`);
        return response.json() as Promise<CostSummary>;
      }).then(value => {if (!controller.signal.aborted) setCosts(value);})
      .catch(err => {if (!controller.signal.aborted) setCostError(err instanceof Error ? err.message : "Request failed");})
      .finally(() => {if (!controller.signal.aborted) setCostLoading(false);});
    return () => controller.abort();
  }, [tab, costReload, fromDate, toDate, datesInvalid]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [history, setHistory] = useState<(string | null)[]>([null]);
  const [page, setPage] = useState(0);
  const [nextToken, setNextToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    if (tab !== "users") return;
    const controller = new AbortController();
    const token = history[page];
    setLoading(true);
    setError(null);
    const qs = new URLSearchParams({ limit: "25" });
    if (token) qs.set("page_token", token);
    apiFetch(`${API_BASE_URL}/api/v1/admin/users?${qs}`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(response.status === 403 ? "Administrator access is required." : `Unable to load user directory (HTTP ${response.status}).`);
        return response.json() as Promise<UserPage>;
      })
      .then(data => { if (!controller.signal.aborted) { setUsers(data.users); setNextToken(data.next_page_token); } })
      .catch(err => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Request failed"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [page, history, reload, tab]);
  const filtered = users.filter(user => `${user.display_name || ""} ${user.email || ""} ${user.uid}`.toLowerCase().includes(search.toLowerCase()));
  const goNext = () => {
    if (!nextToken) return;
    setHistory(current => [...current.slice(0, page + 1), nextToken]);
    setPage(current => current + 1);
    setSearch("");
  };
  return <div className="revai-admin-page">
    <header className="revai-admin-header">
      <div><span className="revai-admin-eyebrow"><ShieldCheck size={15}/> PLATFORM ADMINISTRATION</span><h1>Platform administration</h1><p>Manage registered accounts, production costs, and platform soundtracks.</p></div>
      <button onClick={onBack} className="revai-admin-button"><ArrowLeft size={16}/> Creator workspace</button>
    </header>
    <nav className="revai-admin-tabs" aria-label="Admin modules">
      <button className={tab === "users" ? "selected" : ""} onClick={() => setTab("users")}><Users size={16}/> Registered users</button>
      <button className={tab === "costs" ? "selected" : ""} onClick={() => setTab("costs")}><Wallet size={16}/> Production costs</button>
      <button className={tab === "soundtracks" ? "selected" : ""} onClick={() => setTab("soundtracks")}><Music2 size={16}/> Platform Soundtracks</button>
    </nav>
    {tab === "soundtracks" ? <PlatformSoundtracksPanel /> : tab === "costs" ? <section className="revai-admin-surface">
      <div className="revai-admin-toolbar"><div className="revai-admin-section-title"><Wallet size={18}/> Production-cost ledger</div><button className="revai-admin-button" disabled={costLoading} onClick={() => setCostReload(x => x+1)}><RefreshCw size={15}/> Refresh</button></div>
      <div className="revai-admin-date-toolbar">
        <label>Period <select value={dateMode} onChange={e => selectDatePreset(e.target.value)}><option value="all">All available</option><option value="today">Today</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="month">This month</option><option value="custom">Custom range</option></select></label>
        <label>From <input aria-label="Cost start date" type="date" value={fromDate} onChange={e => {setDateMode("custom");setFromDate(e.target.value);}} /></label>
        <label>To <input aria-label="Cost end date" type="date" value={toDate} onChange={e => {setDateMode("custom");setToDate(e.target.value);}} /></label>
        {datesInvalid && <span role="alert">Start date must not be after end date.</span>}
      </div>
      <p className="revai-admin-notice">Read-only ledger snapshot, not provider-reconciled billing. Channel IDs are taken from transactions; tenant associations are shown as verified only when a saved YouTube connection matches. Actual and estimated values are separate measurements and must not be added.</p>
      {costError && <p className="revai-admin-error" role="alert">{costError}</p>}
      {costLoading && <p className="revai-admin-notice">Loading cost records…</p>}
      {costs && <>
        {costs.has_more && <p className="revai-admin-error" role="status">Partial results: showing the first {costs.scanned_transactions} ledger transactions; totals are not platform-wide.</p>}
        {(costs.undated_transaction_count_in_scan || 0) > 0 && (fromDate || toDate) && <p className="revai-admin-notice">{costs.undated_transaction_count_in_scan} undated records excluded from the selected period.</p>}
        {costs.owner_directory_incomplete && <p className="revai-admin-notice">Account ownership could not be fully verified. Unverified owners remain hidden.</p>}
        <div className="revai-admin-metrics"><div><span>Recorded actual cost</span><strong>{usd(costs.total_actual_cost_usd)}</strong></div><div><span>Estimated cost</span><strong>{usd(costs.total_estimated_cost_usd)}</strong></div><div><span>Reserved estimate</span><strong>{usd(costs.total_reserved_estimate_usd)}</strong></div><div><span>Transactions scanned</span><strong>{costs.scanned_transactions}</strong></div></div>
        {(costs.daily_trend || []).length > 0 && <div className="revai-admin-trends"><strong>Daily recorded costs (UTC)</strong><p>Actual amounts by transaction date; recovered ledger values are not independent provider invoices.</p><div className="revai-admin-trend-bars">{(costs.daily_trend || []).map(day => {const max = Math.max(0.01,...(costs.daily_trend || []).map(d => d.actual_cost_usd));return <div key={day.date} className="revai-admin-trend-day" title={`${day.date}: ${usd(day.actual_cost_usd)}`}><div className="revai-admin-trend-track"><div style={{height: `${Math.max(day.actual_cost_usd > 0 ? 3 : 0,day.actual_cost_usd / max * 100)}%`}} /></div><small>{day.date.slice(5)}</small><small>{usd(day.actual_cost_usd)}</small></div>;})}</div></div>}
        {costs.connection_registry_scan_incomplete && <p className="revai-admin-error">Tenant-connection scan was truncated. Some channel owners may be unverified.</p>}
        <div className="revai-admin-overflow"><table><thead><tr><th>Channel / attribution</th><th>Production jobs / titles</th><th>Transactions</th><th>Actual (USD)</th><th>Estimated (USD)</th><th>Reserved estimate (USD)</th></tr></thead><tbody>{costs.groups.map((g, index) => {
          const key = `${g.attribution}:${g.channel_id || g.tenant_namespace || index}`;
          const expanded = expandedChannels.includes(key);
          return <Fragment key={key}><tr><td>{g.productions.length > 0 && <button className="revai-admin-expand" aria-label={`${expanded ? "Collapse" : "Expand"} productions`} aria-expanded={expanded} onClick={() => setExpandedChannels(prev => expanded ? prev.filter(x => x !== key) : [...prev, key])}>{expanded ? "▾" : "▸"}</button>}<strong>{g.channel_title || g.channel_id || (g.tenant_namespace ? `Tenant ${g.tenant_namespace.slice(0, 12)}…` : "Unattributed")}</strong><small>{g.attribution === "CHANNEL_CONNECTION_MATCH" ? `Matches saved tenant YouTube connection${g.owner ? ` · Account: ${g.owner.display_name}` : " · Account owner unverified"}` : g.attribution === "CHANNEL_ID_ONLY" ? "Channel recorded in ledger · ownership unverified" : g.attribution === "TENANT" ? "Tenant recorded · channel unknown" : "No known channel or tenant"}</small></td><td>{g.production_count} jobs · {g.unique_title_count ?? "—"} titles</td><td>{g.transaction_count}</td><td>{usd(g.actual_cost_usd)}</td><td>{usd(g.estimated_cost_usd)}</td><td>{usd(g.reserved_estimate_usd)}</td></tr>{expanded && <tr className="revai-admin-details-row"><td colSpan={6}>
            <strong>Content titles for {g.channel_title || g.channel_id || "this group"}</strong>
            <p className="revai-admin-detail-help">Each title may contain multiple distinct production jobs. Amounts are recorded ledger estimates or actuals, not independently verified provider invoices.</p>
            <table><thead><tr><th>Title / production job</th><th>Jobs / transactions</th><th>Actual</th><th>Estimated</th><th>Reserved</th></tr></thead><tbody>
            {(g.title_groups || []).map((t, titleIndex) => {
              const titleKey = `${key}:${titleIndex}`;
              const titleExpanded = expandedTitles.includes(titleKey);
              return <Fragment key={titleKey}><tr><td><button className="revai-admin-expand" aria-label={`${titleExpanded ? "Collapse" : "Expand"} jobs for ${t.title}`} aria-expanded={titleExpanded} onClick={() => setExpandedTitles(prev => titleExpanded ? prev.filter(x => x !== titleKey) : [...prev, titleKey])}>{titleExpanded ? "▾" : "▸"}</button><strong>{t.title}</strong></td><td>{t.production_job_count} jobs · {t.transaction_count} transactions</td><td>{usd(t.actual_cost_usd)}</td><td>{usd(t.estimated_cost_usd)}</td><td>{usd(t.reserved_estimate_usd)}</td></tr>
              {titleExpanded && t.jobs.map(p => <tr key={p.production_id} className="revai-admin-job-row"><td><strong>Production job</strong><small>{p.production_id}</small><small>{Object.entries(p.provenance || {}).map(([label, count]) => `${provenanceLabel(label)} (${count})`).join(" · ") || "Provenance unavailable"}</small></td><td>{p.transaction_count} transactions</td><td>{usd(p.actual_cost_usd)}</td><td>{usd(p.estimated_cost_usd)}</td><td>{usd(p.reserved_estimate_usd)}</td></tr>)}</Fragment>;
            })}
            {(!g.title_groups || g.title_groups.length === 0) && g.productions.map(p => <tr key={p.production_id}><td><strong>{p.production_title || "Untitled"}</strong><small>{p.production_id}</small></td><td>{p.transaction_count}</td><td>{usd(p.actual_cost_usd)}</td><td>{usd(p.estimated_cost_usd)}</td><td>{usd(p.reserved_estimate_usd)}</td></tr>)}
            </tbody></table>
            <p className="revai-admin-detail-help">Ledger provenance: {Object.entries(g.provenance || {}).map(([label, count]) => `${provenanceLabel(label)} (${count})`).join(" · ") || "Not available"}. Tenant owner not inferred from channel connection.</p>
          </td></tr>}</Fragment>;
        })}{costs.groups.length === 0 && <tr><td colSpan={6}>No ledger transactions found.</td></tr>}</tbody></table></div>
        <footer className="revai-admin-pagination">Snapshot: {new Date(costs.generated_at).toLocaleString()} · {costs.has_more ? "Partial" : "All ledger records in this query"}</footer>
      </>}
    </section> : <section className="revai-admin-surface">
      <div className="revai-admin-toolbar"><div className="revai-admin-section-title"><Users size={18}/> User directory</div><div className="revai-admin-toolbar-actions"><input aria-label="Filter users on current page" placeholder="Find on this page" value={search} onChange={e => setSearch(e.target.value)}/><button className="revai-admin-button" disabled={loading} onClick={() => setReload(x => x+1)}><RefreshCw size={15}/> Refresh</button></div></div>
      {error && <p className="revai-admin-error" role="alert">{error}</p>}
      <div className="revai-admin-overflow"><table><thead><tr><th>User</th><th>Account status</th><th>Role</th><th>Registered</th><th>Last sign-in</th></tr></thead><tbody>
        {filtered.map(user => <tr key={user.uid}><td><strong>{user.display_name || user.email || "Unnamed user"}</strong><small>{user.email || user.uid}</small></td><td>{user.disabled ? "Disabled" : "Active"}</td><td>{user.platform_role === "PLATFORM_ADMIN" ? "Platform Admin" : "Creator"}</td><td>{dateText(user.created_at)}</td><td>{dateText(user.last_sign_in_at)}</td></tr>)}
        {!loading && !error && filtered.length === 0 && <tr><td colSpan={5}>No users found on this page.</td></tr>}
      </tbody></table></div>
      <footer className="revai-admin-pagination"><span>{loading ? "Loading users…" : `${users.length} accounts on page ${page+1}`}</span><div><button className="revai-admin-button" disabled={loading || page === 0} onClick={() => {setPage(p => p-1); setSearch("");}}><ChevronLeft size={15}/> Previous</button><button className="revai-admin-button" disabled={loading || !nextToken} onClick={goNext}>Next <ChevronRight size={15}/></button></div></footer>
    </section>}
  </div>;
}
