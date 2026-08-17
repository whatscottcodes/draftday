"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import { apiJson, connectDraftSocket } from "@/lib/api";
import type { TeamState } from "@/lib/types";
import { PositionBadge } from "@/components/PositionBadge";

type SortKey = "rank" | "name";
type Position = "ALL" | "QB" | "RB" | "WR" | "TE" | "K" | "DST";

const POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DST", "DEF"];

function rosterText(roster?: Record<string, number>): string {
  if (!roster) return "";
  return POSITION_ORDER.filter((p) => (roster[p] ?? 0) > 0)
    .map((p) => `${p}:${roster[p]}`)
    .join("|");
}

export default function TeamPage({
  params,
}: {
  params: Promise<{ token: string; teamToken: string }>;
}) {
  const { token, teamToken } = use(params);
  const [state, setState] = useState<TeamState | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [position, setPosition] = useState<Position>("ALL");
  const [sort, setSort] = useState<SortKey>("rank");
  const [picking, setPicking] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [view, setView] = useState<"roster" | "available">("roster");
  const [viewInitialized, setViewInitialized] = useState(false);

  useEffect(() => {
    if (state && !viewInitialized) {
      if (state.on_the_clock) setView("available");
      setViewInitialized(true);
    }
  }, [state, viewInitialized]);

  const fetchTeam = useCallback(async () => {
    try {
      setState(
        await apiJson<TeamState>(`/api/draft/${token}/team/${teamToken}`),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, [token, teamToken]);

  useEffect(() => {
    let ws: WebSocket;
    let closed = false;
    fetchTeam();
    const openSocket = () => {
      ws = connectDraftSocket(token, () => fetchTeam(), setConnected);
    };
    openSocket();
    const retry = setInterval(() => {
      if (!closed && ws.readyState === WebSocket.CLOSED) openSocket();
    }, 3000);
    return () => {
      closed = true;
      clearInterval(retry);
      ws?.close();
    };
  }, [fetchTeam, token]);

  const filtered = useMemo(() => {
    if (!state) return [];
    const q = query.trim().toLowerCase();
    return state.players
      .filter(
        (p) =>
          (position === "ALL" || p.position === position) &&
          (!q || p.name.toLowerCase().includes(q)),
      )
      .sort((a, b) => {
        if (sort === "rank") {
          const ra = a.rank ?? 1 << 30;
          const rb = b.rank ?? 1 << 30;
          if (ra !== rb) return ra - rb;
        }
        return a.name.localeCompare(b.name);
      });
  }, [state, query, position, sort]);

  async function submitPick(playerId: number) {
    setPicking(playerId);
    setNotice(null);
    try {
      await apiJson(`/api/draft/${token}/team/${teamToken}/picks`, {
        method: "POST",
        body: JSON.stringify({ player_id: playerId }),
      });
      await fetchTeam();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Pick failed");
    } finally {
      setPicking(null);
    }
  }

  async function selectKeeper(playerId: number) {
    setPicking(playerId);
    setNotice(null);
    try {
      await apiJson(`/api/draft/${token}/team/${teamToken}/keepers`, {
        method: "POST",
        body: JSON.stringify({ player_id: playerId }),
      });
      await fetchTeam();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Keeper not saved");
    } finally {
      setPicking(null);
    }
  }

  async function removeKeeper(playerId: number) {
    const keeper = state?.keepers.find((k) => k.player_id === playerId);
    if (!keeper) return;
    setPicking(playerId);
    setNotice(null);
    try {
      await apiJson(
        `/api/draft/${token}/team/${teamToken}/keepers/${keeper.keeper_id}`,
        { method: "DELETE" },
      );
      await fetchTeam();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Keeper not removed");
    } finally {
      setPicking(null);
    }
  }

  if (error) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 p-4">
        <p className="text-red-400">{error}</p>
      </main>
    );
  }
  if (!state) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 p-4">
        <p className="text-slate-400">Loading…</p>
      </main>
    );
  }

  const current = state.current_slot;

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 max-w-md mx-auto">
      {/* On-the-clock banner */}
      <header
        className={`px-4 py-3 border-b border-slate-800 ${
          state.on_the_clock ? "bg-emerald-900/40" : "bg-slate-900"
        }`}
      >
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-black text-lg">{state.team_name}</h1>
            <p className="text-xs text-slate-400">
              {state.league_name} · {state.status}
              {!connected && " · reconnecting…"}
            </p>
          </div>
          {state.on_the_clock && (
            <div className="text-right">
              <div className="text-3xl font-black text-emerald-400 animate-pulse">
                ON THE CLOCK
              </div>
              <div className="text-xs text-slate-300">
                Pick {current?.pick_number} · Round {current?.round}
              </div>
            </div>
          )}
        </div>
        <div className="flex gap-3 text-xs text-slate-400 mt-2">
          <a
            href={`/draft/${token}/display`}
            className="hover:text-emerald-400"
          >
            ← TV board
          </a>
          <a
            href={`/draft/${token}/rosters`}
            className="hover:text-emerald-400"
          >
            All rosters
          </a>
        </div>
      </header>

      {state.status === "COMPLETED" && (
        <div className="px-4 py-2 bg-amber-900/30 text-amber-300 text-sm font-semibold">
          Draft complete
        </div>
      )}

      {notice && (
        <div className="px-4 py-2 bg-red-900/40 text-red-300 text-sm">{notice}</div>
      )}

      {/* Keepers (pre-draft) */}
      {(state.status === "SETUP" || state.status === "READY") && (
        <section className="px-4 py-3 space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-xs uppercase tracking-widest text-slate-500">
              Keepers ({state.keeper_count}/{state.max_keepers})
            </h2>
            <span className="text-[11px] text-slate-600">
              Selections lock when the draft starts
            </span>
          </div>
          {state.keeper_candidates.length === 0 && state.keeper_count === 0 ? (
            <p className="text-sm text-slate-500">
              No keeper candidates yet.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {state.keeper_candidates.map((k) => (
                <li
                  key={k.candidate_id}
                  className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2"
                >
                  <span className="w-9 text-right text-xs font-semibold text-amber-400/80">
                    R{k.cost_round}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold truncate">
                      {k.player_name}
                      {k.selected && (
                        <span className="ml-1 text-amber-400">★</span>
                      )}
                    </div>
                    <div className="flex items-center gap-1 text-xs text-slate-500">
                      <PositionBadge position={k.position} size="xs" />
                      <span className="truncate">
                        {k.nfl_team ? ` · ${k.nfl_team}` : ""} ·{" "}
                        {k.years_kept === 1
                          ? "Last keepable year"
                          : `Keepable until ${k.keepable_until_year}`}
                      </span>
                    </div>
                  </div>
                  {k.selected ? (
                    <button
                      className="btn-secondary text-xs"
                      disabled={picking === k.player_id}
                      onClick={() => removeKeeper(k.player_id)}
                    >
                      {picking === k.player_id ? "…" : "Remove"}
                    </button>
                  ) : (
                    <button
                      className="btn-primary text-xs"
                      disabled={
                        picking === k.player_id ||
                        state.keeper_count >= state.max_keepers
                      }
                      onClick={() => selectKeeper(k.player_id)}
                    >
                      {picking === k.player_id ? "…" : "Keep"}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* Last 3 picks */}
      {state.recent_picks.length > 0 && (
        <section className="px-4 py-3">
          <h2 className="text-xs uppercase tracking-widest text-slate-500 mb-2">
            Last picks
          </h2>
          <div className="flex flex-wrap gap-1.5">
            {state.recent_picks.slice(0, 3).map((p) => (
              <span
                key={p.id}
                className="badge bg-slate-800 text-slate-200 border border-slate-700 gap-1.5"
              >
                <span className="text-slate-500">#{p.pick_number}</span>
                <span className="font-semibold">{p.player_name}</span>
                <PositionBadge position={p.position} size="xs" />
                <span className="text-slate-500">{p.team_name}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Next 3 picks */}
      {state.next_picks.length > 0 && (
        <section className="px-4 py-3">
          <h2 className="text-xs uppercase tracking-widest text-slate-500 mb-2">
            Up next
          </h2>
          <div className="flex flex-wrap gap-1.5">
            {state.next_picks.map((s) => (
              <span
                key={s.pick_number}
                className="badge border border-slate-700 bg-slate-900 text-slate-300 flex-col items-start gap-0.5 rounded-lg"
              >
                <span className="flex gap-1.5">
                  <span className="text-slate-500">#{s.pick_number}</span>
                  <span className="font-semibold">{s.drafting_team_name}</span>
                  <span className="text-slate-500">R{s.round}</span>
                </span>
                <span className="text-[10px] text-slate-500">
                  {rosterText(s.roster) || "No players"}
                </span>
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Roster / Available tabs */}
      <div className="sticky top-0 z-10 flex border-b border-slate-800 bg-slate-950">
        {(["roster", "available"] as const).map((v) => (
          <button
            key={v}
            className={`flex-1 py-2.5 text-sm font-semibold uppercase tracking-widest ${
              view === v
                ? "text-emerald-400 border-b-2 border-emerald-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
            onClick={() => setView(v)}
          >
            {v === "roster" ? "My Roster" : "Available"}
          </button>
        ))}
      </div>

      {view === "roster" && (
        <section className="px-4 py-3 space-y-3">
          <h2 className="text-xs uppercase tracking-widest text-slate-500">
            Starters
          </h2>
          {state.roster_by_slot.length === 0 && state.keepers.length === 0 && (
            <p className="text-sm text-slate-500">No players yet.</p>
          )}
          <div className="space-y-1.5">
            {state.roster_by_slot.map((r) => (
              <div
                key={r.slot}
                className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2"
              >
                <span className="w-12 text-xs font-semibold text-slate-400">
                  {r.slot}
                </span>
                <PositionBadge position={r.position} size="xs" />
                {r.player ? (
                  <span className="flex-1 font-semibold truncate">
                    {r.player.player_name}
                    <span className="text-xs text-slate-500 ml-1">
                      {r.player.nfl_team ? ` · ${r.player.nfl_team}` : ""} · R
                      {r.player.round}
                    </span>
                  </span>
                ) : (
                  <span className="flex-1 text-sm text-slate-600">Empty</span>
                )}
              </div>
            ))}
          </div>

          {state.bench.length > 0 && (
            <>
              <h2 className="text-xs uppercase tracking-widest text-slate-500">
                Bench ({state.bench.length})
              </h2>
              <div className="flex flex-wrap gap-1.5">
                {state.bench.map((p) => (
                  <span
                    key={p.player_id}
                    className="badge bg-slate-800 text-slate-200 border border-slate-700"
                  >
                    {p.player_name}{" "}
                    <PositionBadge position={p.position} size="xs" />{" "}
                    <span className="text-slate-500">R{p.round}</span>
                  </span>
                ))}
              </div>
            </>
          )}

          {state.keepers.filter(
            (k) => !state.roster.some((r) => r.player_id === k.player_id),
          ).length > 0 && (
            <>
              <h2 className="text-xs uppercase tracking-widest text-slate-500">
                Keepers
              </h2>
              <div className="flex flex-wrap gap-1.5">
                {state.keepers
                  .filter(
                    (k) => !state.roster.some((r) => r.player_id === k.player_id),
                  )
                  .map((k) => (
                    <span
                      key={k.keeper_id}
                      className="badge bg-amber-900/40 text-amber-200 border border-amber-700"
                    >
                      {k.player_name}{" "}
                      <span className="text-amber-300/70">K·R{k.round}</span>
                    </span>
                  ))}
              </div>
            </>
          )}

          {state.my_next_slot && (
            <p className="text-sm text-slate-400">
              Next pick:{" "}
              <span className="text-slate-200">
                Round {state.my_next_slot.round} · Pick{" "}
                {state.my_next_slot.pick_number}
              </span>
            </p>
          )}
        </section>
      )}

      {view === "available" && (
        <section className="px-4 py-3 space-y-3">
          <h2 className="text-xs uppercase tracking-widest text-slate-500">
            Available players ({state.available_count})
          </h2>
          <div className="flex gap-2">
            <input
              className="input"
              placeholder="Search players…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <select
              className="input w-24"
              value={position}
              onChange={(e) => setPosition(e.target.value as Position)}
            >
              {["ALL", "QB", "RB", "WR", "TE", "K", "DST"].map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            <select
              className="input w-24"
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
            >
              <option value="rank">Rank</option>
              <option value="name">Name</option>
            </select>
          </div>

          <ul className="space-y-1.5">
            {filtered.map((p) => (
              <li
                key={p.player_id}
                className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2"
              >
                <span className="w-8 text-right text-slate-500 text-sm">
                  {p.rank ?? "—"}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold truncate">{p.name}</div>
                  <div className="flex items-center gap-1 text-xs text-slate-500">
                    <PositionBadge position={p.position} size="xs" />
                    <span>
                      {p.nfl_team ? ` · ${p.nfl_team}` : ""}
                      {p.bye_week ? ` · BYE ${p.bye_week}` : ""}
                      {p.tier ? ` · Tier ${p.tier}` : ""}
                    </span>
                  </div>
                </div>
                {state.on_the_clock ? (
                  <button
                    className="btn-primary"
                    disabled={picking === p.player_id}
                    onClick={() => submitPick(p.player_id)}
                  >
                    {picking === p.player_id ? "…" : "Draft"}
                  </button>
                ) : (
                  <span className="text-xs text-slate-600">
                    {state.status === "LIVE" ? "waiting" : "—"}
                  </span>
                )}
              </li>
            ))}
            {filtered.length === 0 && (
              <li className="text-sm text-slate-500 py-4 text-center">
                No players match.
              </li>
            )}
          </ul>
        </section>
      )}

      {/* Recent picks */}
      {state.recent_picks.length > 0 && (
        <section className="px-4 py-3">
          <h2 className="text-xs uppercase tracking-widest text-slate-500 mb-2">
            Recent picks
          </h2>
          <ul className="space-y-1 text-sm">
            {state.recent_picks.map((p) => (
              <li key={p.id} className="text-slate-400">
                <span className="text-slate-600">#{p.pick_number}</span>{" "}
                <span className="text-slate-100">{p.player_name}</span>{" "}
                <PositionBadge position={p.position} size="xs" />{" "}
                <span className="text-slate-500">— {p.team_name}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}