import { useState } from "react";
import { CartesianGrid, Line, ComposedChart, Scatter, Tooltip, XAxis, YAxis, Legend } from "recharts";
import { RotateCw } from "lucide-react";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";
import { useAuth } from "../lib/auth";
import { useModelStatus, type RunSummary } from "../lib/useModelStatus";
import { dateTime, number, titleCase } from "../lib/format";
import { Async, Badge, Button, Card, EmptyState, KeyValue, PageHeader, StatTile, StatusBadge } from "../components/ui/primitives";
import { DataTable } from "../components/ui/DataTable";
import { Select } from "../components/ui/Form";
import { CHART, ChartCard } from "../components/ui/Chart";
import { useToast } from "../components/ui/Toast";
import { ModelBanner } from "../components/ModelBanner";

interface M { n: number; positives: number; prevalence: number; threshold: number; precision: number; recall: number; f1: number; accuracy: number;
  roc_auc: number | null; pr_auc: number | null; brier: number; confusion_matrix: { tn: number; fp: number; fn: number; tp: number } }
interface Metrics extends RunSummary {
  evaluation_metrics: {
    chosen_algorithm: string; selection_rule: string; decision_threshold: number; threshold_rule: string; beats_best_baseline_on_test_pr_auc: boolean;
    models: Record<string, { validation: M; test: M }>; chosen_test: M; calibration_test: { mean_predicted: number; observed_rate: number; count: number }[];
    feature_importance: { feature: string; importance: number; std: number }[]; feature_importance_method: string;
    group_importance?: { group: string; features: string[]; importance: number; std: number }[];
    split: { strategy: string; train_cutoffs: string[]; validation_cutoffs: string[]; test_cutoffs: string[]; dropped_for_gap: number;
      sizes: Record<string, number>; positives: Record<string, number> };
    data_quality: { rows: number; products: number; positives: number; positive_rate: number; missing_values: Record<string, number> };
    target_definition: string; deployment_fit: string;
  } | null;
}

const f4 = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : v.toFixed(3));

function Confusion({ cm }: { cm: M["confusion_matrix"] }) {
  const cell = (label: string, v: number, good: boolean) => (
    <div className={`rounded-md px-3 py-3 text-center ${good ? "bg-accent-soft" : "bg-canvas"}`}>
      <p className="text-lg font-semibold tabular">{number(v)}</p><p className="text-[11px] text-ink-3">{label}</p>
    </div>
  );
  return (
    <div className="grid grid-cols-[auto_1fr_1fr] items-center gap-2 text-xs">
      <span /><span className="text-center font-medium text-ink-3">Predicted no failure</span><span className="text-center font-medium text-ink-3">Predicted failure</span>
      <span className="font-medium text-ink-3">Actual: none</span>{cell("True negatives", cm.tn, true)}{cell("False positives", cm.fp, false)}
      <span className="font-medium text-ink-3">Actual: failure</span>{cell("False negatives", cm.fn, false)}{cell("True positives", cm.tp, true)}
    </div>
  );
}

