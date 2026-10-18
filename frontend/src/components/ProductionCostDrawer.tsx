import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Clock, DollarSign, Server, X } from "lucide-react";
import { getProductionCostDetails } from "../api";

type ProductionLike = {
  id?: string;
  title?: string | null;
  status?: string | null;
  provider?: string | null;
  model?: string | null;
  cost_status?: string | null;
  transaction_count?: number | null;
  estimated_cost?: number | null;
  actual_cost?: number | null;
  operations?: Array<{
    id?: string;
    operation_id?: string;
    status?: string | null;
    type?: string | null;
    created_at?: string | null;
    completed_at?: string | null;
  }>;
};

export default function ProductionCostDrawer({
  production,
  onClose,
}: {
  production: ProductionLike | null;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<ProductionLike | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!production?.id) {
      setDetail(null);
      return () => {
        cancelled = true;
      };
    }

    setLoading(true);
    getProductionCostDetails(production.id)
      .then((value) => {
        if (!cancelled) setDetail(value as ProductionLike);
      })
      .catch((error) => {
        console.error("Failed loading production cost detail", error);
        if (!cancelled) setDetail(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [production]);

  if (!production) return null;

  const data = detail || production;
  const hasCost = data.cost_status === "RECORDED" || Number(data.transaction_count || 0) > 0;
  const operations = data.operations || [];

  return (
    <>
      <div className="production-drawer-overlay" onClick={onClose} />

      <aside className="production-cost-drawer">
        <div className="production-drawer-header">
          <div>
            <span>Production Cost</span>
            <h3>{data.title || production.title || production.id}</h3>
          </div>
          <button onClick={onClose} aria-label="Close production cost details">
            <X size={18} />
          </button>
        </div>

        <div className="production-drawer-section">
          <div className="production-drawer-grid">
            <DrawerMetric icon={<Server />} label="Status" value={data.status || "-"} />
            <DrawerMetric icon={<Server />} label="Provider" value={data.provider || (hasCost ? "Google Veo" : "-")} />
            <DrawerMetric icon={<Server />} label="Model" value={data.model || "-"} />
          </div>
        </div>

        <div className="production-drawer-section">
          <h4>
            <DollarSign size={16} />
            Cost Summary
          </h4>

          {!hasCost ? (
            <p className="drawer-empty">
              This production is in the release/production history, but no generation-cost transaction was recorded for it.
            </p>
          ) : (
            <>
              <div className="drawer-cost-row">
                <span>Estimated</span>
                <strong>${Number(data.estimated_cost || 0).toFixed(2)}</strong>
              </div>
              <div className="drawer-cost-row">
                <span>Actual</span>
                <strong>${Number(data.actual_cost || 0).toFixed(2)}</strong>
              </div>
            </>
          )}
        </div>

        <div className="production-drawer-section">
          <h4>
            <Clock size={16} />
            Generation Timeline
          </h4>

          {loading && <p className="drawer-empty">Loading operation history...</p>}
          {!loading && operations.length === 0 && <p className="drawer-empty">No operation history available</p>}

          {operations.map((item, index) => (
            <div key={item.id || item.operation_id || index} className="drawer-timeline-item">
              <strong>{item.status || item.type || "Operation"}</strong>
              <span>{item.completed_at || item.created_at || "-"}</span>
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}

function DrawerMetric({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="drawer-metric">
      {icon}
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
      </div>
    </div>
  );
}
