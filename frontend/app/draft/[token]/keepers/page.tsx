"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import { API_URL, apiJson, isUnauthorized } from "@/lib/api";
import type {
  KeeperPreviewCandidate,
  KeeperPreviewTeam,
  KeeperSetup,
} from "@/lib/types";
import { PositionBadge } from "@/components/PositionBadge";
import AdminUnlock from "@/components/AdminUnlock";

export default function KeeperAdminPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const [setup, setSetup] = useState<KeeperSetup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);

  // Historical draft sources
  const [useDraftIds, setUseDraftIds] = useState({ previous: 0, prior: 0 });

  // Yahoo config
  const [yLeague, setYLeague] = useState("");
  const [yGameId, setYGameId] = useState("");
  const [ySeason, setYSeason] = useState("");
  const [yWeek, setYWeek] = useState("");
  const [yKey, setYKey] = useState("");
  const [ySecret, setYSecret] = useState("");
  const [yCode, setYCode] = useState("");
  const [authUrl, setAuthUrl] = useState<string | null>(null);

  // Mapping
  const [mappings, setMappings] = useState<
    Record<number, { draft_name: string; yahoo_name: string }>
  >({});

  // Review
  const [review, setReview] = useState<KeeperPreviewTeam[]>([]);
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null);
  const [dirtyTeamIds, setDirtyTeamIds] = useState<Set<number>>(new Set());
  const [lastRun, setLastRun] = useState<string | null>(null);

  const editable = setup?.league.editable ?? false;

  const loadSetup = useCallback(async () => {
    setError(null);
    try {
      const s = await apiJson<KeeperSetup>(
        `/api/draft/${token}/admin/keepers/setup`,
      );
      setSetup(s);
      const m: Record<number, { draft_name: string; yahoo_name: string }> = {};
      for (const item of s.mappings) {
        m[item.team_id] = { draft_name: item.draft_name, yahoo_name: item.yahoo_name };
      }
      for (const item of s.suggested_mappings) {
        if (!m[item.team_id]) {
          m[item.team_id] = {
            draft_name: item.draft_name,
            yahoo_name: item.yahoo_name,
          };
        } else {
          if (!m[item.team_id].draft_name && item.draft_name) {
            m[item.team_id].draft_name = item.draft_name;
          }
          if (!m[item.team_id].yahoo_name && item.yahoo_name) {
            m[item.team_id].yahoo_name = item.yahoo_name;
          }
        }
      }
      setMappings(m);
      setReview(s.preview.teams);
      setSelectedTeamId((current) =>
        s.preview.teams.some((team) => team.team_id === current)
          ? current
          : (s.preview.teams[0]?.team_id ?? null),
      );
      setDirtyTeamIds(new Set());
      setYLeague(s.yahoo.league_id_external);
      setYGameId(s.yahoo.game_id ? String(s.yahoo.game_id) : "");
      setYSeason(s.yahoo.season_id);
      setYWeek(s.yahoo.week ? String(s.yahoo.week) : "");
    } catch (e) {
      if (isUnauthorized(e)) {
        setLocked(true);
      } else {
        setError(e instanceof Error ? e.message : "Failed to load");
      }
    }
  }, [token]);

  useEffect(() => {
    loadSetup();
  }, [loadSetup]);

  function flash(ok: boolean, text: string) {
    setNotice(text);
    setTimeout(() => setNotice(null), 5000);
  }

  async function postForm(path: string, fd: FormData, label: string) {
    setError(null);
    setBusy(label);
    try {
      const res = await fetch(`${API_URL}${path}`, { method: "POST", body: fd });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          typeof body.detail === "string" ? body.detail : "Request failed",
        );
      }
      return body;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function postJson(path: string, body: unknown, label: string) {
    setError(null);
    setBusy(label);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res = await apiJson<any>(path, {
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      });
      return res;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function uploadDraft(file: File, role: "previous" | "prior") {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("role", role);
    const body = await postForm(
      `/api/draft/${token}/admin/keepers/draft-html`,
      fd,
      "Parsing ClickyDraft history…",
    );
    if (body) {
      flash(true, `Loaded ${body.year} ${role === "previous" ? "previous season" : "season before"} (${body.total_picks} picks)`);
      await loadSetup();
    }
  }

  async function loadAppDraft(role: "previous" | "prior") {
    const draftId = useDraftIds[role];
    if (!draftId) return;
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/use-draft`,
      { draft_league_id: draftId, role },
      "Loading draft…",
    );
    if (body) {
      flash(true, `Loaded ${body.year} ${role === "previous" ? "previous season" : "season before"}`);
      setUseDraftIds((current) => ({ ...current, [role]: 0 }));
      await loadSetup();
    }
  }

  async function uploadRosters(files: FileList) {
    const fd = new FormData();
    for (const f of Array.from(files)) fd.append("files", f);
    const body = await postForm(
      `/api/draft/${token}/admin/keepers/rosters-csv`,
      fd,
      "Uploading rosters…",
    );
    if (body) {
      flash(true, "Rosters loaded");
      await loadSetup();
    }
  }

  async function uploadRosterHtml(file: File) {
    const fd = new FormData();
    fd.append("file", file);
    const body = await postForm(
      `/api/draft/${token}/admin/keepers/rosters-html`,
      fd,
      "Parsing Yahoo rosters…",
    );
    if (body) {
      const week = body.week ? ` for week ${body.week}` : "";
      flash(
        true,
        `Loaded ${Object.keys(body.teams ?? {}).length} teams and ${body.player_count ?? 0} players${week}`,
      );
      await loadSetup();
    }
  }

  async function uploadTransactionsHtml(file: File) {
    const fd = new FormData();
    fd.append("file", file);
    const body = await postForm(
      `/api/draft/${token}/admin/keepers/transactions-html`,
      fd,
      "Parsing Yahoo transactions…",
    );
    if (body) {
      flash(true, `Loaded ${body.trade_count ?? 0} traded players`);
      await loadSetup();
    }
  }

  async function saveYahooConfig() {
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/yahoo-config`,
      {
        league_id_external: yLeague,
        game_id: yGameId ? Number(yGameId) : null,
        season_id: ySeason,
        week: yWeek ? Number(yWeek) : null,
        consumer_key: yKey,
        consumer_secret: ySecret,
      },
      "Saving Yahoo config…",
    );
    if (body) {
      if (body.teams_fetched && body.teams?.length) {
        flash(true, `Yahoo config saved & verified — pulled ${body.teams.length} team names`);
      } else if (body.warning) {
        flash(false, body.warning);
      } else {
        flash(true, "Yahoo config saved");
      }
      setYKey("");
      setYSecret("");
      await loadSetup();
    }
  }

  async function authorizeYahoo() {
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/yahoo/authorize`,
      {},
      "Preparing authorization…",
    );
    if (body) setAuthUrl(body.authorization_url as string);
  }

  async function completeYahooCode() {
    if (!yCode) return;
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/yahoo/callback`,
      { code: yCode },
      "Authorizing & fetching team names…",
    );
    if (body) {
      if (body.teams_fetched && body.teams?.length) {
        flash(true, `Yahoo authorized & verified — pulled ${body.teams.length} team names`);
      } else if (body.warning) {
        flash(false, body.warning);
      } else {
        flash(true, "Yahoo authorized");
      }
      setYCode("");
      setAuthUrl(null);
      await loadSetup();
    }
  }

  async function fetchTeamNames() {
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/yahoo/teams`,
      {},
      "Testing Yahoo connection & fetching team names…",
    );
    if (body) {
      flash(true, `Yahoo connection verified — ${body.count} teams: ${(body.teams || []).join(", ")}`);
      await loadSetup();
    }
  }

  async function fetchRosters() {
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/fetch`,
      {},
      "Fetching rosters from Yahoo…",
    );
    if (body) {
      flash(true, `Fetched rosters for ${body.teams?.length ?? 0} teams`);
      await loadSetup();
    }
  }

  async function saveMappings() {
    const list = Object.entries(mappings).map(([teamId, m]) => ({
      team_id: Number(teamId),
      draft_name: m.draft_name,
      yahoo_name: m.yahoo_name,
    }));
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/mappings`,
      { mappings: list },
      "Saving mappings…",
    );
    if (body) {
      flash(true, "Mappings saved");
      await loadSetup();
    }
  }

  async function identify() {
    const t0 = performance.now();
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/identify`,
      {},
      "Running keeper identification…",
    );
    if (body) {
      const ms = Math.max(1, Math.round(performance.now() - t0));
      const teams = (body.preview as KeeperPreviewTeam[]).length;
      const warnings = (body.warnings as string[]).length;
      setReview(body.preview as KeeperPreviewTeam[]);
      setSelectedTeamId((body.preview as KeeperPreviewTeam[])[0]?.team_id ?? null);
      setDirtyTeamIds(new Set());
      setLastRun(
        `${body.total} keepable players across ${teams} teams in ${ms}ms` +
          (warnings ? ` · ${warnings} warnings` : ""),
      );
      flash(
        true,
        `Identified ${body.total} keepable players across ${teams} teams`,
      );
      await loadSetup();
    }
  }

  async function saveSelectedTeam() {
    const team = review.find((item) => item.team_id === selectedTeamId);
    if (!team) return;
    const teams = [{
      team_id: team.team_id,
      candidates: team.candidates.map((c) => ({
        player_name: c.player_name,
        position: c.position,
        nfl_team: c.nfl_team,
        player_id_external: c.player_id_external,
        cost_round: Number(c.cost_round),
        years_kept: c.years_kept,
        keepable_until_year: c.keepable_until_year,
      })),
    }];
    const body = await postJson(
      `/api/draft/${token}/admin/keepers/save`,
      { teams },
      `Saving ${team.team_name}…`,
    );
    if (body) {
      setDirtyTeamIds((current) => {
        const next = new Set(current);
        next.delete(team.team_id);
        return next;
      });
      setSetup((current) => current ? {
        ...current,
        preview: {
          ...current.preview,
          saved_at: body.saved_at,
          reviewed_team_ids: body.reviewed_team_ids,
          team_saved_at: body.team_saved_at,
        },
      } : current);
      flash(true, `Saved ${team.team_name}`);
    }
  }

  async function exportCsv() {
    setBusy("Exporting…");
    try {
      const data = await apiJson<{
        teams: { filename: string; csv: string }[];
      }>(`/api/draft/${token}/admin/keepers/export`);
      for (const f of data.teams) {
        const blob = new Blob([f.csv], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = f.filename;
        a.click();
        URL.revokeObjectURL(url);
      }
      flash(true, `Downloaded ${data.teams.length} roster CSVs`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setBusy(null);
    }
  }

  function updateCandidate(
    teamIdx: number,
    candIdx: number,
    patch: Partial<KeeperPreviewCandidate>,
  ) {
    if (selectedTeamId !== null) {
      setDirtyTeamIds((current) => new Set(current).add(selectedTeamId));
    }
    setReview((prev) =>
      prev.map((t, ti) =>
        ti === teamIdx
          ? {
              ...t,
              candidates: t.candidates.map((c, ci) =>
                ci === candIdx ? { ...c, ...patch } : c,
              ),
            }
          : t,
      ),
    );
  }

  function removeCandidate(teamIdx: number, candIdx: number) {
    if (selectedTeamId !== null) {
      setDirtyTeamIds((current) => new Set(current).add(selectedTeamId));
    }
    setReview((prev) =>
      prev.map((t, ti) =>
        ti === teamIdx
          ? { ...t, candidates: t.candidates.filter((_, ci) => ci !== candIdx) }
          : t,
      ),
    );
  }

  const previewTotal = useMemo(
    () => review.reduce((n, t) => n + t.candidates.length, 0),
    [review],
  );
  const selectedTeamIndex = review.findIndex(
    (team) => team.team_id === selectedTeamId,
  );
  const selectedTeam = selectedTeamIndex >= 0 ? review[selectedTeamIndex] : null;
  const reviewedTeamIds = new Set(setup?.preview.reviewed_team_ids ?? []);
  const selectedWarnings = selectedTeam
    ? setup?.preview.warnings.filter((warning) =>
        warning.startsWith(`${selectedTeam.team_name}:`),
      ) ?? []
    : [];

  if (locked) {
    return (
      <AdminUnlock
        onUnlocked={() => {
          setLocked(false);
          setError(null);
          loadSetup();
        }}
      />
    );
  }

  if (error && !setup) {
    return (
      <main className="min-h-screen text-slate-100 flex items-center justify-center p-6">
        <div className="retro-panel p-5 border-2 border-red-500 bg-red-950/80 max-w-sm text-center space-y-3">
          <div className="text-2xl">⚠️</div>
          <div className="font-bold text-sm text-red-200 uppercase">
            Failed to Load Keeper Console
          </div>
          <p className="text-xs text-red-300 font-mono">{error}</p>
          <button
            onClick={() => loadSetup()}
            className="btn btn-secondary text-xs"
          >
            Retry
          </button>
        </div>
      </main>
    );
  }

  if (!setup) {
    return (
      <main className="min-h-screen text-slate-100 flex items-center justify-center p-6">
        <div className="retro-panel p-5 border-2 border-slate-500 bg-slate-900 max-w-xs text-center space-y-2">
          <div className="text-2xl animate-spin">★</div>
          <div className="font-bold text-xs uppercase text-yellow-300">
            LOADING KEEPER CONSOLE…
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen text-slate-100 max-w-4xl mx-auto p-3 sm:p-6 space-y-4 font-sans">
      {/* Top Header Window */}
      <header className="retro-panel p-0 shadow-[4px_4px_0px_#000000]">
        <div className="retro-titlebar-gold">
          <div className="flex items-center gap-2">
            <span>★</span>
            <span className="font-black uppercase tracking-wide">
              KEEPER ADMINISTRATION &amp; CALCULATION ENGINE
            </span>
          </div>
          <a
            href={`/draft/${token}/admin`}
            className="btn btn-secondary text-[10px] py-0.5 px-2 font-mono"
          >
            ← Commissioner Console
          </a>
        </div>
        <div className="p-4 bg-slate-950 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-2xl font-black font-heading text-white">
              Keeper Rules &amp; Roster Importer
            </h1>
            <p className="text-xs text-slate-400 font-mono mt-0.5">
              {setup.league.name} • Season {setup.league.season}
              {setup.preview.saved_at ? " • Calculation Saved" : ""}
            </p>
          </div>
        </div>
      </header>

      {error && (
        <div className="retro-panel p-2.5 text-xs font-mono font-bold border-red-500 bg-red-950 text-red-200">
          ⚠️ ERROR: {error}
        </div>
      )}
      {notice && (
        <div className="retro-panel p-2.5 text-xs font-mono font-bold border-emerald-500 bg-emerald-950 text-emerald-200">
          ✓ NOTICE: {notice}
        </div>
      )}

      {busy && (
        <div className="retro-panel p-2.5 text-xs font-mono font-bold border-yellow-400 bg-amber-950 text-yellow-300 flex items-center gap-2" role="status">
          <span className="animate-spin text-sm">⏳</span>
          <span>{busy}</span>
        </div>
      )}

      {/* Step 1: Historical drafts */}
      <section className="retro-panel p-0 shadow-[3px_3px_0px_#000000]">
        <div className="retro-titlebar">
          <span>1 • CLICKYDRAFT / HISTORICAL DRAFT DATA</span>
          <span className="text-[10px] font-mono text-cyan-300">
            2-YEAR RULE ENGINE
          </span>
        </div>
        <div className="p-4 bg-slate-950 space-y-3">
          <p className="text-xs text-slate-400 font-mono">
            Load both previous seasons so keeper costs and 2-consecutive-year
            eligibility rules calculate accurately. Upload saved ClickyDraft HTML
            or select a completed draft.
          </p>
          <div className="space-y-3">
            {(["previous", "prior"] as const).map((role) => {
              const isPrevious = role === "previous";
              const loadedYear = isPrevious
                ? setup.draft.previous_year
                : setup.draft.prior_year;
              return (
                <div
                  key={role}
                  className="border border-slate-700 bg-black/60 p-3 space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <h3 className="text-xs font-bold text-yellow-300 uppercase font-mono">
                      {isPrevious
                        ? "★ Previous Season Draft"
                        : "★ Season Before Draft (2-Year Rule)"}
                    </h3>
                    <span
                      className={`text-[10px] font-mono font-bold px-1.5 py-0.5 border ${
                        loadedYear
                          ? "bg-emerald-950 text-emerald-300 border-emerald-500"
                          : "bg-amber-950 text-amber-300 border-amber-500"
                      }`}
                    >
                      {loadedYear ? `${loadedYear} LOADED` : "REQUIRED"}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      type="file"
                      accept=".html,.htm,text/html"
                      className="min-w-44 flex-1 text-xs text-slate-400 font-mono file:btn file:btn-secondary file:mr-2 file:text-xs"
                      disabled={!!busy}
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) uploadDraft(file, role);
                        e.target.value = "";
                      }}
                    />
                    <span className="text-xs font-mono text-slate-500">or</span>
                    <select
                      className="input min-w-44 flex-1 text-xs"
                      value={useDraftIds[role]}
                      onChange={(e) =>
                        setUseDraftIds((current) => ({
                          ...current,
                          [role]: Number(e.target.value),
                        }))
                      }
                    >
                      <option value={0}>Select Completed App Draft…</option>
                      {setup.previous_drafts.map((draft) => (
                        <option key={draft.id} value={draft.id}>
                          {draft.name} · {draft.season} · {draft.picks} picks
                        </option>
                      ))}
                    </select>
                    <button
                      className="btn btn-secondary text-xs"
                      disabled={!useDraftIds[role] || !!busy}
                      onClick={() => loadAppDraft(role)}
                    >
                      Load
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="pt-2 border-t border-slate-800 text-xs font-mono text-slate-400 space-y-1">
            {Object.entries(setup.draft.draft_counts).map(([year, byTeam]) => (
              <p key={year}>
                <span className="text-yellow-300 font-bold">{year}:</span>{" "}
                {Object.entries(byTeam)
                  .map(([team, count]) => `${team} (${count})`)
                  .join(", ")}
              </p>
            ))}
            {!setup.draft.has_draft && (
              <p className="text-slate-600">No historical drafts loaded yet.</p>
            )}
          </div>
        </div>
      </section>

      {/* Step 2: Yahoo Rosters and Transactions */}
      <section className="retro-panel p-0 shadow-[3px_3px_0px_#000000]">
        <div className="retro-titlebar">
          <span>2 • YAHOO ROSTERS &amp; TRANSACTIONS</span>
          <span className="text-[10px] font-mono text-cyan-300">
            HTML / API INGESTION
          </span>
        </div>
        <div className="p-4 bg-slate-950 space-y-3">
          {/* Yahoo Rosters HTML */}
          <div className="border border-slate-700 bg-black/60 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-bold text-yellow-300 uppercase font-mono">
                ★ Upload Yahoo Starting Rosters HTML
              </label>
              <span
                className={`text-[10px] font-mono font-bold px-1.5 py-0.5 border ${
                  setup.rosters.teams.length > 0
                    ? "bg-emerald-950 text-emerald-300 border-emerald-500"
                    : "bg-amber-950 text-amber-300 border-amber-500"
                }`}
              >
                {setup.rosters.teams.length > 0
                  ? `${setup.rosters.teams.length} TEAMS LOADED`
                  : "REQUIRED"}
              </span>
            </div>
            <p className="text-xs text-slate-400 font-mono">
              In Yahoo Fantasy, open Starting Rosters (Team tab selected), choose
              the desired week, and save the webpage as complete HTML.
            </p>
            <input
              type="file"
              accept=".html,.htm,text/html"
              className="text-xs text-slate-400 font-mono file:btn file:btn-secondary file:mr-2 file:text-xs"
              disabled={!!busy}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) uploadRosterHtml(file);
                e.target.value = "";
              }}
            />
          </div>

          {/* Yahoo Transactions HTML */}
          <div className="border border-slate-700 bg-black/60 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-bold text-yellow-300 uppercase font-mono">
                ★ Upload Yahoo Transactions HTML
              </label>
              <span
                className={`text-[10px] font-mono font-bold px-1.5 py-0.5 border ${
                  setup.transactions.loaded
                    ? "bg-emerald-950 text-emerald-300 border-emerald-500"
                    : "bg-amber-950 text-amber-300 border-amber-500"
                }`}
              >
                {setup.transactions.loaded
                  ? `${setup.transactions.trade_count} TRADED PLAYERS`
                  : "REQUIRED"}
              </span>
            </div>
            <p className="text-xs text-slate-400 font-mono">
              Save the league Transactions page as HTML to match traded players
              back to original drafting teams.
            </p>
            <input
              type="file"
              accept=".html,.htm,text/html"
              className="text-xs text-slate-400 font-mono file:btn file:btn-secondary file:mr-2 file:text-xs"
              disabled={!!busy}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) uploadTransactionsHtml(file);
                e.target.value = "";
              }}
            />
          </div>

          {/* Legacy Yahoo API & CSV Details */}
          <details className="border-t border-slate-800 pt-2 text-xs font-mono">
            <summary className="cursor-pointer text-yellow-300 font-bold uppercase">
              [+] Legacy Yahoo OAuth API &amp; Roster CSV Options
            </summary>
            <div className="mt-3 space-y-3 p-3 bg-slate-900 border border-slate-800">
              <div className="grid grid-cols-2 gap-2">
                <input
                  className="input"
                  placeholder="Yahoo League ID (e.g. 735068)"
                  value={yLeague}
                  onChange={(e) => setYLeague(e.target.value)}
                />
                <input
                  className="input"
                  placeholder="Game ID (449)"
                  value={yGameId}
                  onChange={(e) => setYGameId(e.target.value)}
                />
                <input
                  className="input"
                  placeholder="Season ID (2025)"
                  value={ySeason}
                  onChange={(e) => setYSeason(e.target.value)}
                />
                <input
                  className="input"
                  placeholder="Week (blank = current)"
                  value={yWeek}
                  onChange={(e) => setYWeek(e.target.value)}
                />
                <input
                  className="input"
                  placeholder="Consumer Key"
                  value={yKey}
                  onChange={(e) => setYKey(e.target.value)}
                />
                <input
                  className="input"
                  type="password"
                  placeholder="Consumer Secret"
                  value={ySecret}
                  onChange={(e) => setYSecret(e.target.value)}
                />
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  className="btn btn-secondary text-xs"
                  onClick={saveYahooConfig}
                  disabled={!!busy}
                >
                  Save Yahoo Config
                </button>
                {setup.yahoo.configured && (
                  <span className="text-[11px] text-slate-400">
                    League {setup.yahoo.league_id_external || "—"} ·{" "}
                    {setup.yahoo.has_token ? "Authorized" : "Not Authorized"}
                  </span>
                )}
              </div>

              {setup.yahoo.configured && (
                <div className="space-y-2 pt-2 border-t border-slate-800">
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      className="btn btn-secondary text-xs"
                      onClick={authorizeYahoo}
                      disabled={!!busy}
                    >
                      {setup.yahoo.has_token ? "Re-authorize" : "Authorize with Yahoo"}
                    </button>
                    {authUrl && (
                      <span className="text-xs text-slate-400">
                        Open{" "}
                        <a
                          href={authUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="text-emerald-400 underline"
                        >
                          this link
                        </a>
                        , authorize, then paste code.
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      className="input flex-1"
                      placeholder="Paste authorization code here"
                      value={yCode}
                      onChange={(e) => setYCode(e.target.value)}
                    />
                    <button
                      className="btn btn-primary text-xs"
                      onClick={completeYahooCode}
                      disabled={!yCode || !!busy}
                    >
                      Connect
                    </button>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      className="btn btn-secondary text-xs"
                      onClick={fetchTeamNames}
                      disabled={!setup.yahoo.has_token || !!busy}
                    >
                      Test Connection &amp; Refresh Teams
                    </button>
                    <button
                      className="btn btn-primary text-xs"
                      onClick={fetchRosters}
                      disabled={!setup.yahoo.has_token || !!busy}
                    >
                      Fetch Rosters From Yahoo
                    </button>
                  </div>
                </div>
              )}

              <div className="pt-2 border-t border-slate-800">
                <input
                  type="file"
                  accept=".csv"
                  multiple
                  className="text-xs text-slate-400 file:btn file:btn-secondary file:mr-2 file:text-xs"
                  onChange={(e) => {
                    if (e.target.files?.length) uploadRosters(e.target.files);
                    e.target.value = "";
                  }}
                />
                <span className="text-[10px] text-slate-500 ml-2">
                  Legacy per-team CSV roster files
                </span>
              </div>
            </div>
          </details>

          <p className="text-xs font-mono text-slate-400">
            {setup.rosters.teams.length > 0
              ? `✓ ${setup.rosters.teams.length} Yahoo teams loaded (${setup.rosters.player_count} players): ${setup.rosters.teams.join(", ")}`
              : "No Yahoo team data loaded yet."}
          </p>
        </div>
      </section>

      {/* Step 3: Team Name Mapping */}
      <section className="retro-panel p-0 shadow-[3px_3px_0px_#000000]">
        <div className="retro-titlebar">
          <span>3 • TEAM NAME MAPPINGS</span>
          <span className="text-[10px] font-mono text-yellow-300">
            DRAFT TEAM ↔ YAHOO TEAM
          </span>
        </div>
        <div className="p-4 bg-slate-950 space-y-3">
          <div className="grid grid-cols-[1fr_1fr_1fr] gap-2 text-xs font-mono text-yellow-300 font-bold border-b border-slate-800 pb-1">
            <span>APP DRAFT TEAM</span>
            <span>CLICKYDRAFT NAME</span>
            <span>YAHOO TEAM NAME</span>
          </div>

          <div className="space-y-2">
            {setup.teams.map((team) => {
              const m = mappings[team.id] ?? { draft_name: "", yahoo_name: "" };
              return (
                <div
                  key={team.id}
                  className="grid grid-cols-[1fr_1fr_1fr] gap-2 items-center"
                >
                  <div className="font-bold text-sm text-white truncate font-sans">
                    {team.name}
                  </div>
                  <select
                    className="input text-xs"
                    value={m.draft_name}
                    onChange={(e) =>
                      setMappings((prev) => ({
                        ...prev,
                        [team.id]: { ...prev[team.id], draft_name: e.target.value },
                      }))
                    }
                  >
                    <option value="">— None —</option>
                    {setup.draft.draft_teams.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                  <select
                    className="input text-xs"
                    value={m.yahoo_name}
                    onChange={(e) =>
                      setMappings((prev) => ({
                        ...prev,
                        [team.id]: { ...prev[team.id], yahoo_name: e.target.value },
                      }))
                    }
                  >
                    <option value="">— None —</option>
                    {setup.rosters.teams.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </div>
              );
            })}
          </div>

          <button
            className="btn btn-secondary text-xs mt-2"
            onClick={saveMappings}
            disabled={!!busy}
          >
            Save Team Mappings
          </button>
        </div>
      </section>

      {/* Step 4: Identify & Review */}
      <section className="retro-panel p-0 shadow-[3px_3px_0px_#000000]">
        <div className="retro-titlebar-gold">
          <span>4 • KEEPER IDENTIFICATION &amp; TEAM REVIEW ({previewTotal})</span>
          {setup.preview.saved_at && (
            <span className="text-[10px] font-mono text-yellow-200">
              {setup.preview.reviewed_team_ids.length}/{review.length} TEAMS SAVED
            </span>
          )}
        </div>

        <div className="p-4 bg-slate-950 space-y-3">
          <div className="flex flex-wrap gap-2">
            <button
              className="btn btn-gold text-xs inline-flex items-center gap-1.5"
              onClick={identify}
              disabled={!!busy}
            >
              <span>⚡</span>
              <span>
                {busy === "Running keeper identification…"
                  ? "Calculating…"
                  : "Run Keeper Calculation Engine"}
              </span>
            </button>
            <button
              className="btn btn-secondary text-xs"
              onClick={exportCsv}
              disabled={!!busy}
            >
              Export Per-Team CSVs
            </button>
          </div>

          {lastRun && (
            <div className="p-2 bg-emerald-950 border border-emerald-500 text-xs text-emerald-200 font-mono">
              ✓ Calculation Result: {lastRun}
            </div>
          )}

          {review.length > 0 && (
            <div className="border border-slate-700 bg-black/60 p-3 space-y-2">
              <label className="block text-xs font-bold uppercase tracking-wider text-yellow-300 font-mono">
                Select Team to Review &amp; Adjust:
              </label>
              <select
                className="input w-full text-xs font-bold"
                value={selectedTeamId ?? ""}
                onChange={(event) =>
                  setSelectedTeamId(Number(event.target.value))
                }
              >
                {review.map((team) => {
                  const dirty = dirtyTeamIds.has(team.team_id);
                  const saved = reviewedTeamIds.has(team.team_id);
                  const status = dirty
                    ? "[UNSAVED CHANGES]"
                    : saved
                      ? "[SAVED]"
                      : "[NOT SAVED]";
                  return (
                    <option key={team.team_id} value={team.team_id}>
                      {team.team_name} ({team.candidates.length} candidates) — {status}
                    </option>
                  );
                })}
              </select>
            </div>
          )}

          {selectedWarnings.length > 0 && (
            <div className="space-y-1 p-2 bg-amber-950 border border-amber-500 text-xs text-amber-200 font-mono">
              {selectedWarnings.map((w, i) => (
                <div key={i}>⚠️ {w}</div>
              ))}
            </div>
          )}

          {review.length === 0 ? (
            <p className="text-xs text-slate-500 font-mono py-4 text-center">
              Load historical drafts &amp; rosters, map team names, then click
              &quot;Run Keeper Calculation Engine&quot;.
            </p>
          ) : (
            selectedTeam && (
              <div className="space-y-3 pt-2">
                <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                  <h3 className="font-bold text-sm text-yellow-300 font-heading">
                    {selectedTeam.team_name} ({selectedTeam.candidates.length} Candidates)
                  </h3>
                  <span className="text-xs font-mono font-bold">
                    {dirtyTeamIds.has(selectedTeam.team_id) ? (
                      <span className="text-amber-400">[UNSAVED EDITS]</span>
                    ) : reviewedTeamIds.has(selectedTeam.team_id) ? (
                      <span className="text-emerald-400">[SAVED]</span>
                    ) : (
                      <span className="text-slate-500">[NOT SAVED]</span>
                    )}
                  </span>
                </div>

                <div className="space-y-1.5">
                  {selectedTeam.candidates.map((c, ci) => (
                    <div
                      key={`${c.player_name}-${ci}`}
                      className="flex items-center justify-between gap-2 border border-slate-800 bg-black/60 p-2 text-xs font-mono"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="font-sans font-bold text-white truncate text-sm">
                          {c.player_name}
                        </div>
                        <div className="flex items-center gap-1.5 text-[10px] text-slate-400">
                          <PositionBadge position={c.position} size="xs" />
                          <span>
                            {c.nfl_team ? `· ${c.nfl_team}` : ""}
                            {c.years_kept === 1 ? " · LAST YEAR ELIGIBLE" : ""}
                          </span>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        <label className="text-[10px] text-slate-400 uppercase">
                          COST RND:
                        </label>
                        <input
                          className="input w-16 text-center font-bold"
                          type="number"
                          min={1}
                          value={c.cost_round}
                          onChange={(e) =>
                            updateCandidate(selectedTeamIndex, ci, {
                              cost_round: Number(e.target.value),
                            })
                          }
                        />
                        <button
                          className="btn btn-danger text-[10px] py-1 px-2"
                          onClick={() => removeCandidate(selectedTeamIndex, ci)}
                        >
                          ✕
                        </button>
                      </div>
                    </div>
                  ))}

                  {selectedTeam.candidates.length === 0 && (
                    <p className="text-xs text-slate-500 font-mono py-2 text-center">
                      No keepable players identified for this team.
                    </p>
                  )}
                </div>

                <button
                  className="btn btn-primary text-xs"
                  disabled={!editable || !!busy}
                  onClick={saveSelectedTeam}
                >
                  Save {selectedTeam.team_name} Keepers
                </button>
              </div>
            )
          )}
        </div>
      </section>
    </main>
  );
}
