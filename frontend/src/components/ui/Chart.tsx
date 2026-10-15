import type { ReactElement, ReactNode } from "react";
import { ResponsiveContainer } from "recharts";
import { Card, EmptyState } from "./primitives";

export const CHART = {
  accent: "#0f766e",
  accent2: "#5aa9a1",
  navy: "#1e3a52",
  muted: "#a9b6c2",
  grid: "#e9ecf0",
  ok: "#15803d",
  warn: "#c2790c",
  bad: "#b42318",
  axis: { fontSize: 11, fill: "#6b7c8c" },
};

export function ChartCard({ title, subtitle, children, height = 240, empty, actions }: {
  title: string; subtitle?: ReactNode; children: ReactNode; height?: number; empty?: boolean; actions?: ReactNode;
}) {
  return (
    <Card title={title} subtitle={subtitle} actions={actions} bodyClass="px-2 pb-3 pt-4">
      {empty ? <EmptyState title="No data for this chart yet" /> : (
        <div style={{ height }}>
          <ResponsiveContainer width="100%" height="100%">{children as ReactElement}</ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
