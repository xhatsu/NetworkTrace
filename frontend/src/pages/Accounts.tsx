import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ArrowLeft, KeyRound, ShieldAlert, UserCheck } from "lucide-react";
import { api, queryString } from "../api";
import {
  ErrorState,
  Loading,
  MetricCard,
  Page,
  Panel,
  chartTooltip,
  n,
  pct,
} from "../components";
import { useFilters } from "../App";

type Account = {
  username: string;
  namespace: string;
  first_seen_ms: number;
  last_seen_ms: number;
};

export function AccountsPage() {
  const { filters } = useFilters();
  const nav = useNavigate();

  const q = useQuery({
    queryKey: ["accounts"],
    queryFn: () =>
      api<{ items: Account[]; identity_caveat: string }>(
        "/api/v1/accounts?limit=500",
      ),
  });

  return (
    <Page
      eyebrow="Identity Tracking"
      title="Request Authenticated Identities"
      description="Extracted usernames from Basic Authorization. Passwords and credentials are scrubbed in-memory prior to storage."
      actions={
        <div className="chip font-mono text-[11px] text-[#8b949e]">
          <span>Sanitized in-memory</span>
        </div>
      }
    >
      {q.isLoading ? (
        <Loading />
      ) : (
        <Panel
          title={`${q.data?.items.length || 0} Registered Client Identities`}
          subtitle={q.data?.identity_caveat}
        >
          <div className="divide-y divide-[rgba(255,255,255,0.04)]">
            {q.data?.items.map((a) => (
              <button
                key={`${a.username}:${a.namespace}`}
                onClick={() =>
                  nav(
                    `/accounts/${encodeURIComponent(a.username)}?${queryString(filters)}`,
                  )
                }
                className="group flex w-full items-center justify-between p-4 text-left transition hover:bg-white/[0.03]"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-[rgba(255,255,255,0.08)] bg-white/[0.03] text-indigo-400 group-hover:text-indigo-300">
                    <KeyRound size={16} />
                  </div>
                  <div className="min-w-0">
                    <div className="truncate text-xs font-semibold text-[#f0f3f6] group-hover:text-indigo-300 transition">
                      {a.username}
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-[#8b949e]">
                      Namespace: <span className="font-mono text-[#c9d1d9]">{a.namespace || "default"}</span> · First seen{" "}
                      {new Date(a.first_seen_ms).toLocaleDateString()}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <span className="rounded bg-white/[0.04] px-2 py-0.5 font-mono text-[11px] text-[#8b949e]">
                    Last seen {new Date(a.last_seen_ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </Panel>
      )}
    </Page>
  );
}

type Detail = {
  account: Account;
  identity_caveat: string;
  targets: {
    service_name: string;
    operation: string;
    requests: number;
    denied: number;
  }[];
  hourly: { hour: number; requests: number }[];
  weekday: { day: number; requests: number }[];
};

export function AccountDetailPage() {
  const { username = "" } = useParams();
  const { filters } = useFilters();
  const nav = useNavigate();
  const qs = queryString({ ...filters, account: undefined });

  const q = useQuery({
    queryKey: ["account", username, qs],
    queryFn: () =>
      api<Detail>(`/api/v1/accounts/${encodeURIComponent(username)}?${qs}`),
  });

  if (q.isLoading) {
    return (
      <Page eyebrow="Account Detail" title={username} description="Loading identity analytics…">
        <Loading />
      </Page>
    );
  }

  if (q.error) {
    return (
      <Page eyebrow="Account Detail" title={username} description="">
        <ErrorState message={q.error.message} />
      </Page>
    );
  }

  const d = q.data!;
  const total = d.targets.reduce((a, b) => a + b.requests, 0);
  const denied = d.targets.reduce((a, b) => a + b.denied, 0);

  return (
    <Page
      eyebrow="Identity Investigation"
      title={`Account: ${username}`}
      description={d.identity_caveat}
      actions={
        <button
          className="btn"
          onClick={() => nav(`/accounts?${qs}`)}
        >
          <ArrowLeft size={13} />
          All Accounts
        </button>
      }
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MetricCard
          label="Total Volume"
          value={n(total)}
          detail="Requests using this credential"
        />
        <MetricCard
          label="Target Services"
          value={String(new Set(d.targets.map((t) => t.service_name)).size)}
          detail="Distinct destination services"
        />
        <MetricCard
          label="Target Operations"
          value={String(new Set(d.targets.map((t) => t.operation)).size)}
          detail="Observed operations"
        />
        <MetricCard
          label="401 / 403 Auth Denials"
          value={pct(denied / Math.max(1, total))}
          detail={`${n(denied)} rejected requests`}
          tone={denied ? "bad" : "good"}
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel
          title="Usage by Hour of Day"
          subtitle="Hourly request volume distribution (UTC)"
        >
          <MiniBars
            data={Array.from({ length: 24 }, (_, hour) => ({
              hour,
              requests: d.hourly.find((x) => x.hour === hour)?.requests || 0,
            }))}
          />
        </Panel>

        <Panel
          title="Usage by Day of Week"
          subtitle="Day distribution (0 = Sunday, 6 = Saturday)"
        >
          <MiniBars data={d.weekday} />
        </Panel>
      </div>

      <Panel
        title="Target Services and Operation Mix"
        subtitle="Confirmed server destinations invoked by this credential"
        className="mt-4"
      >
        <div className="overflow-auto scrollbar">
          <table className="w-full min-w-[700px]">
            <thead>
              <tr className="border-b border-[rgba(255,255,255,0.06)] bg-white/[0.01]">
                {["Target Service", "Operation", "Observed Requests", "Auth Denials (401/403)"].map((h) => (
                  <th key={h} className="table-head px-4 py-2.5">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.targets.map((t) => (
                <tr
                  key={`${t.service_name}-${t.operation}`}
                  className="border-b border-[rgba(255,255,255,0.04)] transition hover:bg-white/[0.02]"
                >
                  <td className="px-4 py-3 text-xs font-semibold text-[#f0f3f6]">
                    {t.service_name}
                  </td>
                  <td className="px-4 py-3 text-xs text-[#8b949e]">
                    {t.operation}
                  </td>
                  <td className="px-4 font-mono text-xs tabular-nums text-[#c9d1d9]">
                    {n(t.requests)}
                  </td>
                  <td className="px-4 font-mono text-xs tabular-nums">
                    <span className={t.denied > 0 ? "text-[#f43f5e] font-semibold" : "text-[#8b949e]"}>
                      {n(t.denied)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </Page>
  );
}

function MiniBars({
  data,
}: {
  data: { hour?: number; day?: number; requests: number }[];
}) {
  return (
    <div className="h-64 p-3">
      <ResponsiveContainer>
        <BarChart data={data}>
          <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
          <XAxis
            dataKey={data[0]?.hour !== undefined ? "hour" : "day"}
            stroke="#484f58"
            fontSize={11}
          />
          <YAxis stroke="#484f58" fontSize={11} width={36} />
          <Tooltip {...chartTooltip} />
          <Bar dataKey="requests" fill="#6366f1" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
