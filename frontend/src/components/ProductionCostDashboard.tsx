import {
  BarChart3,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  DollarSign,
  ImageOff,
  LoaderCircle,
  RefreshCw,
  Search,
  TrendingDown,
  WalletCards,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { getProductionCostDashboard } from "../api";
import ProductionCostDrawer from "./ProductionCostDrawer";

type ProductionCostRow = {
  id: string;
  title?: string | null;
  status?: string | null;
  provider?: string | null;
  model?: string | null;
  created_at?: string | null;
  release_at?: string | null;
  publication_id?: string | null;
  youtube_video_id?: string | null;
  youtube_url?: string | null;
  estimated_cost?: number | null;
  actual_cost?: number | null;
  variance?: number | null;
  cost_status?: "RECORDED" | "UNAVAILABLE" | string | null;
  transaction_count?: number | null;
};

type ProductionCostDashboardData = {
  total_spend: number;
  reserved_budget: number;
  remaining_budget: number;
  average_cost_per_video: number;
  productions: ProductionCostRow[];
  updated_at?: string;
};

type PageToken = number | "ellipsis-left" | "ellipsis-right";

type ProductionCostDashboardProps = {
  cacheKey: string;
};

type DashboardCache = {
  data: ProductionCostDashboardData | null;
  loadedAt: number;
  search: string;
  statuses: string[];
  page: number;
  pageSize: number;
};

const CACHE_STALE_MS = 3 * 60 * 1000;
const AUTO_REFRESH_MS = 60 * 1000;
const PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const;

const dashboardCaches = new Map<string, DashboardCache>();

function createDashboardCache(): DashboardCache {
  return {
    data: null,
    loadedAt: 0,
    search: "",
    statuses: [],
    page: 1,
    pageSize: 25,
  };
}

function getDashboardCache(cacheKey: string): DashboardCache {
  const normalizedKey = cacheKey.trim() || "anonymous";
  const existing = dashboardCaches.get(normalizedKey);
  if (existing) return existing;

  const created = createDashboardCache();
  dashboardCaches.set(normalizedKey, created);
  return created;
}

function dateValue(value?: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatMoney(value?: number | null): string {
  return `$${Number(value || 0).toFixed(2)}`;
}

function formatStatus(value?: string | null): string {
  const normalized = String(value || "UNKNOWN").trim();
  if (!normalized) return "Unknown";
  return normalized
    .replace(/[_-]+/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatPublishedDate(value?: string | null): { date: string; time: string } | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return null;

  return {
    date: new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    }).format(parsed),
    time: new Intl.DateTimeFormat(undefined, {
      hour: "numeric",
      minute: "2-digit",
    }).format(parsed),
  };
}

function youtubeVideoIdFromUrl(value?: string | null): string | null {
  if (!value) return null;
  try {
    const parsed = new URL(value);
    if (parsed.hostname.includes("youtu.be")) {
      return parsed.pathname.split("/").filter(Boolean)[0] || null;
    }
    if (parsed.hostname.includes("youtube.com")) {
      if (parsed.pathname.startsWith("/shorts/")) {
        return parsed.pathname.split("/").filter(Boolean)[1] || null;
      }
      return parsed.searchParams.get("v");
    }
  } catch {
    return null;
  }
  return null;
}

function thumbnailUrl(production: ProductionCostRow): string | null {
  const videoId = production.youtube_video_id || youtubeVideoIdFromUrl(production.youtube_url);
  return videoId ? `https://i.ytimg.com/vi/${encodeURIComponent(videoId)}/mqdefault.jpg` : null;
}

function pageTokens(currentPage: number, pageCount: number): PageToken[] {
  if (pageCount <= 7) {
    return Array.from({ length: pageCount }, (_, index) => index + 1);
  }

  const tokens: PageToken[] = [1];

  if (currentPage > 4) tokens.push("ellipsis-left");

  const start = Math.max(2, currentPage - 1);
  const end = Math.min(pageCount - 1, currentPage + 1);

  if (currentPage <= 4) {
    for (let page = 2; page <= 5; page += 1) tokens.push(page);
  } else if (currentPage >= pageCount - 3) {
    for (let page = pageCount - 4; page <= pageCount - 1; page += 1) tokens.push(page);
  } else {
    for (let page = start; page <= end; page += 1) tokens.push(page);
  }

  if (currentPage < pageCount - 3) tokens.push("ellipsis-right");
  tokens.push(pageCount);
  return tokens;
}

export function ProductionCostDashboard({ cacheKey }: ProductionCostDashboardProps) {
  const initialCache = getDashboardCache(cacheKey);

  const [data, setData] = useState<ProductionCostDashboardData | null>(() => initialCache.data);
  const [selectedProduction, setSelectedProduction] = useState<ProductionCostRow | null>(null);
  const [search, setSearch] = useState(() => initialCache.search);
  const [selectedStatuses, setSelectedStatuses] = useState<string[]>(() => initialCache.statuses);
  const [page, setPage] = useState(() => initialCache.page);
  const [pageSize, setPageSize] = useState(() => initialCache.pageSize);
  const [initialLoading, setInitialLoading] = useState(() => !initialCache.data);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusMenuOpen, setStatusMenuOpen] = useState(false);

  const mountedRef = useRef(true);
  const activeCacheKeyRef = useRef(cacheKey);
  const requestsInFlightRef = useRef<Set<string>>(new Set());
  const statusMenuRef = useRef<HTMLDivElement | null>(null);

  activeCacheKeyRef.current = cacheKey;

  const loadDashboard = useCallback(async (mode: "initial" | "background" | "manual") => {
    const requestCacheKey = cacheKey;
    if (requestsInFlightRef.current.has(requestCacheKey)) return;
    requestsInFlightRef.current.add(requestCacheKey);

    const isCurrentCache = () =>
      mountedRef.current && activeCacheKeyRef.current === requestCacheKey;

    if (isCurrentCache()) {
      if (mode === "initial") setInitialLoading(true);
      if (mode === "manual") setRefreshing(true);
      setError(null);
    }

    try {
      const response = (await getProductionCostDashboard()) as ProductionCostDashboardData;
      const cache = getDashboardCache(requestCacheKey);
      cache.data = response;
      cache.loadedAt = Date.now();

      if (isCurrentCache()) setData(response);
    } catch (loadError) {
      console.error("Failed loading production costs", loadError);
      if (isCurrentCache()) {
        setError(loadError instanceof Error ? loadError.message : "Unable to load production costs.");
      }
    } finally {
      requestsInFlightRef.current.delete(requestCacheKey);
      if (isCurrentCache()) {
        setInitialLoading(false);
        setRefreshing(false);
      }
    }
  }, [cacheKey]);

  useEffect(() => {
    mountedRef.current = true;
    activeCacheKeyRef.current = cacheKey;

    const cache = getDashboardCache(cacheKey);
    setData(cache.data);
    setSelectedProduction(null);
    setSearch(cache.search);
    setSelectedStatuses(cache.statuses);
    setPage(cache.page);
    setPageSize(cache.pageSize);
    setInitialLoading(!cache.data);
    setRefreshing(false);
    setError(null);
    setStatusMenuOpen(false);

    const hasCache = Boolean(cache.data);
    const cacheIsStale = Date.now() - cache.loadedAt >= CACHE_STALE_MS;

    if (!hasCache) {
      void loadDashboard("initial");
    } else if (cacheIsStale) {
      void loadDashboard("background");
    }

    const interval = window.setInterval(() => {
      void loadDashboard("background");
    }, AUTO_REFRESH_MS);

    return () => {
      mountedRef.current = false;
      window.clearInterval(interval);
    };
  }, [cacheKey, loadDashboard]);

  useEffect(() => {
    const cache = getDashboardCache(cacheKey);
    cache.search = search;
    cache.statuses = selectedStatuses;
    cache.page = page;
    cache.pageSize = pageSize;
  }, [cacheKey, search, selectedStatuses, page, pageSize]);

  useEffect(() => {
    if (!statusMenuOpen) return;

    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!statusMenuRef.current?.contains(target)) setStatusMenuOpen(false);
    };

    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [statusMenuOpen]);

  const productions = data?.productions ?? [];

  const availableStatuses = useMemo(() => {
    const values = new Set<string>();
    productions.forEach((production) => {
      const status = String(production.status || "UNKNOWN").trim() || "UNKNOWN";
      values.add(status);
    });
    return Array.from(values).sort((left, right) => formatStatus(left).localeCompare(formatStatus(right)));
  }, [productions]);

  useEffect(() => {
    if (selectedStatuses.length === 0) return;
    const available = new Set(availableStatuses);
    const validStatuses = selectedStatuses.filter((status) => available.has(status));
    if (validStatuses.length !== selectedStatuses.length) {
      setSelectedStatuses(validStatuses);
    }
  }, [availableStatuses, selectedStatuses]);

  const filteredProductions = useMemo(() => {
    const query = search.trim().toLowerCase();
    const selected = new Set(selectedStatuses);

    return productions
      .filter((production) => {
        if (!query) return true;
        return [production.title, production.status, production.id, production.publication_id]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(query));
      })
      .filter((production) => {
        if (selected.size === 0) return true;
        const status = String(production.status || "UNKNOWN").trim() || "UNKNOWN";
        return selected.has(status);
      })
      .sort((a, b) => {
        const releaseDelta = dateValue(b.release_at) - dateValue(a.release_at);
        return releaseDelta !== 0 ? releaseDelta : dateValue(b.created_at) - dateValue(a.created_at);
      });
  }, [productions, search, selectedStatuses]);

  const pageCount = Math.max(1, Math.ceil(filteredProductions.length / pageSize));

  useEffect(() => {
    if (page > pageCount) setPage(pageCount);
  }, [page, pageCount]);

  const pagedProductions = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filteredProductions.slice(start, start + pageSize);
  }, [filteredProductions, page, pageSize]);

  const firstVisible = filteredProductions.length === 0 ? 0 : (page - 1) * pageSize + 1;
  const lastVisible = Math.min(page * pageSize, filteredProductions.length);
  const hasActiveFilters = Boolean(search.trim()) || selectedStatuses.length > 0;

  function changeSearch(value: string) {
    setSearch(value);
    setPage(1);
  }

  function toggleStatus(status: string) {
    setSelectedStatuses((current) =>
      current.includes(status)
        ? current.filter((item) => item !== status)
        : [...current, status],
    );
    setPage(1);
  }

  function clearFilters() {
    setSearch("");
    setSelectedStatuses([]);
    setPage(1);
  }

  function changePageSize(value: number) {
    setPageSize(value);
    setPage(1);
  }

  if (initialLoading && !data) {
    return <ProductionCostLoadingState />;
  }

  return (
    <section className="production-cost-dashboard">
      <div className="production-cost-header">
        <div>
          <span className="eyebrow">Production finance</span>
          <h2>Production Cost Dashboard</h2>
          <p>Track generation spend, budget usage, and production cost history.</p>
        </div>

        <button
          className="production-cost-refresh"
          type="button"
          onClick={() => void loadDashboard("manual")}
          disabled={refreshing}
          aria-busy={refreshing}
        >
          <RefreshCw size={15} className={refreshing ? "production-cost-spin" : undefined} />
          {refreshing ? "Refreshing" : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="production-cost-error" role="alert">
          <span>{error}</span>
          {data && <small>Showing the last successfully loaded dashboard data.</small>}
        </div>
      )}

      <div className="production-cost-kpi-grid">
        <CostCard icon={<DollarSign />} title="Total Spend" value={data?.total_spend} />
        <CostCard icon={<WalletCards />} title="Reserved Budget" value={data?.reserved_budget} />
        <CostCard icon={<TrendingDown />} title="Remaining Budget" value={data?.remaining_budget} />
        <CostCard icon={<BarChart3 />} title="Average Cost / Video" value={data?.average_cost_per_video} />
      </div>

      <div className="production-cost-controls">
        <label className="production-cost-search">
          <Search size={16} aria-hidden="true" />
          <span className="sr-only">Search productions</span>
          <input
            placeholder="Search productions..."
            value={search}
            onChange={(event) => changeSearch(event.target.value)}
          />
          {search && (
            <button type="button" onClick={() => changeSearch("")} aria-label="Clear search">
              <X size={14} />
            </button>
          )}
        </label>

        <div className="production-cost-status-filter" ref={statusMenuRef}>
          <button
            className={`production-cost-status-trigger ${selectedStatuses.length > 0 ? "active" : ""}`}
            type="button"
            aria-haspopup="menu"
            aria-expanded={statusMenuOpen}
            onClick={() => setStatusMenuOpen((current) => !current)}
          >
            <span>
              {selectedStatuses.length === 0
                ? "All statuses"
                : selectedStatuses.length === 1
                  ? formatStatus(selectedStatuses[0])
                  : `${selectedStatuses.length} statuses`}
            </span>
            <ChevronDown size={15} />
          </button>

          {statusMenuOpen && (
            <div className="production-cost-status-menu" role="menu">
              <div className="production-cost-status-menu-head">
                <strong>Filter by status</strong>
                {selectedStatuses.length > 0 && (
                  <button type="button" onClick={() => { setSelectedStatuses([]); setPage(1); }}>
                    Clear
                  </button>
                )}
              </div>

              <label className="production-cost-status-option">
                <input
                  type="checkbox"
                  checked={selectedStatuses.length === 0}
                  onChange={() => { setSelectedStatuses([]); setPage(1); }}
                />
                <span>All statuses</span>
                <em>{productions.length}</em>
              </label>

              {availableStatuses.map((status) => {
                const count = productions.filter(
                  (production) => (String(production.status || "UNKNOWN").trim() || "UNKNOWN") === status,
                ).length;

                return (
                  <label className="production-cost-status-option" key={status}>
                    <input
                      type="checkbox"
                      checked={selectedStatuses.includes(status)}
                      onChange={() => toggleStatus(status)}
                    />
                    <span>{formatStatus(status)}</span>
                    <em>{count}</em>
                  </label>
                );
              })}
            </div>
          )}
        </div>

        <div className="production-cost-result-count" aria-live="polite">
          <strong>{filteredProductions.length}</strong>
          <span>{filteredProductions.length === 1 ? "production" : "productions"}</span>
        </div>
      </div>

      {hasActiveFilters && (
        <div className="production-cost-active-filters">
          <span>Filtered results</span>
          {selectedStatuses.map((status) => (
            <button key={status} type="button" onClick={() => toggleStatus(status)}>
              {formatStatus(status)} <X size={12} />
            </button>
          ))}
          <button className="production-cost-clear-filters" type="button" onClick={clearFilters}>
            Clear filters
          </button>
        </div>
      )}

      <div className="production-cost-table-shell">
        <div className="production-cost-table-scroll">
          <div className="production-cost-table">
            <div className="production-cost-row production-cost-row-header">
              <span>Production</span>
              <span>Published</span>
              <span>Status</span>
              <span>Estimated</span>
              <span>Actual</span>
              <span>Variance</span>
            </div>

            {pagedProductions.map((production) => {
              const hasCost = production.cost_status === "RECORDED" || Number(production.transaction_count || 0) > 0;
              const variance = Number(
                production.variance ?? Number(production.actual_cost || 0) - Number(production.estimated_cost || 0),
              );
              const published = formatPublishedDate(production.release_at);

              return (
                <button
                  key={production.id}
                  className="production-cost-row production-cost-data-row"
                  type="button"
                  onClick={() => setSelectedProduction(production)}
                >
                  <span className="production-cost-production-cell">
                    <ProductionThumbnail production={production} />
                    <span className="production-cost-production-copy">
                      <strong title={production.title || production.id}>{production.title || production.id}</strong>
                      <small title={production.id}>{production.id}</small>
                    </span>
                  </span>

                  <span className="production-cost-published-cell">
                    {published ? (
                      <>
                        <strong>{published.date}</strong>
                        <small>{published.time}</small>
                      </>
                    ) : (
                      <>
                        <strong>Not published</strong>
                        <small>No release time yet</small>
                      </>
                    )}
                  </span>

                  <span className="production-cost-status-cell">
                    <span className="production-status">{formatStatus(production.status)}</span>
                    {!hasCost && <small>Cost unavailable</small>}
                  </span>

                  <span className="production-cost-money-cell">
                    {hasCost ? formatMoney(production.estimated_cost) : "—"}
                  </span>
                  <span className="production-cost-money-cell">
                    {hasCost ? formatMoney(production.actual_cost) : "—"}
                  </span>
                  <span
                    className={`production-cost-money-cell ${
                      !hasCost ? "" : variance > 0 ? "variance-negative" : "variance-positive"
                    }`}
                  >
                    {hasCost ? `${variance >= 0 ? "+" : ""}$${variance.toFixed(2)}` : "—"}
                  </span>
                </button>
              );
            })}

            {pagedProductions.length === 0 && (
              <div className="production-cost-empty">
                <strong>No productions match the current filters.</strong>
                {hasActiveFilters && (
                  <button type="button" onClick={clearFilters}>Clear filters</button>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="production-cost-pagination">
          <div className="production-cost-pagination-summary">
            <span>
              Showing <strong>{firstVisible}–{lastVisible}</strong> of <strong>{filteredProductions.length}</strong>
            </span>
            <label>
              Rows per page
              <select value={pageSize} onChange={(event) => changePageSize(Number(event.target.value))}>
                {PAGE_SIZE_OPTIONS.map((size) => (
                  <option key={size} value={size}>{size}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="production-cost-page-buttons" aria-label="Production cost pages">
            <button
              type="button"
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              disabled={page <= 1 || filteredProductions.length === 0}
              aria-label="Previous page"
            >
              <ChevronLeft size={16} />
            </button>

            {pageTokens(page, pageCount).map((token) =>
              typeof token === "number" ? (
                <button
                  key={token}
                  type="button"
                  className={token === page ? "active" : ""}
                  aria-current={token === page ? "page" : undefined}
                  onClick={() => setPage(token)}
                  disabled={filteredProductions.length === 0}
                >
                  {token}
                </button>
              ) : (
                <span key={token} className="production-cost-page-ellipsis">…</span>
              ),
            )}

            <button
              type="button"
              onClick={() => setPage((current) => Math.min(pageCount, current + 1))}
              disabled={page >= pageCount || filteredProductions.length === 0}
              aria-label="Next page"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </div>

      <ProductionCostDrawer
        production={selectedProduction}
        onClose={() => setSelectedProduction(null)}
      />
    </section>
  );
}

function ProductionThumbnail({ production }: { production: ProductionCostRow }) {
  const [failed, setFailed] = useState(false);
  const url = thumbnailUrl(production);

  if (!url || failed) {
    return (
      <span className="production-cost-thumbnail production-cost-thumbnail-placeholder" aria-hidden="true">
        <ImageOff size={18} />
      </span>
    );
  }

  return (
    <span className="production-cost-thumbnail" aria-hidden="true">
      <img src={url} alt="" loading="lazy" onError={() => setFailed(true)} />
    </span>
  );
}

function ProductionCostLoadingState() {
  return (
    <section className="production-cost-dashboard" aria-busy="true" aria-live="polite">
      <div className="production-cost-header">
        <div>
          <span className="eyebrow">Production finance</span>
          <h2>Production Cost Dashboard</h2>
          <p>Track generation spend, budget usage, and production cost history.</p>
        </div>
        <div className="production-cost-loading-badge">
          <LoaderCircle size={17} className="production-cost-spin" />
          Loading production costs…
        </div>
      </div>

      <div className="production-cost-kpi-grid">
        {Array.from({ length: 4 }, (_, index) => (
          <div className="production-cost-kpi-card production-cost-skeleton-card" key={index}>
            <span className="production-cost-skeleton production-cost-skeleton-icon" />
            <span className="production-cost-skeleton-copy">
              <span className="production-cost-skeleton production-cost-skeleton-label" />
              <span className="production-cost-skeleton production-cost-skeleton-value" />
            </span>
          </div>
        ))}
      </div>

      <div className="production-cost-table-shell production-cost-loading-table">
        <div className="production-cost-loading-center">
          <LoaderCircle size={28} className="production-cost-spin" />
          <strong>Loading production history</strong>
          <span>Preparing costs, publication details, and thumbnails.</span>
        </div>
        {Array.from({ length: 6 }, (_, index) => (
          <div className="production-cost-skeleton-row" key={index}>
            <span className="production-cost-skeleton production-cost-skeleton-thumb" />
            <span className="production-cost-skeleton production-cost-skeleton-line" />
            <span className="production-cost-skeleton production-cost-skeleton-line short" />
            <span className="production-cost-skeleton production-cost-skeleton-line short" />
          </div>
        ))}
      </div>
    </section>
  );
}

function CostCard({
  icon,
  title,
  value,
}: {
  icon: ReactNode;
  title: string;
  value?: number | null;
}) {
  return (
    <div className="production-cost-kpi-card">
      <div className="production-cost-kpi-icon">{icon}</div>
      <div>
        <span>{title}</span>
        <strong>{formatMoney(value)}</strong>
      </div>
    </div>
  );
}
