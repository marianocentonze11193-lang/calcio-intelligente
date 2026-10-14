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
    container.textContent = "Nessuna partita futura con un campione statistico sufficiente. Il sistema riproverà al prossimo aggiornamento.";
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

    const expected = document.createElement("p");
    expected.className = "match-meta";
    expected.textContent = "Gol attesi (modello): " + match.expected_home_goals + " — " + match.expected_away_goals;

    const grid = document.createElement("div");
    grid.className = "probabilities";
    const probabilities = [
      ["1", match.probabilities && match.probabilities.home_win],
      ["X", match.probabilities && match.probabilities.draw],
      ["2", match.probabilities && match.probabilities.away_win],
      ["Over 2,5", match.probabilities && match.probabilities.over_2_5],
      ["Goal", match.probabilities && match.probabilities.btts_yes]
    ];
    for (const pair of probabilities) {
      const item = document.createElement("div");
      item.className = "probability";
      const labelNode = document.createElement("span");
      labelNode.textContent = pair[0];
      const valueNode = document.createElement("strong");
      valueNode.textContent = percent(pair[1]);
      item.append(labelNode, valueNode);
      grid.append(item);
    }

    const confidence = document.createElement("p");
    confidence.className = "match-meta";
    confidence.textContent = "Campione: " + match.sample_matches +
      " partite per squadra · Affidabilità del campione: " + (match.confidence || "iniziale");

    card.append(meta, teams, expected, grid, confidence);
    container.append(card);
  }
}

async function aggiornaDati() {
  const stato = document.getElementById("status");
  const aggiornamento = document.getElementById("updated");
  const pulsante = document.getElementById("refresh");
  if (!stato || !aggiornamento || !pulsante) return;

  pulsante.disabled = true;
  stato.textContent = "Caricamento delle ultime stime disponibili…";

  try {
    const risposta = await fetch(DATA_URL + "?t=" + Date.now(), { cache: "no-store" });
    if (!risposta.ok) throw new Error("File dati non disponibile");
    const dati = await risposta.json();
    if (!Array.isArray(dati.matches)) throw new Error("Formato dati non valido");

    renderMatches(dati.matches);
    stato.textContent = dati.matches.length
      ? "DATI AGGIORNATI · " + dati.matches.length + " partite con stime statistiche disponibili."
      : "NO BET · Nessuna partita futura con dati sufficienti al momento.";
    const stamp = dati.updated_at ? new Date(dati.updated_at).toLocaleString("it-IT") : "non disponibile";
    aggiornamento.textContent = "Ultimo aggiornamento dati: " + stamp + ". Fonte: football-data.co.uk.";
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
