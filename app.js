"use strict";

const DATA_URL = "./data/predictions.json";
const HISTORY_URL = "./data/history.json";
let allLoadedMatches = [];
let lastRefreshAt = 0;

// Evita che una rete mobile lenta lasci la schermata bloccata indefinitamente.
async function fetchJsonWithTimeout(url, timeoutMs = 12000) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error("Risposta HTTP " + response.status);
    return await response.json();
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function isValidMatchRecord(match, expectedStatus) {
  if (!match || typeof match !== "object" || Array.isArray(match)) return false;
  if (typeof match.date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(match.date)) return false;
  const [year, month, day] = match.date.split("-").map(Number);
  const calendarDate = new Date(Date.UTC(year, month - 1, day));
  if (calendarDate.getUTCFullYear() !== year ||
      calendarDate.getUTCMonth() !== month - 1 ||
      calendarDate.getUTCDate() !== day) return false;
  if (typeof match.home_team !== "string" || !match.home_team.trim() ||
      typeof match.away_team !== "string" || !match.away_team.trim() ||
      match.home_team.trim().toLocaleLowerCase() === match.away_team.trim().toLocaleLowerCase()) return false;
  if (expectedStatus === "NO BET") return match.status === "NO BET" &&
    (match.probabilities == null || (typeof match.probabilities === "object" && Object.keys(match.probabilities).length === 0));
  if (match.status !== "Pronostico valutabile" && match.status !== "Stima preliminare") return false;
  const p = match.probabilities;
  if (!p || typeof p !== "object") return false;
  const core = [p.home_win, p.draw, p.away_win];
  return core.every(value => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100) &&
    Math.abs(core.reduce((sum, value) => sum + value, 0) - 100) <= 1.5;
}

function formatDate(value) {
  if (!value) return "Data da confermare";
  const parsed = new Date(value + "T12:00:00");
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString("it-IT", {
    weekday: "short", day: "2-digit", month: "short"
  });
}

function formatFullDate(value) {
  if (!value) return "Data da confermare";
  const parsed = new Date(value + "T12:00:00");
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString("it-IT", {
    weekday: "long", day: "2-digit", month: "long", year: "numeric"
  });
}

function percent(value) {
  return typeof value === "number"
    ? value.toLocaleString("it-IT", { maximumFractionDigits: 1 }) + "%"
    : "—";
}

