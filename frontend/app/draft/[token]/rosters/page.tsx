"use client";

import { use, useEffect, useState } from "react";
import { apiJsonRetry } from "@/lib/api";
import type { RostersState } from "@/lib/types";
import { PositionBadge } from "@/components/PositionBadge";
import { getTeamTheme } from "@/lib/theme";

export default function RostersPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const [state, setState] = useState<RostersState | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiJsonRetry<RostersState>(`/api/draft/${token}/rosters`)
      .then((s) => {
        setState(s);
        setError(null);
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Failed to load rosters"),
      );
  }, [token]);

  if (error && !state) {
    return (
      <main className="min-h-screen text-slate-100 flex items-center justify-center p-6">
        <div className="retro-panel p-5 border-2 border-red-500 bg-red-950/80 max-w-sm text-center space-y-3">
          <div className="text-2xl">⚠️</div>
          <div className="font-bold text-sm text-red-200 uppercase">
            Failed to Load Rosters
          </div>
          <p className="text-xs text-red-300 font-mono">{error}</p>
          <button
            onClick={() => window.location.reload()}
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
      <main className="min-h-screen text-slate-100 flex items-center justify-center p-6">
        <div className="retro-panel p-5 border-2 border-slate-500 bg-slate-900 max-w-xs text-center space-y-2">
          <div className="text-2xl animate-spin">📋</div>
          <div className="font-bold text-xs uppercase text-yellow-300">
            LOADING TEAM ROSTERS…
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen text-slate-100 p-3 sm:p-6 max-w-7xl mx-auto space-y-4">
      {/* Top Header Navigation Window */}
      <header className="retro-panel p-0 shadow-[4px_4px_0px_#000000]">
        <div className="retro-titlebar-gold">
          <div className="flex items-center gap-2">
            <span>📋</span>
            <span className="font-black uppercase tracking-wide">
              {state.league_name} • ALL TEAM ROSTERS
            </span>
          </div>
          <span className="text-[10px] font-mono text-yellow-200">
            SEASON {state.season}
          </span>
        </div>

        <div className="p-4 flex flex-wrap items-center justify-between gap-4 bg-slate-950">
          <div>
            <div className="flex items-center gap-2">
              <a
                href={`/draft/${token}/display`}
                className="btn btn-secondary text-xs"
              >
                ← 📺 TV Board
              </a>
              <a
                href={`/draft/${token}/admin`}
                className="btn btn-secondary text-xs"
              >
                👑 Commissioner
              </a>
            </div>
            <h1 className="text-2xl font-black font-heading tracking-tight text-white mt-2">
              {state.league_name}{" "}
              <span className="text-yellow-400 font-mono text-lg">
                ({state.season})
              </span>
            </h1>
            <p className="text-xs text-slate-400 font-mono">
              {state.num_teams} Teams • {state.num_rounds} Rounds • Draft Status:{" "}
              <span className="badge bg-emerald-950 text-emerald-300 border-emerald-500">
                {state.status}
              </span>
            </p>
          </div>
        </div>
      </header>

      {/* Team Rosters Grid */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {state.teams.map((team) => {
          const theme = getTeamTheme(team.draft_position || team.team_name);
          return (
            <section
              key={team.team_id}
              className="retro-panel p-0 shadow-[3px_3px_0px_#000000] flex flex-col"
              style={{ border: theme.cardBorder }}
            >
              <div
                className="retro-titlebar"
                style={{
                  background: theme.headerGradient,
                  color: theme.headerTextColor,
                }}
              >
                <div className="flex items-center gap-1.5 font-bold truncate">
                  <span>{theme.icon}</span>
                  <span className="text-yellow-300 font-mono text-xs">
                    #{team.draft_position}.
                  </span>
                  <span className="truncate">{team.team_name}</span>
                </div>
              </div>

              <div
                className="p-3 space-y-1.5 flex-1"
                style={{ backgroundColor: theme.cardBg }}
              >
                {/* Starting Slots */}
                <div className="space-y-1">
                  {team.roster.map((r, idx) => (
                    <div
                      key={`${r.slot}-${idx}`}
                      className="border border-slate-700/80 bg-black/60 px-2 py-1 flex items-center justify-between text-xs"
                    >
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span className="w-10 font-mono font-bold text-[10px] text-yellow-300 shrink-0">
                          {r.slot}
                        </span>
                        <PositionBadge position={r.position} size="xs" />
                        {r.player ? (
                          <span className="truncate font-bold text-white text-[11px]">
                            {r.player.player_name}
                            <span className="text-[9px] text-slate-400 ml-1 font-mono">
                              {r.player.nfl_team ? `· ${r.player.nfl_team}` : ""}
                            </span>
                          </span>
                        ) : (
                          <span className="text-slate-600 font-mono text-[10px]">
                            —
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Bench Slots */}
                {team.bench.length > 0 && (
                  <div className="pt-2 border-t border-slate-800">
                    <div className="text-[10px] uppercase font-mono tracking-wider text-slate-400 font-bold mb-1">
                      BENCH ({team.bench.length})
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {team.bench.map((p) => (
                        <span
                          key={p.player_id}
                          className="badge bg-slate-900 border-slate-700 text-slate-200 text-[10px] py-0.5"
                        >
                          {p.player_name}{" "}
                          <PositionBadge position={p.position} size="xs" />
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {team.roster.every((r) => !r.player) && team.bench.length === 0 && (
                  <p className="text-xs text-slate-500 font-mono py-4 text-center">
                    No players drafted yet.
                  </p>
                )}
              </div>
            </section>
          );
        })}
      </div>
    </main>
  );
}
