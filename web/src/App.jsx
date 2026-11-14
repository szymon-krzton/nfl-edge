import {useEffect,useMemo,useState} from "react";
const get=u=>fetch(u).then(r=>r.ok?r.json():Promise.reject(u));
const POS=["QB","RB","WR","TE"];
const TABS={
  QB:[["passing_yards","Pass yds"],["passing_tds","Pass TD"],["completions","Completions"],["attempts","Attempts"],["rushing_yards","Rush yds"],["passing_interceptions","INT"]],
  RB:[["rushing_yards","Rush yds"],["carries","Carries"],["receptions","Receptions"],["receiving_yards","Rec yds"],["targets","Targets"],["td","TD"]],
  WR:[["receiving_yards","Rec yds"],["receptions","Receptions"],["targets","Targets"],["td","TD"],["rushing_yards","Rush yds"]]};
TABS.TE=TABS.WR;
const RANGES=[["prev","Poprzedni sezon"],["cur","Obecny sezon"],["h2h","H2H"],["l5","L5"],["l10","L10"]];
const MAIN={QB:["attempts","completions","passing_yards","passing_tds","rushing_yards"],RB:["carries","rushing_yards","targets","receptions","receiving_yards"],
  WR:["targets","receptions","receiving_yards","receiving_tds"],TE:["targets","receptions","receiving_yards","receiving_tds"]};
const COVS=["MAN","ZONE","COVER_0","COVER_1","COVER_2","2_MAN","COVER_3","COVER_4","COVER_6","OTHER"];
const pc1=v=>v==null?"–":`${v.toFixed(1)}%`;
const D=(s,y=0)=>s&&s.length>=10?`${+s.slice(8,10)}.${s.slice(5,7)}${y===2?`.${s.slice(0,4)}`:y===1?`.${s.slice(2,4)}`:""}`:"";
const f1=(a,b)=>b?(a/b).toFixed(1):"–";
const val=(r,k)=>k==="td"?(r.rushing_tds||0)+(r.receiving_tds||0):(r[k]||0);
const avg=(rows,c)=>rows.length?(rows.reduce((a,r)=>a+(r[c]||0),0)/rows.length).toFixed(1):"–";
const Badge=({s,inj})=>s?<span className={`badge${["Q","D","DTD"].includes(s)?" w":""}`} title={inj}>{s}</span>:null;

function Plain({head,rows}){
  return <div className="t"><table><thead><tr>{head.map(h=><th key={h}>{h.replace(/_/g," ")}</th>)}</tr></thead><tbody>
    {rows.map((r,i)=><tr key={i}>{r.map((c,j)=><td key={j}>{c}</td>)}</tr>)}</tbody></table></div>;
}

function Chart({data,line,empty}){
  const W=720,H=270,L=34,R=8,T=22,B=44,n=data.length;
  if(!n)return <div className="mu" style={{aspectRatio:"720 / 270",display:"grid",placeItems:"center",border:"1px dashed var(--ln)",borderRadius:8}}>{empty}</div>;
  const base=Math.max(1,...data.map(d=>d.v),line||0),mx=base*1.15,iw=W-L-R,bw=Math.min(54,iw/n*.62);
  const y=v=>T+(H-T-B)*(1-v/mx),x=i=>L+iw/n*(i+.5);
  return <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Wykres wyników w kolejnych meczach">
    {[0,.5,1].map(f=>{const t=Math.round(base*f*10)/10;return <g key={f}><line x1={L} x2={W-R} y1={y(t)} y2={y(t)} stroke="var(--ln)"/>
      <text x={L-6} y={y(t)+4} textAnchor="end" fontSize="11" fill="var(--mu)">{t}</text></g>})}
    {data.map((d,i)=><g key={i}>
      <rect x={x(i)-bw/2} y={y(d.v)} width={bw} height={Math.max(1,H-B-y(d.v))} rx="3" fill={line==null||d.v>line?"var(--ac)":"#5b6b7f"}/>
      <text x={x(i)} y={y(d.v)-6} textAnchor="middle" fontSize="12" fontWeight="600" fill="var(--tx)">{d.v}</text>
      <text x={x(i)} y={H-B+16} textAnchor="middle" fontSize="11" fill="var(--mu)">{d.l1}</text>
      <text x={x(i)} y={H-B+30} textAnchor="middle" fontSize="10" fill="var(--mu)">{d.l2}</text></g>)}
    {line!=null&&<g><line x1={L} x2={W-R} y1={y(line)} y2={y(line)} stroke="var(--warn)" strokeDasharray="5 4"/>
      <text x={W-R} y={y(line)-4} textAnchor="end" fontSize="11" fill="var(--warn)">linia {line}</text></g>}
  </svg>;
}

