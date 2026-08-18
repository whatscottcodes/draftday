"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import { API_URL, apiJson } from "@/lib/api";
import type {
  KeeperPreviewCandidate,
  KeeperPreviewTeam,
  KeeperSetup,
} from "@/lib/types";

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
      setError(e instanceof Error ? e.message : "Failed to load");
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

  if (error && !setup) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 p-6">
        <p className="text-red-400">{error}</p>
      </main>
    );
  }
  if (!setup) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 p-6">
        <p className="text-slate-400">Loading keeper console…</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 max-w-3xl mx-auto p-4 space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-black">Keeper Admin</h1>
          <p className="text-xs text-slate-400">
            {setup.league.name} · {setup.league.season}
            {setup.preview.saved_at ? " · last saved" : ""}
          </p>
        </div>
        <a
          href={`/draft/${token}/admin`}
          className="text-xs text-slate-400 hover:text-emerald-400"
        >
          ← Commissioner console
        </a>
      </header>

      {error && <div className="rounded-lg bg-red-900/40 px-3 py-2 text-sm text-red-300">{error}</div>}
      {notice && <div className="rounded-lg bg-emerald-900/40 px-3 py-2 text-sm text-emerald-300">{notice}</div>}

      {busy && (
        <div className="flex items-center gap-3 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-emerald-300" role="status">
          <span
            className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-emerald-400 border-t-transparent"
            aria-hidden="true"
          />
          <span className="font-semibold">{busy}</span>
        </div>
      )}

      {/* Step 1: historical drafts */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-3">
          1 · ClickyDraft history
        </h2>
        <p className="mb-3 text-xs text-slate-400">
          Load both seasons so keeper costs and the two-year eligibility rule
          can be calculated. For either season, upload the saved ClickyDraft
          HTML page or select a completed draft already in this app.
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
                className="rounded-xl border border-slate-800 bg-slate-950/30 p-3"
              >
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold text-slate-200">
                    {isPrevious ? "Previous season" : "Season before (2-year rule)"}
                  </h3>
                  <span className={loadedYear ? "text-xs text-emerald-300" : "text-xs text-amber-300"}>
                    {loadedYear ? `${loadedYear} loaded` : "Required"}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="file"
                    accept=".html,.htm,text/html"
                    className="min-w-48 flex-1 text-xs text-slate-400"
                    disabled={!!busy}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) uploadDraft(file, role);
                      e.target.value = "";
                    }}
                  />
                  <span className="text-xs text-slate-600">or</span>
                  <select
                    className="input min-w-48 flex-1"
                    value={useDraftIds[role]}
                    onChange={(e) =>
                      setUseDraftIds((current) => ({
                        ...current,
                        [role]: Number(e.target.value),
                      }))
                    }
                  >
                    <option value={0}>select completed app draft</option>
                    {setup.previous_drafts.map((draft) => (
                      <option key={draft.id} value={draft.id}>
                        {draft.name} · {draft.season} · {draft.picks} picks
                      </option>
                    ))}
                  </select>
                  <button
                    className="btn-secondary"
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
        <div className="mt-3 space-y-1 text-sm text-slate-400">
          {Object.entries(setup.draft.draft_counts).map(([year, byTeam]) => (
            <p key={year}>
              <span className="text-slate-200 font-semibold">{year}</span> ·{" "}
              {Object.entries(byTeam)
                .map(([team, count]) => `${team} (${count})`)
                .join(", ")}
            </p>
          ))}
          {!setup.draft.has_draft && (
            <p className="text-slate-600">
              No historical drafts loaded yet.
            </p>
          )}
        </div>
      </section>

      {/* Step 2: roster data */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-3">
          2 · Yahoo rosters and transactions
        </h2>
        <div className="rounded-xl border border-emerald-800/60 bg-emerald-950/20 p-4 mb-4">
          <label className="block text-sm font-semibold text-slate-200 mb-1">
            Upload the Yahoo Starting Rosters page
          </label>
          <p className="text-xs text-slate-400 mb-3">
            In Yahoo, open Starting Rosters with the Team tab selected, choose
            the desired week, and save the complete webpage as HTML. One file
            contains every league team.
          </p>
          <input
            type="file"
            accept=".html,.htm,text/html"
            className="text-xs text-slate-400"
            disabled={!!busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) uploadRosterHtml(file);
              e.target.value = "";
            }}
          />
        </div>
        <div className="rounded-xl border border-slate-700 bg-slate-950/30 p-4 mb-4">
          <div className="mb-1 flex items-center justify-between gap-2">
            <label className="text-sm font-semibold text-slate-200">
              Upload the Yahoo Transactions page
            </label>
            <span className={setup.transactions.loaded ? "text-xs text-emerald-300" : "text-xs text-amber-300"}>
              {setup.transactions.loaded
                ? `${setup.transactions.trade_count} traded players loaded`
                : "Required"}
            </span>
          </div>
          <p className="text-xs text-slate-400 mb-3">
            Save the league Transactions page as HTML. Trades are matched back
            to the original drafting team; players without a draft pick receive
            a round 11 cost.
          </p>
          <input
            type="file"
            accept=".html,.htm,text/html"
            className="text-xs text-slate-400"
            disabled={!!busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) uploadTransactionsHtml(file);
              e.target.value = "";
            }}
          />
        </div>
        <details className="border-t border-slate-800 pt-3">
          <summary className="cursor-pointer text-xs font-bold uppercase tracking-widest text-slate-500">
            Legacy Yahoo API and roster CSV options
          </summary>
          <div className="mt-3">
        <div className="grid grid-cols-2 gap-2 mb-3">
          <input
            className="input"
            placeholder="Yahoo league ID (e.g. 735068)"
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
            placeholder="Consumer key"
            value={yKey}
            onChange={(e) => setYKey(e.target.value)}
          />
          <input
            className="input"
            type="password"
            placeholder="Consumer secret"
            value={ySecret}
            onChange={(e) => setYSecret(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn-secondary" onClick={saveYahooConfig} disabled={!!busy}>
            Save Yahoo config
          </button>
          {setup.yahoo.configured && (
            <span className="text-xs text-slate-500">
              League {setup.yahoo.league_id_external || "—"} · key{" "}
              {setup.yahoo.consumer_key || "—"} ·{" "}
              {setup.yahoo.has_token ? "authorized" : "not authorized"}
            </span>
          )}
        </div>
        {setup.yahoo.configured && (
          <div className="mt-3 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <button className="btn-secondary" onClick={authorizeYahoo} disabled={!!busy}>
                {setup.yahoo.has_token ? "Re-authorize" : "Authorize with Yahoo"}
              </button>
              {authUrl && (
                <span className="text-xs text-slate-400 break-all">
                  Open{" "}
                  <a href={authUrl} target="_blank" rel="noreferrer" className="text-emerald-400 underline">
                    this link
                  </a>
                  , authorize, then paste the code.
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
              <button className="btn-primary" onClick={completeYahooCode} disabled={!yCode || !!busy}>
                Connect
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button className="btn-secondary" onClick={fetchTeamNames} disabled={!setup.yahoo.has_token || !!busy}>
                Test connection &amp; refresh teams
              </button>
              <button className="btn-primary" onClick={fetchRosters} disabled={!setup.yahoo.has_token || !!busy}>
                Fetch rosters from Yahoo
              </button>
            </div>
          </div>
        )}
          <div className="mt-3 flex items-center gap-2">
            <input
              type="file"
              accept=".csv"
              multiple
              className="text-xs text-slate-500"
              onChange={(e) => {
                if (e.target.files?.length) uploadRosters(e.target.files);
                e.target.value = "";
              }}
            />
            <span className="text-xs text-slate-600">upload legacy roster CSVs</span>
          </div>
          </div>
        </details>
        <p className="mt-3 text-xs text-slate-400">
          {setup.rosters.teams.length > 0
            ? `${setup.rosters.teams.length} Yahoo teams found${setup.rosters.source ? ` from ${setup.rosters.source}` : ""}${setup.rosters.week ? ` (week ${setup.rosters.week})` : ""}: ${setup.rosters.teams.join(", ")}${setup.rosters.player_count > 0 ? ` (${setup.rosters.player_count} rostered players loaded)` : " (rosters not loaded yet)"}`
            : "No Yahoo team or roster data loaded yet."}
        </p>
      </section>

      {/* Step 3: team name mapping */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-3">
          3 · Team name mapping
        </h2>
        <div className="grid grid-cols-[1fr_1fr_1fr_auto] gap-2 text-xs text-slate-500 mb-1 px-1">
          <span>App team</span>
          <span>ClickyDraft team</span>
          <span>Yahoo team</span>
          <span />
        </div>
        <div className="space-y-2">
          {setup.teams.map((team) => {
            const m = mappings[team.id] ?? { draft_name: "", yahoo_name: "" };
            return (
              <div key={team.id} className="grid grid-cols-[1fr_1fr_1fr_auto] gap-2">
                <div className="flex items-center text-sm font-semibold truncate">
                  {team.name}
                </div>
                <select
                  className="input"
                  value={m.draft_name}
                  onChange={(e) =>
                    setMappings((prev) => ({
                      ...prev,
                      [team.id]: { ...prev[team.id], draft_name: e.target.value },
                    }))
                  }
                >
                  <option value="">— none —</option>
                  {setup.draft.draft_teams.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
                <select
                  className="input"
                  value={m.yahoo_name}
                  onChange={(e) =>
                    setMappings((prev) => ({
                      ...prev,
                      [team.id]: { ...prev[team.id], yahoo_name: e.target.value },
                    }))
                  }
                >
                  <option value="">— none —</option>
                  {setup.rosters.teams.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
                <span className="w-6" />
              </div>
            );
          })}
        </div>
        <button className="btn-secondary mt-3" onClick={saveMappings} disabled={!!busy}>
          Save mappings
        </button>
      </section>

      {/* Step 4: identify / review / save / export */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-bold uppercase tracking-widest text-slate-400">
            4 · Review by team ({previewTotal})
          </h2>
          {setup.preview.saved_at && (
            <span className="text-xs text-slate-500">
              {setup.preview.reviewed_team_ids.length}/{review.length} teams saved
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-2 mb-2">
          <button
            className="btn-primary inline-flex items-center gap-2"
            onClick={identify}
            disabled={!!busy}
          >
            {busy === "Running keeper identification…" && (
              <span
                className="h-3 w-3 animate-spin rounded-full border-2 border-slate-950 border-t-transparent"
                aria-hidden="true"
              />
            )}
            {busy === "Running keeper identification…"
              ? "Identifying…"
              : "Identify keepable players"}
          </button>
          <button className="btn-secondary" onClick={exportCsv} disabled={!!busy}>
            Export per-team CSVs
          </button>
        </div>
        {lastRun && (
          <p className="mb-3 text-xs text-slate-400">
            Last run: <span className="text-emerald-300 font-semibold">{lastRun}</span>
          </p>
        )}
        <p className="mb-3 text-xs text-slate-600">
          Run identification only when source data changes. Saved team edits,
          including adjusted rounds, are restored when you return before the draft.
        </p>
        {review.length > 0 && (
          <div className="mb-4 rounded-xl border border-slate-800 bg-slate-950/30 p-3">
            <label className="mb-1 block text-xs font-bold uppercase tracking-widest text-slate-500">
              Team to review
            </label>
            <select
              className="input w-full"
              value={selectedTeamId ?? ""}
              onChange={(event) => setSelectedTeamId(Number(event.target.value))}
            >
              {review.map((team) => {
                const dirty = dirtyTeamIds.has(team.team_id);
                const saved = reviewedTeamIds.has(team.team_id);
                const status = dirty ? "unsaved changes" : saved ? "saved" : "not saved";
                return (
                  <option key={team.team_id} value={team.team_id}>
                    {team.team_name} ({team.candidates.length}) - {status}
                  </option>
                );
              })}
            </select>
          </div>
        )}
        {selectedWarnings.length > 0 && (
          <ul className="mb-4 space-y-0.5 text-xs text-amber-300/90 bg-amber-900/20 rounded-lg p-2">
            {selectedWarnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        )}
        {review.length === 0 ? (
          <p className="text-sm text-slate-500">
            Run the identify step to compute costs from the drafts and
            rosters.
          </p>
        ) : (
          selectedTeam && (
              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h3 className="text-sm font-bold text-slate-200">
                    {selectedTeam.team_name} ({selectedTeam.candidates.length})
                  </h3>
                  <span className="text-xs text-slate-500">
                    {dirtyTeamIds.has(selectedTeam.team_id)
                      ? "Unsaved changes"
                      : reviewedTeamIds.has(selectedTeam.team_id)
                        ? "Saved"
                        : "Not saved"}
                  </span>
                </div>
                <div className="space-y-1.5">
                  {selectedTeam.candidates.map((c, ci) => (
                    <div
                      key={`${c.player_name}-${ci}`}
                      className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900 px-3 py-1.5 text-sm"
                    >
                      <span className="flex-1 min-w-0">
                        <span className="font-semibold truncate">{c.player_name}</span>{" "}
                        <span className="text-xs text-slate-500">
                          {c.position} · {c.nfl_team}
                          {c.years_kept === 1 ? " · last year" : ""}
                        </span>
                      </span>
                      <input
                        className="input w-20"
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
                        className="text-xs text-red-400 hover:underline"
                        onClick={() => removeCandidate(selectedTeamIndex, ci)}
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                  {selectedTeam.candidates.length === 0 && (
                    <p className="text-xs text-slate-600">No keepable players.</p>
                  )}
                </div>
                <button
                  className="btn-primary mt-3"
                  disabled={!editable || !!busy}
                  onClick={saveSelectedTeam}
                >
                  Save {selectedTeam.team_name}
                </button>
              </div>
          )
        )}
      </section>
    </main>
  );
}