function translateAvailabilityTerm(value) {
  if (!value) return "";
  const original = String(value).trim();
  const normalized = original.toLowerCase().replace(/[’']/g, "'").replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  const exact = {
    "injury": "Infortunio", "injured": "Infortunato", "injuries": "Infortuni",
    "suspended": "Squalificato", "suspension": "Squalifica", "questionable": "In dubbio",
    "doubtful": "In dubbio", "missing fixture": "Non disponibile", "red card": "Espulsione",
    "yellow cards": "Squalifica per cartellini", "illness": "Malattia", "ill": "Malato",
    "knee injury": "Problema al ginocchio", "ankle injury": "Problema alla caviglia",
    "hamstring injury": "Problema ai muscoli posteriori della coscia", "thigh injury": "Problema alla coscia",
    "muscle injury": "Problema muscolare", "calf injury": "Problema al polpaccio",
    "groin injury": "Problema all'inguine", "back injury": "Problema alla schiena",
    "foot injury": "Problema al piede", "shoulder injury": "Problema alla spalla",
    "cruciate ligament injury": "Lesione ai legamenti crociati", "achilles tendon injury": "Problema al tendine d'Achille",
    "international duty": "Impegno con la nazionale", "personal reasons": "Motivi personali",
    "coach's decision": "Scelta tecnica", "coachs decision": "Scelta tecnica",
    "not in squad": "Non convocato", "unknown": "Non specificato", "unknown injury": "Infortunio non specificato",
    "rest": "Riposo", "suspended for yellow cards": "Squalifica per somma di ammonizioni",
    "red card suspension": "Squalifica dopo espulsione", "fitness": "Condizione fisica da verificare",
    "transfer": "Trasferimento", "no information": "Informazioni non disponibili", "inactive": "Non attivo"
  };
  if (Object.prototype.hasOwnProperty.call(exact, normalized)) return exact[normalized];
  const words = {
    injury: "infortunio", injured: "infortunato", suspension: "squalifica",
    suspended: "squalificato", doubtful: "in dubbio", questionable: "in dubbio",
    knee: "ginocchio", ankle: "caviglia", hamstring: "muscoli posteriori della coscia",
    thigh: "coscia", muscle: "muscolare", calf: "polpaccio", foot: "piede",
    shoulder: "spalla", back: "schiena", groin: "inguine", illness: "malattia",
    personal: "personali", reasons: "motivi", decision: "decisione", coach: "allenatore",
    international: "nazionale", duty: "impegno", unknown: "non specificato",
    unavailable: "non disponibile", absent: "assente", card: "cartellino", cards: "cartellini",
    red: "rosso", yellow: "giallo", ligament: "legamento", tendon: "tendine",
    fracture: "frattura", surgery: "intervento chirurgico", fitness: "condizione fisica",
    not: "non", squad: "convocati", rest: "riposo", inactive: "non attivo"
  };
  const translated = normalized.split(" ").map(word => words[word] || word).join(" ");
  return translated.charAt(0).toLocaleUpperCase("it-IT") + translated.slice(1);
}

function appendAvailability(match, card) {
  const data = match && match.availability_data ? match.availability_data : {};
  const section = document.createElement("section");
  section.className = "availability-panel";
  const title = document.createElement("strong");
  title.textContent = "Disponibilità e formazioni";
  const note = document.createElement("p");
  note.className = "match-meta";
  note.textContent = data.note || "Dati non verificati: la fonte disponibilità non ha restituito informazioni.";
  section.append(title, note);
  const injuries = Array.isArray(data.injuries) ? data.injuries : [];
  if (injuries.length) {
    const heading = document.createElement("p");
    heading.className = "availability-heading";
    heading.textContent = "Indisponibilità segnalate dalla fonte";
    section.append(heading);
    const list = document.createElement("ul");
    list.className = "availability-list";
    for (const item of injuries.slice(0, 12)) {
      const li = document.createElement("li");
      const details = [translateAvailabilityTerm(item.type), translateAvailabilityTerm(item.reason)].filter(Boolean).join(" · ");
      li.textContent = [item.player, item.team, details].filter(Boolean).join(" — ");
      list.append(li);
    }
    if (injuries.length > 12) {
      const more = document.createElement("li");
      more.textContent = "Altre " + (injuries.length - 12) + " segnalazioni non mostrate.";
      list.append(more);
    }
    section.append(list);
  }
  const lineups = data.lineups;
  if (lineups && (lineups.home_starters?.length || lineups.away_starters?.length)) {
    const heading = document.createElement("p");
    heading.className = "availability-heading";
    heading.textContent = "Formazioni pubblicate";
    section.append(heading);
    for (const side of [
      { label: match.home_team, formation: lineups.home_formation, starters: lineups.home_starters },
      { label: match.away_team, formation: lineups.away_formation, starters: lineups.away_starters }
    ]) {
      if (!side.starters || !side.starters.length) continue;
      const line = document.createElement("p");
      line.className = "match-meta";
      line.textContent = side.label + (side.formation ? " (" + side.formation + ")" : "") + ": " + side.starters.join(", ");
      section.append(line);
    }
    const updated = document.createElement("p");
    updated.className = "match-meta";
    updated.textContent = "Ultimo controllo formazioni: " + (lineups.updated_at ? new Date(lineups.updated_at).toLocaleString("it-IT") : "orario non disponibile");
    section.append(updated);
  } else if (data.lineup_status === "non_pubblicate") {
    const lineupNote = document.createElement("p");
    lineupNote.className = "match-meta";
    lineupNote.textContent = "Formazioni ufficiali non ancora disponibili nella fonte.";
    section.append(lineupNote);
  }
  card.append(section);
}

function renderMatches(matches) {
  const container = document.getElementById("matches");
  if (!container) return;
  container.replaceChildren();

  if (!matches.length) {
    container.textContent = "Nessuna partita nei prossimi 6 giorni supera il controllo storico minimo. Il sistema riproverà al prossimo aggiornamento.";
    return;
  }

  const orderMode = document.getElementById("date-order-filter")?.value || "competition";
  let previousGroup = "";
  for (const match of matches) {
    const group = orderMode === "competition"
      ? (match.country || "Altro") + " · " + (match.league || "Competizione")
      : match.date;
    if (group !== previousGroup) {
      const heading = document.createElement("h3");
      heading.className = "competition-heading";
      heading.textContent = orderMode === "competition" ? group : formatFullDate(match.date);
      container.append(heading);
      previousGroup = group;
    }
    const card = document.createElement("article");
    card.className = "match-card";

    const meta = document.createElement("p");
    meta.className = "match-meta";
    meta.textContent = (orderMode === "competition"
      ? formatDate(match.date)
      : (match.country || "Altro") + " · " + (match.league || "Competizione")) +
      (match.kickoff ? " · " + match.kickoff : " · orario da confermare");

    const teams = document.createElement("h3");
    teams.className = "match-teams";
    teams.textContent = match.home_team + " — " + match.away_team;

    if (match.status === "NO BET") {
      const noBet = document.createElement("p");
      noBet.className = "no-bet";
      const noBetLabels = {
        dati_mancanti: "DATI MANCANTI",
        campione_insufficiente: "CAMPIONE INSUFFICIENTE",
        stima_non_affidabile: "STIMA NON AFFIDABILE"
      };
      const noBetLabel = noBetLabels[match.no_bet_type] || "CONTROLLO NON SUPERATO";
      noBet.textContent = "NO BET · " + noBetLabel + " — " +
        (match.reason || "Dati insufficienti: nessun esito consigliato.") +
        (match.data_quality ? " · Controllo qualità: " + match.data_quality : "");
      card.append(meta, teams, noBet);
      appendAvailability(match, card);
      if (match.analysis) {
        const analysis = document.createElement("p");
        analysis.className = "match-analysis";
        analysis.textContent = (match.analysis_provider === "Gemini" ? "Analisi Gemini: " : "Nota statistica: ") + match.analysis;
        card.append(analysis);
      }
      container.append(card);
      continue;
    }

    const expected = document.createElement("p");
    expected.className = "match-meta";
    expected.textContent = "Gol attesi (modello): " + match.expected_home_goals + " — " + match.expected_away_goals;

    const grid = document.createElement("div");
    grid.className = "probabilities";
    const probabilities = [
      ["1", match.probabilities && match.probabilities.home_win],
      ["X", match.probabilities && match.probabilities.draw],
      ["2", match.probabilities && match.probabilities.away_win],
      ["1X", match.probabilities && match.probabilities.double_chance_1x],
      ["X2", match.probabilities && match.probabilities.double_chance_x2],
      ["12", match.probabilities && match.probabilities.double_chance_12],
      ["Over 1,5", match.probabilities && match.probabilities.over_1_5],
      ["Over 2,5", match.probabilities && match.probabilities.over_2_5],
      ["Over 3,5", match.probabilities && match.probabilities.over_3_5],
      ["Under 1,5", match.probabilities && match.probabilities.under_1_5],
      ["Under 2,5", match.probabilities && match.probabilities.under_2_5],
      ["Under 3,5", match.probabilities && match.probabilities.under_3_5],
      ["Goal", match.probabilities && match.probabilities.btts_yes],
      ["No Goal", match.probabilities && match.probabilities.btts_no],
      ["Segna casa", match.probabilities && match.probabilities.home_scores],
      ["Segna trasferta", match.probabilities && match.probabilities.away_scores]
    ];
    for (const pair of probabilities) {
      const item = document.createElement("div");
      item.className = "probability";
      const labelNode = document.createElement("span");
      labelNode.textContent = pair[0];
      const valueNode = document.createElement("strong");
      valueNode.textContent = percent(pair[1]);
      const p = pair[1];
      if (typeof p === "number") {
        item.classList.add(p >= 70 ? "signal-green" : p >= 55 ? "signal-yellow" : "signal-red");
        item.title = p >= 70 ? "Probabilità stimata alta (70% o più)" : p >= 55 ? "Probabilità stimata intermedia (55–69,9%)" : "Probabilità stimata bassa (meno del 55%)";
      }
      item.append(labelNode, valueNode);
      grid.append(item);
    }

    const confidence = document.createElement("p");
    confidence.className = "match-meta";
    confidence.classList.add("reliability-line");
    confidence.textContent = (match.status === "Pronostico valutabile" ? "PRONOSTICO VALUTABILE" : "STIMA PRELIMINARE") +
      " · Dati: " + (match.home_matches_sample ?? "—") +
      " gare casa della squadra di casa / " + (match.away_matches_sample ?? "—") +
      " trasferte della squadra ospite · " + (match.confidence || "quantità dati non specificata") +
      (match.data_quality ? " · Controllo: " + match.data_quality : "") +
      (match.elo_home != null && match.elo_away != null ? " · Elo " + match.elo_home + " / " + match.elo_away : "");

    const score = document.createElement("p");
    score.className = "match-meta";
    score.textContent = match.top_scorelines && match.top_scorelines.length
      ? "Risultati esatti più probabili (stime): " + match.top_scorelines.map(s => s.score + " (" + percent(s.probability) + ")").join(" · ")
      : "";

    card.append(meta, teams, expected, grid, confidence);
    const motivation = match.motivation_context;
    if (motivation && motivation.status === "indizi_classifica") {
      const motivationNote = document.createElement("p");
      motivationNote.className = "match-meta";
      const describeTeam = (teamName, context) => {
        if (!context) return "";
        const signals = Array.isArray(context.signals) ? context.signals.join(", ") : "";
        return teamName + " " + context.position + "ª (" + context.points + " punti): " + signals;
      };
      motivationNote.textContent = "MOTIVAZIONI DI CLASSIFICA · " +
        [describeTeam(match.home_team, motivation.home), describeTeam(match.away_team, motivation.away)].filter(Boolean).join(" · ") +
        ". Indicazioni orientative basate sui risultati disponibili: non confermano obiettivi già raggiunti né verdetti matematici.";
      card.append(motivationNote);
    }
    if (Array.isArray(match.recent_competition_context) && match.recent_competition_context.length) {
      const europe = document.createElement("p");
      europe.className = "market-no-pick";
      europe.textContent = "ATTENZIONE IMPEGNI RAVVICINATI · " + match.recent_competition_context.map(item =>
        item.team + ": " + item.competition + " il " + item.match_date +
        " (" + item.days_before + " giorni prima, " + item.venue + ")" +
        " · correzione sperimentale " + item.adjustment_pct + "%"
      ).join(" | ") +
        ". Stima declassata a preliminare; minuti giocati, viaggio e supplementari non sono verificati.";
      card.append(europe);
    }
    appendAvailability(match, card);
    if (match.odds_1x2) {
      const odds = document.createElement("p");
      odds.className = "match-meta";
      const q = match.odds_1x2;
      odds.textContent = "Migliori quote 1 / X / 2 disponibili: " +
        (q.home ?? "—") + " / " + (q.draw ?? "—") + " / " + (q.away ?? "—") +
        " · Fonte: " + (match.odds_source || "fonte quote configurata");
      card.append(odds);
      if (match.market_implied_probability_1x2) {
        const marketLine = document.createElement("p");
        marketLine.className = "match-meta";
        const implied = match.market_implied_probability_1x2;
        const delta = match.model_vs_market_delta_1x2 || {};
        marketLine.textContent = "Probabilità mercato depurata dal margine 1 / X / 2: " +
          percent(implied.home) + " / " + percent(implied.draw) + " / " + percent(implied.away) +
          " · Scarto modello-mercato: " + (typeof delta.home === "number" ? (delta.home > 0 ? "+" : "") + delta.home.toFixed(1) + "%" : "—") +
          " / " + (typeof delta.draw === "number" ? (delta.draw > 0 ? "+" : "") + delta.draw.toFixed(1) + "%" : "—") +
          " / " + (typeof delta.away === "number" ? (delta.away > 0 ? "+" : "") + delta.away.toFixed(1) + "%" : "—") +
          (typeof match.market_overround_1x2 === "number" ? " · Margine quote grezze: " + match.market_overround_1x2.toFixed(1) + "%" : "");
        card.append(marketLine);
      }
      if (match.expected_value_1x2) {
        const ev = match.expected_value_1x2;
        const evNode = document.createElement("p");
        evNode.className = "market-no-pick";
        evNode.textContent = "Valore atteso teorico 1 / X / 2: " +
          (ev.home * 100).toFixed(1) + "% / " + (ev.draw * 100).toFixed(1) + "% / " +
          (ev.away * 100).toFixed(1) + "%. Stima teorica non validata; non dimostra un vantaggio reale né redditività.";
        card.append(evNode);
      }
      if (Array.isArray(match.value_bets) && match.value_bets.length) {
        const value = document.createElement("p");
        value.className = "market-chip market-green";
        value.textContent = "Candidati teorici EV ≥ 5% (campione ≥ 8 gare per lato, quote fresche): " + match.value_bets.map(v =>
          v.market + " @ " + v.best_odds + " (EV " + (v.expected_value * 100).toFixed(1) + "%)"
        ).join(" · ");
        card.append(value);
      }
    }
    if (match.market_analysis_markets && Object.keys(match.market_analysis_markets).length) {
      const extraTitle = document.createElement("p");
      extraTitle.className = "match-meta";
      extraTitle.textContent = "QUOTE E CONFRONTO DEI MERCATI GOAL · quando disponibili";
      card.append(extraTitle);
      const marketLabels = {
        over_under_1_5: ["Over/Under 1,5", "over", "under"],
        over_under_2_5: ["Over/Under 2,5", "over", "under"],
        over_under_3_5: ["Over/Under 3,5", "over", "under"],
        btts: ["Gol / No Gol", "yes", "no"]
      };
      for (const [key, labelAndSides] of Object.entries(marketLabels)) {
        const data = match.market_analysis_markets[key];
        if (!data || !data.odds || !data.model_probability || !data.market_implied_probability) continue;
        const [label, sideA, sideB] = labelAndSides;
        const line = document.createElement("p");
        line.className = "match-meta";
        const part = side => {
          const odd = data.odds[side];
          const modelP = data.model_probability[side];
          const marketP = data.market_implied_probability[side];
          const ev = data.expected_value && data.expected_value[side];
          return side.toUpperCase() + " quota " + odd + " · modello " + percent(modelP) +
            " · mercato " + percent(marketP) +
            (typeof ev === "number" ? " · EV " + (ev * 100).toFixed(1) + "%" : "");
        };
        line.textContent = label + ": " + part(sideA) + " | " + part(sideB) + ". EV teorico non validato: non prova un vantaggio reale.";
        card.append(line);
      }
      const dc = match.market_analysis_markets.double_chance;
      if (dc && Object.keys(dc).length) {
        const dcLine = document.createElement("p");
        dcLine.className = "match-meta";
        dcLine.textContent = "Doppia chance: " + Object.entries(dc).map(([key, item]) =>
          key.toUpperCase() + " quota " + item.odds + " · modello " + percent(item.model_probability) +
          " · EV teorico " + (item.expected_value * 100).toFixed(1) + "%"
        ).join(" | ") + ". EV non validato; probabilità implicita 1/quota non depurata: le selezioni si sovrappongono.";
        card.append(dcLine);
      }
    }
    if (match.analysis) {
      const analysis = document.createElement("p");
      analysis.className = "match-analysis";
      analysis.textContent = (match.analysis_provider === "Gemini" ? "Analisi assistita da Gemini: " : "Analisi sintetica: ") + match.analysis;
      card.append(analysis);
    }
    if (Array.isArray(match.suggested_markets) && match.suggested_markets.length) {
      const suggested = document.createElement("div");
      suggested.className = "suggested-markets";
      const title = document.createElement("p");
      title.className = "match-meta";
      title.textContent = "ESITI DA VALUTARE · probabilità modello ≥70% (controllare le quote)";
      suggested.append(title);
      for (const market of match.suggested_markets) {
        const chip = document.createElement("span");
        chip.className = "market-chip market-green";
        chip.textContent = "✓ " + market;
        suggested.append(chip);
      }
      card.append(suggested);
    } else {
      const noPick = document.createElement("p");
      noPick.className = "market-no-pick";
      noPick.textContent = "NESSUN ESITO SELEZIONATO · nessun mercato supera la soglia automatica del 70%.";
      card.append(noPick);
    }
    if (score.textContent) card.append(score);
    container.append(card);
  }
}


function renderHistory(history) {
  const metricsNode = document.getElementById("history-metrics");
  const listNode = document.getElementById("history-list");
  if (!metricsNode || !listNode) return;
  const metrics = history && history.metrics ? history.metrics : {};
  metricsNode.replaceChildren();

  const metricItems = [
    ["Partite verificate", Number(metrics.settled_matches || 0).toLocaleString("it-IT")],
    ["Accuratezza 1X2", typeof metrics.accuracy_1x2 === "number" ? percent(metrics.accuracy_1x2) : "Non ancora pubblicabile"],
    ["Brier score", typeof metrics.brier_score_1x2 === "number" ? metrics.brier_score_1x2.toLocaleString("it-IT", { maximumFractionDigits: 4 }) : "Non ancora pubblicabile"],
    ["Log loss", typeof metrics.log_loss_1x2 === "number" ? metrics.log_loss_1x2.toLocaleString("it-IT", { maximumFractionDigits: 4 }) : "Non ancora pubblicabile"]
  ];
  for (const [label, value] of metricItems) {
    const item = document.createElement("div");
    item.className = "history-metric";
    const caption = document.createElement("span");
    caption.className = "match-meta";
    caption.textContent = label;
    const strong = document.createElement("strong");
    strong.textContent = value;
    item.append(caption, strong);
    metricsNode.append(item);
  }

  if (typeof metrics.note === "string") {
    const readiness = document.createElement("p");
    readiness.className = "match-meta";
    readiness.textContent = metrics.note;
    metricsNode.append(readiness);
  }
  const valueMetrics = history && history.value_bet_metrics;
  if (valueMetrics) {
    const heading = document.createElement("h3");
    heading.textContent = "Rendimento storico dei candidati 1X2";
    metricsNode.append(heading);
    const row = document.createElement("p");
    row.className = "match-meta";
    row.textContent = (valueMetrics.settled_bets || 0) + " selezioni concluse · " +
      (valueMetrics.wins || 0) + " vinte · " + (valueMetrics.losses || 0) + " perse · saldo teorico " +
      (valueMetrics.net_units_per_one_unit_stake ?? 0) + " unità con puntata fissa di 1 unità per selezione · ROI " +
      (typeof valueMetrics.roi_percent === "number" ? valueMetrics.roi_percent + "%" : "non pubblicabile prima di 30 selezioni concluse");
    metricsNode.append(row);
    const note = document.createElement("p");
    note.className = "match-meta";
    note.textContent = valueMetrics.note || "Rendimento teorico dei candidati archiviati, non delle schedine personali.";
    metricsNode.append(note);
  }

  const resultMatching = history && history.result_matching;
  if (resultMatching && Number(resultMatching.unresolved_past_matches || 0) > 0) {
    const unresolved = document.createElement("p");
    unresolved.className = "match-meta";
    unresolved.textContent = resultMatching.unresolved_past_matches +
      " partite con data passata non hanno ancora un risultato associato. Sono escluse dalle metriche finché l'esito non viene verificato.";
    metricsNode.append(unresolved);
  }

  const europeanMetrics = history && history.metrics_by_european_context;
  if (europeanMetrics && europeanMetrics.groups) {
    const heading = document.createElement("h3");
    heading.textContent = "Validazione: partite dopo le coppe europee";
    metricsNode.append(heading);
    const note = document.createElement("p");
    note.className = "match-meta";
    note.textContent = europeanMetrics.note || "Confronto descrittivo; non dimostra causalità.";
    metricsNode.append(note);
    for (const [key, values] of Object.entries(europeanMetrics.groups)) {
      const row = document.createElement("p");
      row.className = "match-meta";
      const label = key === "recent_european_match" ? "Con impegno europeo recente" : "Senza impegno europeo recente";
      row.textContent = label + ": " + (values.context_matches_archived || 0) + " archiviate · " +
        (values.settled_matches || 0) + " risultati verificati · accuratezza " +
        (typeof values.accuracy_1x2 === "number" ? percent(values.accuracy_1x2) : "campione insufficiente") +
        " · Brier " + (typeof values.brier_score_1x2 === "number" ? values.brier_score_1x2 : "—");
      metricsNode.append(row);
    }
  }

  const comparison = history && history.model_vs_market_metrics;
  if (comparison) {
    const heading = document.createElement("h3");
    heading.textContent = "Modello contro mercato (stesse partite concluse)";
    metricsNode.append(heading);
    const summary = document.createElement("p");
    summary.className = "match-meta";
    summary.textContent = comparison.settled_matches_with_model_and_odds + " partite concluse con probabilità e quote archiviate. " +
      (comparison.model && comparison.market
        ? "Accuratezza: modello " + percent(comparison.model.accuracy_1x2) + " vs mercato " + percent(comparison.market.accuracy_1x2) +
          " · Brier: " + comparison.model.brier_score_1x2 + " vs " + comparison.market.brier_score_1x2 +
          " · Log loss: " + comparison.model.log_loss_1x2 + " vs " + comparison.market.log_loss_1x2 +
          " (Brier e log loss: più basso è meglio)."
        : (comparison.note || "Confronto in attesa di un campione sufficiente."));
    metricsNode.append(summary);
  }

  const records = Array.isArray(history && history.records) ? [...history.records] : [];
  records.sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  listNode.replaceChildren();
  if (!records.length) {
    listNode.textContent = "Lo storico non contiene ancora partite archiviate.";
    return;
  }
  const summary = document.createElement("p");
  summary.className = "match-meta";
  summary.textContent = records.length + " partite archiviate · " + (metrics.settled_matches || 0) + " con risultato verificato";
  listNode.append(summary);

  const byLeague = history && history.metrics_by_league ? history.metrics_by_league : {};
  const leagueEntries = Object.entries(byLeague);
  if (leagueEntries.length) {
    const heading = document.createElement("h3");
    heading.textContent = "Validazione storica per campionato";
    listNode.append(heading);
    const note = document.createElement("p");
    note.className = "match-meta";
    note.textContent = "Solo partite con esito verificato. Campioni piccoli non dimostrano affidabilità futura.";
    listNode.append(note);
    for (const [league, values] of leagueEntries.sort((a, b) => a[0].localeCompare(b[0], "it"))) {
      const row = document.createElement("p");
      row.className = "match-meta";
      row.textContent = league + ": " + values.settled_matches + " verificate · accuratezza " +
        (typeof values.accuracy_1x2 === "number" ? percent(values.accuracy_1x2) : "in attesa") +
        " · Brier " + (typeof values.brier_score_1x2 === "number"
          ? values.brier_score_1x2.toLocaleString("it-IT", { maximumFractionDigits: 4 }) : "in attesa");
      listNode.append(row);
    }
  }

  const extraMetrics = history && history.additional_market_metrics ? history.additional_market_metrics : {};
  const availableExtraMetrics = Object.entries(extraMetrics).filter(([, value]) => value && value.model && value.market);
  if (availableExtraMetrics.length) {
    const heading = document.createElement("h3");
    heading.textContent = "Validazione storica mercati Over/Under e Gol/No Gol";
    listNode.append(heading);
    for (const [market, value] of availableExtraMetrics) {
      const row = document.createElement("p");
      row.className = "match-meta";
      row.textContent = market.replaceAll("_", " ") + ": " + value.settled_matches_with_model_and_odds +
        " partite · accuratezza modello " + percent(value.model.accuracy) +
        " / mercato " + percent(value.market.accuracy) +
        " · Brier modello " + value.model.brier_score + " / mercato " + value.market.brier_score;
      listNode.append(row);
    }
  }
  for (const record of records.slice(0, 12)) {
    const card = document.createElement("article");
    card.className = "history-item";
    const meta = document.createElement("p");
    meta.className = "match-meta";
    meta.textContent = (record.league || "Campionato") + " · " + formatDate(record.date);
    const teams = document.createElement("p");
    teams.className = "match-teams";
    teams.textContent = (record.home_team || "Casa") + " — " + (record.away_team || "Trasferta");
    const outcome = document.createElement("p");
    if (record.outcome === "1" || record.outcome === "X" || record.outcome === "2") {
      outcome.className = "history-result";
      outcome.textContent = "Risultato finale: " + record.home_goals + "–" + record.away_goals + " · Esito " + record.outcome;
    } else {
      outcome.className = "history-pending";
      outcome.textContent = "Esito in attesa del risultato ufficiale";
    }
    const prediction = document.createElement("p");
    prediction.className = "match-meta";
    const p = record.probabilities || {};
    prediction.textContent = "Probabilità archiviate 1 / X / 2: " + percent(p.home_win) + " / " + percent(p.draw) + " / " + percent(p.away_win);
    card.append(meta, teams, outcome, prediction);
    listNode.append(card);
  }
  if (typeof metrics.note === "string") {
    const note = document.createElement("p");
    note.className = "match-meta";
    note.textContent = metrics.note;
    listNode.append(note);
  }
}

async function aggiornaStorico() {
  const listNode = document.getElementById("history-list");
  try {
    const history = await fetchJsonWithTimeout(HISTORY_URL + "?t=" + Date.now());
    if (!history || !Array.isArray(history.records) || !history.metrics || typeof history.metrics !== "object") {
      throw new Error("Formato archivio non valido");
    }
    renderHistory(history);
  } catch (error) {
    if (listNode) listNode.textContent = "Lo storico non è ancora disponibile. Verrà pubblicato dopo il prossimo aggiornamento automatico.";
  }
}

async function aggiornaDati() {
  const stato = document.getElementById("status");
  const aggiornamento = document.getElementById("updated");
  const pulsante = document.getElementById("refresh");
  if (!stato || !aggiornamento || !pulsante) return;

  pulsante.disabled = true;
  stato.textContent = "Ricarico le stime già pubblicate…";

  try {
    const dati = await fetchJsonWithTimeout(DATA_URL + "?t=" + Date.now());
    if (!dati || !Array.isArray(dati.matches)) throw new Error("Formato dati non valido");
    lastRefreshAt = Date.now();

    // Mostra soltanto oggi e i prossimi 5 giorni: 6 date di calendario in totale.
    // Il filtro lato pagina evita anche di mostrare partite vecchie se il file dati è datato.
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const lastDay = new Date(today);
    lastDay.setDate(lastDay.getDate() + 5);
    const isoLocalDate = date => [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, "0"),
      String(date.getDate()).padStart(2, "0")
    ].join("-");

    const firstDate = isoLocalDate(today);
    const lastDate = isoLocalDate(lastDay);
    const rejectedForecasts = dati.matches.filter(match => !isValidMatchRecord(match)).length;
    const validMatches = dati.matches
      .filter(match => isValidMatchRecord(match))
      .filter(match => match.date >= firstDate && match.date <= lastDate)
      .sort((a, b) =>
        (a.country || "Altro").localeCompare(b.country || "Altro", "it") ||
        (a.league || "").localeCompare(b.league || "", "it") ||
        a.date.localeCompare(b.date) ||
        (a.kickoff || "99:99").localeCompare(b.kickoff || "99:99") ||
        (a.home_team || "").localeCompare(b.home_team || "", "it")
      );
    const rawNoBetMatches = Array.isArray(dati.no_bet_matches) ? dati.no_bet_matches : [];
    const rejectedNoBets = rawNoBetMatches.filter(match => !isValidMatchRecord(match, "NO BET")).length;
    const noBetMatches = rawNoBetMatches
      .filter(match => isValidMatchRecord(match, "NO BET"))
      .filter(match => match.date >= firstDate && match.date <= lastDate)
      .sort((a, b) =>
        a.date.localeCompare(b.date) ||
        (a.kickoff || "99:99").localeCompare(b.kickoff || "99:99") ||
        (a.league || "").localeCompare(b.league || "", "it") ||
        (a.home_team || "").localeCompare(b.home_team || "", "it")
      );
    const combined = [...validMatches, ...noBetMatches].sort((a, b) =>
      (a.country || "Altro").localeCompare(b.country || "Altro", "it") ||
      (a.league || "").localeCompare(b.league || "", "it") ||
      a.date.localeCompare(b.date) ||
      (a.kickoff || "99:99").localeCompare(b.kickoff || "99:99") ||
      (a.home_team || "").localeCompare(b.home_team || "", "it")
    );
    allLoadedMatches = combined;
    populateFilters(combined);
    applyFilters();
    const coverage = dati.coverage || {};
    const historyCount = Array.isArray(coverage.leagues_with_history)
      ? coverage.leagues_with_history.length
      : null;
    const coverageNote = historyCount !== null
      ? " Copertura storico recente: " + historyCount + "/" + (coverage.leagues_configured || "?") + " campionati con almeno un risultato disponibile; non equivale a copertura completa."
      : "";
    const coverageWarning = Array.isArray(coverage.leagues_without_history) && coverage.leagues_without_history.length
      ? " Senza storico: " + coverage.leagues_without_history.join(", ") + "."
      : "";
    const marketDiagnostics = dati.market_analysis || {};
    const quoteTotal = Number(marketDiagnostics.matches_total || validMatches.length);
    const quoteCount = Number(marketDiagnostics.matches_with_fresh_1x2_quotes || 0);
    const extraQuoteCount = Number(marketDiagnostics.matches_with_fresh_additional_markets || 0);
    const oddsProviders = dati.odds_providers || {};
    const secondaryOddsMissing = oddsProviders.the_odds_api &&
      oddsProviders.the_odds_api.status === "chiave_non_configurata";
    const oddsNote = " Quote aggiornate: " + quoteCount + "/" + quoteTotal +
      " partite con 1X2 e " + extraQuoteCount + " con mercati aggiuntivi.";
    const oddsWarning = secondaryOddsMissing
      ? " La fonte quote secondaria non è configurata; la copertura dipende dal piano API-Football e dai dati pubblici."
      : "";
    stato.textContent = (validMatches.length
      ? "STIME DISPONIBILI · " + validMatches.length + " partite con probabilità; " + noBetMatches.length + " NO BET senza dati sufficienti. Le stime preliminari sono indicate come tali."
      : "NO BET · Nessuna partita ha dati sufficienti per stimare probabilità; il calendario mostra le partite disponibili.")
      + coverageNote + coverageWarning + oddsNote + oddsWarning;
    const parsedUpdate = dati.updated_at ? new Date(dati.updated_at) : null;
    const validUpdate = parsedUpdate && !Number.isNaN(parsedUpdate.getTime());
    const dataAgeHours = validUpdate ? (Date.now() - parsedUpdate.getTime()) / 3600000 : Infinity;
    const staleWarning = !validUpdate || dataAgeHours < 0 || dataAgeHours > 2;
    const stamp = validUpdate ? parsedUpdate.toLocaleString("it-IT") : "non disponibile";
    const failedSources = Array.isArray(coverage.failed_sources) ? coverage.failed_sources : [];
    if (failedSources.length) {
      stato.textContent += " Fonti con problemi: " + failedSources.join(", ") + ".";
    }
    if (rejectedForecasts || rejectedNoBets) {
      const rejectedTotal = rejectedForecasts + rejectedNoBets;
      stato.textContent += " Avviso integrità: " + rejectedTotal +
        " record esclus" + (rejectedTotal === 1 ? "o" : "i") +
        " perché non superano i controlli di formato/coerenza.";
    }
    if (staleWarning) {
      stato.textContent = "ATTENZIONE · I dati pubblicati sono obsoleti o hanno un timestamp non valido. Non considerarli aggiornati. " + stato.textContent;
    }
    aggiornamento.textContent = "Ultimo calcolo salvato: " + stamp +
      (staleWarning ? " · ATTENZIONE: dati più vecchi di 2 ore o data non valida." : "") +
      ". Il pulsante ricarica il file pubblicato; non avvia direttamente il calcolo sul server.";
  } catch (errore) {
    stato.textContent = "DATI NON DISPONIBILI · " + (errore && errore.message ? errore.message : "L'aggiornamento non è riuscito.");
    const container = document.getElementById("matches");
    if (container) container.textContent = "Non è stato possibile leggere le stime. Controlla la connessione e premi Ricarica dati.";
    aggiornamento.textContent = "Il file dati non è stato caricato o non ha il formato atteso.";
  } finally {
    pulsante.disabled = false;
  }
}

