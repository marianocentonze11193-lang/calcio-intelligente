
"use strict";

const DATA_URL = "./data/predictions.json";

async function aggiornaDati() {
  const stato = document.getElementById("status");
  const partite = document.getElementById("matches");
  const aggiornamento = document.getElementById("updated");
  const pulsante = document.getElementById("refresh");

  if (!stato || !partite || !aggiornamento || !pulsante) {
    return;
  }

  pulsante.disabled = true;
  stato.textContent = "Controllo della disponibilità dei dati…";

  try {
    const risposta = await fetch(DATA_URL, { cache: "no-store" });

    if (!risposta.ok) {
      throw new Error("File dati non disponibile");
    }

    const dati = await risposta.json();

    if (!Array.isArray(dati.matches)) {
      throw new Error("Formato dei dati non valido");
    }

    aggiornamento.textContent =
      "Ultimo aggiornamento dichiarato: " +
      (dati.updated_at || "non disponibile");

    if (dati.matches.length === 0) {
      stato.textContent =
        "NO BET · Nessuna partita verificata disponibile.";
      partite.textContent =
        "In attesa di una fonte calcistica verificata.";
    } else {
      stato.textContent =
        "DATI DA VERIFICARE · Non pubblicare pronostici automaticamente.";
      partite.textContent =
        "Elementi ricevuti: " + dati.matches.length +
        ". Mancano ancora i controlli completi di qualità.";
    }
  } catch (errore) {
    stato.textContent =
      "DATI NON VERIFICATI · Aggiornamento non riuscito.";
    partite.textContent =
      "Nessun pronostico pubblicato.";
    aggiornamento.textContent =
      "Ultimo aggiornamento verificato: non disponibile";
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