const TS=s=>new Date(s).toLocaleString("pl-PL",{day:"numeric",month:"numeric",hour:"2-digit",minute:"2-digit"});

function GameOdds({gl,gh}){
  if(!gl)return null;
  const sg=n=>n>0?`+${n}`:`${n}`,parts=[];
  const op=(now,first,fmt)=>first!=null&&first!==now?` (otwarcie: ${fmt(first)})`:"";
  if(gl.spread)parts.push("spread "+Object.entries(gl.spread).map(([t,x])=>`${t} ${sg(x.line)} (${x.price})${op(x.line,gh?.spread?.[t]?.[0]?.[1],sg)}`).join(" / "));
  if(gl.moneyline)parts.push("ML "+Object.entries(gl.moneyline).map(([t,x])=>`${t} ${x}${op(x,gh?.moneyline?.[t]?.[0]?.[1],v=>v)}`).join(" / "));
  if(gl.total)parts.push(`total ${gl.total.line}${op(gl.total.line,gh?.total?.[0]?.[1],v=>v)} (Over ${gl.total.over} / Under ${gl.total.under})`);
  return parts.length?<div className="mu">Superbet: {parts.join(" · ")}</div>:null;
}

function Moves({hs,td}){
  if(!hs||hs.length<2)return null;
  const f=hs[0],l=hs[hs.length-1],d=l[1]-f[1];
  const ch=td?`kurs ${f[1]} → ${l[1]}`:`linia ${f[1]} → ${l[1]}${d?` (${d>0?"+":""}${d.toFixed(1)})`:""}`;
  return <details style={{margin:"0 0 8px"}}><summary className="mu" style={{cursor:"pointer"}}>Ruch linii od otwarcia rynku: {ch} · {hs.length} zmian</summary>
    <div style={{maxHeight:260,overflowY:"auto"}}><Plain head={td?["Czas","Kurs"]:["Czas","Linia","Over","Under"]} rows={hs.map(r=>[TS(r[0]),...r.slice(1)])}/></div></details>;
}

function OddsChip({o,hs}){
  const b=v=><b style={{color:"var(--tx)"}}>{v}</b>;
  if(o.yes!=null)return <><p className="mu" style={{margin:"8px 0"}}>Superbet: anytime TD {b(o.yes)}</p><Moves hs={hs} td/></>;
  const x=1/o.over,y=1/o.under;
  return <><p className="mu" style={{margin:"8px 0"}}>Superbet: linia {b(o.line)} · Over {b(o.over)} · Under {b(o.under)} · szansa Over bez marży {b(`${(x/(x+y)*100).toFixed(1)}%`)}</p><Moves hs={hs}/></>;
}

function ChartBlock({p,log,g,opp,odds,hist}){
  const tabs=TABS[p.pos]||TABS.WR;
  const [k,setK]=useState(tabs[0][0]),[rg,setRg]=useState("cur"),[line,setLine]=useState("");
  const o=odds?.players?.[p.player_id]?.[k],hs=hist?.[g.game_id]?.players?.[p.player_id]?.[k];
  useEffect(()=>{setLine(o&&o.line!=null?String(o.line):"")},[k,o?.line]);
  const rows=useMemo(()=>rg==="prev"?log.filter(r=>r.season===g.season-1):rg==="cur"?log.filter(r=>r.season===g.season)
    :rg==="h2h"?log.filter(r=>r.opponent_team===opp):rg==="l5"?log.slice(-5):log.slice(-10),[log,rg,g,opp]);
  const multi=new Set(rows.map(r=>r.season)).size>1;
  const data=rows.map(r=>({v:val(r,k),l1:r.opponent_team,l2:D(r.date,multi?1:0)||`T${r.week}`}));
  const vs=data.map(d=>d.v),n=vs.length,s=[...vs].sort((a,b)=>a-b);
  const mean=n?vs.reduce((a,b)=>a+b,0)/n:0,med=n?(n%2?s[(n-1)/2]:(s[n/2-1]+s[n/2])/2):0;
  const ln=parseFloat(String(line).replace(",",".")),L=isFinite(ln)?ln:null,over=L==null?0:vs.filter(v=>v>L).length;
  return <section className="card"><h2>Wyniki w meczach <small>{tabs.find(t=>t[0]===k)[1]}</small></h2>
    <div className="chips">{tabs.map(([key,nm])=><button key={key} className="tab" aria-pressed={k===key} onClick={()=>setK(key)}>{nm}</button>)}</div>
    {o&&<OddsChip o={o} hs={hs}/>}
    <Chart data={data} line={L} empty={rg==="h2h"?"Brak bezpośredniego meczu":"Brak meczów w wybranym zakresie"}/>
    <div className="chips">{RANGES.map(([key,nm])=><button key={key} className="chip" aria-pressed={rg===key} onClick={()=>setRg(key)}>{nm}</button>)}
      <label className="mu" style={{marginLeft:"auto"}}>Linia <input inputMode="decimal" placeholder="np. 62.5" value={line} onChange={e=>setLine(e.target.value)}/></label></div>
    <div className="stat"><div><span className="mu">Mecze</span><b>{n}</b></div><div><span className="mu">Średnia</span><b>{n?mean.toFixed(1):"–"}</b></div>
      <div><span className="mu">Mediana</span><b>{n?med:"–"}</b></div><div><span className="mu">Max</span><b>{n?s[n-1]:"–"}</b></div><div><span className="mu">Min</span><b>{n?s[0]:"–"}</b></div>
      {L!=null&&n>0&&<div><span className="mu">Over {L}</span><b>{over}/{n} ({Math.round(over/n*100)}%)</b></div>}</div>
    {rg==="h2h"&&<p className="mu" style={{fontSize:12}}>H2H: wszystkie mecze przeciwko {opp} w pobranych sezonach.</p>}
  </section>;
}