function populateFilters(matches) {
  const country = document.getElementById("country-filter");
  const league = document.getElementById("league-filter");
  const day = document.getElementById("date-filter");
  if (!country || !league || !day) return;
  const selectedCountry = country.value;
  const selectedLeague = league.value;
  const selectedDay = day.value;
  const countries = [...new Set(matches.map(m => m.country || "Altro"))].sort((a, b) => a.localeCompare(b, "it"));
  country.replaceChildren(new Option("Tutte le nazioni", ""));
  for (const value of countries) country.add(new Option(value, value));
  country.value = countries.includes(selectedCountry) ? selectedCountry : "";
  const filtered = matches.filter(m => !country.value || (m.country || "Altro") === country.value);
  const leagues = [...new Set(filtered.map(m => m.league || "Competizione"))].sort((a, b) => a.localeCompare(b, "it"));
  league.replaceChildren(new Option("Tutte le competizioni", ""));
  for (const value of leagues) league.add(new Option(value, value));
  league.value = leagues.includes(selectedLeague) ? selectedLeague : "";

  const days = [...new Set(matches.map(m => m.date))].sort((a, b) => a.localeCompare(b));
  day.replaceChildren(new Option("Tutti i giorni", ""));
  for (const value of days) day.add(new Option(formatFullDate(value), value));
  day.value = days.includes(selectedDay) ? selectedDay : "";
}

