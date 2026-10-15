"use strict";

const DATA_URL = "./data/predictions.json";
const HISTORY_URL = "./data/history.json";
let allLoadedMatches = [];

function formatDate(value) {
  if (!value) return "Data da confermare";
  const parsed = new Date(value + "T12:00:00");
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString("it-IT", {
    weekday: "short", day: "2-digit", month: "short"
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

  let previousGroup = "";
  for (const match of matches) {
    const group = (match.country || "Altro") + " · " + (match.league || "Competizione");
    if (group !== previousGroup) {
      const heading = document.createElement("h3");
      heading.className = "competition-heading";
      heading.textContent = group;
      container.append(heading);
      previousGroup = group;
    }
    const card = document.createElement("article");
    card.className = "match-card";

    const meta = document.createElement("p");
    meta.className = "match-meta";
    meta.textContent = formatDate(match.date) +
      (match.kickoff ? " · " + match.kickoff : " · orario da confermare");

    const teams = document.createElement("h3");
    teams.className = "match-teams";
    teams.textContent = match.home_team + " — " + match.away_team;

    if (match.status === "NO BET") {
      const noBet = document.createElement("p");
      noBet.className = "no-bet";
      noBet.textContent = "NO BET · " + (match.reason || "Dati insufficienti: nessun esito consigliato.");
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
    confidence.textContent = "Campione minimo: " + match.sample_matches +
      " partite nel contesto casa/trasferta · Stato: " + (match.status || "Pronostico valutabile") +
      " · Fiducia: " + (match.confidence || "iniziale") +
      (match.elo_home != null && match.elo_away != null ? " · Elo " + match.elo_home + " / " + match.elo_away : "");

    const score = document.createElement("p");
    score.className = "match-meta";
    score.textContent = match.top_scorelines && match.top_scorelines.length
      ? "Risultati esatti più probabili (stime): " + match.top_scorelines.map(s => s.score + " (" + percent(s.probability) + ")").join(" · ")
      : "";

    card.append(meta, teams, expected, grid, confidence);
    appendAvailability(match, card);
    if (match.odds_1x2) {
      const odds = document.createElement("p");
      odds.className = "match-meta";
      const q = match.odds_1x2;
      odds.textContent = "Migliori quote 1 / X / 2 disponibili: " +
        (q.home ?? "—") + " / " + (q.draw ?? "—") + " / " + (q.away ?? "—") +
        " · Fonte: " + (match.odds_source || "fonte quote configurata");
      card.append(odds);
      if (match.expected_value_1x2) {
        const ev = match.expected_value_1x2;
        const evNode = document.createElement("p");
        evNode.className = "market-no-pick";
        evNode.textContent = "Valore atteso teorico 1 / X / 2: " +
          (ev.home * 100).toFixed(1) + "% / " + (ev.draw * 100).toFixed(1) + "% / " +
          (ev.away * 100).toFixed(1) + "%. Stima basata sul modello, prima di considerare l'errore del modello.";
        card.append(evNode);
      }
      if (Array.isArray(match.value_bets) && match.value_bets.length) {
        const value = document.createElement("p");
        value.className = "market-chip market-green";
        value.textContent = "Candidati teorici EV ≥ 3%: " + match.value_bets.map(v =>
          v.market + " @ " + v.best_odds + " (EV " + (v.expected_value * 100).toFixed(1) + "%)"
        ).join(" · ");
        card.append(value);
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
    ["Accuratezza 1X2", typeof metrics.accuracy_1x2 === "number" ? percent(metrics.accuracy_1x2) : "In attesa"],
    ["Brier score", typeof metrics.brier_score_1x2 === "number" ? metrics.brier_score_1x2.toLocaleString("it-IT", { maximumFractionDigits: 4 }) : "In attesa"]
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
    const response = await fetch(HISTORY_URL + "?t=" + Date.now(), { cache: "no-store" });
    if (!response.ok) throw new Error("Archivio non disponibile");
    renderHistory(await response.json());
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
    const risposta = await fetch(DATA_URL + "?t=" + Date.now(), { cache: "no-store" });
    if (!risposta.ok) throw new Error("File dati non disponibile");
    const dati = await risposta.json();
    if (!Array.isArray(dati.matches)) throw new Error("Formato dati non valido");

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
    const validMatches = dati.matches
      .filter(match => match.date >= firstDate && match.date <= lastDate)
      .sort((a, b) =>
        (a.country || "Altro").localeCompare(b.country || "Altro", "it") ||
        (a.league || "").localeCompare(b.league || "", "it") ||
        a.date.localeCompare(b.date) ||
        (a.kickoff || "99:99").localeCompare(b.kickoff || "99:99") ||
        (a.home_team || "").localeCompare(b.home_team || "", "it")
      );
    const noBetMatches = (Array.isArray(dati.no_bet_matches) ? dati.no_bet_matches : [])
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
    stato.textContent = validMatches.length
      ? "STIME DISPONIBILI · " + validMatches.length + " partite con probabilità; " + noBetMatches.length + " NO BET senza dati sufficienti. Le stime preliminari sono indicate come tali."
      : "NO BET · Nessuna partita ha dati sufficienti per stimare probabilità; il calendario mostra le partite disponibili.";
    const stamp = dati.updated_at ? new Date(dati.updated_at).toLocaleString("it-IT") : "non disponibile";
    aggiornamento.textContent = "Ultimo calcolo salvato: " + stamp + ". Il pulsante ricarica il file pubblicato; non avvia direttamente il calcolo sul server.";
  } catch (errore) {
    stato.textContent = "DATI NON DISPONIBILI · L'aggiornamento non è riuscito.";
    const container = document.getElementById("matches");
    if (container) container.textContent = "Non è stato possibile leggere le stime. Riprova più tardi.";
    aggiornamento.textContent = "Vengono mostrate solo le stime già salvate nel file dati.";
  } finally {
    pulsante.disabled = false;
  }
}

function populateFilters(matches) {
  const country = document.getElementById("country-filter");
  const league = document.getElementById("league-filter");
  if (!country || !league) return;
  const selectedCountry = country.value;
  const selectedLeague = league.value;
  const countries = [...new Set(matches.map(m => m.country || "Altro"))].sort((a, b) => a.localeCompare(b, "it"));
  country.replaceChildren(new Option("Tutte le nazioni", ""));
  for (const value of countries) country.add(new Option(value, value));
  country.value = countries.includes(selectedCountry) ? selectedCountry : "";
  const filtered = matches.filter(m => !country.value || (m.country || "Altro") === country.value);
  const leagues = [...new Set(filtered.map(m => m.league || "Competizione"))].sort((a, b) => a.localeCompare(b, "it"));
  league.replaceChildren(new Option("Tutte le competizioni", ""));
  for (const value of leagues) league.add(new Option(value, value));
  league.value = leagues.includes(selectedLeague) ? selectedLeague : "";
}

function applyFilters() {
  const country = document.getElementById("country-filter");
  const league = document.getElementById("league-filter");
  const selectedCountry = country ? country.value : "";
  const selectedLeague = league ? league.value : "";
  renderMatches(allLoadedMatches.filter(m =>
    (!selectedCountry || (m.country || "Altro") === selectedCountry) &&
    (!selectedLeague || (m.league || "Competizione") === selectedLeague)
  ));
}

document.addEventListener("DOMContentLoaded", () => {
  const pulsante = document.getElementById("refresh");
  if (pulsante) {
    pulsante.addEventListener("click", aggiornaDati);
    const country = document.getElementById("country-filter");
    const league = document.getElementById("league-filter");
    if (country) country.addEventListener("change", () => { populateFilters(allLoadedMatches); applyFilters(); });
    if (league) league.addEventListener("change", applyFilters);
    aggiornaDati();
    aggiornaStorico();
  }
});
