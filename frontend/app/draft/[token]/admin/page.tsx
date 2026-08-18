"use client";

import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { apiJson, connectDraftSocket } from "@/lib/api";
import type { AdminConfig, DraftState } from "@/lib/types";
import { PositionBadge } from "@/components/PositionBadge";

export default function AdminPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const [config, setConfig] = useState<AdminConfig | null>(null);
  const [state, setState] = useState<DraftState | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  const [keeperTeam, setKeeperTeam] = useState("");
  const [keeperPlayer, setKeeperPlayer] = useState("");
  const [keeperRound, setKeeperRound] = useState(1);
  const [csvText, setCsvText] = useState("");
  const [exported, setExported] = useState<string | null>(null);
  const [rosterSlotsText, setRosterSlotsText] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (config) setRosterSlotsText(config.league.roster_slots.join("\n"));
  }, [config]);

  const loadConfig = useCallback(async () => {
    for (let attempt = 1; attempt <= 4; attempt++) {
      try {
        setConfig(
          await apiJson<AdminConfig>(`/api/draft/${token}/admin/config`),
        );
        setError(null);
        return;
      } catch (e) {
        if (attempt === 4) {
          setError(e instanceof Error ? e.message : "Failed to load");
        } else {
          await new Promise((resolve) => setTimeout(resolve, 5000));
        }
      }
    }
  }, [token]);

  const configRef = useRef<AdminConfig | null>(null);
  configRef.current = config;

  useEffect(() => {
    let ws: WebSocket;
    let closed = false;
    loadConfig();
    const openSocket = () => {
      ws = connectDraftSocket(token, setState, (ok) => {
        setConnected(ok);
        if (ok && !configRef.current) loadConfig();
      });
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
  }, [loadConfig, token]);

  async function action(
    method: string,
    path: string,
    body?: unknown,
    reload = true,
  ): Promise<boolean> {
    setError(null);
    setNotice(null);
    try {
      await apiJson(path, {
        method,
        body: body ? JSON.stringify(body) : undefined,
      });
      if (reload) await loadConfig();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
      return false;
    }
  }

  function flash(ok: boolean, text: string) {
    setNotice({ ok, text });
    setTimeout(() => setNotice(null), 4000);
  }

  if (error && !config) {
    return (
      <main className="min-h-screen text-slate-100 flex items-center justify-center p-6">
        <div className="retro-panel p-5 border-2 border-red-500 bg-red-950/80 max-w-sm text-center space-y-3">
          <div className="text-2xl">⚠️</div>
          <div className="font-bold text-sm text-red-200 uppercase">
            Failed to Load Console
          </div>
          <p className="text-xs text-red-300 font-mono">{error}</p>
          <button
            onClick={() => loadConfig()}
            className="btn btn-secondary text-xs"
          >
            Retry
          </button>
        </div>
      </main>
    );
  }

  if (!config) {
    return (
      <main className="min-h-screen text-slate-100 flex items-center justify-center p-6">
        <div className="retro-panel p-5 border-2 border-slate-500 bg-slate-900 max-w-xs text-center space-y-2">
          <div className="text-2xl animate-spin">👑</div>
          <div className="font-bold text-xs uppercase text-yellow-300">
            LOADING COMMISSIONER CONSOLE…
          </div>
        </div>
      </main>
    );
  }

  const { league, teams, slots, keepers, players, validation } = config;
  const editable = league.status === "SETUP" || league.status === "READY";

  async function updateSlot(slotId: number, teamId: number) {
    const ok = await action(
      "PUT",
      `/api/draft/${token}/admin/slots/${slotId}`,
      { drafting_team_id: Number(teamId) },
    );
    if (ok) flash(true, "Slot updated");
  }

  async function addKeeper() {
    const ok = await action("POST", `/api/draft/${token}/admin/keepers`, {
      team_id: Number(keeperTeam),
      player_id: Number(keeperPlayer),
      round: Number(keeperRound),
    });
    if (ok) flash(true, "Keeper added");
  }

  async function removeKeeper(id: number) {
    await action("DELETE", `/api/draft/${token}/admin/keepers/${id}`);
  }

  async function importCsvFile(file: File) {
    const fd = new FormData();
    fd.append("file", file);
    setError(null);
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/draft/${token}/admin/import/csv`,
        { method: "POST", body: fd },
      );
      if (!res.ok) throw new Error((await res.json()).detail ?? "Import failed");
      flash(true, "Players imported");
      await loadConfig();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    }
  }

  async function importKeeperFiles(files: FileList) {
    const fd = new FormData();
    for (const f of Array.from(files)) fd.append("files", f);
    setError(null);
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/draft/${token}/admin/import/keepers`,
        { method: "POST", body: fd },
      );
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail ?? "Import failed");
      const { stats, warnings } = body;
      const parts = [
        `${stats?.created ?? 0} created, ${stats?.updated ?? 0} updated`,
        stats?.unmatched_teams?.length
          ? `unmatched teams: ${stats.unmatched_teams.join(", ")}`
          : null,
        stats?.unmatched_players?.length
          ? `unmatched players: ${stats.unmatched_players.join(", ")}`
          : null,
        warnings?.length ? `warnings: ${warnings.join("; ")}` : null,
      ].filter(Boolean);
      flash(true, `Keepers imported — ${parts.join(" · ")}`);
      await loadConfig();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    }
  }

  async function clearKeeperCandidates() {
    const ok = await action(
      "DELETE",
      `/api/draft/${token}/admin/keepers/candidates`,
    );
    if (ok) flash(true, "Keeper candidates cleared");
  }

  async function importCsvText() {
    if (!csvText.trim()) return;
    try {
      await apiJson(`/api/draft/${token}/admin/import/text`, {
        method: "POST",
        body: JSON.stringify({ csv: csvText }),
      });
      flash(true, "Players imported");
      setCsvText("");
      await loadConfig();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    }
  }

  async function exportResults() {
    const data = await apiJson<unknown>(
      `/api/draft/${token}/admin/export`,
    );
    setExported(JSON.stringify(data, null, 2));
  }

  async function saveRosterSlots() {
    const slots = rosterSlotsText
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    if (!slots.length) return;
    const ok = await action("PUT", `/api/draft/${token}/admin/roster`, { slots });
    if (ok) flash(true, "Roster slots saved");
  }

  async function removeDraft() {
    if (
      !window.confirm(
        "Delete this entire draft? This cannot be undone.",
      )
    )
      return;
    const ok = await action("DELETE", `/api/draft/${token}/admin/delete`);
    if (ok) window.location.href = "/";
  }

  async function start() {
    const ok = await action("POST", `/api/draft/${token}/admin/start`);
    if (ok) flash(true, "Draft started");
  }
  async function reopen() {
    await action("POST", `/api/draft/${token}/admin/reopen`);
  }
  async function undo() {
    const ok = await action("POST", `/api/draft/${token}/admin/undo`);
    if (ok) flash(true, "Last pick undone");
  }
  async function makePickForCurrent(slotId: number | undefined, playerId: number) {
    const ok = await action(
      "POST",
      `/api/draft/${token}/admin/picks`,
      {
        slot_id: slotId,
        player_id: playerId,
        override: true,
      },
      false,
    );
    if (ok) flash(true, "Pick recorded");
  }

  return (
    <main className="min-h-screen text-slate-100 p-3 sm:p-6 max-w-6xl mx-auto space-y-6">
      {/* Top Header Navigation Box */}
      <header className="retro-panel p-0 shadow-[4px_4px_0px_#000000]">
        <div className="retro-titlebar-gold">
          <div className="flex items-center gap-2">
            <span>👑</span>
            <span className="font-black uppercase tracking-wide">
              COMMISSIONER CONTROL PANEL • {league.name}
            </span>
          </div>
          <span
            className={`text-[10px] font-mono px-1.5 py-0.5 border ${
              connected
                ? "bg-emerald-950 text-emerald-300 border-emerald-400"
                : "bg-red-950 text-red-300 border-red-400 animate-pulse"
            }`}
          >
            {connected ? "LIVE SYNC" : "OFFLINE"}
          </span>
        </div>

        <div className="p-4 flex flex-wrap items-center justify-between gap-4 bg-slate-950">
          <div>
            <Link
              href="/"
              className="text-xs text-yellow-300 hover:underline font-mono"
            >
              ← Back to All Drafts
            </Link>
            <h1 className="text-2xl sm:text-3xl font-black font-heading tracking-tight text-white mt-1">
              {league.name}{" "}
              <span className="text-yellow-400 font-mono text-lg">
                ({league.season})
              </span>
            </h1>
            <p className="text-xs text-slate-400 font-mono mt-0.5">
              {league.num_teams} Teams • {league.num_rounds} Rounds • Status:{" "}
              <span className="badge bg-emerald-950 text-emerald-300 border-emerald-500">
                {league.status}
              </span>
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            {league.status === "LIVE" && (
              <button className="btn btn-danger text-xs" onClick={undo}>
                ⏮ Undo Last Pick
              </button>
            )}
            {league.status === "COMPLETED" && (
              <button className="btn btn-secondary text-xs" onClick={reopen}>
                🔄 Reopen Draft
              </button>
            )}
            <button className="btn btn-secondary text-xs" onClick={loadConfig}>
              ⟳ Refresh
            </button>
            <a
              href={`/draft/${token}/keepers`}
              className="btn btn-gold text-xs inline-flex items-center gap-1"
            >
              ★ Keeper Admin
            </a>
            <a
              href={`/draft/${token}/display`}
              className="btn btn-secondary text-xs inline-flex items-center gap-1"
            >
              📺 TV Board
            </a>
            {editable && (
              <button
                className="btn btn-primary text-xs"
                onClick={start}
                disabled={!validation.valid}
                title={
                  validation.valid
                    ? "Start the draft"
                    : "Fix validation errors to start"
                }
              >
                ▶ Validate &amp; Start Draft
              </button>
            )}
            <button className="btn btn-danger text-xs" onClick={removeDraft}>
              ✕ Delete Draft
            </button>
          </div>
        </div>
      </header>

      {notice && (
        <div
          className={`retro-panel p-2.5 text-xs font-mono font-bold ${
            notice.ok
              ? "border-emerald-500 bg-emerald-950 text-emerald-200"
              : "border-red-500 bg-red-950 text-red-200"
          }`}
        >
          {notice.ok ? "✓ SUCCESS: " : "⚠️ NOTICE: "}
          {notice.text}
        </div>
      )}
      {error && (
        <div className="retro-panel p-2.5 text-xs font-mono font-bold border-red-500 bg-red-950 text-red-200">
          ⚠️ ERROR: {error}
        </div>
      )}

      {/* Validation Panel */}
      <section className="retro-panel p-0 shadow-[3px_3px_0px_#000000]">
        <div className="retro-titlebar">
          <span>⚙️ DRAFT VALIDATION STATUS</span>
          <span
            className={`font-mono text-[10px] font-bold ${
              validation.valid ? "text-emerald-300" : "text-red-300"
            }`}
          >
            [{validation.valid ? "READY FOR DRAFT" : "ACTION REQUIRED"}]
          </span>
        </div>
        <div className="p-4 space-y-2 bg-slate-950">
          {validation.errors.length === 0 && validation.warnings.length === 0 && (
            <p className="text-xs text-emerald-400 font-mono">
              ✓ All validation checks passed. League is ready to begin.
            </p>
          )}
          <ul className="space-y-1 text-xs font-mono">
            {validation.errors.map((v, i) => (
              <li key={i} className="text-red-300 bg-red-950/60 p-1.5 border border-red-800">
                <span className="font-bold text-red-400">ERROR:</span> {v.message}
              </li>
            ))}
            {validation.warnings.map((v, i) => (
              <li key={i} className="text-amber-300 bg-amber-950/60 p-1.5 border border-amber-800">
                <span className="font-bold text-amber-400">WARNING:</span> {v.message}
              </li>
            ))}
          </ul>
          {editable && (
            <button
              className="btn btn-secondary text-xs mt-2"
              onClick={() => action("POST", `/api/draft/${token}/admin/validate`)}
            >
              Re-run Validation Checks
            </button>
          )}
        </div>
      </section>

      {/* Commissioner Override Pick (Live Draft) */}
      {league.status === "LIVE" && state && (
        <section className="retro-panel p-0 shadow-[3px_3px_0px_#000000] border-amber-500">
          <div className="retro-titlebar-gold">
            <span>⚡ COMMISSIONER LIVE OVERRIDE PICK</span>
            <span className="text-[10px] font-mono text-yellow-300">
              MANUAL INTERVENTION
            </span>
          </div>
          <div className="p-4 bg-slate-950">
            <OverridePick
              state={state}
              players={players}
              keepers={keepers}
              onPick={(slotId, playerId) =>
                makePickForCurrent(slotId, playerId)
              }
            />
          </div>
        </section>
      )}

      {/* Draft History */}
      {state && (
        <section className="retro-panel p-0 shadow-[3px_3px_0px_#000000]">
          <div className="retro-titlebar">
            <span>📜 RECENT DRAFT PICKS LOG</span>
            <span className="text-[10px] font-mono text-slate-300">
              AUDIT TRAIL
            </span>
          </div>
          <div className="p-4 bg-slate-950">
            {state.recent_picks.length === 0 && (
              <p className="text-xs text-slate-500 font-mono">No picks recorded yet.</p>
            )}
            <ul className="space-y-1 text-xs font-mono">
              {state.recent_picks.map((p) => (
                <li key={p.id} className="flex items-center gap-2 border-b border-slate-900 pb-1">
                  <span className="text-yellow-400 font-bold w-8">
                    #{p.pick_number}
                  </span>
                  <span className="font-sans font-bold text-white">
                    {p.player_name}
                  </span>
                  <PositionBadge position={p.position} size="xs" />
                  <span className="text-slate-400">— {p.team_name}</span>
                  {p.pick_type !== "live" && (
                    <span className="badge bg-amber-950 text-amber-300 border-amber-500 text-[9px]">
                      {p.pick_type}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {/* Team Access Links */}
      <section className="retro-panel p-0 shadow-[3px_3px_0px_#000000]">
        <div className="retro-titlebar">
          <span>🔗 INDIVIDUAL TEAM ACCESS LINKS ({teams.length})</span>
          <span className="text-[10px] font-mono text-cyan-300">
            SHARE WITH MANAGERS
          </span>
        </div>
        <div className="p-4 bg-slate-950 space-y-3">
          <div className="grid gap-2 sm:grid-cols-2 md:grid-cols-3">
            {teams.map((t) => (
              <a
                key={t.id}
                href={`/draft/${token}/team/${t.access_token}`}
                className="border border-slate-700 bg-black/60 p-2.5 text-xs hover:border-yellow-400 transition-none block"
              >
                <div className="text-yellow-400 font-mono font-bold text-[10px]">
                  PICK #{t.draft_position}
                </div>
                <div className="font-bold text-white truncate text-sm">
                  {t.name}
                </div>
                {t.manager_name && (
                  <div className="text-[10px] text-slate-400 font-mono">
                    Manager: {t.manager_name}
                  </div>
                )}
              </a>
            ))}
          </div>
        </div>
      </section>

      {/* Roster Slots Configuration */}
      {editable && (
        <section className="retro-panel p-0 shadow-[3px_3px_0px_#000000]">
          <div className="retro-titlebar">
            <span>📋 ROSTER SLOTS CONFIGURATION</span>
            <span className="text-[10px] font-mono text-slate-300">
              PRE-DRAFT SETTING
            </span>
          </div>
          <div className="p-4 bg-slate-950 space-y-2">
            <p className="text-xs text-slate-400 font-mono">
              One slot per line. Use Flex for RB/WR/TE. Players that do not fit
              starting slots automatically route to Bench.
            </p>
            <textarea
              className="input h-28 font-mono text-xs"
              value={rosterSlotsText}
              onChange={(e) => setRosterSlotsText(e.target.value)}
            />
            <button
              className="btn btn-secondary text-xs"
              disabled={!rosterSlotsText.trim()}
              onClick={saveRosterSlots}
            >
              Save Roster Slots
            </button>
          </div>
        </section>
      )}

      {/* Draft Grid / Slots Editor */}
      <section className="retro-panel p-0 shadow-[3px_3px_0px_#000000]">
        <div className="retro-titlebar">
          <span>📊 DRAFT SLOTS &amp; TRADED PICKS ({slots.length})</span>
          <span className="text-[10px] font-mono text-slate-300">
            ORDER &amp; OWNERSHIP
          </span>
        </div>
        <div className="p-4 bg-slate-950 overflow-x-auto">
          <table className="retro-table text-xs font-mono">
            <thead>
              <tr>
                <th>PICK</th>
                <th>ROUND</th>
                <th>ORIGINAL OWNER</th>
                <th>DRAFTING TEAM</th>
                <th>STATUS</th>
              </tr>
            </thead>
            <tbody>
              {slots.map((s) => {
                const original = teams.find((t) => t.id === s.original_team_id);
                return (
                  <tr key={s.slot_id} className="hover:bg-slate-900">
                    <td className="text-yellow-400 font-bold">#{s.pick_number}</td>
                    <td>R{s.round}</td>
                    <td className="text-slate-400">{original?.name ?? "?"}</td>
                    <td>
                      {editable ? (
                        <select
                          className="input w-44 py-1 text-xs"
                          value={s.drafting_team_id}
                          onChange={(e) =>
                            updateSlot(s.slot_id, Number(e.target.value))
                          }
                        >
                          {teams.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.name}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span className="font-bold text-white">
                          {
                            teams.find((t) => t.id === s.drafting_team_id)
                              ?.name
                          }
                        </span>
                      )}
                    </td>
                    <td>
                      <span
                        className={`badge ${
                          s.status === "FILLED"
                            ? "bg-slate-800 text-slate-200 border-slate-600"
                            : s.status === "KEEPER"
                              ? "bg-amber-950 text-amber-300 border-amber-500"
                              : "bg-emerald-950 text-emerald-300 border-emerald-500"
                        }`}
                      >
                        {s.status}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Keepers Management */}
      <section className="retro-panel p-0 shadow-[3px_3px_0px_#000000]">
        <div className="retro-titlebar-gold">
          <span>★ CONFIRMED KEEPERS ({keepers.length})</span>
          <span className="text-[10px] font-mono">LOCKS AT DRAFT</span>
        </div>
        <div className="p-4 bg-slate-950 space-y-3">
          {editable && (
            <div className="flex flex-wrap gap-2">
              <select
                className="input w-36 text-xs"
                value={keeperTeam}
                onChange={(e) => setKeeperTeam(e.target.value)}
              >
                <option value="">Select Team…</option>
                {teams.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
              <select
                className="input w-48 text-xs"
                value={keeperPlayer}
                onChange={(e) => setKeeperPlayer(e.target.value)}
              >
                <option value="">Select Player…</option>
                {players
                  .filter((p) => !p.taken)
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.position})
                    </option>
                  ))}
              </select>
              <input
                className="input w-20 text-xs font-mono"
                type="number"
                min={1}
                max={league.num_rounds}
                value={keeperRound}
                onChange={(e) => setKeeperRound(Number(e.target.value))}
                placeholder="Rnd"
              />
              <button
                className="btn btn-gold text-xs"
                disabled={!keeperTeam || !keeperPlayer}
                onClick={addKeeper}
              >
                + Add Keeper
              </button>
            </div>
          )}

          {keepers.length === 0 && (
            <p className="text-xs text-slate-500 font-mono">
              No manual keepers added yet.
            </p>
          )}

          <ul className="space-y-1 text-xs font-mono">
            {keepers.map((k) => (
              <li
                key={k.keeper_id}
                className="flex items-center gap-2 border border-slate-800 bg-black/60 p-1.5 px-2"
              >
                <span className="font-sans font-bold text-white">
                  {k.player_name}
                </span>
                <PositionBadge position={k.position} size="xs" />
                <span className="text-slate-400">
                  → {k.team_name} • Round {k.round}
                </span>
                {editable && (
                  <button
                    className="ml-auto text-red-400 hover:text-red-300 font-bold"
                    onClick={() => removeKeeper(k.keeper_id)}
                  >
                    [Remove]
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* Keeper Candidates Import */}
      <section className="retro-panel p-0 shadow-[3px_3px_0px_#000000]">
        <div className="retro-titlebar">
          <span>📁 KEEPER CANDIDATES IMPORT ({config.keeper_candidates.length})</span>
          <span className="text-[10px] font-mono text-cyan-300">CSV IMPORTER</span>
        </div>
        <div className="p-4 bg-slate-950 space-y-3">
          {editable && (
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="file"
                accept=".csv"
                multiple
                className="text-xs font-mono text-slate-400 file:btn file:btn-secondary file:mr-2 file:text-xs"
                onChange={(e) => {
                  const fs = e.target.files;
                  if (fs?.length) importKeeperFiles(fs);
                  e.target.value = "";
                }}
              />
              <span className="text-[11px] text-slate-400 font-mono">
                Roster CSVs (filename = team) or keepers_2024.csv
              </span>
            </div>
          )}

          {config.keeper_candidates.length === 0 ? (
            <p className="text-xs text-slate-500 font-mono">
              No keeper candidates imported yet.
            </p>
          ) : (
            <>
              <ul className="space-y-1 text-xs font-mono max-h-48 overflow-y-auto">
                {config.keeper_candidates.map((k) => (
                  <li
                    key={k.candidate_id}
                    className="flex items-center gap-2 border border-slate-800 bg-black/60 p-1.5 px-2"
                  >
                    <span className="font-sans font-bold text-white">
                      {k.player_name}
                    </span>
                    <PositionBadge position={k.position} size="xs" />
                    <span className="text-slate-400">
                      {k.nfl_team ? `· ${k.nfl_team} ` : ""}· Cost: R{k.cost_round} · {k.team_name}
                    </span>
                  </li>
                ))}
              </ul>
              {editable && (
                <button
                  className="btn btn-danger text-xs"
                  onClick={clearKeeperCandidates}
                >
                  Clear All Candidates
                </button>
              )}
            </>
          )}
        </div>
      </section>

      {/* Player Pool & Rankings Import */}
      <section className="retro-panel p-0 shadow-[3px_3px_0px_#000000]">
        <div className="retro-titlebar">
          <span>👥 PLAYER POOL &amp; RANKINGS ({players.length})</span>
          <span className="text-[10px] font-mono text-yellow-300">
            CSV DATA INGESTION
          </span>
        </div>
        <div className="p-4 bg-slate-950 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={fileRef}
              type="file"
              accept=".csv"
              className="text-xs font-mono text-slate-400 file:btn file:btn-secondary file:mr-2 file:text-xs"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) importCsvFile(f);
              }}
            />
            <span className="text-[11px] text-slate-400 font-mono">
              FantasyPros CSV or standard rankings export
            </span>
          </div>

          <textarea
            className="input h-24 font-mono text-xs"
            placeholder='Paste CSV content here: RK,TIERS,"PLAYER NAME",TEAM,"POS","BYE WEEK",...'
            value={csvText}
            onChange={(e) => setCsvText(e.target.value)}
          />

          <button
            className="btn btn-secondary text-xs"
            disabled={!csvText.trim()}
            onClick={importCsvText}
          >
            Import Pasted CSV
          </button>

          {players.length > 0 && (
            <details className="mt-2 text-xs font-mono">
              <summary className="text-yellow-300 cursor-pointer font-bold">
                [+] View All {players.length} Loaded Players
              </summary>
              <ul className="mt-2 space-y-0.5 text-xs text-slate-400 max-h-48 overflow-y-auto border border-slate-800 p-2 bg-black">
                {players.map((p) => (
                  <li key={p.id} className="flex gap-2">
                    <span className="w-10 text-right text-yellow-400 font-bold">
                      {p.rank ?? "—"}
                    </span>
                    <span className={p.taken ? "line-through text-slate-600 font-bold" : "font-bold text-white"}>
                      {p.name}
                    </span>
                    <PositionBadge position={p.position} size="xs" />
                    <span className="text-slate-400">{p.nfl_team}</span>
                    {p.bye_week && (
                      <span className="text-slate-500">BYE {p.bye_week}</span>
                    )}
                    {p.tier && (
                      <span className="text-amber-400 font-bold">T{p.tier}</span>
                    )}
                    {p.taken && <span className="text-emerald-400 font-bold">[TAKEN]</span>}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      </section>

      {/* JSON Export */}
      <section className="retro-panel p-0 shadow-[3px_3px_0px_#000000]">
        <div className="retro-titlebar">
          <span>💾 EXPORT LEAGUE DRAFT DATA</span>
          <span className="text-[10px] font-mono text-slate-300">JSON BACKUP</span>
        </div>
        <div className="p-4 bg-slate-950 space-y-2">
          <button className="btn btn-secondary text-xs" onClick={exportResults}>
            Generate JSON Export
          </button>
          {exported && (
            <pre className="text-[11px] font-mono text-cyan-300 bg-black border border-slate-800 p-3 overflow-x-auto max-h-60">
              {exported}
            </pre>
          )}
        </div>
      </section>
    </main>
  );
}

function OverridePick({
  state,
  players,
  keepers,
  onPick,
}: {
  state: DraftState;
  players: AdminConfig["players"];
  keepers: AdminConfig["keepers"];
  onPick: (slotId: number | undefined, playerId: number) => void;
}) {
  const [slotId, setSlotId] = useState<string>("");
  const [query, setQuery] = useState<string>("");
  const [playerId, setPlayerId] = useState<string>("");
  const [open, setOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const target = slotId
    ? state.board.find((b) => b.slot_id === Number(slotId))
    : state.current_slot;

  const draftedIds = useMemo(() => {
    const ids = new Set<number>();
    for (const s of state.board) {
      if (s.player_id != null) ids.add(s.player_id);
    }
    for (const k of keepers) ids.add(k.player_id);
    return ids;
  }, [state.board, keepers]);

  const available = useMemo(
    () => players.filter((p) => !p.taken && !draftedIds.has(p.id)),
    [players, draftedIds],
  );

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? available.filter(
          (p) =>
            p.name.toLowerCase().includes(q) ||
            (p.nfl_team ?? "").toLowerCase().includes(q),
        )
      : available;
    const ranked = list
      .slice()
      .sort((a, b) => (a.rank ?? 1 << 30) - (b.rank ?? 1 << 30));
    return q ? ranked : ranked.slice(0, 20);
  }, [available, query]);

  return (
    <div className="flex flex-wrap gap-2 items-end font-mono text-xs">
      <label className="space-y-1 text-slate-300">
        <span className="font-bold">TARGET SLOT:</span>
        <select
          className="input w-48 font-mono text-xs"
          value={slotId}
          onChange={(e) => setSlotId(e.target.value)}
        >
          <option value="">Current (Pick #{state.current_slot?.pick_number})</option>
          {state.board
            .filter((b) => b.status === "OPEN")
            .map((b) => (
              <option key={b.slot_id} value={b.slot_id}>
                Pick #{b.pick_number} · {teamName(state, b.drafting_team_id)}
              </option>
            ))}
        </select>
      </label>

      <div className="relative flex-1 min-w-64 space-y-1 text-slate-300" ref={pickerRef}>
        <span className="font-bold">SELECT PLAYER:</span>
        <input
          className="input w-full font-sans text-xs"
          placeholder="Type to search player name…"
          value={query}
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setQuery(e.target.value);
            setPlayerId("");
            setOpen(true);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") setOpen(false);
          }}
        />
        {open && (
          <div className="absolute z-20 w-full max-h-56 overflow-y-auto border-2 border-slate-500 bg-slate-900 shadow-[4px_4px_0px_#000000]">
            {matches.map((p) => (
              <button
                key={p.id}
                type="button"
                className="w-full text-left px-3 py-1.5 flex items-center gap-2 hover:bg-slate-800 border-b border-slate-800 text-xs font-sans"
                onClick={() => {
                  setPlayerId(String(p.id));
                  setQuery("");
                  setOpen(false);
                }}
              >
                <span className="w-8 text-right text-yellow-400 font-mono font-bold shrink-0">
                  {p.rank ?? "—"}
                </span>
                <span className="font-bold truncate text-white">{p.name}</span>
                <PositionBadge position={p.position} size="xs" />
                <span className="text-slate-400 text-[11px] shrink-0 font-mono">{p.nfl_team}</span>
              </button>
            ))}
            {matches.length === 0 && (
              <p className="text-xs text-slate-400 px-3 py-2 font-mono">
                No matching players found.
              </p>
            )}
          </div>
        )}
      </div>

      <button
        className="btn btn-gold text-xs py-2 px-4 shadow-[2px_2px_0px_#000000]"
        disabled={!playerId}
        onClick={() =>
          onPick(
            target?.slot_id,
            Number(playerId),
          )
        }
      >
        ⚡ Submit Override Pick
      </button>

      {target && (
        <div className="w-full text-[11px] text-yellow-300 font-mono mt-1">
          {target.slot_id === state.current_slot?.slot_id
            ? `On the clock: ${teamName(state, target.drafting_team_id)} (Pick #${target.pick_number})`
            : `Overriding slot: Pick #${target.pick_number} · ${teamName(state, target.drafting_team_id)}`}
        </div>
      )}
    </div>
  );
}

function teamName(state: DraftState, id: number): string {
  return state.teams.find((t) => t.id === id)?.name ?? "?";
}
