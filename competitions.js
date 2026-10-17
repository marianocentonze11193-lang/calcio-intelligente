"use strict";
const DATA_PATH="./data/competition_data.json";
let competitionData=null;
const byId=id=>document.getElementById(id);
function safeDate(value){if(!value)return "Data non disponibile";const d=new Date(value+"T12:00:00");return Number.isNaN(d.getTime())?value:d.toLocaleDateString("it-IT",{weekday:"short",day:"2-digit",month:"short",year:"numeric"});}
function fmt(value){return value===null||value===undefined||value===""?"—":Number.isInteger(value)?String(value):Number(value).toLocaleString("it-IT",{maximumFractionDigits:1});}
function optionLabel(code,meta){return (meta?.name||code)+" · "+(meta?.country||"");}
async function loadData(){
 const status=byId("data-status");status.textContent="Lettura dell'ultimo archivio pubblicato…";
 try{
  const response=await fetch(DATA_PATH+"?t="+Date.now(),{cache:"no-store"});
  if(!response.ok)throw new Error("HTTP "+response.status);
  const data=await response.json();
  if(!data||!Array.isArray(data.fixtures)||typeof data.standings!=="object")throw new Error("Struttura del file non valida");
  competitionData=data;
  const summary=data.summary||{};
  const updated=data.updated_at?new Date(data.updated_at).toLocaleString("it-IT"):"non disponibile";
  const age=data.updated_at?(Date.now()-new Date(data.updated_at).getTime())/3600000:Infinity;
  status.textContent="Ultimo aggiornamento: "+updated+". "+summary.fixtures_total+" partite archiviate, "+summary.fixtures_completed+" concluse, "+summary.standings_available+" classifiche disponibili su "+summary.competitions_configured+" competizioni configurate."+(age>36?" ATTENZIONE: archivio più vecchio di 36 ore.":"");
  const coverageList=byId("coverage-list");coverageList.replaceChildren();
  const coverageEntries=Object.entries(data.coverage||{}).sort((a,b)=>labelFor(a[0]).localeCompare(labelFor(b[0]),"it"));
  for(const [code,diag] of coverageEntries){
   const line=document.createElement("p");line.className="muted";
   const count=diag.events??0;const source=diag.source||"fonte non indicata";
   const state=diag.status==="loaded"||diag.status==="complete_window"?"Acquisito":diag.status==="partial"?"Parziale":"Non aggiornato";
   line.textContent=labelFor(code)+": "+state+" · "+count+" partite · "+source+(diag.error?" · "+diag.error:"")+(diag.chunks_failed?.length?" · "+diag.chunks_failed.length+" intervalli non recuperati":"");
   coverageList.append(line);
  }
  const codes=[...new Set([...Object.keys(data.coverage||{}),...Object.keys(data.standings||{})])].sort((a,b)=>labelFor(a).localeCompare(labelFor(b),"it"));
  const cal=byId("calendar-competition"),tab=byId("table-competition"),oldCal=cal.value,oldTab=tab.value;
  cal.replaceChildren(new Option("Tutte le competizioni",""));
  tab.replaceChildren(new Option("Seleziona una competizione",""));
  for(const code of codes){cal.add(new Option(labelFor(code),code));if(data.standings[code])tab.add(new Option(labelFor(code),code));}
  cal.value=codes.includes(oldCal)?oldCal:"";tab.value=Object.prototype.hasOwnProperty.call(data.standings,oldTab)?oldTab:(tab.options.length>1?tab.options[1].value:"");
  renderCalendar();renderTable();
 }catch(error){status.textContent="DATI NON DISPONIBILI · "+(error.message||"Errore di lettura")+". L'archivio verrà riprovato al prossimo aggiornamento.";}
}
function labelFor(code){const row=competitionData?.standings?.[code];if(row)return (row.competition||code)+" · "+(row.country||"");const item=(competitionData?.fixtures||[]).find(x=>x.competition_code===code);return item?(item.competition||code)+" · "+(item.country||""):code;}
function renderCalendar(){
 if(!competitionData)return;
 const code=byId("calendar-competition").value,period=byId("calendar-period").value,now=new Date(),today=[now.getFullYear(),String(now.getMonth()+1).padStart(2,"0"),String(now.getDate()).padStart(2,"0")].join("-");
 let rows=competitionData.fixtures.filter(x=>(!code||x.competition_code===code));
 if(period==="upcoming")rows=rows.filter(x=>x.date>=today&&x.status!=="completed").sort((a,b)=>(a.date+a.kickoff).localeCompare(b.date+b.kickoff));
 else if(period==="completed")rows=rows.filter(x=>x.status==="completed").sort((a,b)=>(b.date+b.kickoff).localeCompare(a.date+a.kickoff));
 else rows.sort((a,b)=>(a.date+a.kickoff).localeCompare(b.date+b.kickoff));
 const max=period==="all"?600:300;
 byId("calendar-status").textContent=rows.length+" partite trovate."+(rows.length>max?" Mostrate le prime "+max+"; filtra per competizione per consultare il resto.":"");
 const list=byId("calendar-list");list.replaceChildren();
 if(!rows.length){list.textContent="Nessuna partita disponibile per questi filtri. Controlla lo stato della competizione qui sopra.";return;}
 for(const match of rows.slice(0,max)){
  const card=document.createElement("article");card.className="fixture";
  const date=document.createElement("div");date.className="fixture-date";date.textContent=safeDate(match.date)+(match.kickoff?" · "+match.kickoff:"");
  const middle=document.createElement("div");const teams=document.createElement("div");teams.className="fixture-teams";teams.textContent=match.home_team+" — "+match.away_team;
  const meta=document.createElement("div");meta.className="fixture-meta";meta.textContent=match.competition+" · "+match.source+" · "+(match.status==="completed"?"Conclusa":match.status==="in_progress"?"In corso":"Programmata");middle.append(teams,meta);
  const score=document.createElement("div");score.className="score";score.textContent=match.status==="completed"?(match.home_goals+" - "+match.away_goals):"vs";
  card.append(date,middle,score);list.append(card);
 }
}
function renderTable(){
 if(!competitionData)return;
 const code=byId("table-competition").value,wrap=byId("table-list"),status=byId("table-status");wrap.replaceChildren();
 const table=competitionData.standings?.[code];
 if(!table){status.textContent="Classifica non disponibile per la competizione selezionata.";return;}
 const diag=table.diagnostics||{},stamp=table.updated_at?new Date(table.updated_at).toLocaleString("it-IT"):"non disponibile";
 status.textContent=(diag.status==="computed_from_results"?"Classifica calcolata dai risultati":diag.status==="available"?"Classifica acquisita dalla fonte":diag.status==="partial"?"ATTENZIONE · Classifica parziale":"ATTENZIONE · Classifica non aggiornata")+" · stagione "+table.season+" · "+table.rows.length+" squadre · fonte "+(diag.source||"non indicata")+" · aggiornamento "+stamp+(diag.refresh_error?" · ultimo errore: "+diag.refresh_error:"");
 const groups={};for(const row of table.rows||[])(groups[row.group||table.competition]??=[]).push(row);
 for(const [groupName,rows] of Object.entries(groups)){
  const heading=document.createElement("h3");heading.className="group-title";heading.textContent=groupName;wrap.append(heading);
  const container=document.createElement("div");container.className="table-wrap";const tableEl=document.createElement("table");
  const thead=document.createElement("thead"),tr=document.createElement("tr");
  for(const col of ["Pos","Squadra","PG","V","N","P","GF","GS","DR","Pt"]){const th=document.createElement("th");th.textContent=col;tr.append(th);}thead.append(tr);tableEl.append(thead);
  const tbody=document.createElement("tbody");
  rows.sort((a,b)=>(a.position??999)-(b.position??999)||String(a.team).localeCompare(String(b.team),"it"));
  for(const row of rows){const line=document.createElement("tr");const values=[fmt(row.position),row.team,fmt(row.played),fmt(row.wins),fmt(row.draws),fmt(row.losses),fmt(row.goals_for),fmt(row.goals_against),fmt(row.goal_difference),fmt(row.points)];
   values.forEach((value,index)=>{const td=document.createElement("td");td.textContent=value;if(index===1)td.style.textAlign="left";line.append(td);});tbody.append(line);}
  tableEl.append(tbody);container.append(tableEl);wrap.append(container);
 }
}
document.addEventListener("DOMContentLoaded",()=>{byId("reload").addEventListener("click",loadData);byId("calendar-competition").addEventListener("change",renderCalendar);byId("calendar-period").addEventListener("change",renderCalendar);byId("table-competition").addEventListener("change",renderTable);loadData();});