function applyFilters() {
  const country = document.getElementById("country-filter");
  const league = document.getElementById("league-filter");
  const day = document.getElementById("date-filter");
  const dateOrder = document.getElementById("date-order-filter");
  const selectedCountry = country ? country.value : "";
  const selectedLeague = league ? league.value : "";
  const selectedDay = day ? day.value : "";
  const orderMode = dateOrder ? dateOrder.value : "competition";
  const filtered = allLoadedMatches.filter(m =>
    (!selectedCountry || (m.country || "Altro") === selectedCountry) &&
    (!selectedLeague || (m.league || "Competizione") === selectedLeague) &&
    (!selectedDay || m.date === selectedDay)
  );
  filtered.sort((a, b) => {
    if (orderMode === "date-asc" || orderMode === "date-desc") {
      const byDate = a.date.localeCompare(b.date);
      if (byDate) return orderMode === "date-desc" ? -byDate : byDate;
      return (a.kickoff || "99:99").localeCompare(b.kickoff || "99:99") ||
        (a.league || "").localeCompare(b.league || "", "it") ||
        (a.home_team || "").localeCompare(b.home_team || "", "it");
    }
    return (a.country || "Altro").localeCompare(b.country || "Altro", "it") ||
      (a.league || "").localeCompare(b.league || "", "it") ||
      a.date.localeCompare(b.date) ||
      (a.kickoff || "99:99").localeCompare(b.kickoff || "99:99") ||
      (a.home_team || "").localeCompare(b.home_team || "", "it");
  });
  renderMatches(filtered);
}

