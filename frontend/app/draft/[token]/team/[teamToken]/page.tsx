"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import { apiJson, apiJsonRetry, connectDraftSocket } from "@/lib/api";
import type { TeamState } from "@/lib/types";
import { PositionBadge } from "@/components/PositionBadge";
import { getTeamTheme } from "@/lib/theme";

type SortKey = "rank" | "name";
type Position = "ALL" | "QB" | "RB" | "WR" | "TE" | "K" | "DST";

const POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DST", "DEF"];

function rosterText(roster?: Record<string, number>): string {
  if (!roster) return "";
  return POSITION_ORDER.filter((p) => (roster[p] ?? 0) > 0)
    .map((p) => `${p}:${roster[p]}`)
    .join(" | ");
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
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, [token, teamToken]);

  useEffect(() => {
    let ws: WebSocket;
    let closed = false;
    apiJsonRetry<TeamState>(`/api/draft/${token}/team/${teamToken}`)
      .then((s) => {
        setState(s);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"));
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
  }, [fetchTeam, token, teamToken]);

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

  if (error && !state) {
    return (
      <main className="min-h-screen text-slate-100 flex items-center justify-center p-4">
        <div className="retro-panel p-5 border-2 border-red-500 bg-red-950/90 max-w-sm text-center space-y-3">
          <div className="text-2xl">⚠️</div>
          <div className="font-bold text-sm text-red-200 uppercase">
            Connection Error
          </div>
          <p className="text-xs text-red-300 font-mono">{error}</p>
          <button
            onClick={() => fetchTeam()}
            className="btn btn-secondary text-xs"
          >
            Retry
          </button>
        </div>
      </main>
    );
  }

  if (!state) {
    return (
      <main className="min-h-screen text-slate-100 flex items-center justify-center p-4">
        <div className="retro-panel p-5 border-2 border-slate-500 bg-slate-900 max-w-xs text-center space-y-2">
          <div className="text-2xl animate-spin">🏈</div>
          <div className="font-bold text-xs uppercase text-yellow-300">
            LOADING TEAM DRAFT ROOM…
          </div>
        </div>
      </main>
    );
  }

  const theme = getTeamTheme(state.draft_position || 1);
  const current = state.current_slot;

  return (
    <main
      className="min-h-screen text-slate-100 p-2 sm:p-4"
      style={{
        backgroundImage: `url(${theme.bgUrl})`,
        backgroundColor: theme.bgColor,
        backgroundRepeat: "repeat",
      }}
    >
      <div className="max-w-lg mx-auto space-y-3">
        {/* Team Room Header Window */}
        <header
          className="retro-panel p-0 shadow-[4px_4px_0px_#000000]"
          style={{ border: theme.cardBorder }}
        >
          <div
            className="retro-titlebar"
            style={{
              background: theme.headerGradient,
              color: theme.headerTextColor,
            }}
          >
            <div className="flex items-center gap-1.5 font-black truncate">
              <span>{theme.icon}</span>
              <span className="truncate">{state.team_name}</span>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              <span
                className={`text-[9px] font-mono px-1 py-0.5 border ${
                  connected
                    ? "bg-emerald-950 text-emerald-300 border-emerald-400"
                    : "bg-red-950 text-red-300 border-red-400 animate-pulse"
                }`}
              >
                {connected ? "LIVE" : "SYNCING"}
              </span>
            </div>
          </div>

          <div
            className="p-3.5 space-y-2"
            style={{ backgroundColor: theme.cardBg }}
          >
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-xl font-black font-heading tracking-tight text-white flex items-center gap-2">
                  <span>{theme.icon}</span>
                  <span>{state.team_name}</span>
                </h1>
                <p className="text-xs font-mono" style={{ color: theme.mutedTextColor }}>
                  {state.league_name} • STATUS: [{state.status}]
                </p>
              </div>
              <div className="text-right">
                <span className="text-[10px] font-mono uppercase text-yellow-300 border border-yellow-400/60 bg-black/60 px-1.5 py-0.5">
                  THEME: {theme.name}
                </span>
              </div>
            </div>

            {/* Top Quick Links */}
            <div className="flex gap-2 text-xs pt-1 border-t border-slate-800">
              <a
                href={`/draft/${token}/display`}
                className="btn btn-secondary text-[10px] py-1 inline-flex items-center gap-1"
              >
                📺 TV Board
              </a>
              <a
                href={`/draft/${token}/rosters`}
                className="btn btn-secondary text-[10px] py-1 inline-flex items-center gap-1"
              >
                📋 All Rosters
              </a>
            </div>
          </div>
        </header>

        {/* Dramatic ON THE CLOCK Banner */}
        {state.on_the_clock && state.status === "LIVE" && (
          <div
            className="border-4 p-3 text-center shadow-[4px_4px_0px_#000000] animate-pulse"
            style={{
              background: theme.clockBannerBg,
              borderColor: theme.accentColor,
              color: theme.clockBannerTextColor,
            }}
          >
            <div className="text-xs uppercase font-mono tracking-widest font-black">
              ★★★ YOUR TEAM IS ON THE CLOCK! ★★★
            </div>
            <div className="text-3xl font-black font-heading tracking-tight mt-0.5">
              MAKE YOUR SELECTION
            </div>
            <div className="text-xs font-mono font-bold mt-1 opacity-90">
              ROUND {current?.round} • OVERALL PICK #{current?.pick_number}
            </div>
          </div>
        )}

        {state.status === "COMPLETED" && (
          <div className="retro-panel p-2.5 bg-amber-950 border-2 border-amber-400 text-yellow-300 text-xs font-bold text-center font-mono">
            🏆 DRAFT COMPLETED — FINAL ROSTERS LOCKED 🏆
          </div>
        )}

        {notice && (
          <div className="retro-panel p-2 bg-red-950 border-2 border-red-500 text-red-200 text-xs font-mono font-bold flex items-center gap-2">
            <span>⚠️</span>
            <span>{notice}</span>
          </div>
        )}

        {/* Keepers Section (Pre-Draft) */}
        {(state.status === "SETUP" || state.status === "READY") && (
          <section
            className="retro-panel p-0 shadow-[3px_3px_0px_#000000]"
            style={{ border: theme.cardBorder }}
          >
            <div className="retro-titlebar-gold">
              <span>
                ★ KEEPER SELECTION ({state.keeper_count}/{state.max_keepers})
              </span>
              <span className="text-[10px] font-mono">LOCKS AT DRAFT START</span>
            </div>
            <div
              className="p-3 space-y-2"
              style={{ backgroundColor: theme.cardBg }}
            >
              {state.keeper_candidates.length === 0 && state.keeper_count === 0 ? (
                <p className="text-xs text-slate-400 font-mono py-2 text-center">
                  No keeper candidates imported yet.
                </p>
              ) : (
                <div className="space-y-1.5">
                  {state.keeper_candidates.map((k) => (
                    <div
                      key={k.candidate_id}
                      className="border border-slate-700 bg-black/60 p-2 flex items-center justify-between gap-2 text-xs"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="font-mono font-black text-yellow-400 w-8 text-center bg-slate-900 border border-slate-700 py-0.5">
                          R{k.cost_round}
                        </span>
                        <div className="min-w-0">
                          <div className="font-bold truncate flex items-center gap-1">
                            <span>{k.player_name}</span>
                            {k.selected && (
                              <span className="text-yellow-400 font-black">
                                ★
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-1 text-[10px] text-slate-400 font-mono">
                            <PositionBadge position={k.position} size="xs" />
                            <span>
                              {k.nfl_team ? `· ${k.nfl_team}` : ""} ·{" "}
                              {k.years_kept === 1
                                ? "Last year"
                                : `Until ${k.keepable_until_year}`}
                            </span>
                          </div>
                        </div>
                      </div>

                      <div>
                        {k.selected ? (
                          <button
                            className="btn btn-danger text-[10px] py-1"
                            disabled={picking === k.player_id}
                            onClick={() => removeKeeper(k.player_id)}
                          >
                            {picking === k.player_id ? "…" : "Remove"}
                          </button>
                        ) : (
                          <button
                            className="btn btn-gold text-[10px] py-1"
                            disabled={
                              picking === k.player_id ||
                              state.keeper_count >= state.max_keepers
                            }
                            onClick={() => selectKeeper(k.player_id)}
                          >
                            {picking === k.player_id ? "…" : "Keep"}
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        )}

        {/* Up Next / Next Pick Info */}
        {state.next_picks.length > 0 && (
          <section
            className="retro-panel p-0 shadow-[2px_2px_0px_#000000]"
            style={{ border: theme.cardBorder }}
          >
            <div className="retro-titlebar">
              <span>⏳ UP NEXT ON THE CLOCK</span>
              <span className="text-[10px] font-mono text-cyan-300">
                UPCOMING PICKS
              </span>
            </div>
            <div
              className="p-2.5 flex flex-wrap gap-2"
              style={{ backgroundColor: theme.cardBg }}
            >
              {state.next_picks.map((s) => (
                <div
                  key={s.pick_number}
                  className="border border-slate-700 bg-black/60 px-2 py-1 text-xs font-mono flex-1 min-w-32"
                >
                  <div className="flex justify-between text-yellow-300 font-bold">
                    <span>#{s.pick_number}</span>
                    <span>R{s.round}</span>
                  </div>
                  <div className="font-sans font-bold truncate text-white">
                    {s.drafting_team_name}
                  </div>
                  <div className="text-[9px] text-slate-400 truncate">
                    {rosterText(s.roster) || "No picks"}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Roster / Available Tabs */}
        <div className="flex border-2 border-slate-700 bg-black shadow-[2px_2px_0px_#000000]">
          <button
            className={`flex-1 py-2 text-xs font-black uppercase tracking-wider font-sans border-r-2 border-slate-700 ${
              view === "roster"
                ? "bg-slate-800 text-yellow-300 border-b-2 border-b-yellow-400"
                : "bg-slate-950 text-slate-400 hover:text-white"
            }`}
            onClick={() => setView("roster")}
          >
            📋 My Roster
          </button>
          <button
            className={`flex-1 py-2 text-xs font-black uppercase tracking-wider font-sans ${
              view === "available"
                ? "bg-slate-800 text-yellow-300 border-b-2 border-b-yellow-400"
                : "bg-slate-950 text-slate-400 hover:text-white"
            }`}
            onClick={() => setView("available")}
          >
            🔍 Draft Players ({state.available_count})
          </button>
        </div>

        {/* View: Roster */}
        {view === "roster" && (
          <section
            className="retro-panel p-0 shadow-[3px_3px_0px_#000000]"
            style={{ border: theme.cardBorder }}
          >
            <div className="retro-titlebar">
              <span>🏈 STARTING LINEUP</span>
              {state.my_next_slot && (
                <span className="text-[10px] font-mono text-yellow-300">
                  NEXT PICK: R{state.my_next_slot.round} • #{state.my_next_slot.pick_number}
                </span>
              )}
            </div>

            <div
              className="p-3 space-y-1.5"
              style={{ backgroundColor: theme.cardBg }}
            >
              {state.roster_by_slot.length === 0 && state.keepers.length === 0 && (
                <p className="text-xs text-slate-400 font-mono py-2 text-center">
                  No players drafted yet.
                </p>
              )}

              {state.roster_by_slot.map((r, idx) => (
                <div
                  key={`${r.slot}-${idx}`}
                  className="border border-slate-700 bg-black/60 p-1.5 px-2 flex items-center justify-between text-xs"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="w-12 font-mono font-bold text-[11px] text-yellow-300">
                      {r.slot}
                    </span>
                    <PositionBadge position={r.position} size="xs" />
                    {r.player ? (
                      <span className="font-bold truncate text-white">
                        {r.player.player_name}
                        <span className="text-[10px] text-slate-400 ml-1 font-mono">
                          {r.player.nfl_team ? `· ${r.player.nfl_team}` : ""} (R{r.player.round})
                        </span>
                      </span>
                    ) : (
                      <span className="text-slate-600 font-mono text-[11px]">
                        — EMPTY —
                      </span>
                    )}
                  </div>
                </div>
              ))}

              {/* Bench */}
              {state.bench.length > 0 && (
                <div className="pt-2 border-t border-slate-800 space-y-1">
                  <div className="text-[10px] uppercase font-mono tracking-wider text-slate-400 font-bold">
                    BENCH ({state.bench.length})
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {state.bench.map((p) => (
                      <span
                        key={p.player_id}
                        className="badge bg-slate-900 border-slate-700 text-slate-200 text-xs py-1"
                      >
                        {p.player_name}{" "}
                        <PositionBadge position={p.position} size="xs" />{" "}
                        <span className="text-slate-500 font-mono text-[10px]">
                          R{p.round}
                        </span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Keepers not yet in live roster */}
              {state.keepers.filter(
                (k) => !state.roster.some((r) => r.player_id === k.player_id),
              ).length > 0 && (
                <div className="pt-2 border-t border-slate-800 space-y-1">
                  <div className="text-[10px] uppercase font-mono tracking-wider text-amber-300 font-bold">
                    CONFIRMED KEEPERS
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {state.keepers
                      .filter(
                        (k) => !state.roster.some((r) => r.player_id === k.player_id),
                      )
                      .map((k) => (
                        <span
                          key={k.keeper_id}
                          className="badge bg-amber-950/80 border-amber-600 text-amber-200 text-xs py-1"
                        >
                          {k.player_name}{" "}
                          <span className="text-amber-400 font-mono text-[10px]">
                            ★ R{k.round}
                          </span>
                        </span>
                      ))}
                  </div>
                </div>
              )}
            </div>
          </section>
        )}

        {/* View: Available Players */}
        {view === "available" && (
          <section
            className="retro-panel p-0 shadow-[3px_3px_0px_#000000]"
            style={{ border: theme.cardBorder }}
          >
            <div className="retro-titlebar">
              <span>🔍 DRAFT POOL ({state.available_count} AVAILABLE)</span>
              <span className="text-[10px] font-mono text-yellow-300">
                LIVE DRAFTING
              </span>
            </div>

            <div
              className="p-3 space-y-3"
              style={{ backgroundColor: theme.cardBg }}
            >
              {/* Search & Filter Controls */}
              <div className="flex gap-2">
                <input
                  className="input flex-1"
                  placeholder="Search player by name…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
                <select
                  className="input w-20 font-bold"
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
                  className="input w-24 font-bold"
                  value={sort}
                  onChange={(e) => setSort(e.target.value as SortKey)}
                >
                  <option value="rank">By Rank</option>
                  <option value="name">By Name</option>
                </select>
              </div>

              {/* Player List */}
              <div className="space-y-1.5 max-h-[500px] overflow-y-auto pr-1">
                {filtered.map((p) => (
                  <div
                    key={p.player_id}
                    className="border border-slate-700 bg-black/60 p-2 flex items-center justify-between gap-2 text-xs"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="font-mono text-yellow-400 font-bold w-7 text-right">
                        {p.rank ?? "—"}
                      </span>
                      <div className="min-w-0">
                        <div className="font-black text-white truncate text-sm">
                          {p.name}
                        </div>
                        <div className="flex items-center gap-1.5 text-[10px] text-slate-400 font-mono">
                          <PositionBadge position={p.position} size="xs" />
                          <span>
                            {p.nfl_team ? p.nfl_team : ""}
                            {p.bye_week ? ` · BYE ${p.bye_week}` : ""}
                          </span>
                        </div>
                      </div>
                    </div>

                    <div>
                      {state.on_the_clock ? (
                        <button
                          className="btn btn-gold text-xs py-1 px-3 shadow-[2px_2px_0px_#000000]"
                          disabled={picking === p.player_id}
                          onClick={() => submitPick(p.player_id)}
                        >
                          {picking === p.player_id ? "DRAFTING…" : "⚡ DRAFT"}
                        </button>
                      ) : (
                        <span className="text-[10px] font-mono text-slate-500 uppercase px-2 py-1 border border-slate-800 bg-black">
                          {state.status === "LIVE" ? "WAITING" : "LOCKED"}
                        </span>
                      )}
                    </div>
                  </div>
                ))}

                {filtered.length === 0 && (
                  <div className="text-center py-6 text-slate-400 font-mono text-xs">
                    No players match your search filter.
                  </div>
                )}
              </div>
            </div>
          </section>
        )}

        {/* Recent Picks Window */}
        {state.recent_picks.length > 0 && (
          <section
            className="retro-panel p-0 shadow-[2px_2px_0px_#000000]"
            style={{ border: theme.cardBorder }}
          >
            <div className="retro-titlebar">
              <span>📢 RECENT LEAGUE PICKS</span>
              <span className="text-[10px] font-mono text-slate-300">
                LATEST ACTIVITY
              </span>
            </div>
            <div
              className="p-2.5 divide-y divide-slate-800 text-xs font-mono"
              style={{ backgroundColor: theme.cardBg }}
            >
              {state.recent_picks.map((p) => (
                <div
                  key={p.id}
                  className="py-1.5 flex items-center justify-between gap-2"
                >
                  <div className="flex items-center gap-2 truncate">
                    <span className="text-yellow-400 font-bold">
                      #{p.pick_number}
                    </span>
                    <span className="font-sans font-bold text-white truncate">
                      {p.player_name}
                    </span>
                    <PositionBadge position={p.position} size="xs" />
                  </div>
                  <span className="text-slate-400 text-[11px] truncate">
                    {p.team_name}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