function CoverageBlock({p,opp,cov,pc}){
  if(!cov)return <section className="card"><h2>Krycia obrony</h2><p className="mu">Brak danych o coverage (FTN publikuje je po zakończeniu sezonu).</p></section>;
  const d=cov.teams?.[opp],qb=p.pos==="QB",src=qb?pc?.pass:pc?.cov;
  const sortU=ks=>[...ks].sort((x,y)=>(d?.usage?.[y]??-1)-(d?.usage?.[x]??-1));
  const order=[...sortU(COVS.slice(0,2)),...sortU(COVS.slice(2))];
  const rows=order.filter(k=>src?.[k]).map(k=>{const v=src[k],u=d?.usage?.[k];
    return qb?[k,v.dropbacks,v.att,v.cmp,v.yds,v.td,v.int,v.epa,pc1(u)]:[k,v.targets,v.rec,v.yds,f1(v.yds,v.targets),v.td,v.epa,pc1(u)]});
  return <section className="card"><h2>Krycia obrony {opp} i wyniki zawodnika <small>sezony: {cov.meta.seasons.join(", ")}</small></h2>
    <h3>Użycie coverage przez {opp} (% dropbacków, {cov.meta.def_season})</h3>
    {d?<Plain head={order} rows={[order.map(k=>pc1(d.usage?.[k]))]}/>:<p className="mu">Brak danych o tej obronie.</p>}
    <h3>{p.name} przeciwko rodzajom krycia</h3>
    {rows.length?<Plain head={qb?["Krycie","dropbacki","próby","celne","jardy","TD","INT","EPA/dropback",`% użycia ${opp}`]:["Krycie","targety","przyjęcia","jardy","jardy/target","TD","EPA/target",`% użycia ${opp}`]} rows={rows}/>
      :<p className="mu">Brak danych o coverage dla tego zawodnika.</p>}</section>;
}

function OthersBlock({p,opp,def,rank}){
  const cols=MAIN[p.pos],others=def?def.recent.filter(r=>r.position===p.pos&&r.player_display_name!==p.name):[];
  const al=def?.allowed?.[p.pos];
  return <section className="card"><h2>Inni {p.pos} przeciwko {opp} <small>ostatnie 8 meczów obrony</small></h2>
    {!def?<p className="mu">Brak danych o obronie.</p>:<>
      {al&&<><h3>Średnio oddaje pozycji {p.pos} na mecz</h3><Plain head={cols} rows={[cols.map(c=>al[c])]}/></>}
      <h3>Pojedyncze wyniki <span className="mu" style={{fontWeight:400,fontSize:13}}>(depth = pozycja w tygodniu meczu)</span></h3>
      {others.length?<Plain head={["Zawodnik","Drużyna","Depth","Data",...cols]} rows={[
        ...others.map(r=>[r.player_display_name,r.team,rank(r),D(r.date,2)||`T${r.week}`,...cols.map(c=>r[c])]),
        [<b>Średnia ({others.length})</b>,"","","",...cols.map(c=><b>{avg(others,c)}</b>)]]}/>:<p className="mu">Brak danych.</p>}</>}</section>;
}

function Rank({r}){
  const c=r<=10?"var(--bad)":r<=22?"var(--warn)":"var(--ac)";
  return <span style={{display:"inline-block",minWidth:30,textAlign:"center",padding:"1px 9px",borderRadius:999,fontWeight:700,color:c,
    background:`color-mix(in srgb, ${c} 18%, transparent)`}}>{r}</span>;
}

