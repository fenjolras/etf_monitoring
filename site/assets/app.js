/* Fonctions partagées par toutes les pages : données, calculs, formats, thème des graphiques. */
const App = (() => {
  let donnees;

  async function charger() {
    if (!donnees) {
      donnees = fetch("data/prices.json").then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      });
    }
    return donnees;
  }

  function erreur(cible, e) {
    console.error(e);
    cible.innerHTML = `<p class="notice">Impossible de charger les données (${e.message}).
      Le site doit être servi par un serveur web, pas ouvert directement depuis le disque.</p>`;
  }

  // --- Dates (chaînes "AAAA-MM-JJ", comparables directement) ---

  function decaler(date, { jours = 0, mois = 0, ans = 0 }) {
    const d = new Date(`${date}T00:00:00Z`);
    const annee = d.getUTCFullYear() - ans;
    const m = d.getUTCMonth() - mois;
    // 31 mars - 1 mois = 28/29 février (et non 3 mars)
    const dernierJour = new Date(Date.UTC(annee, m + 1, 0)).getUTCDate();
    const t = Date.UTC(annee, m, Math.min(d.getUTCDate(), dernierJour)) - jours * 86400000;
    return new Date(t).toISOString().slice(0, 10);
  }

  /** Index de la dernière date <= cible, ou -1. */
  function indexAuPlusTard(dates, cible) {
    let lo = 0, hi = dates.length - 1, res = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (dates[mid] <= cible) { res = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return res;
  }

  const PERIODES = [
    ["1 jour", { jours: 1 }],
    ["1 sem.", { jours: 7 }],
    ["1 mois", { mois: 1 }],
    ["3 mois", { mois: 3 }],
    ["6 mois", { mois: 6 }],
    ["1 an", { ans: 1 }],
    ["3 ans", { ans: 3 }],
    ["5 ans", { ans: 5 }],
  ];

  /** Variation entre le dernier cours et le cours à (dernière date - période). null si historique insuffisant. */
  function variation(serie, periode) {
    const n = serie.dates.length - 1;
    const i = indexAuPlusTard(serie.dates, decaler(serie.dates[n], periode));
    return i < 0 ? null : serie.close[n] / serie.close[i] - 1;
  }

  /** Taux annualisé ; null sous un an, où l'annualisation est trompeuse. */
  function annualiser(variationTotale, jours) {
    if (jours < 365) return null;
    return Math.pow(1 + variationTotale, 365.25 / jours) - 1;
  }

  function joursEntre(a, b) {
    return Math.round((new Date(`${b}T00:00:00Z`) - new Date(`${a}T00:00:00Z`)) / 86400000);
  }

  // --- Formats ---

  const fPct = new Intl.NumberFormat("fr-FR", {
    style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1, signDisplay: "exceptZero",
  });
  const fPrix = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fTaux = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 4, maximumFractionDigits: 4 });

  const pct = (x) => (x == null || !isFinite(x) ? "—" : fPct.format(x));
  const sens = (x) => (x == null ? "" : x > 0 ? "up" : x < 0 ? "down" : "");
  const prix = (actif, v) => (actif.est_parite ? fTaux.format(v) : `${fPrix.format(v)} €`);
  const date = (s) =>
    new Date(`${s}T00:00:00Z`).toLocaleDateString("fr-FR", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" });

  const echapper = (s) =>
    String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  // --- Graphiques (Plotly) ---

  const css = (nom) => getComputedStyle(document.documentElement).getPropertyValue(nom).trim();
  const couleurSerie = (slot) => css(`--series-${slot + 1}`);
  const NB_COULEURS = 8;

  function axe() {
    return {
      gridcolor: css("--grid"), linecolor: css("--axis"), zeroline: false,
      tickfont: { color: css("--text-muted") }, fixedrange: true,
    };
  }

  function layout(extra = {}) {
    return {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: css("--font"), color: css("--text-secondary"), size: 12 },
      margin: { l: 52, r: 12, t: 8, b: 36 },
      hovermode: "x unified",
      hoverlabel: { bgcolor: css("--surface-1"), bordercolor: css("--border-strong"), font: { color: css("--text-primary") } },
      separators: ", ",
      showlegend: false,
      dragmode: false,
      ...extra,
      xaxis: { ...axe(), ...(extra.xaxis || {}) },
      yaxis: { ...axe(), ...(extra.yaxis || {}) },
    };
  }

  const PLOTLY_CONFIG = { displayModeBar: false, responsive: true };

  /** Rappelle `rendu` quand le thème clair/sombre du système change. */
  function surChangementTheme(rendu) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", rendu);
  }

  // --- Accès aux données ---

  const actif = (d, id) => d.actifs.find((a) => a.id === id);
  const actifsHorsParite = (d) => d.actifs.filter((a) => !a.est_parite);
  const derniereMaj = (d) =>
    Object.values(d.series).reduce((m, s) => (s.dates.at(-1) > m ? s.dates.at(-1) : m), "");

  function piedDePage(d) {
    const el = document.getElementById("maj");
    if (el) el.textContent = `Données au ${date(derniereMaj(d))}.`;
  }

  return {
    charger, erreur, decaler, indexAuPlusTard, PERIODES, variation, annualiser, joursEntre,
    pct, sens, prix, date, echapper, couleurSerie, NB_COULEURS, layout, PLOTLY_CONFIG,
    surChangementTheme, actif, actifsHorsParite, derniereMaj, piedDePage, css,
  };
})();
