/* eslint-disable @next/next/no-img-element */
"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { API_URL, apiJson } from "@/lib/api";
import type { LeagueSummary, LeagueStatus } from "@/lib/types";

interface TeamRow {
  name: string;
  manager_name: string;
}

interface CreatedLeague {
  access_token: string;
  teams: { draft_position: number; name: string; access_token: string }[];
}

export default function Home() {
  const [name, setName] = useState("Draft Night 2002");
  const [season, setSeason] = useState("2026");
  const [numTeams, setNumTeams] = useState(12);
  const [numRounds, setNumRounds] = useState(15);
  const [teamNames, setTeamNames] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<CreatedLeague | null>(null);
  const [leagues, setLeagues] = useState<LeagueSummary[]>([]);

  useEffect(() => {
    apiJson<LeagueSummary[]>("/api/leagues")
      .then(setLeagues)
      .catch(() => setLeagues([]));
  }, []);

  const teamRows: TeamRow[] = useMemo(
    () =>
      Array.from({ length: numTeams }, (_, i) => ({
        name: teamNames[i]?.trim() || `Team ${i + 1}`,
        manager_name: "",
      })),
    [numTeams, teamNames],
  );

  async function create() {
    setError(null);
    setCreating(true);
    try {
      const res = await apiJson<CreatedLeague>("/api/leagues", {
        method: "POST",
        body: JSON.stringify({
          name,
          season,
          num_teams: numTeams,
          num_rounds: numRounds,
          teams: teamRows,
        }),
      });
      setCreated(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create league");
    } finally {
      setCreating(false);
    }
  }

  async function remove(id: number, accessToken: string) {
    if (!window.confirm("Delete this draft? This cannot be undone.")) return;
    try {
      await apiJson(`/api/draft/${accessToken}/admin/delete`, { method: "DELETE" });
      setLeagues((prev) => prev.filter((l) => l.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete draft");
    }
  }

  if (created) {
    return (
      <main className="min-h-screen text-slate-100 flex items-center justify-center p-4">
        <div className="max-w-2xl w-full retro-panel border-2 border-t-slate-300 border-l-slate-300 border-b-black border-r-black bg-slate-950 p-0 shadow-[4px_4px_0px_#000000]">
          <div className="retro-titlebar-gold">
            <span className="flex items-center gap-1.5 font-black">
              <span>🏆</span> LEAGUE CREATED SUCCESSFULLY
            </span>
            <span className="font-mono text-[10px] text-yellow-200">
              [ 2002 EDITION ]
            </span>
          </div>

          <div className="p-6 space-y-5">
            <div>
              <h1 className="text-2xl font-black glitter-text">{name}</h1>
              <p className="text-xs text-yellow-300 font-mono mt-1">
                ★ LEAGUE CREATION CONFIRMED — BOOKMARK & SHARE THESE LINKS ★
              </p>
            </div>

            <div className="space-y-2">
              <LinkRow
                label="👑 COMMISSIONER CONSOLE"
                href={`/draft/${created.access_token}/admin`}
                desc="Configure keepers, draft order, traded picks, and run the draft clock."
                highlight
              />
              <LinkRow
                label="📺 TV / PROJECTOR DRAFT BOARD"
                href={`/draft/${created.access_token}/display`}
                desc="Full-screen read-only draft board for the big screen."
              />
              <div className="pt-2 pb-1 text-xs uppercase tracking-widest text-slate-400 font-bold border-b border-slate-800">
                Team Draft Rooms ({created.teams.length} Teams)
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {created.teams.map((t) => (
                  <LinkRow
                    key={t.draft_position}
                    label={`Pick #${t.draft_position}: ${t.name}`}
                    href={`/draft/${created.access_token}/team/${t.access_token}`}
                    desc={`Live drafting interface.`}
                    compact
                  />
                ))}
              </div>
            </div>

            <div className="pt-4 border-t border-slate-800 flex justify-between items-center">
              <Link
                href="/"
                className="btn btn-secondary inline-flex items-center gap-1"
              >
                ← Create Another League
              </Link>
              <span className="text-[10px] text-slate-500 font-mono">
                SECURE ACCESS TOKENS GENERATED
              </span>
            </div>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen text-slate-100 flex flex-col items-center justify-start p-4 md:p-8 space-y-6">
      {/* 90s Header Banner */}
      <div className="max-w-2xl w-full text-center space-y-2 pt-2">
        <div className="flex items-center justify-center gap-3">
          <img
            src="/assets/badges/football.svg"
            alt="Football"
            className="w-8 h-8 inline-block animate-bounce"
          />
          <h1 className="text-4xl md:text-5xl font-black tracking-tight font-heading">
            <span className="text-yellow-400 drop-shadow-[2px_2px_0px_#000000]">
              DRAFT
            </span>
            <span className="text-cyan-400 drop-shadow-[2px_2px_0px_#000000]">
              {" "}
              NIGHT
            </span>
          </h1>
          <img
            src="/assets/badges/football.svg"
            alt="Football"
            className="w-8 h-8 inline-block animate-bounce"
          />
        </div>
        <p className="text-xs uppercase tracking-widest font-mono text-yellow-300 font-bold">
          ★ PREMIER FANTASY FOOTBALL LIVE DRAFT COMMAND CENTER • EST. 2002 ★
        </p>

        {/* Retro Marquee */}
        <div className="retro-marquee-container shadow-[2px_2px_0px_#000000]">
          <div className="retro-marquee-content">
            +++ WELCOME TO DRAFT NIGHT 2002 +++ REAL-TIME WEBSOCKET SYNC +++ NO
            POP-UPS +++ KEEPER IMPORT SUPPORTED +++ NETSCAPE 4.0 CERTIFIED +++
          </div>
        </div>
      </div>

      {/* Main Form Window */}
      <div className="max-w-2xl w-full retro-panel border-2 border-t-slate-300 border-l-slate-300 border-b-black border-r-black bg-slate-950 p-0 shadow-[4px_4px_0px_#000000]">
        <div className="retro-titlebar">
          <span className="flex items-center gap-2">
            <span>💾</span> CREATE NEW FANTASY LEAGUE
          </span>
          <div className="flex gap-1">
            <button className="w-4 h-4 bg-slate-700 text-[9px] font-mono leading-none border border-slate-400 text-white font-bold">
              _
            </button>
            <button className="w-4 h-4 bg-slate-700 text-[9px] font-mono leading-none border border-slate-400 text-white font-bold">
              □
            </button>
            <button className="w-4 h-4 bg-red-800 text-[9px] font-mono leading-none border border-red-400 text-white font-bold">
              ✕
            </button>
          </div>
        </div>

        <div className="p-5 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="League Name">
              <input
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field label="Season Year">
              <input
                className="input"
                value={season}
                onChange={(e) => setSeason(e.target.value)}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Total Teams">
              <input
                className="input font-mono"
                type="number"
                min={2}
                max={32}
                value={numTeams}
                onChange={(e) => setNumTeams(Number(e.target.value))}
              />
            </Field>
            <Field label="Draft Rounds">
              <input
                className="input font-mono"
                type="number"
                min={1}
                max={40}
                value={numRounds}
                onChange={(e) => setNumRounds(Number(e.target.value))}
              />
            </Field>
          </div>

          <Field label="Team Names (Optional — One Per Line)">
            <textarea
              className="input h-24 font-mono text-xs"
              placeholder={"Team 1\nTeam 2\nTeam 3..."}
              value={teamNames.join("\n")}
              onChange={(e) =>
                setTeamNames(e.target.value.split("\n").slice(0, numTeams))
              }
            />
          </Field>

          {error && (
            <div className="border-2 border-red-500 bg-red-950 p-2 text-red-200 text-xs font-mono font-bold">
              ⚠️ ERROR: {error}
            </div>
          )}

          <button
            onClick={create}
            disabled={creating}
            className="w-full btn btn-gold py-2.5 text-sm tracking-wider flex items-center justify-center gap-2"
          >
            {creating ? (
              <>
                <span className="animate-spin">⏳</span>
                <span>INITIALIZING LEAGUE DRAFT…</span>
              </>
            ) : (
              <>
                <span>⚡</span>
                <span>INITIALIZE LEAGUE DRAFT</span>
                <span>⚡</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Existing Drafts Window */}
      {leagues.length > 0 && (
        <div className="max-w-2xl w-full retro-panel border-2 border-t-slate-300 border-l-slate-300 border-b-black border-r-black bg-slate-950 p-0 shadow-[4px_4px_0px_#000000]">
          <div className="retro-titlebar-gold">
            <span className="flex items-center gap-1.5 font-black">
              <span>📂</span> ACTIVE LEAGUE DATABASE ({leagues.length})
            </span>
            <span className="text-[10px] font-mono text-yellow-300">
              SUPABASE ONLINE
            </span>
          </div>

          <div className="p-4 divide-y divide-slate-800">
            {leagues.map((l) => (
              <div
                key={l.id}
                className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-sm text-yellow-300 truncate">
                      {l.name}
                    </span>
                    <StatusBadge status={l.status} />
                  </div>
                  <p className="text-xs text-slate-400 font-mono mt-0.5">
                    Season {l.season} • {l.num_teams} Teams • {l.num_rounds} Rounds
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <a
                    href={`/draft/${l.access_token}/admin`}
                    className="btn btn-primary text-xs"
                  >
                    Enter →
                  </a>
                  <button
                    onClick={() => remove(l.id, l.access_token)}
                    className="btn btn-danger text-xs"
                    title="Delete Draft"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 90s Web Badges Footer */}
      <footer className="max-w-2xl w-full webring-footer space-y-3">
        <div className="flex flex-wrap items-center justify-center gap-3">
          <img
            src="/assets/badges/netscape.svg"
            alt="Netscape Now 4.0"
            className="h-8 border border-black"
          />
          <img
            src="/assets/badges/ie.svg"
            alt="Microsoft Internet Explorer 5.0"
            className="h-8 border border-black"
          />
          <img
            src="/assets/badges/under-construction.svg"
            alt="Under Construction"
            className="h-6"
          />
          <div className="flex items-center gap-1 bg-black border border-slate-700 px-2 py-1">
            <span className="text-[10px] font-mono text-slate-400 uppercase">
              VISITORS:
            </span>
            <img
              src="/assets/badges/hit-counter.svg"
              alt="Visitor Counter"
              className="h-5"
            />
          </div>
        </div>
        <p className="text-[10px] text-slate-500 font-mono">
          ★ DRAFT NIGHT V1.0 • BEST VIEWED IN 1024x768 • BACKEND: {API_URL} ★
        </p>
      </footer>
    </main>
  );
}

function StatusBadge({ status }: { status: LeagueStatus }) {
  const badgeStyle =
    status === "LIVE"
      ? "bg-emerald-950 text-emerald-300 border-emerald-500"
      : status === "COMPLETED"
        ? "bg-amber-950 text-amber-300 border-amber-500"
        : "bg-slate-900 text-slate-300 border-slate-600";
  return (
    <span
      className={`text-[10px] font-mono font-black px-1.5 py-0.5 border ${badgeStyle}`}
    >
      [{status}]
    </span>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-xs uppercase tracking-wider text-yellow-300 font-bold font-sans">
        {label}
      </span>
      {children}
    </label>
  );
}

function LinkRow({
  label,
  href,
  desc,
  highlight = false,
  compact = false,
}: {
  label: string;
  href: string;
  desc: string;
  highlight?: boolean;
  compact?: boolean;
}) {
  return (
    <a
      href={href}
      className={`block border-2 border-t-slate-500 border-l-slate-500 border-b-black border-r-black bg-slate-900 hover:bg-slate-800 transition-none ${
        compact ? "p-2.5" : "p-3.5"
      } ${highlight ? "border-amber-400 bg-amber-950/40" : ""}`}
    >
      <div
        className={`font-black text-sm ${
          highlight ? "text-yellow-300" : "text-cyan-400"
        }`}
      >
        {label}
      </div>
      <div className="text-xs text-slate-400 mt-0.5">{desc}</div>
    </a>
  );
}