function RoutesBlock({p,opp,cov,pc}){
  const d=cov?.teams?.[opp],routes=Object.entries(pc?.routes||{}).sort((a,b)=>b[1].targets-a[1].targets);
  return <section className="card"><h2>Ścieżki zawodnika i obrona {opp} <small>ścieżki przy targetach</small></h2>
    {p.pos==="QB"||!routes.length?<p className="mu">Brak danych o ścieżkach dla tego zawodnika.</p>:
      <Plain head={["Ścieżka","targety","% targetów","ranking obrony","jardy/target oddane","EPA/target oddane"]} rows={routes.map(([r,v])=>{const x=d?.routes?.[r];
        return [r,v.targets,pc1(v.share),
          x?<Rank r={x.rank}/>:"–",x?x.ypt:"–",x?x.epa:"–"]})}/>}
    <p className="mu" style={{fontSize:12}}>Ranking: 1 = najlepsza obrona przeciw tej ścieżce (najniższe EPA na target). Kolory matchupu: zielony – dobry (miejsca 23–32), pomarańczowy – średni (11–22), czerwony – zły (1–10). Dane FTN obejmują ścieżkę głównego odbiorcy na akcji.</p></section>;
}

function Usage({usage,teams,depth,pick}){
  const [tab,setTab]=useState("rec"),[win,setWin]=useState(0);
  const i=tab==="rec"?0:1;
  const lab=(t,x)=>{const l=depth[t]?.[x.pos]||[],k=l.findIndex(y=>y.player_id===x.player_id);return k>=0?{r:`${x.pos}${k+1}`,s:l[k].status,inj:l[k].injury}:{r:x.pos,s:"",inj:""}};
  if(!usage)return null;
  return <section className="card"><h2>Usage zawodników {teams.join(" / ")} <small>bieżący sezon</small></h2>
    <div className="chips">{[["rec","Receiving"],["rush","Rushing"]].map(([k,n])=><button key={k} className="tab" aria-pressed={tab===k} onClick={()=>setTab(k)}>{n}</button>)}
      <span style={{width:10}}/>{[[0,"Sezon"],[5,"L5"],[3,"L3"],[1,"L1"]].map(([k,n])=><button key={n} className="chip" aria-pressed={win===k} onClick={()=>setWin(k)}>{n}</button>)}</div>
    <div className="grid">{teams.map(t=>{
      const u=usage[t];if(!u)return null;
      const ws=win?u.weeks.slice(-win):u.weeks;
      const all=u.players.filter(x=>tab==="rec"?x.pos!=="QB":true).map(x=>({...x,v:ws.reduce((s,w)=>s+(x.g[w]?.[i]||0),0)})).filter(x=>x.v>0).sort((a,b)=>b.v-a.v);
      const tot=all.reduce((s,x)=>s+x.v,0);
      const rows=all.slice(0,12).map(x=>{const l=lab(t,x);return [
        <button className="link" onClick={()=>pick(x,t,l)}>{x.name}</button>,<span className="mu">{l.r}<Badge s={l.s} inj={l.inj}/></span>,
        x.v,<span style={{display:"inline-flex",alignItems:"center",gap:8}}><span className="bar"><i style={{width:`${x.v/all[0].v*100}%`}}/></span>{(x.v/tot*100).toFixed(1)}%</span>,(x.v/ws.length).toFixed(1)]});
      return <div key={t}><h3>{t} <span className="mu" style={{fontWeight:400,fontSize:13}}>({ws.length} {ws.length===1?"mecz":"meczów"}: {D(u.dates?.[ws[0]])||`T${ws[0]}`}{ws.length>1?`–${D(u.dates?.[ws[ws.length-1]])||`T${ws[ws.length-1]}`}`:""})</span></h3>
        <Plain head={["Zawodnik","Poz.",tab==="rec"?"Targety":"Carries",tab==="rec"?"% targetów":"% carries","na mecz"]} rows={rows}/></div>})}</div>
    <p className="mu" style={{fontSize:12}}>Okno L liczone w ostatnich meczach drużyny; „na mecz" to średnia na mecz drużyny w oknie.</p></section>;
}

