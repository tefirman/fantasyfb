(function () {
  "use strict";

  var D = JSON.parse(document.getElementById("report-data").textContent);
  var CFG = D.config || {};
  var CW = D.week;
  var sched = D.schedule || [];
  var stand = D.standings || [];
  var HAS_SCHED = sched.length > 0;
  var ANALYSES = ["adds", "pickups", "drops", "trades"];
  var POS = ["ALL", "QB", "RB", "WR", "TE", "K", "DEF"];
  var ORD = { QB: 0, RB: 1, WR: 2, TE: 3, K: 4, DEF: 5 };
  var FA_LIMIT = 40;

  var TABS = [["week", "My week"], ["stand", "Standings"], ["sched", "Schedule"], ["moves", "Moves"], ["fa", "Free agents"]]
    .filter(function (t) {
      if (t[0] === "sched" && !HAS_SCHED) return false;
      if (t[0] === "moves" && !ANALYSES.some(function (k) { return (D[k] || []).length; })) return false;
      return true;
    });
  var MOVE_LABELS = { adds: "Adds", pickups: "Pickups", drops: "Drops", trades: "Trades" };
  var MOVES = ANALYSES.filter(function (k) { return (D[k] || []).length; });

  var S = {
    team: D.me, tab: TABS[0][0], sKey: "earnings", sDir: -1, week: CW,
    mv: MOVES[0], aKey: "earnings", aDir: -1, addPos: "ALL", tf: "all",
    faPos: "ALL", faAll: false, q: ""
  };

  /* ---------- helpers ---------- */
  var $ = function (id) { return document.getElementById(id); };
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function num(v) { return typeof v === "number" && isFinite(v) ? v : 0; }
  function fx(v, n) { return num(v).toFixed(n); }
  function pct(v) { v = num(v); return (v * 100).toFixed(v >= 0.1 || v === 0 ? 0 : 1) + "%"; }
  function sg(v, f) { return (v > 0 ? "+" : v < 0 ? "−" : "") + f(Math.abs(v)); }
  function dc(v) { return v > 0 ? "var(--color-accent-700)" : v < 0 ? "var(--color-neutral-600)" : "inherit"; }
  function pp(v) { return sg(num(v), function (x) { return (x * 100).toFixed(1) + " pts"; }); }
  function money(v) { return sg(num(v), function (x) { return "$" + x.toFixed(2); }); }
  function wins(v) { return sg(num(v), function (x) { return x.toFixed(2); }); }
  function pos(p) { return '<span class="tag tag-neutral">' + esc(p) + "</span>"; }
  function sub(t) { return '<span style="font-size:12px;color:var(--color-neutral-700)">' + esc(t) + "</span>"; }
  function seg(name, opts, cur, action) {
    return '<div class="seg">' + opts.map(function (o) {
      return '<label class="seg-opt"><input type="radio" name="' + name + '" data-action="' + action + '" value="' + esc(o[0]) + '"' +
        (o[0] === cur ? " checked" : "") + ' style="position:absolute;opacity:0;width:0;height:0">' + esc(o[1]) + "</label>";
    }).join("") + "</div>";
  }
  function corners() { return '<i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>'; }
  function bar(frac, color, valueHtml, w) {
    var f = Math.max(0, Math.min(1, frac || 0)) * 100;
    return '<div style="display:flex;align-items:center;gap:6px"><div style="flex:1;height:6px;background:var(--color-neutral-200);position:relative">' +
      '<div style="position:absolute;top:0;bottom:0;left:0;width:' + f + '%;background:' + color + '"></div></div>' +
      '<span style="font-size:12px;width:' + (w || 34) + 'px;text-align:right">' + valueHtml + "</span></div>";
  }
  function sortBtn(label, key, cur, dir, action, right) {
    var arrow = cur === key ? (dir > 0 ? "↑" : "↓") : "";
    return '<th' + (right ? ' style="text-align:right"' : "") + '><button class="btn btn-ghost" data-action="' + action + '" data-key="' + key +
      '" style="padding:0;font:inherit;letter-spacing:inherit;color:inherit;min-height:0">' + esc(label) + " " + arrow + "</button></th>";
  }
  function statusTag(p, withUntil) {
    if (!p.status) return "";
    var t = p.status + (withUntil && p.until != null ? " · wk " + p.until : "");
    return '<span class="tag tag-accent">' + esc(t) + "</span>";
  }
  function playerCell(p, withUntil) {
    return '<div style="display:flex;align-items:center;gap:var(--space-2);flex-wrap:wrap"><span style="font-weight:500">' + esc(p.name) + "</span>" +
      sub(p.current_team) + statusTag(p, withUntil) + "</div>";
  }
  function mfColor(m) { return m >= 1.03 ? "var(--color-accent-700)" : m <= 0.97 ? "var(--color-neutral-600)" : "inherit"; }
  function table(minW, head, rows) {
    return '<div style="overflow-x:auto"><table class="table" style="min-width:' + minW + 'px"><thead><tr>' + head + "</tr></thead><tbody>" + rows + "</tbody></table></div>";
  }
  var TH_R = function (t) { return '<th style="text-align:right">' + t + "</th>"; };

  /* ---------- derived data ---------- */
  function recOf(t) {
    var w = 0, l = 0;
    sched.forEach(function (g) {
      if (g.week >= CW) return;
      if (g.team_1 === t) g.win_1 ? w++ : l++;
      if (g.team_2 === t) g.win_2 ? w++ : l++;
    });
    return w + "–" + l;
  }
  function side(g, team) {
    return g.team_1 === team
      ? { opp: g.team_2, win: g.win_1, my: g.points_avg_1, mySd: g.points_stdev_1, op: g.points_avg_2, opSd: g.points_stdev_2 }
      : { opp: g.team_1, win: g.win_2, my: g.points_avg_2, mySd: g.points_stdev_2, op: g.points_avg_1, opSd: g.points_stdev_1 };
  }
  function find(rows, key, val) { for (var i = 0; i < rows.length; i++) if (rows[i][key] === val) return rows[i]; return null; }
  var maxWar = Math.max.apply(null, [0.0001].concat((D.rosters || []).map(function (p) { return num(p.WAR); })));
  var maxFaWar = Math.max.apply(null, [0.0001].concat((D.available || []).map(function (p) { return num(p.WAR); })));
  var byName = {};
  (D.rosters || []).concat(D.available || []).forEach(function (p) { if (!(p.name in byName)) byName[p.name] = p; });

  /* ---------- header / title ---------- */
  function renderHead() {
    var teams = stand.map(function (s) { return s.team; }).sort();
    $("team-select").innerHTML = teams.map(function (t) {
      return '<option value="' + esc(t) + '"' + (t === S.team ? " selected" : "") + ">" + esc(t) + "</option>";
    }).join("");
    var st = find(stand, "team", S.team) || {};
    $("kicker").textContent = S.team === D.me ? "Your team" : "Scouting report";
    $("team-name").textContent = S.team;
    $("team-sub").textContent = (HAS_SCHED ? recOf(S.team) + " record · " : "") + pct(st.playoffs) + " playoff odds";
    $("tabs").innerHTML = seg("tab", TABS, S.tab, "tab");
  }

  /* ---------- My week ---------- */
  function matchupCard() {
    var g = sched.filter(function (x) { return x.week === CW && (x.team_1 === S.team || x.team_2 === S.team); })[0];
    if (!g) return "";
    var c = side(g, S.team);
    var sdMine = Math.max(c.mySd, 0.01), sdOpp = Math.max(c.opSd, 0.01);
    var lo = Math.min(c.my - 3 * sdMine, c.op - 3 * sdOpp), hi = Math.max(c.my + 3 * sdMine, c.op + 3 * sdOpp);
    var X = function (v) { return (v - lo) / (hi - lo) * 560; };
    var pdf = function (x, m, s) { return Math.exp(-0.5 * Math.pow((x - m) / s, 2)) / s; };
    var peak = Math.max(1 / sdMine, 1 / sdOpp);
    var curve = function (m, s) {
      var p = "";
      for (var i = 0; i <= 80; i++) {
        var x = lo + (hi - lo) * i / 80;
        p += (i ? "L" : "M") + X(x).toFixed(1) + " " + (110 - pdf(x, m, s) / peak * 100).toFixed(1);
      }
      return p;
    };
    var myPath = curve(c.my, sdMine), ticks = "";
    for (var t = Math.ceil(lo / 20) * 20; t <= hi; t += 20) {
      ticks += '<line x1="' + X(t).toFixed(1) + '" y1="110" x2="' + X(t).toFixed(1) + '" y2="114" stroke="var(--color-neutral-500)"></line>' +
        '<text x="' + X(t).toFixed(1) + '" y="126" text-anchor="middle" font-size="10" fill="var(--color-neutral-700)">' + t + "</text>";
    }
    return '<div class="card blueprint" style="padding:var(--space-6);gap:var(--space-4)">' + corners() +
      '<div class="card-kicker" style="color:var(--color-accent-700)">Week ' + CW + ' matchup</div>' +
      '<div style="display:grid;grid-template-columns:1fr auto 1fr;align-items:end;gap:var(--space-4)">' +
      '<div><div style="font-family:var(--font-heading);font-size:22px;line-height:1.1">' + esc(S.team) + "</div>" +
      '<div style="font-family:var(--font-heading);font-size:44px;line-height:1;margin-top:4px">' + fx(c.my, 1) + "</div>" +
      '<div style="font-size:13px;color:var(--color-neutral-700)">± ' + fx(c.mySd, 1) + " pts</div></div>" +
      '<div style="text-align:center;padding-bottom:6px"><div style="font-family:var(--font-heading);font-size:64px;line-height:0.9;color:var(--color-accent-700)">' + pct(c.win) + "</div>" +
      '<div style="font-size:11px;letter-spacing:0.1em;text-transform:uppercase;color:var(--color-neutral-700)">win probability</div></div>' +
      '<div style="text-align:right"><div style="font-family:var(--font-heading);font-size:22px;line-height:1.1">' + esc(c.opp) + "</div>" +
      '<div style="font-family:var(--font-heading);font-size:44px;line-height:1;margin-top:4px;color:var(--color-neutral-600)">' + fx(c.op, 1) + "</div>" +
      '<div style="font-size:13px;color:var(--color-neutral-700)">± ' + fx(c.opSd, 1) + " pts</div></div></div>" +
      '<svg viewBox="0 0 560 130" style="width:100%;height:auto;display:block"><line x1="0" y1="110" x2="560" y2="110" stroke="var(--color-divider)"></line>' +
      '<path d="' + curve(c.op, sdOpp) + '" fill="none" stroke="var(--color-neutral-500)" stroke-width="1.5" stroke-dasharray="4 3"></path>' +
      '<path d="' + myPath + 'L560 110L0 110Z" fill="var(--color-accent)" fill-opacity="0.12" stroke="none"></path>' +
      '<path d="' + myPath + '" fill="none" stroke="var(--color-accent)" stroke-width="1.75"></path>' + ticks + "</svg>" +
      '<div class="card-meta" style="gap:var(--space-4);flex-wrap:wrap">' +
      '<span style="display:flex;align-items:center;gap:6px"><span style="width:16px;height:2px;background:var(--color-accent)"></span>' + esc(S.team) + "</span>" +
      '<span style="display:flex;align-items:center;gap:6px"><span style="width:16px;height:0;border-top:2px dashed var(--color-neutral-500)"></span>' + esc(c.opp) + "</span>" +
      "<span>Projected score distributions</span></div></div>";
  }

  function outlookPlate() {
    var st = find(stand, "team", S.team) || {};
    var rank = stand.slice().sort(function (a, b) { return b.earnings - a.earnings; }).map(function (s) { return s.team; }).indexOf(S.team) + 1;
    var cells = [
      ["Make playoffs", pct(st.playoffs), "of simulated seasons"],
      ["First-round bye", pct(st.playoff_bye), "top-2 seed"],
      ["Win title", pct(st.winner), pct(st.runner_up) + " runner-up · " + pct(st.third) + " third"],
      ["Projected wins", fx(st.wins_avg, 1), "± " + fx(st.wins_stdev, 1) + " · " + fx(st.per_game_avg, 1) + " pts/gm"],
      ["Expected payout", "$" + Math.round(num(st.earnings)), "probability-weighted"],
      ["League rank", "#" + rank, "by expected payout"]
    ];
    return '<div class="blueprint" style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr))">' + corners() + cells.map(function (o) {
      return '<div style="padding:var(--space-4) var(--space-6);border-right:1px solid var(--color-divider);border-bottom:1px solid var(--color-divider);display:flex;flex-direction:column;gap:2px;margin:0 -1px -1px 0">' +
        '<div style="font-size:11px;letter-spacing:0.1em;text-transform:uppercase;color:var(--color-neutral-700)">' + esc(o[0]) + "</div>" +
        '<div style="font-family:var(--font-heading);font-size:38px;line-height:1.05">' + esc(o[1]) + "</div>" +
        '<div style="font-size:12px;color:var(--color-neutral-700)">' + esc(o[2]) + "</div></div>";
    }).join("") + "</div>";
  }

  function seasonPath() {
    var games = sched.filter(function (g) { return g.team_1 === S.team || g.team_2 === S.team; }).sort(function (a, b) { return a.week - b.week; });
    if (!games.length) return "";
    var lastFinal = games.filter(function (g) { return g.week < CW; }).length;
    var cols = games.map(function (g) {
      var s = side(g, S.team), past = g.week < CW, now = g.week === CW;
      var title = "Week " + g.week + " vs " + s.opp + " — " + (past ? (s.win ? "Won" : "Lost") + " " + fx(s.my, 1) + "–" + fx(s.op, 1) : pct(s.win) + " to win");
      var fill = past ? (s.win ? "var(--color-accent-700)" : "var(--color-neutral-400)") : s.win >= 0.5 ? "var(--color-accent)" : "var(--color-accent-300)";
      return '<div title="' + esc(title) + '" style="min-width:56px;padding:var(--space-3) var(--space-2);border-right:1px solid var(--color-divider);display:flex;flex-direction:column;gap:var(--space-2);background:' + (now ? "var(--color-accent-100)" : "transparent") + '">' +
        '<div style="font-size:11px;letter-spacing:0.08em;text-transform:uppercase;color:var(--color-neutral-700)">Wk ' + g.week + "</div>" +
        '<div style="height:64px;display:flex;align-items:flex-end;border-bottom:1px solid var(--color-divider)"><div style="width:100%;height:' + (past ? 100 : num(s.win) * 100) + "%;background:" + fill + '"></div></div>' +
        '<div style="font-family:var(--font-heading);font-size:18px;line-height:1">' + (past ? (s.win ? "W" : "L") : pct(s.win)) + "</div>" +
        '<div style="font-size:11px;line-height:1.25;color:var(--color-neutral-700);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">vs ' + esc(s.opp) + "</div></div>";
    }).join("");
    var note = "Win probability by week" + (lastFinal ? " · weeks 1–" + lastFinal + " final" : "");
    return '<section style="display:flex;flex-direction:column;gap:var(--space-3)">' +
      '<div style="display:flex;align-items:baseline;justify-content:space-between;gap:var(--space-4);flex-wrap:wrap"><h3 style="margin:0">Season path</h3>' +
      '<span style="font-size:13px;color:var(--color-neutral-700)">' + note + "</span></div>" +
      '<div class="blueprint" style="display:grid;grid-template-columns:repeat(' + games.length + ',minmax(0,1fr));overflow-x:auto">' + corners() + cols + "</div></section>";
  }

  function lineupRows(list, bench) {
    return list.map(function (p) {
      var war = num(p.WAR);
      var third = bench ? '<td style="text-align:right">' + esc(p.bye_week == null ? "" : p.bye_week) + "</td>"
        : '<td style="text-align:right;color:' + mfColor(p.matchup_factor) + '">' + fx(p.matchup_factor, 2) + "</td>";
      return "<tr><td style=\"width:56px\">" + pos(p.position) + "</td><td>" + playerCell(p, false) + "</td>" +
        '<td style="text-align:right;white-space:nowrap">' + fx(p.points_avg, 1) + " " + sub("± " + fx(p.points_stdev, 1)) + "</td>" + third +
        '<td style="width:120px">' + bar(war / maxWar, bench ? "var(--color-accent-400)" : "var(--color-accent)", fx(war, 2)) + "</td></tr>";
    }).join("");
  }
  function lineupSection() {
    var roster = (D.rosters || []).filter(function (p) { return p.fantasy_team === S.team; });
    var starters = roster.filter(function (p) { return p.starter; }).sort(function (a, b) {
      return (ORD[a.position] - ORD[b.position]) || (b.points_avg - a.points_avg);
    });
    var bench = roster.filter(function (p) { return !p.starter; }).sort(function (a, b) { return b.WAR - a.WAR; });
    var total = starters.reduce(function (t, p) { return t + num(p.points_avg); }, 0);
    var hdr = function (title, right) {
      return '<div style="display:flex;align-items:baseline;justify-content:space-between;gap:var(--space-4)"><h3 style="margin:0">' + title +
        '</h3><span style="font-size:13px;color:var(--color-neutral-700)">' + right + "</span></div>";
    };
    var head = function (third) { return "<th>Pos</th><th>Player</th>" + TH_R("Proj") + TH_R(third) + "<th>WAR</th>"; };
    return '<section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));gap:var(--space-6);align-items:start">' +
      '<div style="display:flex;flex-direction:column;gap:var(--space-3)">' + hdr("Starting lineup", fx(total, 1) + " pts projected") +
      '<table class="table"><thead><tr>' + head("Matchup") + "</tr></thead><tbody>" + lineupRows(starters, false) + "</tbody></table></div>" +
      (bench.length ? '<div style="display:flex;flex-direction:column;gap:var(--space-3)">' + hdr("Bench", bench.length + " players") +
        '<table class="table"><thead><tr>' + head("Bye") + "</tr></thead><tbody>" + lineupRows(bench, true) + "</tbody></table></div>" : "") +
      "</section>";
  }

  function tabWeek() {
    var top = HAS_SCHED
      ? '<section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:var(--space-6)">' + matchupCard() + outlookPlate() + "</section>" + seasonPath()
      : '<section style="display:grid;grid-template-columns:1fr">' + outlookPlate() + "</section>";
    return top + lineupSection();
  }

  /* ---------- Standings ---------- */
  function prob(frac, color, w) { return '<td style="width:140px">' + bar(frac, color, pct(frac), w || 40) + "</td>"; }
  function tabStand() {
    var rows = stand.slice().sort(function (a, b) {
      return S.sKey === "team" ? S.sDir * String(a.team).localeCompare(b.team) : S.sDir * (num(a[S.sKey]) - num(b[S.sKey]));
    }).map(function (s, i) {
      var me = s.team === S.team;
      return '<tr data-action="pick-team" data-team="' + esc(s.team) + '" style="background:' + (me ? "var(--color-accent-100)" : "transparent") + ';cursor:pointer">' +
        '<td style="color:var(--color-neutral-700)">' + (i + 1) + "</td>" +
        '<td style="font-weight:' + (me ? 600 : 400) + '">' + esc(s.team) + "</td>" +
        (HAS_SCHED ? "<td>" + recOf(s.team) + "</td>" : "") +
        '<td style="text-align:right;white-space:nowrap">' + fx(s.wins_avg, 1) + " " + sub("± " + fx(s.wins_stdev, 1)) + "</td>" +
        '<td style="text-align:right">' + fx(s.per_game_avg, 1) + "</td>" +
        prob(s.playoffs, "var(--color-accent)") + prob(s.playoff_bye, "var(--color-accent)") + prob(s.winner, "var(--color-accent-700)") +
        '<td style="text-align:right;font-weight:500">$' + fx(s.earnings, 0) + "</td></tr>";
    }).join("");
    var sb = function (l, k, r) { return sortBtn(l, k, S.sKey, S.sDir, "sort-stand", r); };
    var head = '<th style="width:32px">#</th>' + sb("Team", "team") + (HAS_SCHED ? "<th>Record</th>" : "") + sb("Proj. wins", "wins_avg", true) +
      sb("Pts / gm", "per_game_avg", true) + sb("Playoffs", "playoffs") + sb("Bye", "playoff_bye") + sb("Title", "winner") + sb("Exp. $", "earnings", true);
    return '<section style="display:flex;flex-direction:column;gap:var(--space-3)">' +
      '<div style="display:flex;align-items:baseline;justify-content:space-between;gap:var(--space-4);flex-wrap:wrap"><h3 style="margin:0">Simulated final standings</h3>' +
      '<span style="font-size:13px;color:var(--color-neutral-700)">Click a column to sort · click a team to view it</span></div>' +
      table(860, head, rows) + "</section>";
  }

  /* ---------- Schedule ---------- */
  function tabSched() {
    var weeks = sched.map(function (g) { return g.week; }).filter(function (w, i, a) { return a.indexOf(w) === i; }).sort(function (a, b) { return a - b; });
    var opts = weeks.map(function (w) {
      return '<option value="' + w + '"' + (w === S.week ? " selected" : "") + ">Week " + w + (w < CW ? " · final" : w === CW ? " · this week" : "") + "</option>";
    }).join("");
    var chev = function (d, label, action) {
      return '<button class="btn btn-secondary btn-icon" data-action="' + action + '" aria-label="' + label + '"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="' + d + '"></path></svg></button>';
    };
    var cards = sched.filter(function (g) { return g.week === S.week; }).map(function (g) {
      var past = g.week < CW, mine = g.team_1 === S.team || g.team_2 === S.team;
      var fw1 = (past ? g.win_1 : g.win_1 >= 0.5) ? 600 : 400, fw2 = (past ? g.win_2 : g.win_2 > 0.5) ? 600 : 400;
      var row = function (t, p, fw) {
        return '<span style="font-weight:' + fw + ';overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(t) + '</span><span style="font-family:var(--font-heading);font-size:20px">' + fx(p, 1) + "</span>";
      };
      return '<div class="card blueprint" style="padding:var(--space-4);gap:var(--space-3);border-color:' + (mine ? "var(--color-accent)" : "var(--color-divider)") + '">' + corners() +
        '<div style="display:flex;justify-content:space-between;align-items:baseline"><span class="card-kicker" style="color:var(--color-accent-700)">' + (past ? "Final" : "Projected") + "</span>" +
        (mine ? '<span class="tag tag-accent">Your team</span>' : "") + "</div>" +
        '<div style="display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px var(--space-3);align-items:baseline">' + row(g.team_1, g.points_avg_1, fw1) + row(g.team_2, g.points_avg_2, fw2) + "</div>" +
        '<div style="display:flex;height:8px;background:var(--color-neutral-300)"><div style="width:' + num(g.win_1) * 100 + '%;background:var(--color-accent)"></div></div>' +
        '<div style="display:flex;justify-content:space-between;font-size:12px;color:var(--color-neutral-700)"><span>' + (past ? (g.win_1 ? "Won" : "Lost") : pct(g.win_1)) + "</span><span>" + (past ? (g.win_2 ? "Won" : "Lost") : pct(g.win_2)) + "</span></div></div>";
    }).join("");
    return '<section style="display:flex;flex-direction:column;gap:var(--space-4)">' +
      '<div style="display:flex;align-items:center;justify-content:space-between;gap:var(--space-4);flex-wrap:wrap"><h3 style="margin:0">League schedule · Week ' + S.week + "</h3>" +
      '<div style="display:flex;align-items:center;gap:var(--space-2)">' + chev("m15 18-6-6 6-6", "Previous week", "prev-week") +
      '<select class="input" style="width:auto" data-action="week">' + opts + "</select>" + chev("m9 18 6-6-6-6", "Next week", "next-week") + "</div></div>" +
      '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,380px),1fr));gap:var(--space-6)">' + cards + "</div></section>";
  }

  /* ---------- Moves ---------- */
  var DELTA_COLS = [["wins_avg", "Δ Wins", wins], ["playoffs", "Δ Playoffs", pp], ["playoff_bye", "Δ Bye", pp], ["winner", "Δ Title", pp], ["earnings", "Δ Exp. $", money]];
  function dcell(row, col, fmt, bold) {
    var v = num(row[col]);
    return '<td style="text-align:right;' + (bold ? "font-weight:500;" : "") + "color:" + dc(v) + '">' + fmt(v) + "</td>";
  }
  function posTag(name, key) { var p = byName[name]; return p ? pos(p[key || "position"]) : ""; }

  function addsView() {
    var rows = D.adds.filter(function (a) { return S.addPos === "ALL" || a.position === S.addPos; })
      .sort(function (a, b) { return S.aDir * (num(a[S.aKey]) - num(b[S.aKey])); }).map(function (a) {
        var p = byName[a.player_to_add] || {};
        return "<tr><td><span style=\"font-weight:500\">" + esc(a.player_to_add) + "</span> " + sub(a.current_team) + "</td><td>" + pos(a.position) + "</td>" +
          '<td style="text-align:right">' + (p.points_avg != null ? fx(p.points_avg, 1) : "") + "</td>" +
          DELTA_COLS.map(function (c) { return dcell(a, c[0], c[2], c[0] === "earnings"); }).join("") + "</tr>";
      }).join("");
    var sb = function (l, k, r) { return sortBtn(l, k, S.aKey, S.aDir, "sort-adds", r); };
    var head = "<th>Player</th><th>Pos</th>" + TH_R("Proj") + DELTA_COLS.map(function (c) { return sb(c[1], c[0], true); }).join("");
    var other = S.team !== D.me
      ? '<div style="font-size:13px;padding:var(--space-3);border:1px dashed var(--color-divider);color:var(--color-neutral-800)">Add simulations were only run for ' + esc(D.me) + " this run — switch back to see your own team’s results.</div>" : "";
    return '<div style="display:flex;justify-content:space-between;align-items:center;gap:var(--space-4);flex-wrap:wrap">' +
      '<span style="font-size:13px;color:var(--color-neutral-700)">Adding a free agent to an open roster spot · no drop assumed</span>' +
      seg("addpos", POS.map(function (p) { return [p, p === "ALL" ? "All" : p]; }), S.addPos, "add-pos") + "</div>" + other + table(820, head, rows);
  }

  function pickupsView() {
    var rows = D.pickups.slice().sort(function (a, b) { return num(b.earnings) - num(a.earnings); }).map(function (p) {
      var arrow = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M5 12h14"></path><path d="m12 5 7 7-7 7"></path></svg>';
      var add = byName[p.player_to_add] || {};
      return "<tr><td><div style=\"display:flex;align-items:center;gap:var(--space-2)\">" + posTag(p.player_to_drop) +
        '<span style="color:var(--color-neutral-700);text-decoration:line-through;text-decoration-color:var(--color-neutral-400)">' + esc(p.player_to_drop) + "</span></div></td>" +
        '<td style="width:28px;color:var(--color-neutral-500)">' + arrow + "</td>" +
        '<td><div style="display:flex;align-items:center;gap:var(--space-2)">' + posTag(p.player_to_add) + '<span style="font-weight:500">' + esc(p.player_to_add) + "</span>" + sub(add.current_team) + "</div></td>" +
        [DELTA_COLS[0], DELTA_COLS[1], DELTA_COLS[3], DELTA_COLS[4]].map(function (c) { return dcell(p, c[0], c[2], c[0] === "earnings"); }).join("") + "</tr>";
    }).join("");
    return table(820, "<th>Drop</th><th></th><th>Add</th>" + TH_R("Δ Wins") + TH_R("Δ Playoffs") + TH_R("Δ Title") + TH_R("Δ Exp. $"), rows);
  }

  function dropsView() {
    var safe = CFG.drop_safe_threshold, depth = CFG.drop_depth_threshold;
    var rows = D.drops.slice().sort(function (a, b) { return num(b.earnings) - num(a.earnings); }).map(function (p) {
      var e = num(p.earnings), r = byName[p.player_to_drop] || {};
      var verdict = e > safe ? ["Safe to cut", "tag tag-accent"] : e > depth ? ["Depth", "tag tag-neutral"] : ["Keep", "tag tag-neutral"];
      return "<tr><td><div style=\"display:flex;align-items:center;gap:var(--space-2)\">" + posTag(p.player_to_drop) + '<span style="font-weight:500">' + esc(p.player_to_drop) + "</span>" + sub(r.current_team) + "</div></td>" +
        '<td style="color:var(--color-neutral-700)">' + (r.starter ? "Starter" : "Bench") + "</td>" +
        [DELTA_COLS[1], DELTA_COLS[3], DELTA_COLS[4]].map(function (c) { return dcell(p, c[0], c[2], c[0] === "earnings"); }).join("") +
        '<td><span class="' + verdict[1] + '">' + verdict[0] + "</span></td></tr>";
    }).join("");
    return table(760, "<th>Player</th><th>Role</th>" + TH_R("Δ Playoffs") + TH_R("Δ Title") + TH_R("Δ Exp. $") + "<th>Verdict</th>", rows);
  }

  function tradesView() {
    var all = D.trades;
    var maxT = Math.max.apply(null, [1].concat(all.map(function (t) { return Math.max(Math.abs(num(t.my_earnings)), Math.abs(num(t.their_earnings))); })));
    var div = function (v, pos_color) {
      var w = Math.abs(v) / maxT * 50;
      return '<div style="height:7px;position:relative;background:var(--color-neutral-200)"><div style="position:absolute;top:0;bottom:0;left:' + (v >= 0 ? 50 : 50 - w) + "%;width:" + w + "%;background:" + (v >= 0 ? pos_color : "var(--color-neutral-400)") + '"></div></div>';
    };
    var rows = all.filter(function (t) {
      var m = num(t.my_earnings), th = num(t.their_earnings);
      return S.tf === "all" || (S.tf === "win2" ? m > 0 && th > 0 : m > 0);
    }).sort(function (a, b) { return num(b.my_earnings) - num(a.my_earnings); }).map(function (t) {
      var m = num(t.my_earnings), th = num(t.their_earnings);
      var v = m > 0 && th > 0 ? ["Win-win", "tag tag-accent"] : m > 0 ? ["Favors you", "tag tag-outline"] : th > 0 ? ["Favors them", "tag tag-neutral"] : ["Lose-lose", "tag tag-neutral"];
      return "<tr><td><div style=\"display:flex;align-items:center;gap:var(--space-2)\">" + posTag(t.player_to_trade_away) + "<span>" + esc(t.player_to_trade_away) + "</span></div></td>" +
        '<td><div style="display:flex;align-items:center;gap:var(--space-2)">' + posTag(t.player_to_trade_for) + '<span style="font-weight:500">' + esc(t.player_to_trade_for) + "</span></div></td>" +
        '<td style="font-size:13px;color:var(--color-neutral-700)">' + esc(t.their_team) + "</td>" +
        '<td><div style="display:flex;flex-direction:column;gap:3px;position:relative">' + div(m, "var(--color-accent)") + div(th, "var(--color-accent-700)") +
        '<div style="position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:var(--color-text)"></div></div></td>' +
        '<td style="text-align:right;font-weight:500;color:' + dc(m) + '">' + money(m) + '</td><td style="text-align:right;color:' + dc(th) + '">' + money(th) + "</td>" +
        '<td><span class="' + v[1] + '">' + v[0] + "</span></td></tr>";
    }).join("");
    var key = function (c, t) { return '<span style="display:flex;align-items:center;gap:6px"><span style="width:14px;height:8px;background:' + c + '"></span>' + t + "</span>"; };
    return '<div style="display:flex;justify-content:space-between;align-items:center;gap:var(--space-4);flex-wrap:wrap">' +
      '<div style="display:flex;gap:var(--space-4);font-size:12px;color:var(--color-neutral-700)">' + key("var(--color-accent)", "Your Δ Exp. $") + key("var(--color-accent-700)", "Their Δ Exp. $") + "<span>Center line = no change</span></div>" +
      seg("tf", [["all", "All"], ["mine", "Favors you"], ["win2", "Win-win"]], S.tf, "trade-filter") + "</div>" +
      table(900, "<th>You give</th><th>You get</th><th>Partner</th><th style=\"width:200px\">Impact</th>" + TH_R("You") + TH_R("Them") + "<th>Verdict</th>", rows);
  }

  function tabMoves() {
    var views = { adds: addsView, pickups: pickupsView, drops: dropsView, trades: tradesView };
    var opts = MOVES.map(function (k) { return [k, MOVE_LABELS[k] + " · " + D[k].length]; });
    return '<section style="display:flex;flex-direction:column;gap:var(--space-4)">' +
      '<div style="display:flex;align-items:flex-end;justify-content:space-between;gap:var(--space-4);flex-wrap:wrap">' +
      '<div style="flex:1 1 320px;min-width:0"><h3 style="margin:0">Roster moves for ' + esc(D.me) + "</h3>" +
      '<div style="font-size:13px;color:var(--color-neutral-700)">Change in season outcomes after each simulated move · From this run</div></div>' +
      '<div style="flex:none;margin-left:auto">' + seg("mv", opts, S.mv, "move-view") + "</div></div>" + views[S.mv]() + "</section>";
  }

  /* ---------- Free agents ---------- */
  function faResults() {
    var q = S.q.trim().toLowerCase();
    var all = (D.available || []).filter(function (p) {
      return (S.faPos === "ALL" || p.position === S.faPos) && (!q || String(p.name).toLowerCase().indexOf(q) >= 0 || String(p.current_team || "").toLowerCase() === q);
    });
    var shown = S.faAll ? all : all.slice(0, FA_LIMIT);
    var rows = shown.map(function (p) {
      return "<tr><td>" + playerCell(p, true) + "</td><td>" + pos(p.position) + "</td>" +
        '<td style="text-align:right;white-space:nowrap">' + fx(p.points_avg, 1) + " " + sub("± " + fx(p.points_stdev, 1)) + "</td>" +
        '<td style="text-align:right;color:' + mfColor(p.matchup_factor) + '">' + fx(p.matchup_factor, 2) + "</td>" +
        '<td style="width:130px">' + bar(num(p.WAR) / maxFaWar, "var(--color-accent)", fx(p.WAR, 2), 40) + "</td>" +
        '<td style="text-align:right">' + esc(p.bye_week == null ? "" : p.bye_week) + '</td><td style="text-align:right">' + pct(p.pct_rostered || 0) + "</td></tr>";
    }).join("");
    var more = all.length > shown.length
      ? '<div><button class="btn btn-secondary" data-action="fa-more">Show all ' + all.length + "</button></div>" : "";
    return { count: all.length, html: table(820, "<th>Player</th><th>Pos</th>" + TH_R("Proj") + TH_R("Matchup") + "<th>WAR</th>" + TH_R("Bye") + TH_R("Rostered"), rows) + more };
  }
  function tabFA() {
    return '<section style="display:flex;flex-direction:column;gap:var(--space-3)">' +
      '<div style="display:flex;align-items:center;justify-content:space-between;gap:var(--space-4);flex-wrap:wrap"><div><h3 style="margin:0">Free agents</h3>' +
      '<div id="fa-count" style="font-size:13px;color:var(--color-neutral-700)"></div></div>' +
      '<div style="display:flex;gap:var(--space-3);flex-wrap:wrap;align-items:center">' +
      '<input class="input" id="fa-q" style="width:220px" placeholder="Search players or NFL team" value="' + esc(S.q) + '">' +
      seg("fapos", POS.map(function (p) { return [p, p === "ALL" ? "All" : p]; }), S.faPos, "fa-pos") + "</div></div>" +
      '<div id="fa-results"></div></section>';
  }
  function paintFA() {
    var r = faResults();
    $("fa-count").textContent = r.count + " matching · sorted by WAR";
    $("fa-results").innerHTML = r.html;
  }

  /* ---------- render + events ---------- */
  function render() {
    renderHead();
    var body = { week: tabWeek, stand: tabStand, sched: tabSched, moves: tabMoves, fa: tabFA }[S.tab]();
    $("content").innerHTML = body;
    if (S.tab === "fa") paintFA();
    try { history.replaceState(null, "", "#tab=" + S.tab + "&team=" + encodeURIComponent(S.team)); } catch (e) { /* file:// or sandboxed */ }
  }

  function toggleSort(key, curKey, curDir, textKey) {
    return { key: key, dir: curKey === key ? -curDir : (key === textKey ? 1 : -1) };
  }
  function weekList() {
    return sched.map(function (g) { return g.week; }).filter(function (w, i, a) { return a.indexOf(w) === i; }).sort(function (a, b) { return a - b; });
  }

  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-action]");
    if (!el || el.tagName === "INPUT" || el.tagName === "SELECT") return;
    var a = el.getAttribute("data-action"), weeks = weekList();
    if (a === "sort-stand") { var s = toggleSort(el.dataset.key, S.sKey, S.sDir, "team"); S.sKey = s.key; S.sDir = s.dir; }
    else if (a === "sort-adds") { var t = toggleSort(el.dataset.key, S.aKey, S.aDir); S.aKey = t.key; S.aDir = t.dir; }
    else if (a === "pick-team") { S.team = el.dataset.team; S.tab = "week"; }
    else if (a === "prev-week") S.week = Math.max(weeks[0], S.week - 1);
    else if (a === "next-week") S.week = Math.min(weeks[weeks.length - 1], S.week + 1);
    else if (a === "fa-more") { S.faAll = true; paintFA(); return; }
    else return;
    render();
  });
  document.addEventListener("change", function (e) {
    var el = e.target, a = el.getAttribute && el.getAttribute("data-action");
    if (el.id === "team-select") { S.team = el.value; render(); return; }
    if (!a) return;
    if (a === "tab") S.tab = el.value;
    else if (a === "move-view") S.mv = el.value;
    else if (a === "add-pos") S.addPos = el.value;
    else if (a === "trade-filter") S.tf = el.value;
    else if (a === "week") S.week = +el.value;
    else if (a === "fa-pos") { S.faPos = el.value; S.faAll = false; }
    else return;
    render();
  });
  document.addEventListener("input", function (e) {
    if (e.target.id === "fa-q") { S.q = e.target.value; S.faAll = false; paintFA(); }
  });

  /* ---------- boot ---------- */
  (function readHash() {
    var h = (location.hash || "").replace(/^#/, "");
    h.split("&").forEach(function (kv) {
      var p = kv.split("="), k = p[0], v = decodeURIComponent(p.slice(1).join("="));
      if (k === "tab" && TABS.some(function (t) { return t[0] === v; })) S.tab = v;
      if (k === "team" && find(stand, "team", v)) S.team = v;
    });
  })();
  $("meta").textContent = "Week " + D.week + " · " + D.day + " projections · " + (D.sims || 0).toLocaleString("en-US") + " sims";
  render();
})();
