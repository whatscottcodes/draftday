"use client";

import { use } from "react";
import { DraftBoard } from "@/components/DraftBoard";
import { useDraftState } from "@/hooks/useDraftState";
import { API_URL } from "@/lib/api";
import { positionColor } from "@/lib/positions";
import { PositionBadge } from "@/components/PositionBadge";

export default function DisplayPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const { state, connected, error } = useDraftState(token);

  if (error && !state) {
    return (
      <main className="min-h-screen text-slate-100 flex items-center justify-center p-6">
        <div className="retro-panel p-6 border-2 border-red-500 bg-red-950/80 max-w-md text-center space-y-3">
          <div className="text-2xl">⚠️</div>
          <h2 className="text-lg font-bold text-red-200">CONNECTION ERROR</h2>
          <p className="text-xs text-red-300 font-mono">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="btn btn-secondary text-xs"
          >
            Retry Connection
          </button>
        </div>
      </main>
    );
  }

  if (!state) {
    return (
      <main className="min-h-screen text-slate-100 flex items-center justify-center p-6">
        <div className="retro-panel p-6 border-2 border-slate-500 bg-slate-900 max-w-sm text-center space-y-3">
          <div className="animate-spin text-3xl">🏈</div>
          <div className="font-bold text-sm tracking-wider uppercase text-yellow-300">
            CONNECTING TO DRAFT SERVER…
          </div>
          <div className="text-[10px] text-slate-400 font-mono">
            ESTABLISHING WEBSOCKET CONNECTION
          </div>
        </div>
      </main>
    );
  }

  const onClock = state.current_slot
    ? state.teams.find((t) => t.id === state.current_slot?.drafting_team_id)
    : undefined;
  const lastPicks = state.recent_picks.slice(0, 6);

  return (
    <main className="min-h-screen text-slate-100 p-3 md:p-6 space-y-4">
      {/* Top Header Navigation Bar */}
      <header className="retro-panel p-0">
        <div className="retro-titlebar-gold">
          <div className="flex items-center gap-2">
            <span>🏆</span>
            <span className="font-black tracking-wide uppercase">
              {state.league_name} • SEASON {state.season}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`text-[10px] font-mono font-bold px-1.5 py-0.5 border ${
                connected
                  ? "bg-emerald-950 text-emerald-300 border-emerald-500"
                  : "bg-red-950 text-red-300 border-red-500 animate-pulse"
              }`}
            >
              {connected ? "● LIVE SYNC" : "○ RECONNECTING"}
            </span>
            <span className="font-mono text-[10px] text-yellow-300">
              TV MODE
            </span>
          </div>
        </div>

        <div className="p-3 flex flex-wrap items-center justify-between gap-4 bg-slate-950">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl md:text-3xl font-black font-heading glitter-text">
                {state.league_name}
              </h1>
              <span className="badge bg-blue-950 border-blue-400 text-blue-200">
                {state.status}
              </span>
            </div>
            <div className="flex items-center gap-3 mt-1 text-xs">
              <a
                href={`/draft/${token}/admin`}
                className="btn btn-secondary text-xs inline-flex items-center gap-1"
              >
                👑 Commissioner Console
              </a>
              <a
                href={`/draft/${token}/rosters`}
                className="btn btn-secondary text-xs inline-flex items-center gap-1"
              >
                📋 All Rosters
              </a>
            </div>
          </div>

          {/* Dramatic ON THE CLOCK Banner */}
          {onClock && state.status === "LIVE" && (
            <div className="border-4 border-yellow-400 bg-gradient-to-r from-red-950 via-amber-900 to-red-950 p-2.5 px-5 text-right shadow-[3px_3px_0px_#000000] animate-pulse">
              <div className="text-[10px] uppercase font-mono tracking-widest text-yellow-300 font-bold flex items-center justify-end gap-1">
                <span>⚡</span>
                <span>
                  ROUND {state.current_slot!.round} • OVERALL PICK #{state.current_slot!.pick_number}
                </span>
                <span>⚡</span>
              </div>
              <div className="text-2xl md:text-4xl font-black text-yellow-300 font-heading tracking-tight drop-shadow-[2px_2px_0px_#000000]">
                {onClock.name}
              </div>
              <div className="text-[10px] uppercase tracking-wider text-amber-200 font-bold">
                ★ NOW ON THE CLOCK ★
              </div>
            </div>
          )}

          {state.status === "COMPLETED" && (
            <div className="border-4 border-yellow-400 bg-amber-950 p-3 text-center shadow-[3px_3px_0px_#000000]">
              <div className="text-2xl font-black text-yellow-300 font-heading">
                🏆 DRAFT COMPLETED 🏆
              </div>
              <div className="text-xs text-amber-200 font-mono">
                ALL ROSTERS ARE LOCKED
              </div>
            </div>
          )}
        </div>
      </header>

      {/* Recent Picks Ticker */}
      {lastPicks.length > 0 && (
        <section className="retro-panel p-2.5 space-y-1.5 bg-slate-950">
          <div className="text-[10px] uppercase tracking-widest font-mono text-yellow-300 font-bold flex items-center gap-1">
            <span>📢</span> RECENT DRAFT SELECTIONS:
          </div>
          <div className="flex flex-wrap gap-2">
            {lastPicks.map((p) => (
              <div
                key={p.id}
                className="rounded-none border-t border-l border-t-white/80 border-l-white/80 border-b border-r border-b-black border-r-black px-2 py-1 text-xs font-bold flex items-center gap-1.5 shadow-[1px_1px_0px_#000000]"
                style={{
                  backgroundColor: positionColor(p.position),
                  color: "#000000",
                }}
              >
                <span className="font-mono text-[10px] opacity-75">
                  #{p.pick_number}
                </span>
                <span className="font-black">{p.player_name}</span>
                <span className="bg-black text-white px-1 py-0 text-[9px] font-black">
                  {p.position}
                </span>
                <span className="opacity-80 text-[10px]">
                  ({p.team_name})
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Main Draft Board Grid */}
      <DraftBoard state={state} />

      {/* Top Available Players */}
      {state.top_available.length > 0 && (
        <section className="retro-panel p-0 bg-slate-950">
          <div className="retro-titlebar">
            <span>⭐ TOP AVAILABLE PLAYERS ({state.available_count} REMAINING)</span>
            <span className="text-[10px] font-mono text-cyan-300">
              SORTED BY CONSENSUS RANK
            </span>
          </div>
          <div className="p-3 flex flex-wrap gap-2">
            {state.top_available.slice(0, 16).map((p) => (
              <span
                key={p.player_id}
                className="rounded-none border-t border-l border-t-white/80 border-l-white/80 border-b border-r border-b-black border-r-black px-2 py-1 text-xs font-bold inline-flex items-center gap-1 shadow-[1px_1px_0px_#000000]"
                style={{
                  backgroundColor: positionColor(p.position),
                  color: "#000000",
                }}
              >
                {p.rank !== null && (
                  <span className="font-mono text-[10px] opacity-70">
                    {p.rank}.
                  </span>
                )}
                <span className="font-black">{p.name}</span>
                <PositionBadge position={p.position} size="xs" />
                {p.bye_week && (
                  <span className="text-[9px] font-mono opacity-80">
                    (BYE {p.bye_week})
                  </span>
                )}
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Footer */}
      <footer className="flex items-center justify-between text-[10px] font-mono text-slate-500 pt-2 border-t border-slate-900">
        <span>DRAFT NIGHT • LIVE PROJECTOR DISPLAY</span>
        <span>API: {API_URL}</span>
      </footer>
    </main>
  );
}