function initializeCalcioIntelligente() {
  const pulsante = document.getElementById("refresh");
  if (pulsante) {
    pulsante.addEventListener("click", aggiornaDati);
    const country = document.getElementById("country-filter");
    const league = document.getElementById("league-filter");
    if (country) country.addEventListener("change", () => { populateFilters(allLoadedMatches); applyFilters(); });
    if (league) league.addEventListener("change", applyFilters);
    const day = document.getElementById("date-filter");
    if (day) day.addEventListener("change", applyFilters);
    const dateOrder = document.getElementById("date-order-filter");
    if (dateOrder) dateOrder.addEventListener("change", applyFilters);
    aggiornaDati();
    aggiornaStorico();

    // Il backend pubblica dati nuovi ogni ora; la pagina aperta li rilegge ogni 15 minuti.
    // Se la scheda era in background, aggiorna al ritorno senza sovrapporre richieste.
    window.setInterval(() => {
      if (document.visibilityState === "visible" && !pulsante.disabled) {
        aggiornaDati();
        aggiornaStorico();
      }
    }, 15 * 60 * 1000);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" &&
          Date.now() - lastRefreshAt >= 15 * 60 * 1000 &&
          !pulsante.disabled) {
        aggiornaDati();
        aggiornaStorico();
      }
    });
  }
}

// Supporta sia script defer sia inserimento dopo DOMContentLoaded.
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeCalcioIntelligente, { once: true });
} else {
  initializeCalcioIntelligente();
}
