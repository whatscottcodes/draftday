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
    try {
      setConfig(
        await apiJson<AdminConfig>(`/api/draft/${token}/admin/config`),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, [token]);

  useEffect(() => {
    let ws: WebSocket;
    let closed = false;
    loadConfig();
    const openSocket = () => {
      ws = connectDraftSocket(token, setState, setConnected);
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
      <main className="min-h-screen bg-slate-950 text-slate-100 p-6">
        <p className="text-red-400">{error}</p>
      </main>
    );
  }
  if (!config) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 p-6">
        <p className="text-slate-400">Loading commissioner console…</p>
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
    <main className="min-h-screen bg-slate-950 text-slate-100 p-6 max-w-6xl mx-auto space-y-8">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <Link href="/" className="text-sm text-slate-400 hover:text-emerald-400">
            ← All drafts
          </Link>
          <h1 className="text-3xl font-black mt-1">
            {league.name}{" "}
            <span className="text-slate-500 font-normal text-xl">
              · {league.season}
            </span>
          </h1>
          <p className="text-sm text-slate-400">
            Commissioner console · {league.num_teams} teams · {league.num_rounds}{" "}
            rounds · status{" "}
            <span className="badge bg-emerald-500/20 text-emerald-300">
              {league.status}
            </span>
            {!connected && " · reconnecting…"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {league.status === "LIVE" && (
            <button className="btn-danger" onClick={undo}>
              Undo last pick
            </button>
          )}
          {league.status === "COMPLETED" && (
            <button className="btn-secondary" onClick={reopen}>
              Reopen draft
            </button>
          )}
          <button className="btn-secondary" onClick={loadConfig}>
            Refresh
          </button>
          {editable && (
            <button
              className="btn-primary"
              onClick={start}
              disabled={!validation.valid}
              title={
                validation.valid
                  ? "Start the draft"
                  : "Fix validation errors to start"
              }
            >
              Validate & start
            </button>
          )}
          <button className="btn-danger" onClick={removeDraft}>
            Delete draft
          </button>
        </div>
      </header>

      {notice && (
        <div
          className={`rounded-lg px-4 py-2 text-sm ${
            notice.ok
              ? "bg-emerald-900/40 text-emerald-300"
              : "bg-red-900/40 text-red-300"
          }`}
        >
          {notice.text}
        </div>
      )}
      {error && (
        <div className="rounded-lg px-4 py-2 text-sm bg-red-900/40 text-red-300">
          {error}
        </div>
      )}

      {/* Validation */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-3">
          Validation{" "}
          <span
            className={
              validation.valid
                ? "text-emerald-400"
                : "text-red-400"
            }
          >
            {validation.valid ? "— ready" : "— errors"}
          </span>
        </h2>
        {validation.errors.length === 0 && validation.warnings.length === 0 && (
          <p className="text-sm text-slate-500">No issues.</p>
        )}
        <ul className="space-y-1 text-sm">
          {validation.errors.map((v, i) => (
            <li key={i} className="text-red-300">
              <span className="font-bold">Error:</span> {v.message}
            </li>
          ))}
          {validation.warnings.map((v, i) => (
            <li key={i} className="text-amber-300">
              <span className="font-bold">Warning:</span> {v.message}
            </li>
          ))}
        </ul>
        {editable && (
          <button
            className="btn-secondary mt-3"
            onClick={() => action("POST", `/api/draft/${token}/admin/validate`)}
          >
            Re-run validation
          </button>
        )}
      </section>

      {/* Roster slots */}
      {editable && (
        <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-3">
            Roster slots
          </h2>
          <p className="text-xs text-slate-500 mb-2">
            One slot per line. Use Flex for a RB/WR/TE slot. Players that do not
            fit a slot go to the bench.
          </p>
          <textarea
            className="input h-32 font-mono text-xs"
            value={rosterSlotsText}
            onChange={(e) => setRosterSlotsText(e.target.value)}
          />
          <button
            className="btn-secondary mt-2"
            disabled={!rosterSlotsText.trim()}
            onClick={saveRosterSlots}
          >
            Save roster slots
          </button>
        </section>
      )}

      {/* Commissioner override pick */}
      {league.status === "LIVE" && state && (
        <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-3">
            Commissioner override
          </h2>
          <OverridePick
            state={state}
            players={players}
            onPick={(slotId, playerId) =>
              makePickForCurrent(slotId, playerId)
            }
          />
        </section>
      )}

      {/* Live board preview */}
      {state && (
        <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-3">
            Draft history
          </h2>
          {state.recent_picks.length === 0 && (
            <p className="text-sm text-slate-500">No picks yet.</p>
          )}
          <ul className="space-y-1 text-sm">
            {state.recent_picks.map((p) => (
              <li key={p.id} className="text-slate-400">
                <span className="text-slate-600">#{p.pick_number}</span>{" "}
                <span className="text-slate-100">{p.player_name}</span>{" "}
                <PositionBadge position={p.position} size="xs" />{" "}
                <span className="text-slate-500">
                  — {p.team_name}
                  {p.pick_type !== "live" && (
                    <span className="badge bg-amber-500/20 text-amber-300 ml-1">
                      {p.pick_type}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Team access links */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-3">
          Team links
        </h2>
        <div className="grid gap-2 sm:grid-cols-2">
          {teams.map((t) => (
            <a
              key={t.id}
              href={`/draft/${token}/team/${t.access_token}`}
              className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm hover:border-emerald-500"
            >
              <span className="text-slate-500">{t.draft_position}.</span>{" "}
              <span className="font-semibold">{t.name}</span>
              {t.manager_name && (
                <span className="text-slate-500"> — {t.manager_name}</span>
              )}
            </a>
          ))}
        </div>
        <p className="text-xs text-slate-600 mt-3">
          TV view:{" "}
          <a
            href={`/draft/${token}/display`}
            className="text-emerald-400 underline"
          >
            /draft/{token}/display
          </a>{" "}
          · Rosters:{" "}
          <a
            href={`/draft/${token}/rosters`}
            className="text-emerald-400 underline"
          >
            /draft/{token}/rosters
          </a>
        </p>
      </section>

      {/* Draft grid editor */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-3">
          Draft slots
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr>
                <th className="px-2 py-1 text-left text-slate-500">Pick</th>
                <th className="px-2 py-1 text-left text-slate-500">Round</th>
                <th className="px-2 py-1 text-left text-slate-500">
                  Original owner
                </th>
                <th className="px-2 py-1 text-left text-slate-500">
                  Drafting team
                </th>
                <th className="px-2 py-1 text-left text-slate-500">Status</th>
              </tr>
            </thead>
            <tbody>
              {slots.map((s) => {
                const original = teams.find(
                  (t) => t.id === s.original_team_id,
                );
                return (
                  <tr key={s.slot_id} className="border-t border-slate-800">
                    <td className="px-2 py-1 text-slate-400">{s.pick_number}</td>
                    <td className="px-2 py-1 text-slate-400">{s.round}</td>
                    <td className="px-2 py-1 text-slate-400">
                      {original?.name ?? "?"}
                    </td>
                    <td className="px-2 py-1">
                      {editable ? (
                        <select
                          className="input w-40"
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
                        <span>
                          {
                            teams.find((t) => t.id === s.drafting_team_id)
                              ?.name
                          }
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-1">
                      <span
                        className={`badge ${
                          s.status === "FILLED"
                            ? "bg-slate-700 text-slate-200"
                            : s.status === "KEEPER"
                              ? "bg-amber-500/20 text-amber-300"
                              : "bg-emerald-500/20 text-emerald-300"
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

      {/* Keepers */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-3">
          Keepers ({keepers.length})
        </h2>
        {editable && (
          <div className="flex flex-wrap gap-2 mb-3">
            <select
              className="input w-36"
              value={keeperTeam}
              onChange={(e) => setKeeperTeam(e.target.value)}
            >
              <option value="">Team…</option>
              {teams.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            <select
              className="input w-44"
              value={keeperPlayer}
              onChange={(e) => setKeeperPlayer(e.target.value)}
            >
              <option value="">Player…</option>
              {players
                .filter((p) => !p.taken)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.position})
                  </option>
                ))}
            </select>
            <input
              className="input w-20"
              type="number"
              min={1}
              max={league.num_rounds}
              value={keeperRound}
              onChange={(e) => setKeeperRound(Number(e.target.value))}
            />
            <button
              className="btn-primary"
              disabled={!keeperTeam || !keeperPlayer}
              onClick={addKeeper}
            >
              Add keeper
            </button>
          </div>
        )}
        {keepers.length === 0 && (
          <p className="text-sm text-slate-500">No keepers configured.</p>
        )}
        <ul className="space-y-1 text-sm">
          {keepers.map((k) => (
            <li
              key={k.keeper_id}
              className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900 px-3 py-1.5"
            >
              <span className="font-semibold">{k.player_name}</span>{" "}
              <PositionBadge position={k.position} size="xs" />{" "}
              <span className="text-slate-500">
                → {k.team_name} · round {k.round}
              </span>
              {editable && (
                <button
                  className="ml-auto text-xs text-red-400 hover:underline"
                  onClick={() => removeKeeper(k.keeper_id)}
                >
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      {/* Player import */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-3">
          Players &amp; rankings ({players.length})
        </h2>
        <div className="flex flex-wrap items-center gap-2 mb-2">
          <input
            ref={fileRef}
            type="file"
            accept=".csv"
            className="text-sm"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) importCsvFile(f);
            }}
          />
          <span className="text-xs text-slate-600">
            FantasyPros export or CSV columns:
            player_id,name,position,nfl_team,status,rank,adp
          </span>
        </div>
        <textarea
          className="input h-24 font-mono text-xs"
          placeholder='Paste a CSV here — e.g. FantasyPros: RK,TIERS,"PLAYER NAME",TEAM,"POS","BYE WEEK",...'
          value={csvText}
          onChange={(e) => setCsvText(e.target.value)}
        />
        <button
          className="btn-secondary mt-2"
          disabled={!csvText.trim()}
          onClick={importCsvText}
        >
          Import pasted CSV
        </button>
        {players.length > 0 && (
          <details className="mt-3">
            <summary className="text-sm text-slate-400 cursor-pointer">
              Browse imported players
            </summary>
            <ul className="mt-2 space-y-0.5 text-xs text-slate-400 max-h-48 overflow-y-auto">
              {players.map((p) => (
                <li key={p.id} className="flex gap-2">
                  <span className="w-10 text-right text-slate-600">
                    {p.rank ?? "—"}
                  </span>
                  <span className={p.taken ? "line-through text-slate-600" : ""}>
                    {p.name}
                  </span>
                  <PositionBadge position={p.position} size="xs" />
                  <span className="text-slate-600">{p.nfl_team}</span>
                  {p.bye_week && (
                    <span className="text-slate-600">BYE {p.bye_week}</span>
                  )}
                  {p.tier && (
                    <span className="text-amber-500/80">Tier {p.tier}</span>
                  )}
                  {p.taken && <span className="text-emerald-500">taken</span>}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>

      {/* Export */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-3">
          Export
        </h2>
        <button className="btn-secondary" onClick={exportResults}>
          Export results (JSON)
        </button>
        {exported && (
          <pre className="mt-3 text-xs text-slate-400 bg-slate-950 rounded-lg p-3 overflow-x-auto max-h-72">
            {exported}
          </pre>
        )}
      </section>
    </main>
  );
}

function OverridePick({
  state,
  players,
  onPick,
}: {
  state: DraftState;
  players: AdminConfig["players"];
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

  const available = useMemo(
    () => players.filter((p) => !p.taken),
    [players],
  );

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? available.filter(
          (p) =>
            p.name.toLowerCase().includes(q) ||
            (p.nfl_team ?? "").toLowerCase().includes(q),
        )
      : available.slice(0, 50);
    return list
      .slice()
      .sort((a, b) => (a.rank ?? 1 << 30) - (b.rank ?? 1 << 30))
      .slice(0, 60);
  }, [available, query]);

  return (
    <div className="flex flex-wrap gap-2 items-end">
      <label className="space-y-1 text-xs text-slate-400">
        Slot
        <select
          className="input w-44"
          value={slotId}
          onChange={(e) => setSlotId(e.target.value)}
        >
          <option value="">Current (pick {state.current_slot?.pick_number})</option>
          {state.board
            .filter((b) => b.status === "OPEN")
            .map((b) => (
              <option key={b.slot_id} value={b.slot_id}>
                Pick {b.pick_number} · {teamName(state, b.drafting_team_id)}
              </option>
            ))}
        </select>
      </label>
      <div className="relative flex-1 min-w-64 space-y-1 text-xs text-slate-400" ref={pickerRef}>
        <span>Player</span>
        <input
          className="input w-full"
          placeholder="Search players…"
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
          <div className="absolute z-20 w-full max-h-56 overflow-y-auto rounded-lg border border-slate-800 bg-slate-900 shadow-xl">
            {matches.map((p) => (
              <button
                key={p.id}
                type="button"
                className="w-full text-left px-3 py-1.5 flex items-center gap-2 hover:bg-slate-800"
                onClick={() => {
                  setPlayerId(String(p.id));
                  setQuery(p.name);
                  setOpen(false);
                }}
              >
                <span className="w-8 text-right text-slate-500 shrink-0">
                  {p.rank ?? "—"}
                </span>
                <span className="font-semibold truncate">{p.name}</span>
                <PositionBadge position={p.position} size="xs" />
                <span className="text-slate-500 shrink-0">{p.nfl_team}</span>
              </button>
            ))}
            {matches.length === 0 && (
              <p className="text-sm text-slate-500 px-3 py-2">
                No players match.
              </p>
            )}
          </div>
        )}
      </div>
      <button
        className="btn-primary"
        disabled={!playerId}
        onClick={() =>
          onPick(
            target?.slot_id,
            Number(playerId),
          )
        }
      >
        Make pick
      </button>
      {target && (
        <p className="text-xs text-slate-500">
          {target.slot_id === state.current_slot?.slot_id
            ? `Current slot: ${teamName(state, target.drafting_team_id)}`
            : `Selected slot: pick ${target.pick_number} · ${teamName(state, target.drafting_team_id)}`}
        </p>
      )}
    </div>
  );
}

function teamName(state: DraftState, id: number): string {
  return state.teams.find((t) => t.id === id)?.name ?? "?";
}