export default function ModelPerformance() {
  const toast = useToast();
  const { user } = useAuth();
  const status = useModelStatus();
  const runs = useApi<RunSummary[]>("/models/runs");
  const [runId, setRunId] = useState<string>("");
  const metrics = useApi<Metrics>(status.data?.active_run || runId ? `/models/metrics${runId ? `?training_run_id=${runId}` : ""}` : null);
  const [training, setTraining] = useState(false);
  const canTrain = !!user && (status.data?.training_restricted_to ?? []).includes(user.role);

  const train = async () => {
    setTraining(true);
    try {
      const r = await api<RunSummary>("/models/train", { method: "POST", json: {} });
      if (r.training_status === "Completed") toast.success(`Trained ${r.model_version} (${r.model_classification})`);
      else toast.error(`${r.training_status}: ${r.notes}`);
      setRunId(""); status.reload(); runs.reload(); metrics.reload();
    } catch (e) { toast.error(e); } finally { setTraining(false); }
  };

  return (
    <>
      <PageHeader title="Model performance" description="Evaluation of the failure-risk classifier on a held-out, later time period."
        actions={<>
          {runs.data && runs.data.length > 0 && (
            <Select aria-label="Training run" className="w-64" value={runId} onChange={(e) => setRunId(e.target.value)}>
              <option value="">Active model</option>
              {runs.data.map((r) => <option key={r.training_run_id} value={r.training_run_id}>#{r.training_run_id} {r.model_version} · {r.training_status}</option>)}
            </Select>
          )}
          {canTrain && <Button variant="primary" icon={<RotateCw className="size-3.5" />} loading={training} onClick={train}>{training ? "Training…" : "Train model"}</Button>}
        </>} />
      <ModelBanner status={status.data} />
      {!status.data?.active_run && !runId ? (
        <Card><EmptyState title="No trained model" hint={canTrain ? "Train a model from the historical data. If there is not enough eligible history the run is recorded as ‘Insufficient Data’ and nothing is deployed." : "Ask an administrator to train a model."} /></Card>
      ) : (
        <Async state={metrics}>
          {(m) => {
            const e = m.evaluation_metrics;
            if (!e) return <Card><EmptyState title={`Run ${m.model_version}: ${m.training_status}`} hint={m.notes ?? undefined} /></Card>;
            const t = e.chosen_test;
            const order = ["baseline_prior_rate", "baseline_recent_failure_rule", "random_forest", "gradient_boosting"];
            return (
              <div className="space-y-4">
                <div className="grid grid-cols-6 gap-3 max-xl:grid-cols-3">
                  <StatTile label="PR-AUC (test)" value={f4(t.pr_auc)} sub={`Prevalence ${f4(t.prevalence)} = random baseline`} />
                  <StatTile label="ROC-AUC (test)" value={f4(t.roc_auc)} />
                  <StatTile label="Precision" value={f4(t.precision)} sub={`at threshold ${f4(t.threshold)}`} />
                  <StatTile label="Recall" value={f4(t.recall)} />
                  <StatTile label="F1" value={f4(t.f1)} />
                  <StatTile label="Brier score" value={f4(t.brier)} sub="Lower = better calibrated" />
                </div>
                <div className="grid grid-cols-3 gap-4 max-xl:grid-cols-1">
                  <Card title="Model comparison" subtitle={e.selection_rule} className="col-span-2 max-xl:col-span-1" bodyClass="p-0">
                    <DataTable dense rows={order.filter((k) => e.models[k]).map((k) => ({ k, ...e.models[k] }))} rowKey={(r) => r.k} columns={[
                      { key: "n", header: "Model", render: (r) => <span className="inline-flex items-center gap-1.5">{titleCase(r.k)}{r.k === e.chosen_algorithm && <Badge tone="accent">Deployed</Badge>}</span> },
                      { key: "vp", header: "Val PR-AUC", align: "right", render: (r) => f4(r.validation.pr_auc) },
                      { key: "tp", header: "Test PR-AUC", align: "right", render: (r) => f4(r.test.pr_auc) },
                      { key: "tr", header: "Test ROC-AUC", align: "right", render: (r) => f4(r.test.roc_auc) },
                      { key: "p", header: "Precision", align: "right", render: (r) => f4(r.test.precision) },
                      { key: "rc", header: "Recall", align: "right", render: (r) => f4(r.test.recall) },
                      { key: "f", header: "F1", align: "right", render: (r) => f4(r.test.f1) },
                      { key: "b", header: "Brier", align: "right", render: (r) => f4(r.test.brier) },
                    ]} />
                    <p className="border-t border-line px-3 py-2 text-[11px] text-ink-3">
                      Accuracy is not used for selection: with {(t.prevalence * 100).toFixed(1)}% failures, predicting “no failure” for everyone is {(100 - t.prevalence * 100).toFixed(1)}% accurate.
                      {e.beats_best_baseline_on_test_pr_auc ? " The deployed model beats both baselines on test PR-AUC." : " The deployed model does NOT beat the best baseline on test PR-AUC."}
                    </p>
                  </Card>
                  <Card title="Confusion matrix (test)" subtitle={`Threshold ${f4(e.decision_threshold)} — ${e.threshold_rule}`}><Confusion cm={t.confusion_matrix} /></Card>
                  <ChartCard title="Calibration (test)" subtitle="Mean predicted probability vs observed failure rate per bin" height={240} empty={!e.calibration_test.length}>
                    <ComposedChart data={e.calibration_test} margin={{ left: -10, right: 12 }}>
                      <CartesianGrid stroke={CHART.grid} />
                      <XAxis type="number" dataKey="mean_predicted" domain={[0, "dataMax"]} tick={CHART.axis} tickFormatter={(v) => v.toFixed(2)} name="Predicted" />
                      <YAxis type="number" domain={[0, "dataMax"]} tick={CHART.axis} tickFormatter={(v) => v.toFixed(2)} />
                      <Tooltip formatter={(v) => Number(v).toFixed(3)} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      <Line isAnimationActive={false} dataKey="mean_predicted" name="Perfect calibration" stroke={CHART.muted} strokeDasharray="4 4" dot={false} />
                      <Scatter isAnimationActive={false} dataKey="observed_rate" name="Observed rate" fill={CHART.accent} />
                    </ComposedChart>
                  </ChartCard>
                  <Card title="What the model relies on" subtitle="Permutation importance on held-out snapshots: drop in PR-AUC when shuffled. Associative, not causal.">
                    {e.group_importance && (
                      <div className="mb-3 space-y-1.5">
                        {e.group_importance.map((g) => {
                          const max = Math.max(...e.group_importance!.map((x) => Math.abs(x.importance)), 0.001);
                          return (
                            <div key={g.group} className="grid grid-cols-[1fr_110px_64px] items-center gap-2 text-xs" title={g.features.join(", ")}>
                              <span className="truncate text-ink-2">{g.group}</span>
                              <span className="h-2 rounded bg-canvas"><span className={`block h-full rounded ${g.importance > 0 ? "bg-ink" : "bg-line-strong"}`} style={{ width: `${Math.max(0, g.importance) / max * 100}%` }} /></span>
                              <span className="text-right tabular text-ink-3">{g.importance.toFixed(3)} ± {g.std.toFixed(3)}</span>
                            </div>
                          );
                        })}
                        <p className="pt-1 text-[11px] text-ink-4">Feature groups are shuffled jointly because related features (e.g. failures in 30/90/180 days) carry overlapping signal.</p>
                      </div>
                    )}
                    <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-ink-4">Individual features (top 6)</p>
                    <table className="w-full text-xs"><tbody>
                      {e.feature_importance.slice(0, 6).map((f) => (
                        <tr key={f.feature} className="border-t border-line"><td className="py-1 font-mono text-[11px]">{f.feature}</td>
                          <td className="py-1 text-right tabular text-ink-3">{f.importance.toFixed(4)} ± {f.std.toFixed(4)}</td></tr>))}
                    </tbody></table>
                  </Card>
                  <Card title="Data & evaluation design">
                    <KeyValue cols={1} items={[
                      ["Classification", <StatusBadge value={m.model_classification} />],
                      ["Target", <span className="whitespace-normal text-xs">{e.target_definition}</span>],
                      ["Split", <span className="whitespace-normal text-xs">{e.split.strategy}</span>],
                      ["Periods", <span className="text-xs">train {e.split.train_cutoffs.join(" → ")} · val {e.split.validation_cutoffs.join(" → ")} · test {e.split.test_cutoffs.join(" → ")}</span>],
                      ["Snapshots", <span className="text-xs">{Object.entries(e.split.sizes).map(([k, v]) => `${k} ${v} (${e.split.positives[k]} failures)`).join(" · ")}; {e.split.dropped_for_gap} dropped for the gap</span>],
                      ["Dataset", <span className="text-xs">{m.training_dataset_version} · {e.data_quality.products} products · positive rate {(e.data_quality.positive_rate * 100).toFixed(1)}%</span>],
                      ["Deployment", <span className="whitespace-normal text-xs">{e.deployment_fit}</span>],
                    ]} />
                  </Card>
                </div>
              </div>
            );
          }}
        </Async>
      )}
      <Card title="Training runs" className="mt-4" bodyClass="p-0">
        <DataTable dense rows={runs.data} error={runs.error} rowKey={(r) => r.training_run_id} emptyTitle="No training runs yet" columns={[
          { key: "id", header: "#", render: (r) => r.training_run_id },
          { key: "v", header: "Version", render: (r) => <span className="font-mono text-xs">{r.model_version}</span> },
          { key: "s", header: "Status", render: (r) => <StatusBadge value={r.training_status} /> },
          { key: "c", header: "Classification", render: (r) => <Badge tone={r.model_classification === "demonstration" ? "warn" : r.model_classification === "validated" ? "ok" : "neutral"}>{r.model_classification}</Badge> },
          { key: "a", header: "Algorithm", render: (r) => r.chosen_algorithm ? titleCase(r.chosen_algorithm) : "—" },
          { key: "n", header: "Snapshots", align: "right", render: (r) => number(r.training_sample_count) },
          { key: "p", header: "Test PR-AUC", align: "right", render: (r) => f4(r.test_pr_auc) },
          { key: "d", header: "Started", render: (r) => <span className="text-xs">{dateTime(r.training_started_at)}</span> },
          { key: "act", header: "", render: (r) => r.is_active ? <Badge tone="accent">Active</Badge> : null },
          { key: "notes", header: "Notes", className: "whitespace-normal max-w-sm", render: (r) => <span className="line-clamp-1 text-xs text-ink-3" title={r.notes ?? ""}>{r.notes}</span> },
        ]} />
      </Card>
    </>
  );
}
