import { useEffect, useState } from "react";
import Card from "../components/Card";
import Heatmap from "../components/Heatmap";
import EditableNumberField from "../components/EditableNumberField";
import EditableMatrixField from "../components/EditableMatrixField";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import { useDistribution, useResolveDistribution } from "../hooks/useDistribution";

export default function RegionalLoad() {
  const { data, isLoading, isError, error } = useDistribution();
  const resolve = useResolveDistribution();

  const [capacities, setCapacities] = useState(null);
  const [costMatrix, setCostMatrix] = useState(null);

  useEffect(() => {
    if (data && capacities === null) {
      setCapacities(data.demand);
      setCostMatrix(data.cost);
    }
  }, [data, capacities]);

  if (isLoading) return <LoadingState label="Solving regional distribution..." />;
  if (isError) return <ErrorState error={error} />;

  const regionLabels = data.supply.map((_, i) => `Region ${i + 1}`);
  const centreLabels = data.demand.map((_, i) => `Centre ${i + 1}`);

  function resolveNow() {
    resolve.mutate({ capacities, cost_matrix: costMatrix });
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-4 items-start">
      <Card eyebrow="Module III · Transportation" title="Allocation" subtitle="Region -> support-centre ticket routing (transportation problem optimum).">
        <Heatmap matrix={data.allocation} rowLabels={regionLabels} colLabels={centreLabels} />
        <p className="mt-4 font-display text-2xl font-semibold text-ink tabular-nums">{data.total_cost.toFixed(0)}</p>
        <p className="text-xs text-muted">total routing cost -- {data.source}</p>
      </Card>

      <Card eyebrow="Editable" title="Editable assumptions" subtitle="Centre intake capacity and routing/handling cost are a business policy input, not data -- change them and re-solve.">
        {capacities && costMatrix && (
          <div className="space-y-4">
            <div>
              <p className="text-xs text-muted mb-2">Centre capacities</p>
              <div className="grid grid-cols-3 gap-3">
                {capacities.map((cap, i) => (
                  <EditableNumberField
                    key={i}
                    label={centreLabels[i]}
                    value={cap}
                    onChange={(v) =>
                      setCapacities((c) => c.map((x, idx) => (idx === i ? v : x)))
                    }
                  />
                ))}
              </div>
            </div>
            <div>
              <p className="text-xs text-muted mb-2">Routing/handling cost matrix</p>
              <EditableMatrixField
                matrix={costMatrix}
                rowLabels={regionLabels}
                colLabels={centreLabels}
                onChange={setCostMatrix}
              />
            </div>
            <button
              className="rounded-control bg-accent text-accent-ink text-sm font-medium px-4 py-2 hover:brightness-110 transition-[filter] duration-150 ease-out disabled:opacity-50"
              onClick={resolveNow}
              disabled={resolve.isPending}
            >
              {resolve.isPending ? "Re-solving..." : "Re-solve distribution"}
            </button>
            {resolve.isError && <ErrorState error={resolve.error} />}
          </div>
        )}
      </Card>
    </div>
  );
}
