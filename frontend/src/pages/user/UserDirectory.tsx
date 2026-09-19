import { useMemo, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertOctagon,
  ArrowRight,
  ChevronRight,
  Filter,
  Layers,
  Radio,
  Search,
  Shield,
  ShieldAlert,
  Sparkles,
  User,
  Users,
  UserX,
  Zap,
} from "lucide-react";
import { api, queryString } from "../../api";
import { useFilters } from "../../App";
import { useI18n } from "../../i18n";

export function UserDirectory() {
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const [search, setSearch] = useState("");
  const [activeFilter, setActiveFilter] = useState<string>("all");
  const [sortKey, setSortKey] = useState<string>("most_changed");

  // Summary stats
  const { data: summary } = useQuery({
    queryKey: ["users-summary", filters],
    queryFn: () => api<any>(`/api/v1/users/summary?${queryString(filters)}`),
  });

  // Users list
  const { data: usersData, isLoading } = useQuery({
    queryKey: ["users-list", filters, search, activeFilter, sortKey],
    queryFn: () => {
      const extra: Record<string, string> = {
        sort: sortKey,
        limit: "100",
      };
      if (search) extra.q = search;
      if (activeFilter === "active") extra.active = "active";
      if (activeFilter === "inactive") extra.active = "inactive";
      return api<any>(`/api/v1/users?${queryString(filters, extra)}`);
    },
  });

  // Defensive deduplication by principal_name in case backend parts have unmerged rows
  const users: any[] = useMemo(() => {
    const raw = usersData?.items || [];
    const seen = new Set<string>();
    return raw.filter((u: any) => {
      if (!u?.principal_name || seen.has(u.principal_name)) return false;
      seen.add(u.principal_name);
      return true;
    });
  }, [usersData?.items]);

  return (
    <div className="mx-auto max-w-[1720px] px-4 py-6 md:px-8 space-y-6">
      {/* Header Banner */}
      <div className="rounded-2xl border border-[#262838] bg-[#141622] p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="grid h-14 w-14 place-items-center rounded-2xl bg-indigo-600 border border-indigo-400/40 text-white">
              <Users size={28} strokeWidth={2.2} />
            </div>
            <div>
              <span className="text-[11px] font-bold uppercase tracking-[0.15em] text-cyan-400">
                {t("User Intelligence & Identity Directory")}
              </span>
              <h1 className="mt-0.5 text-2xl md:text-3xl font-bold tracking-tight text-white">
                {t("User Directory")}
              </h1>
              <p className="mt-1 text-xs text-[#cbd5e1]">
                {t("Continuous identity behavioral baseline monitoring across service topologies")}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Link
              to="/unknown-users"
              className="flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/15 px-3 py-1 text-xs font-mono font-bold text-amber-300 hover:bg-amber-500/25 hover:text-white transition-all"
            >
              <UserX size={13} />
              <span>{t("Unknown Users & Public Traffic", "Lưu Lượng Chưa Định Danh")}</span>
            </Link>
            <span className="rounded-full border border-emerald-500/40 bg-emerald-500/15 px-3 py-1 text-xs font-mono font-bold text-emerald-300">
              ● {t("Active Behavioral Engine", "Động Cơ Hành Vi Đang Hoạt Động")}
            </span>
          </div>
        </div>

        {/* 4 Summary Cards */}
        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-xl border border-[#262838] bg-[#10121a] p-3.5">
            <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">{t("Observed Identities")}</span>
            <div className="mt-1 font-mono text-2xl font-bold text-white">
              {(summary?.observed_principals || users.length).toLocaleString()}
            </div>
          </div>
          <div className="rounded-xl border border-[#262838] bg-[#10121a] p-3.5">
            <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">{t("Currently Active", "Đang Hoạt Động")}</span>
            <div className="mt-1 font-mono text-2xl font-bold text-emerald-300">
              {(summary?.active_principals || 0).toLocaleString()}
            </div>
          </div>
          <div className="rounded-xl border border-white/10 bg-black/30 p-3.5">
            <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">{t("Accounts with Changes", "Tài Khoản Có Thay Đổi")}</span>
            <div className="mt-1 font-mono text-2xl font-bold text-amber-300">
              {(summary?.principals_with_changes || 0).toLocaleString()}
            </div>
          </div>
          <div className="rounded-xl border border-white/10 bg-black/30 p-3.5">
            <span className="text-[10px] font-bold uppercase tracking-wider text-[#94a3b8]">{t("Dormant Reactivated", "Tái Hoạt Động Sau Ngủ Đông")}</span>
            <div className="mt-1 font-mono text-2xl font-bold text-rose-300">
              {(summary?.dormant_reactivated || 0).toLocaleString()}
            </div>
          </div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[rgba(255,255,255,0.18)] bg-[#171329] p-3.5 shadow-md">
        <div className="relative flex-1 min-w-[240px] max-w-md">
          <Search className="absolute left-3 top-2.5 text-[#94a3b8]" size={14} />
          <input
            type="text"
            placeholder={t("Search identities...")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-white/20 bg-black/40 pl-9 pr-3 py-1.5 text-xs text-white placeholder:text-[#94a3b8] focus:border-cyan-400 focus:outline-none"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Active Filter */}
          <div className="flex items-center rounded-lg border border-white/10 bg-black/40 p-0.5 text-xs">
            {[
              { id: "all", label: t("All Statuses") },
              { id: "active", label: t("Active (5m)") },
              { id: "inactive", label: t("Inactive") },
            ].map((af) => (
              <button
                key={af.id}
                onClick={() => setActiveFilter(af.id)}
                className={`rounded px-2.5 py-1 font-semibold transition ${
                  activeFilter === af.id
                    ? "bg-cyan-500 text-black font-bold shadow-sm"
                    : "text-[#cbd5e1] hover:text-white"
                }`}
              >
                {af.label}
              </button>
            ))}
          </div>

          {/* Sort */}
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value)}
            className="rounded-lg border border-white/20 bg-[#1e1938] px-2.5 py-1 text-xs font-semibold text-white focus:outline-none cursor-pointer"
          >
            <option value="most_changed">{t("Sort: Most Changed", "Xếp theo: Thay đổi nhiều nhất")}</option>
            <option value="most_active">{t("Sort: Most Active", "Xếp theo: Hoạt động nhiều nhất")}</option>
            <option value="most_target_services">{t("Sort: Most Target Services", "Xếp theo: Nhiều đích nhất")}</option>
            <option value="most_operations">{t("Sort: Most Endpoints", "Xếp theo: Nhiều API nhất")}</option>
            <option value="newest">{t("Sort: Newest First", "Xếp theo: Mới nhất")}</option>
            <option value="dormant_returned">{t("Sort: Dormant Reactivated", "Xếp theo: Tái hoạt động")}</option>
          </select>
        </div>
      </div>

      {/* Users Table */}
      <div className="rounded-2xl border border-[rgba(255,255,255,0.18)] bg-[#171329] shadow-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-white/10 bg-white/5 font-mono text-[10px] font-bold uppercase text-[#94a3b8]">
                <th className="px-5 py-3">{t("User / Identity")}</th>
                <th className="px-4 py-3">{t("Type")}</th>
                <th className="px-4 py-3">{t("Status")}</th>
                <th className="px-4 py-3">{t("Risk Score")}</th>
                <th className="px-4 py-3 text-right">{t("Total Requests")}</th>
                <th className="px-4 py-3 text-right">{t("Targets")}</th>
                <th className="px-4 py-3 text-right">{t("Callers")}</th>
                <th className="px-4 py-3 text-right">{t("Operations")}</th>
                <th className="px-4 py-3 text-center">{t("Recent Changes")}</th>
                <th className="px-5 py-3 text-right">{t("Actions")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/10 font-mono">
              {isLoading ? (
                <tr>
                  <td colSpan={10} className="py-12 text-center text-xs text-cyan-300 animate-pulse">
                    {t("Loading...")}
                  </td>
                </tr>
              ) : users.length === 0 ? (
                <tr>
                  <td colSpan={10} className="py-12 text-center text-xs text-[#cbd5e1]">
                    {t("No users matching criteria")}
                  </td>
                </tr>
              ) : (
                users.map((u) => {
                  const score = u.behavior_score || 0;
                  const isHigh = score >= 60;
                  const isMed = score >= 25 && score < 60;

                  return (
                    <tr
                      key={u.principal_name}
                      onClick={() => nav(`/users/${encodeURIComponent(u.principal_name)}/overview`)}
                      className="cursor-pointer hover:bg-white/[0.06] transition"
                    >
                      <td className="px-5 py-3 font-bold text-white flex items-center gap-2.5">
                        <div className="grid h-7 w-7 place-items-center rounded-lg bg-white/10 text-cyan-300 font-sans text-xs">
                          <User size={14} />
                        </div>
                        <span className="truncate max-w-[220px]" title={u.principal_name}>
                          {u.principal_name}
                        </span>
                      </td>

                      <td className="px-4 py-3 font-sans text-xs text-[#cbd5e1]">
                        <span className="capitalize">{t(u.principal_type || "service", u.principal_type || "Dịch vụ")}</span>
                      </td>

                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-bold ${
                            u.status === "Active"
                              ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                              : "bg-slate-800 text-slate-400 border border-slate-700"
                          }`}
                        >
                          <span className={`h-1.5 w-1.5 rounded-full ${u.status === "Active" ? "bg-emerald-400" : "bg-slate-500"}`} />
                          <span>{t(u.status || "Active")}</span>
                        </span>
                      </td>

                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-bold border ${
                            isHigh
                              ? "border-rose-500/50 bg-rose-500/15 text-rose-300"
                              : isMed
                              ? "border-amber-500/50 bg-amber-500/15 text-amber-300"
                              : "border-emerald-500/50 bg-emerald-500/15 text-emerald-300"
                          }`}
                        >
                          {isHigh ? <ShieldAlert size={12} /> : <Shield size={12} />}
                          <span>{t("Risk Score")}: {score} ({t(u.behavior_level || (isHigh ? "High" : isMed ? "Medium" : "Low"))})</span>
                        </span>
                      </td>

                      <td className="px-4 py-3 text-right font-bold text-white">
                        {(u.total_requests || 0).toLocaleString()}
                      </td>

                      <td className="px-4 py-3 text-right text-cyan-300">
                        {u.unique_targets || 0}
                      </td>

                      <td className="px-4 py-3 text-right text-violet-300">
                        {u.unique_callers || 0}
                      </td>

                      <td className="px-4 py-3 text-right text-emerald-300">
                        {u.unique_operations || 0}
                      </td>

                      <td className="px-4 py-3 text-center">
                        <span
                          className={`rounded px-2 py-0.5 text-[10px] font-bold ${
                            (u.recent_changes || 0) > 0
                              ? "bg-amber-400/20 text-amber-300 border border-amber-400/40"
                              : "text-[#94a3b8]"
                          }`}
                        >
                          {u.recent_changes || 0} {t("changes", "thay đổi")}
                        </span>
                      </td>

                      <td className="px-5 py-3 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            nav(`/users/${encodeURIComponent(u.principal_name)}/overview`);
                          }}
                          className="inline-flex items-center gap-1 rounded-lg border border-cyan-400/50 bg-cyan-500/15 px-2.5 py-1 text-xs font-bold text-cyan-200 hover:bg-cyan-500/30 transition"
                        >
                          <span>{t("Inspect Workspace")}</span>
                          <ArrowRight size={12} />
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