export default function App(){
  const [games,setGames]=useState(null),[depth,setDepth]=useState({}),[g,setG]=useState(null),[p,setP]=useState(null),[log,setLog]=useState([]),
    [def,setDef]=useState(null),[cov,setCov]=useState(null),[pc,setPc]=useState(null),[usage,setUsage]=useState(null),[odds,setOdds]=useState(null),[hist,setHist]=useState(null);
  useEffect(()=>{get("/data/schedule.json").then(s=>{setGames(s);setG(s[0]||null)}).catch(()=>setGames([]));
    get("/data/depth.json").then(setDepth).catch(()=>{});get("/data/usage.json").then(setUsage).catch(()=>{});
    get("/data/coverage/defense.json").then(setCov).catch(()=>{});get("/data/odds.json").then(setOdds).catch(()=>{});get("/data/odds_history.json").then(setHist).catch(()=>{})},[]);
  const opp=p&&g?(p.team===g.home_team?g.away_team:g.home_team):"";
  useEffect(()=>{setLog([]);setPc(null);if(!p)return;
    get(`/data/logs/${p.player_id}.json`).then(setLog).catch(()=>{});get(`/data/coverage/players/${p.player_id}.json`).then(setPc).catch(()=>{})},[p]);
  useEffect(()=>{if(opp)get(`/data/defense/${opp}.json`).then(setDef).catch(()=>setDef(null));else setDef(null)},[opp]);
  const rank=r=>{if(r.depth_rank)return `${r.position}${r.depth_rank}`;
    for(const t of [r.team,...Object.keys(depth)]){const l=depth[t]?.[r.position]||[],i=l.findIndex(x=>x.player_id===r.player_id);
      if(i>=0)return `${r.position}${i+1}`}return "–"};
  const pick=(x,team,l)=>{setP({player_id:x.player_id,name:x.name,pos:x.pos,team,status:l.s,injury:l.inj});window.scrollTo(0,0)};
  const Depth=({team})=><section className="card"><h2>{team} <small>depth chart</small></h2>{POS.map(pos=><div key={pos} style={{marginBottom:8}}><span className="mu">{pos}</span>
    <div className="chips">{(depth[team]?.[pos]||[]).map((x,i)=><button key={x.player_id} className="chip" onClick={()=>pick({...x,pos},team,{s:x.status,inj:x.injury})}>
      <span className="mu">{pos}{i+1}</span> {x.name}<Badge s={x.status} inj={x.injury}/>{x.usage!=null&&<span className="mu"> {x.usage}</span>}</button>)}</div></div>)}</section>;
  if(!games)return <main><p className="mu">Ładowanie…</p></main>;
  const footer=<footer className="mu" style={{marginTop:32,paddingTop:12,borderTop:"1px solid var(--ln)",fontSize:12}}>
    Źródła danych: statystyki, terminarze i składy – nflverse; dane o rodzajach krycia (coverage) i ścieżkach – FTN Data via nflverse, na licencji{" "}
    <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noopener noreferrer" style={{color:"var(--ac)"}}>CC BY-SA 4.0</a>; depth charty i statusy kontuzji – ESPN.
    Kursy: Superbet (PL) via OddsPapi; mogą różnić się od aktualnych na stronie bukmachera. Aplikacja ma charakter informacyjny i nie gwarantuje wyników zakładów. Hazard wiąże się z ryzykiem, 18+.</footer>;
  if(p&&g)return <main>
    <button className="back" onClick={()=>setP(null)}>← Wróć do meczu {g.away_team} @ {g.home_team}</button>
    <h1>{p.name}<Badge s={p.status} inj={p.injury}/></h1>
    <div className="mu">{p.pos} · {p.team} vs {opp} · {D(g.gameday,2)}</div>
    <GameOdds gl={odds?.games?.[g.game_id]} gh={hist?.[g.game_id]?.game}/>
    <ChartBlock key={p.player_id} p={p} log={log} g={g} opp={opp} odds={odds} hist={hist}/>
    <CoverageBlock p={p} opp={opp} cov={cov} pc={pc}/>
    <OthersBlock p={p} opp={opp} def={def} rank={rank}/>
    <RoutesBlock p={p} opp={opp} cov={cov} pc={pc}/>
    <Usage usage={usage} teams={[p.team]} depth={depth} pick={pick}/>
    {footer}</main>;
  return <main><h1>NFL Edge</h1><p className="mu">Wybierz mecz, a potem zawodnika z depth chartu.</p>
    {!games.length&&<p className="mu">Brak nadchodzących meczów w terminarzu.</p>}
    <div className="chips">{games.map(x=><button key={x.game_id} className="chip" aria-pressed={g?.game_id===x.game_id} onClick={()=>setG(x)}>{x.away_team} @ {x.home_team} <span className="mu">{D(x.gameday,2)}</span></button>)}</div>
    {g&&<div className="grid"><Depth team={g.away_team}/><Depth team={g.home_team}/></div>}{footer}</main>;
}