/**
 * Relevé hebdomadaire automatique de l'onglet Historique (Sheet modèle de Portfolio Insights).
 *
 * Chaque samedi matin, ajoute une ligne : date, valeur et montant investi du PEA
 * et du CTO, lus dans l'onglet Positions (déjà calculé par les formules).
 *
 * Installation (une seule fois) : dans le Google Sheet, Extensions > Apps Script,
 * coller ce fichier, enregistrer, puis exécuter `installerDeclencheur`.
 * Pour tester tout de suite : exécuter `releveHebdo`.
 */

function releveHebdo() {
  const ss = SpreadsheetApp.getActive();
  const positions = ss.getSheetByName("Positions");
  const historique = ss.getSheetByName("Historique");
  SpreadsheetApp.flush();

  // Colonnes de Positions : D = enveloppe, G = investi €, K = valeur €
  const rows = positions.getRange(2, 1, Math.max(positions.getLastRow() - 1, 1), 11).getValues();
  const totaux = { PEA: { valeur: 0, investi: 0 }, CTO: { valeur: 0, investi: 0 } };
  for (const row of rows) {
    const enveloppe = row[3];
    if (!row[0] || !totaux[enveloppe]) continue;
    const investi = row[6], valeur = row[10];
    // Un cours GOOGLEFINANCE en erreur ferait enregistrer un relevé faux : on s'arrête
    if (typeof valeur !== "number" || typeof investi !== "number") {
      throw new Error(`Relevé annulé : valeur illisible pour ${row[0]} (${valeur})`);
    }
    totaux[enveloppe].valeur += valeur;
    totaux[enveloppe].investi += investi;
  }

  const aujourdhui = new Date();
  aujourdhui.setHours(0, 0, 0, 0);
  const derniere = historique.getLastRow();
  if (derniere > 1) {
    const derniereDate = historique.getRange(derniere, 1).getValue();
    if (derniereDate instanceof Date && derniereDate.getTime() === aujourdhui.getTime()) return; // déjà fait
  }

  const n = derniere + 1;
  historique.getRange(n, 1, 1, 8).setValues([[
    aujourdhui,
    totaux.PEA.valeur, totaux.PEA.investi,
    totaux.CTO.valeur, totaux.CTO.investi,
    `=B${n}+D${n}`, `=C${n}+E${n}`, `=F${n}/G${n}-1`,
  ]]);
}

/** À exécuter une seule fois : relevé chaque samedi entre 8h et 9h. */
function installerDeclencheur() {
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === "releveHebdo")
    .forEach((t) => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger("releveHebdo")
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.SATURDAY)
    .atHour(8)
    .create();
}
