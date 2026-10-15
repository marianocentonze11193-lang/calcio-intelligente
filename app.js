"use strict";

const DATA_URL = "./data/predictions.json";

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

function renderMatches(matches) {
  const container = document.getElementById("matches");
  if (!container) return;
  container.replaceChildren();

  if (!matches.length) {
    container.textContent = "Nessuna partita nei prossimi 6 giorni supera il controllo storico minimo. Il sistema riproverà al prossimo aggiornamento.";
    return;
  }

  for (const match of matches) {
    const card = document.createElement("article");
    card.className = "match-card";

    const meta = document.createElement("p");
    meta.className = "match-meta";
    meta.textContent = (match.league || "Campionato") + " · " + formatDate(match.date) +
      (match.kickoff ? " · " + match.kickoff : "");

    const teams = document.createElement("h3");
    teams.className = "match-teams";
    teams.textContent = match.home_team + " — " + match.away_team;

    if (match.status === "NO BET") {
      const noBet = document.createElement("p");
      noBet.className = "no-bet";
      noBet.textContent = "NO BET · " + (match.reason || "Dati insufficienti: nessun esito consigliato.");
      card.append(meta, teams, noBet);
      if (match.analysis) {
        const analysis = document.createElement("p");
        analysis.className = "match-analysis";
        analysis.textContent = match.analysis;
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
      " partite per squadra · Stato: " + (match.status || "Pronostico valutabile") +
      " · Campione: " + (match.confidence || "iniziale");

    const score = document.createElement("p");
    score.className = "match-meta";
    score.textContent = match.top_scorelines && match.top_scorelines.length
      ? "Risultati esatti più probabili (stime): " + match.top_scorelines.map(s => s.score + " (" + percent(s.probability) + ")").join(" · ")
      : "";

    card.append(meta, teams, expected, grid, confidence);
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
      .filter(match =>
        match.date >= firstDate &&
        match.date <= lastDate &&
        Number.isFinite(Number(match.sample_matches)) &&
        Number(match.sample_matches) >= 3
      )
      .sort((a, b) =>
        a.date.localeCompare(b.date) ||
        (a.kickoff || "99:99").localeCompare(b.kickoff || "99:99") ||
        (a.league || "").localeCompare(b.league || "", "it") ||
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
      a.date.localeCompare(b.date) ||
      (a.kickoff || "99:99").localeCompare(b.kickoff || "99:99") ||
      (a.league || "").localeCompare(b.league || "", "it")
    );
    renderMatches(combined);
    stato.textContent = validMatches.length
      ? "PRONOSTICI VALUTABILI · " + validMatches.length + " partite con dati sufficienti; sono mostrate anche " + noBetMatches.length + " partite NO BET quando lo storico è insufficiente."
      : "NO BET · Nessuna partita supera il controllo minimo; vengono comunque mostrate le partite in calendario con dati insufficienti.";
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

document.addEventListener("DOMContentLoaded", () => {
  const pulsante = document.getElementById("refresh");
  if (pulsante) {
    pulsante.addEventListener("click", aggiornaDati);
    aggiornaDati();
  }
});
