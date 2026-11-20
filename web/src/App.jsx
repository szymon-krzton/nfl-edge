/**
 * NFL Edge - aplikacja do analizy statystyk NFL pod kątem typowania (React + Vite).
 * Cały interfejs jest w tym pliku. Dane to statyczne pliki JSON z web/public/data (generują je skrypty z ingest/),
 * wczytywane przez fetch. Widoki: ekran główny (mecz + depth charty), karta zawodnika (wykres, krycia, alignment,
 * red zone, strefy, ścieżki, usage) i podstrona meczu (alignment obron).
 */
import {useEffect,useMemo,useState} from "react";
/**
 * Pobiera JSON z adresu; przy kodzie innym niż 2xx odrzuca obietnicę (wywołanie z .catch pokazuje wtedy stan
 * „brak danych”).
 */
const get=u=>fetch(u).then(r=>r.ok?r.json():Promise.reject(u));
/** Pozycje ofensywne obsługiwane w aplikacji. */
const POS=["QB","RB","WR","TE"];
/**
 * Zakładki statystyk pod wykresem dla każdej pozycji: [klucz w logu, etykieta]. Klucz „td” to suma TD z biegu
 * i z odbioru.
 */
const TABS={
  QB:[["passing_yards","Pass yds"],["passing_tds","Pass TD"],["completions","Completions"],["attempts","Attempts"],["rushing_yards","Rush yds"],["passing_interceptions","INT"]],
  RB:[["rushing_yards","Rush yds"],["carries","Carries"],["receptions","Receptions"],["receiving_yards","Rec yds"],["targets","Targets"],["td","TD"]],
  WR:[["receiving_yards","Rec yds"],["receptions","Receptions"],["targets","Targets"],["td","TD"],["rushing_yards","Rush yds"]]};
TABS.TE=TABS.WR;
/** Zakresy meczów: poprzedni sezon, bieżący, H2H, L5, L10 (kafelki pod wykresem dodają jeszcze zakres własny). */
const RANGES=[["prev","Poprzedni sezon"],["cur","Obecny sezon"],["h2h","H2H"],["l5","L5"],["l10","L10"]];
/** Kolumny statystyk w tabeli „Inni zawodnicy” dla każdej pozycji. */
const MAIN={QB:["attempts","completions","passing_yards","passing_tds","rushing_yards"],RB:["carries","rushing_yards","targets","receptions","receiving_yards"],
  WR:["targets","receptions","receiving_yards","receiving_tds"],TE:["targets","receptions","receiving_yards","receiving_tds"]};
/** Rodzaje krycia z danych FTN (blok krycia na danych z poprzedniego sezonu), w domyślnej kolejności. */
const COVS=["MAN","ZONE","COVER_0","COVER_1","COVER_2","2_MAN","COVER_3","COVER_4","COVER_6","OTHER"];
/** Formatuje liczbę jako procent z jednym miejscem po przecinku; null daje myślnik. */
const pc1=v=>v==null?"–":`${v.toFixed(1)}%`;
/** Formatuje datę ISO jako D.MM; y=1 dodaje rok dwucyfrowy, y=2 pełny rok; pusty tekst, gdy brak daty. */
const D=(s,y=0)=>s&&s.length>=10?`${+s.slice(8,10)}.${s.slice(5,7)}${y===2?`.${s.slice(0,4)}`:y===1?`.${s.slice(2,4)}`:""}`:"";
/** Dzieli a przez b i zaokrągla do jednego miejsca po przecinku; przy b=0 zwraca myślnik (np. jardy na target). */
const f1=(a,b)=>b?(a/b).toFixed(1):"–";
/** Wartość statystyki k z wiersza logu r; dla klucza „td” suma TD z biegu i z odbioru. */
const val=(r,k)=>k==="td"?(r.rushing_tds||0)+(r.receiving_tds||0):(r[k]||0);
/** Średnia pola c po wierszach (jedno miejsce po przecinku), myślnik dla pustej listy. */
const avg=(rows,c)=>rows.length?(rows.reduce((a,r)=>a+(r[c]||0),0)/rows.length).toFixed(1):"–";
/** Plakietka statusu kontuzji: Q/D/DTD na pomarańczowo, OUT/IR na czerwono; tytuł pokazuje rodzaj urazu. */
const Badge=({s,inj})=>s?<span className={`badge${["Q","D","DTD"].includes(s)?" w":""}`} title={inj}>{s}</span>:null;

/** Prosta tabela: head to nagłówki kolumn, rows to tablica wierszy (komórki mogą być elementami JSX). */
function Plain({head,rows}){
  return <div className="t"><table><thead><tr>{head.map(h=><th key={h}>{h.replace(/_/g," ")}</th>)}</tr></thead><tbody>
    {rows.map((r,i)=><tr key={i}>{r.map((c,j)=><td key={j}>{c}</td>)}</tr>)}</tbody></table></div>;
}

/**
 * Wykres słupkowy SVG wyników w kolejnych meczach. Słupki są zielone, gdy wynik przekracza linię bukmachera
 * (przerywana), pod nimi widać przeciwnika (@ wyjazd, vs dom) i pełną datę. Kliknięcie słupka wywołuje onPick
 * (box score). Gdy brak meczów, pokazuje komunikat empty.
 */
function Chart({data,line,empty,onPick}){
  const n=data.length,W=720,H=340,L=34,R=64,T=24,slot=(W-L-R)/Math.max(n,1),fs=Math.max(7,Math.min(11,slot/5.6)),fs1=Math.max(7,Math.min(11,slot/3.2)),stag=slot<fs*5.6+2,B=stag?58:44;
  if(!n)return <div className="mu" style={{aspectRatio:"720 / 340",display:"grid",placeItems:"center",border:"1px dashed var(--ln)",borderRadius:8}}>{empty}</div>;
  const base=Math.max(1,...data.map(d=>d.v),line||0),mx=base*1.15,iw=W-L-R,bw=Math.min(64,iw/n*.62);
  const y=v=>T+(H-T-B)*(1-v/mx),x=i=>L+iw/n*(i+.5);
  return <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Wykres wyników w kolejnych meczach">
    {[0,.5,1].map(f=>{const t=Math.round(base*f*10)/10;return <g key={f}><line x1={L} x2={W-R} y1={y(t)} y2={y(t)} stroke="var(--ln)"/>
      <text x={L-6} y={y(t)+4} textAnchor="end" fontSize="11" fill="var(--mu)">{t}</text></g>})}
    {data.map((d,i)=><g key={i} className={d.gid?"barhit":undefined} role={d.gid?"button":undefined} tabIndex={d.gid?0:undefined}
      aria-label={d.gid?`Box score: ${d.l1} ${d.l2}`:undefined} onClick={()=>d.gid&&onPick&&onPick(d)}
      onKeyDown={e=>{if(d.gid&&onPick&&(e.key==="Enter"||e.key===" ")){e.preventDefault();onPick(d)}}}>
      <rect className="hit" x={x(i)-slot/2} y={T} width={slot} height={H-T-B+36} fill="transparent"/>
      <rect x={x(i)-bw/2} y={y(d.v)} width={bw} height={Math.max(1,H-B-y(d.v))} rx="3" fill={line==null||d.v>line?"var(--ac)":"#5b6b7f"}/>
      <text x={x(i)} y={y(d.v)-6} textAnchor="middle" fontSize="12" fontWeight="600" fill="var(--tx)">{d.v}</text>
      <text x={x(i)} y={H-B+16} textAnchor="middle" fontSize={fs1} fill="var(--mu)">{d.l1}</text>
      <text x={x(i)} y={H-B+30+(stag&&i%2?11:0)} textAnchor="middle" fontSize={fs} fill="var(--mu)">{d.l2}</text></g>)}
    {line!=null&&<g><line x1={L} x2={W-R} y1={y(line)} y2={y(line)} stroke="var(--warn)" strokeDasharray="5 4"/>
      <text x={W-R+6} y={y(line)+4} textAnchor="start" fontSize="11" fill="var(--warn)">linia {line}</text></g>}
  </svg>;
}

/** Formatuje znacznik czasu jako lokalną datę i godzinę (pl-PL). */
const TS=s=>new Date(s).toLocaleString("pl-PL",{day:"numeric",month:"numeric",hour:"2-digit",minute:"2-digit"});

/**
 * Linijka z kursami Superbet dla meczu: spread, moneyline i total z pierwszym pomiarem (otwarcie) oraz
 * informacją o rynkach zamkniętych lub wstrzymanych.
 */
function GameOdds({gl,gh}){
  if(!gl)return null;
  const sg=n=>n>0?`+${n}`:`${n}`,parts=[];
  const op=(now,first,fmt)=>first!=null&&first!==now?` (otwarcie: ${fmt(first)})`:"";
  if(gl.spread)parts.push("spread "+Object.entries(gl.spread).map(([t,x])=>`${t} ${sg(x.line)} (${x.price})${op(x.line,gh?.spread?.[t]?.[0]?.[1],sg)}`).join(" / "));
  if(gl.moneyline)parts.push("ML "+Object.entries(gl.moneyline).map(([t,x])=>`${t} ${x}${op(x,gh?.moneyline?.[t]?.[0]?.[1],v=>v)}`).join(" / "));
  if(gl.total)parts.push(`total ${gl.total.line}${op(gl.total.line,gh?.total?.[0]?.[1],v=>v)} (Over ${gl.total.over} / Under ${gl.total.under})`);
  if(gl.closed?.length)parts.push(`zamknięte lub wstrzymane: ${gl.closed.join(", ")}`);
  return parts.length?<div className="mu">Superbet: {parts.join(" · ")}</div>:null;
}

/** Rozwijana tabela ruchu linii zawodnika od otwarcia rynku (czas, linia, kursy Over/Under). */
function Moves({hs,td}){
  if(!hs||hs.length<2)return null;
  const f=hs[0],l=hs[hs.length-1],d=l[1]-f[1];
  const ch=td?`kurs ${f[1]} → ${l[1]}`:`linia ${f[1]} → ${l[1]}${d?` (${d>0?"+":""}${d.toFixed(1)})`:""}`;
  return <details style={{margin:"0 0 8px"}}><summary className="mu" style={{cursor:"pointer"}}>Ruch linii od otwarcia rynku: {ch} · {hs.length} zmian</summary>
    <div style={{maxHeight:260,overflowY:"auto"}}><Plain head={td?["Czas","Kurs"]:["Czas","Linia","Over","Under"]} rows={hs.map(r=>[TS(r[0]),...r.slice(1)])}/></div></details>;
}

/**
 * Podsumowanie linii Superbet dla zawodnika: linia, kursy i szansa Over bez marży (dla anytime TD sam kurs), z
 * historią ruchu linii.
 */
function OddsChip({o,hs}){
  const b=v=><b style={{color:"var(--tx)"}}>{v}</b>;
  if(o.yes!=null)return <><p className="mu" style={{margin:"8px 0"}}>Superbet: anytime TD {b(o.yes)}{o.closed&&" · linia zamykająca / wstrzymana"}</p><Moves hs={hs} td/></>;
  const x=1/o.over,y=1/o.under;
  return <><p className="mu" style={{margin:"8px 0"}}>Superbet: linia {b(o.line)} · Over {b(o.over)} · Under {b(o.under)} · szansa Over bez marży {b(`${(x/(x+y)*100).toFixed(1)}%`)}{o.closed&&" · linia zamykająca / wstrzymana"}</p><Moves hs={hs}/></>;
}

/**
 * Filtry kontekstu meczu: miejsce, rola (faworyt/underdog), total, dach i pogoda, odpoczynek, rywal dywizyjny,
 * nawierzchnia, pora meczu.
 */
const CTX=[
  ["place","Miejsce",[["home","Dom"],["away","Wyjazd"]]],
  ["role","Rola",[["fav","Faworyt"],["dog","Underdog"]]],
  ["total","Total meczu",[["low","Niski (<42)"],["mid","Średni (42–48)"],["high","Wysoki (>48)"]]],
  ["roof","Dach / pogoda",[["closed","Kopuła / zamknięty"],["open","Na zewnątrz"],["wind","Na zewnątrz, wiatr ≥15 mph"]]],
  ["rest","Odpoczynek",[["short","Krótki (≤6 dni)"],["norm","Normalny (7–8)"],["long","Długi (≥9)"]]],
  ["div","Rywal",[["div","Dywizyjny"],["non","Spoza dywizji"]]],
  ["surf","Nawierzchnia",[["grass","Trawa"],["turf","Sztuczna"]]],
  ["prime","Pora meczu",[["prime","Prime time (od 19:00 ET)"],["day","Pozostałe mecze"]]]];
/** Wartości dachu oznaczające mecz na zewnątrz. */
const OUTD=["outdoors","open"];
/**
 * Czy mecz r (wiersz logu) spełnia wszystkie ustawione filtry kontekstu c; mecze bez danych dla ustawionego
 * filtra odpadają.
 */
const ctxOk=(r,c)=>
  (!c.place||(c.place==="home"?r.home===true:r.home===false))&&
  (!c.role||(r.sp==null?false:c.role==="fav"?r.sp>0:r.sp<0))&&
  (!c.total||(r.tot==null?false:c.total==="low"?r.tot<42:c.total==="mid"?r.tot>=42&&r.tot<=48:r.tot>48))&&
  (!c.roof||(c.roof==="closed"?["dome","closed"].includes(r.roof):c.roof==="open"?OUTD.includes(r.roof):OUTD.includes(r.roof)&&(r.wind||0)>=15))&&
  (!c.rest||(r.rest==null?false:c.rest==="short"?r.rest<=6:c.rest==="norm"?r.rest>=7&&r.rest<=8:r.rest>=9))&&
  (!c.div||(r.div==null?false:c.div==="div"?r.div===1:r.div===0))&&
  (!c.surf||(r.surf==null?false:r.surf===c.surf))&&
  (!c.prime||(r.prime==null?false:c.prime==="prime"?r.prime===1:r.prime===0));

/**
 * Pasek filtrów kontekstu z przyciskami „Dopasuj do meczu” (ustawia filtry według nadchodzącego meczu) i
 * „Wyczyść”.
 */
function ContextFilter({ctx,setCtx,onMatch}){
  const on=Object.values(ctx).some(Boolean);
  return <div className="chips" style={{marginTop:6}}>
    <span className="mu">Kontekst:</span>
    {CTX.map(([k,label,opts])=><select key={k} value={ctx[k]||""} aria-label={label} onChange={e=>setCtx({...ctx,[k]:e.target.value})}>
      <option value="">{label}: dowolne</option>{opts.map(([v,t])=><option key={v} value={v}>{t}</option>)}</select>)}
    <button className="chip" onClick={onMatch} title="Ustaw filtry tak, jak wygląda nadchodzący mecz">Dopasuj do meczu</button>
    {on&&<button className="chip" onClick={()=>setCtx({})}>Wyczyść ×</button>}</div>;
}

/** Filtr składu: wybór kolegi z drużyny i tryb „Z nim” lub „Bez niego”; aktywne filtry są chipami do usunięcia. */
function RosterFilter({mates,flt,setFlt}){
  const [id,setId]=useState("");
  const add=mode=>{const m=mates.find(x=>x.id===id);if(m)setFlt([...flt.filter(f=>f.id!==id),{...m,mode}])};
  return <div className="chips" style={{marginTop:6}}>
    <span className="mu">Skład:</span>
    <select value={id} onChange={e=>setId(e.target.value)} aria-label="Zawodnik z tej samej drużyny">
      <option value="">wybierz zawodnika…</option>{mates.map(m=><option key={m.id} value={m.id}>{m.name} ({m.pos})</option>)}</select>
    <button className="chip" disabled={!id} onClick={()=>add("with")}>Z nim</button>
    <button className="chip" disabled={!id} onClick={()=>add("without")}>Bez niego</button>
    {flt.map(f=><button key={f.id} className="chip" aria-pressed="true" title="Usuń filtr" onClick={()=>setFlt(flt.filter(x=>x.id!==f.id))}>{f.mode==="with"?"z":"bez"} {f.name} ×</button>)}</div>;
}

/**
 * Okienko z uproszczonym box score'em meczu (podania, biegi, odbiory obu drużyn; sekcje wyrównane w
 * wierszach). Zawodnik z karty jest wyróżniony, zamyka Esc, krzyżyk lub kliknięcie w tło.
 */
function BoxScore({gid,pid,onClose}){
  const [b,setB]=useState(undefined);
  useEffect(()=>{get(`/data/box/${gid}.json`).then(setB).catch(()=>setB(null))},[gid]);
  useEffect(()=>{const f=e=>{if(e.key==="Escape")onClose()};window.addEventListener("keydown",f);return()=>window.removeEventListener("keydown",f)},[onClose]);
  const n=(x,c)=>x[c]||0,hi=x=>x.id===pid?<b style={{color:"var(--ac)"}}>{x.name}</b>:x.name;
  const SECS=[
    ["Podania",["Zawodnik","C/ATT","Jardy","TD","INT"],x=>n(x,"attempts")>0,"passing_yards",x=>[`${n(x,"completions")}/${n(x,"attempts")}`,n(x,"passing_yards"),n(x,"passing_tds"),n(x,"passing_interceptions")]],
    ["Biegi",["Zawodnik","Carries","Jardy","TD"],x=>n(x,"carries")>0,"rushing_yards",x=>[n(x,"carries"),n(x,"rushing_yards"),n(x,"rushing_tds")]],
    ["Odbiory",["Zawodnik","Targety","Przyjęcia","Jardy","TD"],x=>n(x,"targets")>0||n(x,"receptions")>0,"receiving_yards",x=>[n(x,"targets"),n(x,"receptions"),n(x,"receiving_yards"),n(x,"receiving_tds")]]];
  const body=()=>{
    const ts=[b.away.team,b.home.team],score=t=>(t===b.away.team?b.away.score:b.home.score)??"–";
    const rows=(t,[,,f,key,cells])=>b.players.filter(x=>x.team===t&&f(x)).sort((a,z)=>n(z,key)-n(a,key)).map(x=>[hi(x),...cells(x)]);
    return <>
      <div className="grid">{ts.map(t=><h2 key={t} style={{marginTop:6}}>{t} <span className="mu" style={{fontSize:16}}>{score(t)}</span></h2>)}</div>
      {SECS.map(s=>{const R=ts.map(t=>rows(t,s));
        return R.some(r=>r.length>0)&&<div className="grid" key={s[0]}>{ts.map((t,k)=><div key={t}>{R[k].length>0&&<><h3>{s[0]}</h3><Plain head={s[1]} rows={R[k]}/></>}</div>)}</div>})}
    </>};
  return <div className="modal-back" onClick={onClose}><div className="modal" role="dialog" aria-modal="true" aria-label="Box score" onClick={e=>e.stopPropagation()}>
    <button className="back" onClick={onClose} aria-label="Zamknij" style={{float:"right",fontSize:26,lineHeight:1,margin:0}}>×</button>
    {b===undefined?<p className="mu">Ładowanie…</p>:b===null?<p className="mu">Brak box score’u dla tego meczu. Uruchom ponownie skrypt danych.</p>:<>
      <h1 style={{fontSize:28}}>{b.away.team} @ {b.home.team}</h1>
      <div className="mu">{D(b.date,2)} · tydzień {b.week} · wynik {b.away.score??"–"} – {b.home.score??"–"}</div>
      {body()}
      <p className="mu" style={{fontSize:12}}>Uproszczony box score: tylko QB, RB, WR i TE. Zawodnik z otwartej karty jest wyróżniony.</p></>}
  </div></div>;
}

/**
 * Blok „Wyniki w meczach”: zakładki statystyk, filtry składu i kontekstu, linia Superbet, wykres, kafelki
 * trafności Over dla zakresów (sezony, H2H, L5, L10, własny) i okienko box score po kliknięciu słupka.
 */
function ChartBlock({p,log,g,opp,odds,hist,mates}){
  const tabs=TABS[p.pos]||TABS.WR;
  const [k,setK]=useState(tabs[0][0]),[rg,setRg]=useState("cur"),[line,setLine]=useState("");
  const o=odds?.players?.[p.player_id]?.[k],hs=hist?.[g.game_id]?.players?.[p.player_id]?.[k];
  useEffect(()=>{setLine(o&&o.line!=null?String(o.line):"")},[k,o?.line]);
  const [nC,setNC]=useState(20),[box,setBox]=useState(null),[flt,setFlt]=useState([]),[tl,setTl]=useState({}),[ctx,setCtx]=useState({});
  useEffect(()=>{flt.forEach(f=>{if(tl[f.id]===undefined){setTl(t=>({...t,[f.id]:null}));
    get(`/data/logs/${f.id}.json`).then(r=>setTl(t=>({...t,[f.id]:r}))).catch(()=>setTl(t=>({...t,[f.id]:[]})))}})},[flt]);
  // obecność kolegi = ma wiersz ze statystykami w tym meczu; mecze z sezonów, w których nie było go w drużynie, pomijamy
  const okRow=r=>flt.every(f=>{const t=tl[f.id];if(!t)return true;const sr=t.filter(x=>x.season===r.season&&x.team===r.team);
    if(!sr.length)return false;const here=sr.some(x=>x.week===r.week);return f.mode==="with"?here:!here});
  const ctxOn=Object.values(ctx).some(Boolean);
  const flog=(flt.length?log.filter(okRow):log).filter(r=>ctxOk(r,ctx));
  const matchCtx=()=>{ // kontekst nadchodzącego meczu: Superbet (jeśli jest), w przeciwnym razie terminarz nflverse
    const home=p.team===g.home_team,go=odds?.games?.[g.game_id];
    const nsp=g.spread_line!=null?(home?g.spread_line:-g.spread_line):null,osp=go?.spread?.[p.team]?.line,sp=osp!=null?-osp:nsp;
    const tot=go?.total?.line??g.total_line,rest=home?g.home_rest:g.away_rest;
    setCtx({place:home?"home":"away",role:sp==null||sp===0?"":sp>0?"fav":"dog",total:tot==null?"":tot<42?"low":tot<=48?"mid":"high",
      roof:g.roof==null?"":["dome","closed"].includes(g.roof)?"closed":"open",rest:rest==null?"":rest<=6?"short":rest<=8?"norm":"long",
      div:g.div_game==null?"":g.div_game===1?"div":"non",
      surf:g.surface?(/grass/i.test(g.surface)?"grass":"turf"):"",prime:g.gametime?(parseInt(g.gametime.slice(0,2))>=19?"prime":"day"):""})};
  const rowsFor=key=>key==="prev"?flog.filter(r=>r.season===g.season-1):key==="cur"?flog.filter(r=>r.season===g.season)
    :key==="h2h"?flog.filter(r=>r.opponent_team===opp):key==="l5"?flog.slice(-5):key==="cu"?flog.slice(-nC):flog.slice(-10);
  const rows=rowsFor(rg);
  const multi=new Set(rows.map(r=>r.season)).size>1;
  const data=rows.map(r=>({v:val(r,k),l1:`${r.home==null?"":r.home?"vs ":"@ "}${r.opponent_team}`,l2:D(r.date,2)||`T${r.week}/${r.season}`,gid:r.gid}));
  const vs=data.map(d=>d.v),n=vs.length,s=[...vs].sort((a,b)=>a-b);
  const mean=n?vs.reduce((a,b)=>a+b,0)/n:0,med=n?(n%2?s[(n-1)/2]:(s[n/2-1]+s[n/2])/2):0;
  const ln=parseFloat(String(line).replace(",",".")),L=isFinite(ln)?ln:null,over=L==null?0:vs.filter(v=>v>L).length;
  return <section className="card"><h2>Wyniki w meczach <label className="mu" style={{fontSize:13,fontWeight:400,fontFamily:"Inter,sans-serif"}}>Linia <input inputMode="decimal" placeholder="np. 62.5" value={line} onChange={e=>setLine(e.target.value)}/></label></h2>
    <div className="chips">{tabs.map(([key,nm])=><button key={key} className="tab" aria-pressed={k===key} onClick={()=>setK(key)}>{nm}</button>)}</div>
    <RosterFilter mates={mates||[]} flt={flt} setFlt={setFlt}/>
    <ContextFilter ctx={ctx} setCtx={setCtx} onMatch={matchCtx}/>
    {o&&<OddsChip o={o} hs={hs}/>}
    <Chart data={data} line={L} onPick={d=>setBox(d.gid)} empty={rg==="h2h"?"Brak bezpośredniego meczu":"Brak meczów w wybranym zakresie"}/>
    <div className="chips" style={{justifyContent:"space-between"}}>
      <span className="mu">{L!=null?`Kafelki: mecze ponad linią ${L} (Over)`:"Wpisz linię, aby zobaczyć trafność Over w każdym zakresie"}</span>
      {rg==="cu"&&<label className="mu">Liczba meczów <input type="number" min="1" max="99" value={nC} onChange={e=>setNC(Math.max(1,Math.min(99,parseInt(e.target.value)||1)))}/></label>}</div>
    <div className="tiles">{[["prev",`Sezon ${g.season-1}`],["cur",`Sezon ${g.season}`],["h2h","H2H"],["l5","L5"],["l10","L10"],["cu",null]].map(([key,label])=>{
      const vs=rowsFor(key).map(r=>val(r,k)),n=vs.length,hit=L==null?null:vs.filter(v=>v>L).length,pct=hit==null||!n?null:hit/n*100;
      const mix=pct==null?null:`color-mix(in srgb, ${pct>=50?"var(--ac)":"var(--bad)"} ${Math.round(10+Math.abs(pct-50)*.7)}%, var(--card2))`;
      const main=!n?"–":L!=null?`${hit}/${n}`:(vs.reduce((s,v)=>s+v,0)/n).toFixed(1),sub=!n?"":L!=null?`${Math.round(pct)}%`:"";
      const pick=()=>setRg(key);
      return <div key={key} role="button" tabIndex={0} aria-pressed={rg===key} className={`tile${n?"":" empty"}`} style={mix?{background:mix}:undefined}
        onClick={pick} onKeyDown={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();pick()}}}>
        <small style={key==="cu"?{color:"#b794f4"}:undefined}>{key==="cu"?`L${nC} · własne`:label}</small>
        <b>{main}</b><span className="mu">{sub||"\u00a0"}</span></div>})}</div>
    <p className="mu" style={{fontSize:12,margin:"4px 0 0"}}>Kliknij słupek, aby zobaczyć box score meczu.{rg==="h2h"?` H2H: wszystkie mecze przeciwko ${opp} w pobranych sezonach.`:""}</p>
    {(flt.length>0||ctxOn)&&<p className="mu" style={{fontSize:12,margin:"4px 0 0"}}>Filtry: {flog.length} z {log.length} meczów spełnia warunki.{flt.length>0?" Obecność = zawodnik zapisał jakąkolwiek statystykę w meczu; mecze z sezonów, w których nie grał w tej drużynie, są pominięte.":""}{ctxOn?" Spread, total, dach, nawierzchnia, pora meczu i odpoczynek pochodzą z terminarza nflverse (linie zamykające); mecze bez tych danych są pomijane.":""}</p>}
    {box&&<BoxScore gid={box} pid={p.player_id} onClose={()=>setBox(null)}/>}
  </section>;
}

/** Nazwa krycia w formacie „Cover 1”: spacje zamiast podkreślników, tylko pierwsza litera wielka. */
const cname=k=>{const s=k.replace(/_/g," ").toLowerCase();return s.charAt(0).toUpperCase()+s.slice(1)};

/**
 * Blok krycia na danych FTN z poprzedniego sezonu (dla QB i zawodników bez danych Gridiris): przełącznik
 * Man/Zone oraz Top 4 krycia obrony rywala.
 */
function CoverageBlock({p,opp,cov,pc}){
  const [mode,setMode]=useState("mz");
  if(!cov)return <section className="card"><h2>Krycia obrony</h2><p className="mu">Brak danych o coverage (FTN publikuje je po zakończeniu sezonu).</p></section>;
  const d=cov.teams?.[opp],qb=p.pos==="QB",src=qb?pc?.pass:pc?.cov,use=k=>d?.usage?.[k],byUse=ks=>[...ks].sort((x,y)=>(use(y)??-1)-(use(x)??-1));
  const top=byUse(COVS.slice(2).filter(k=>k!=="OTHER")).slice(0,4);
  const keys=mode==="mz"?byUse(["ZONE","MAN"]).filter(k=>src?.[k]):top;
  const rows=keys.map(k=>{const v=src?.[k],u=use(k);
    if(!v)return [cname(k),...Array(qb?7:6).fill("–"),pc1(u)];
    return qb?[cname(k),v.dropbacks,v.att,v.cmp,v.yds,v.td,v.int,v.epa,pc1(u)]:[cname(k),v.targets,v.rec,v.yds,f1(v.yds,v.targets),v.td,v.epa,pc1(u)]});
  return <section className="card"><h2>Krycia obrony {opp} i wyniki zawodnika <small>sezony: {cov.meta.seasons.join(", ")}</small></h2>
    <div className="chips">
      <button className="chip" aria-pressed={mode==="mz"} onClick={()=>setMode("mz")}>Man / Zone</button>
      <button className="chip" aria-pressed={mode==="top"} onClick={()=>setMode("top")}>Top 4 krycia {opp}</button></div>
    {rows.length?<Plain head={qb?["Krycie","dropbacki","próby","celne","jardy","TD","INT","EPA/dropback",`% użycia ${opp}`]:["Krycie","targety","przyjęcia","jardy","jardy/target","TD","EPA/target",`% użycia ${opp}`]} rows={rows}/>
      :<p className="mu">Brak danych o coverage dla tego zawodnika.</p>}
    <p className="mu" style={{fontSize:12}}>Dane FTN o rodzajach krycia pojawiają się dopiero po zakończeniu sezonu, więc to ostatni pełny sezon. Dane z bieżącego sezonu są w bloku „Strefy targetów".</p></section>;
}

/**
 * Red zone i linia bramkowa: targety, biegi i okazje zawodnika (oraz jego udział w drużynie) w strefach do
 * 20/10/5 jardów, TD, okna Sezon/L5/L3 i skuteczność obrony rywala z rankingiem.
 */
function RedZoneBlock({p,opp,rz,usage}){
  const [win,setWin]=useState(0);
  if(!rz)return <section className="card"><h2>Red zone</h2><p className="mu">Brak danych o red zone. Uruchom ponownie skrypt danych.</p></section>;
  const weeks=usage?.[p.team]?.weeks||[],ws=win?weeks.slice(-win):weeks;
  const me=rz.players?.[p.player_id]?.g,tm=rz.teams?.[p.team]?.g;
  const sum=(g,i)=>ws.reduce((s,w)=>s+(g?.[w]?.[i]||0),0),sh=(a,b)=>b?pc1(a/b*100):"–";
  const row=(label,ti,ci)=>{const t=sum(me,ti),c=sum(me,ci),tt=sum(tm,ti),tc=sum(tm,ci);return [label,t,sh(t,tt),c,sh(c,tc),t+c,sh(t+c,tt+tc)]};
  const tdr=sum(me,6),tdc=sum(me,7),dz=rz.defense?.[opp],z=dz?.z20,z5=dz?.z5;
  const dr=(label,n,td,rk)=>[label,n,td,n?pc1(td/n*100):"–",rk?<Rank r={rk}/>:"–"];
  return <section className="card"><h2>Red zone i linia bramkowa <small>sezon {rz.meta.season}, do tygodnia {rz.meta.through_week}</small></h2>
    <div className="chips">{[[0,"Sezon"],[5,"L5"],[3,"L3"]].map(([k,n])=><button key={n} className="chip" aria-pressed={win===k} onClick={()=>setWin(k)}>{n}</button>)}</div>
    <Plain head={["Strefa","targety","% targetów drużyny","biegi","% biegów drużyny","okazje","% okazji"]}
      rows={[row("Red zone (do 20 jardów)",0,1),row("Do 10 jardów",2,3),row("Do 5 jardów",4,5)]}/>
    <p className="mu" style={{margin:"8px 0"}}>TD z akcji rozpoczętych w red zone: <b style={{color:"var(--tx)"}}>{tdr+tdc}</b> ({tdr} z podania, {tdc} z biegu) w {ws.length} {ws.length===1?"meczu":"meczach"} drużyny.</p>
    <h3>Obrona {opp} w red zone</h3>
    {z?<Plain head={["Akcje","liczba","TD","TD %","ranking obrony"]} rows={[
      dr("Podania (do 20 jardów)",z.pa,z.ptd,z.rank_p),dr("Biegi (do 20 jardów)",z.ra,z.rtd,z.rank_r),
      dr("Razem (do 20 jardów)",z.pa+z.ra,z.ptd+z.rtd,z.rank_all),...(z5?[dr("Razem (do 5 jardów)",z5.pa+z5.ra,z5.ptd+z5.rtd,z5.rank_all)]:[])]}/>
      :<p className="mu">Za mało akcji obrony w red zone, żeby policzyć ranking.</p>}
    {z&&<p className="mu" style={{margin:"8px 0 0"}}>Obrona {opp} broni w red zone {sh(z.pa,z.pa+z.ra)} podań i {sh(z.ra,z.pa+z.ra)} biegów.</p>}
    <p className="mu" style={{fontSize:12}}>Okno L liczone w ostatnich meczach drużyny. Ranking: 1 = najlepsza obrona (najmniej TD na akcję); kolory jak przy ścieżkach. Udziały liczone od targetów i biegów drużyny w tej strefie; bez klęknięć, spike’ów i prób na 2 punkty.</p></section>;
}

/** Ustawienia przed snapem (alignment) z Gridiris: [klucz, etykieta]. */
const AL=[["slot","Slot"],["wide","Wide"],["tight","Tight (inline)"],["backfield","Backfield"]];
/** Etykieta krycia z Gridiris (ZONE -> Zone, MAN -> Man). */
const gname=k=>k==="ZONE"?"Zone":k==="MAN"?"Man":k;

/** Adnotacja o źródle i próbce danych Gridiris (sezon, liczba meczów, mecze zawodnika). */
function GiMeta({gd,gp}){
  return <p className="mu" style={{fontSize:12,margin:"0 0 8px"}}>Gridiris (dane NFL Next Gen Stats): sezon {gd.meta.season}, {gd.meta.games} meczów (do tygodnia {gd.meta.through_week}); zawodnik w {gp.games} z nich.</p>;
}

/**
 * Alignment zawodnika (Gridiris): % snapów w slocie, wide, tight i backfield, trasy, targety, jardy, ranking
 * obrony rywala w danym ustawieniu, udział w trasach drużyny i podział na stronę boiska.
 */
function AlignmentBlock({p,opp,gd,gp}){
  if(!gd||!gp)return <section className="card"><h2>Alignment</h2><p className="mu">Brak danych Gridiris dla tego zawodnika. Zaimportuj mecze skryptem ingest/gridiris_import.py, zacommituj pliki z ingest/gridiris i uruchom odświeżenie danych.</p></section>;
  const d=gd.teams?.[opp]?.al||{},tot=gp.snaps||0,tt=Object.values(gp.al).reduce((s,c)=>s+c.t,0);
  const rows=AL.filter(([k])=>gp.al[k]).map(([k,n])=>{const c=gp.al[k],x=d[k];
    return [n,<span style={{display:"inline-flex",alignItems:"center",gap:8}}><span className="bar"><i style={{width:`${c.n/tot*100}%`}}/></span>{pc1(c.n/tot*100)}</span>,
      c.r,c.t,tt?pc1(c.t/tt*100):"–",c.yds,c.na?(c.sa/c.na).toFixed(1):"–",x?.rank?<Rank r={x.rank}/>:"–"]});
  const side=["left","right"].filter(k=>gp.side[k]).map(k=>{const c=gp.side[k];return [k==="left"?"Lewa":"Prawa",pc1(c.n/tot*100),c.r,c.t,c.yds]});
  return <section className="card"><h2>Alignment i strony boiska <small>ustawienie przed snapem w podaniach</small></h2>
    <GiMeta gd={gd} gp={gp}/>
    <p className="mu" style={{margin:"0 0 8px"}}>Udział w trasach: <b style={{color:"var(--tx)"}}>{gp.tp?pc1(gp.routes/gp.tp*100):"–"}</b> podań drużyny ({gp.routes} tras w {gp.tp} podaniach).</p>
    <Plain head={["Ustawienie","% snapów","trasy","targety","% targetów","jardy","śr. separacja",`ranking obrony ${opp}`]} rows={rows}/>
    <h3>Strona boiska</h3>
    <Plain head={["Strona","% snapów","trasy","targety","jardy"]} rows={side}/>
    <p className="mu" style={{fontSize:12}}>Ranking: 1 = najlepsza obrona (najmniej oddanych jardów na trasę, min. 15 tras, liczony gdy próbkę ma co najmniej 8 obron); kolory jak przy ścieżkach. Tight oznacza ustawienie w linii (inline), także dla zawodników innych pozycji.</p></section>;
}

/**
 * Krycia na bieżących danych Gridiris: wyniki zawodnika wobec Man/Zone albo Top 4 krycia obrony rywala wraz z
 * procentem ich użycia.
 */
function CoverageGI({p,opp,gd,gp}){
  const [mode,setMode]=useState("mz");
  const d=gd.teams?.[opp],use=k=>d?.usage?.[k],byUse=ks=>[...ks].sort((x,y)=>(use(y)??-1)-(use(x)??-1));
  const top=byUse(["Cover 0","Cover 1","Cover 2","2-Man","Cover 3","Cover 4","Cover 6"]).slice(0,4);
  const keys=mode==="mz"?byUse(["ZONE","MAN"]):top;
  const rows=keys.map(k=>{const c=gp.cv[k];return c?[gname(k),c.r,c.t,c.rec,c.yds,c.td,pc1(use(k))]:[gname(k),...Array(5).fill("–"),pc1(use(k))]});
  return <section className="card"><h2>Krycia obrony {opp} i wyniki zawodnika <small>Gridiris, bieżący sezon</small></h2>
    <GiMeta gd={gd} gp={gp}/>
    <div className="chips">
      <button className="chip" aria-pressed={mode==="mz"} onClick={()=>setMode("mz")}>Man / Zone</button>
      <button className="chip" aria-pressed={mode==="top"} onClick={()=>setMode("top")}>Top 4 krycia {opp}</button></div>
    <Plain head={["Krycie","trasy","targety","przyjęcia","jardy","TD",`% użycia ${opp}`]} rows={rows}/>
    <p className="mu" style={{fontSize:12}}>Rodzaj krycia jest szacowany przez Gridiris (est.); część podań jest oznaczona jako niejasna lub niesklasyfikowana i nie wchodzi do powyższych kategorii. Man = Cover 0/1 i 2-Man, Zone = Cover 2/3/4/6.</p></section>;
}

/**
 * Ścieżki zawodnika (Gridiris): udział każdej ścieżki w jego trasach, targety, przyjęcia, jardy i ranking
 * obrony rywala wobec tej ścieżki.
 */
function RoutesGI({p,opp,gd,gp}){
  const d=gd.teams?.[opp]?.rt||{},tot=Object.values(gp.rt).reduce((s,c)=>s+c.r,0);
  const rows=Object.entries(gp.rt).sort((a,b)=>b[1].r-a[1].r).map(([k,c])=>{const x=d[k];
    return [k,c.r,pc1(c.r/tot*100),c.t,c.rec,c.yds,x?.rank?<Rank r={x.rank}/>:"–"]});
  return <section className="card"><h2>Ścieżki zawodnika i obrona {opp} <small>Gridiris, bieżący sezon</small></h2>
    <GiMeta gd={gd} gp={gp}/>
    {rows.length?<Plain head={["Ścieżka","trasy","% tras","targety","przyjęcia","jardy",`ranking obrony ${opp}`]} rows={rows}/>:<p className="mu">Brak tras zawodnika w zaimportowanych meczach.</p>}
    <p className="mu" style={{fontSize:12}}>Trasy to wszystkie ścieżki zawodnika w podaniach (nie tylko targety). Ranking: 1 = najlepsza obrona (najmniej jardów na trasę; min. 15 tras); kolory jak wcześniej.</p></section>;
}

/** Kolor tła komórki zależny od rankingu obrony (czerwony do 10. miejsca, pomarańczowy do 22., dalej zielony). */
const tint=r=>r==null?null:`color-mix(in srgb, ${r<=10?"var(--bad)":r<=22?"var(--warn)":"var(--ac)"} 38%, var(--card2))`;

/**
 * Podstrona meczu: dwa boxy z alignmentem obron (gdzie przeciekają) i lista zawodników obu drużyn z odsetkiem
 * snapów w każdym ustawieniu, kolorowanym rankingiem obrony rywala; filtr drużyn, kliknięcie nazwiska otwiera
 * kartę zawodnika.
 */
function MatchupPage({g,gd,gt,gdf,onBack,pick}){
  const [only,setOnly]=useState("");
  const ts=[g.away_team,g.home_team],opp=t=>t===g.away_team?g.home_team:g.away_team;
  if(!gd)return <><button className="back" onClick={onBack}>← Wróć</button><h1>{g.away_team} @ {g.home_team}</h1><p className="mu">Brak danych Gridiris. Zaimportuj mecze skryptem ingest/gridiris_import.py i uruchom odświeżenie danych.</p></>;
  const ptint=sp=>sp==null?undefined:`color-mix(in srgb, ${sp>=67?"var(--ac)":sp>=34?"var(--warn)":"var(--bad)"} 38%, var(--card2))`;
  const sep=x=>x.na?(x.sa/x.na).toFixed(1):"–",first=n=>n.split(" ")[0];
  const box=t=>{const d=gd.teams?.[t],al=d?.al||{},tot=Object.values(al).reduce((s,c)=>s+c.t,0);
    const worst=AL.map(([k,n])=>[n,al[k]?.rank]).filter(x=>x[1]!=null).sort((a,b)=>b[1]-a[1])[0];
    return <section className="card" key={t}><h2>Obrona {t} <small>{d?`${d.pp} podań w próbce`:"brak danych"}</small></h2>
      {worst&&<p className="mu" style={{margin:"0 0 8px"}}>Najsłabiej broni: <b style={{color:"var(--tx)"}}>{worst[0]}</b> (miejsce {worst[1]} z 32)</p>}
      {d?<Plain head={["Ustawienie","trasy","targety","% targetów","przyjęcia","jardy","TD","ranking"]} rows={AL.filter(([k])=>al[k]).map(([k,n])=>{const c=al[k];
        return [n,c.r,c.t,tot?pc1(c.t/tot*100):"–",c.rec,c.yds,c.td,c.rank?<Rank r={c.rank}/>:"–"]})}/>:<p className="mu">Obrona nie ma jeszcze zaimportowanych meczów.</p>}</section>};
  const defBox=t=>{const list=(gdf?.[t]||[]).filter(x=>x.r>=8).slice(0,10);
    return <section className="card" key={t}><h2>Obrońcy {t} <small>kogo kryją i ile separacji dają</small></h2>
      {list.length?<Plain head={["Obrońca","Poz.","Trasy","Najczęściej kryje","Targety","% przyjęć","Jardy","TD","Śr. separacja"]} rows={list.map(x=>{
        const m=AL.map(([k,n])=>[first(n),x.al[k]?.r||0]).sort((a,b)=>b[1]-a[1])[0];
        return [x.name,x.pos||"–",x.r,`${m[0]} ${pc1(m[1]/x.r*100)}`,x.t,x.t?pc1(x.rec/x.t*100):"–",x.yds,x.td,
          <span title="średnia separacja krytego odbiorcy w momencie rzutu (jardy); zielony = obrońca zostawia dużo miejsca" style={{display:"inline-block",minWidth:44,padding:"2px 8px",borderRadius:6,background:ptint(x.sp)}}>{sep(x)}</span>]})}/>
        :<p className="mu">Brak obrońców z próbką (minimum 8 tras) w zaimportowanych meczach.</p>}</section>};
  const list=ts.filter(t=>!only||t===only).flatMap(t=>(gt?.[t]||[]).map(x=>({...x,team:t})));
  const rows=list.map(x=>{const od=gd.teams?.[opp(x.team)]?.al||{},ds=gdf?.[opp(x.team)]||[];
    const main=AL.map(([k,n])=>[k,first(n),x.al[k]?x.al[k].n/x.n:0]).sort((a,b)=>b[2]-a[2])[0];
    const cands=ds.filter(d=>d.al?.[main[0]]?.r>=3).sort((a,b)=>b.al[main[0]].r-a.al[main[0]].r),d=cands[0];
    return [<button className="link" onClick={()=>pick({player_id:x.id,name:x.name,pos:x.pos},x.team,{s:"",inj:""})}>{x.name}</button>,x.team,x.pos,
      x.tp?pc1(x.r/x.tp*100):"–",...AL.map(([k])=>{const c=x.al[k],r=od[k]?.rank,share=c?c.n/x.n*100:0;
        return <span title={c?`${c.n} snapów, ${c.t} targetów`:"brak"} style={{display:"inline-block",minWidth:56,padding:"2px 8px",borderRadius:6,background:share>=5?tint(r):"transparent",opacity:share>=5?1:.45}}>{c?pc1(share):"–"}</span>}),
      x.t,sep(x),main[2]>0?`${main[1]} ${pc1(main[2]*100)}`:"–",
      d?<span title={cands.slice(0,3).map(c=>`${c.name}: ${c.al[main[0]].r} tras w ustawieniu ${main[1]}, śr. separacja ${sep(c)}`).join("; ")} style={{display:"inline-block",padding:"2px 8px",borderRadius:6,background:ptint(d.sp)}}>{d.name} <span className="mu">({d.al[main[0]].r}{d.pos?`, ${d.pos}`:""})</span></span>:"–"]});
  return <>
    <button className="back" onClick={onBack}>← Wróć</button>
    <h1>{g.away_team} @ {g.home_team} <span className="mu" style={{fontSize:18}}>alignment: gdzie obrona przecieka</span></h1>
    <div className="grid">{ts.map(box)}</div>
    <div className="grid">{ts.map(defBox)}</div>
    <section className="card"><h2>Zawodnicy, ich ustawienia i prawdopodobny krywający <small>kolor komórki = ranking obrony rywala w danym ustawieniu (zielony: przecieka)</small></h2>
      <div className="chips"><button className="chip" aria-pressed={only===""} onClick={()=>setOnly("")}>Obie drużyny</button>
        {ts.map(t=><button key={t} className="chip" aria-pressed={only===t} onClick={()=>setOnly(t)}>{t}</button>)}</div>
      {rows.length?<Plain head={["Zawodnik","Drużyna","Poz.","% tras drużyny",...AL.map(a=>`% snapów ${first(a[1])}`),"targety","śr. separacja","główne ustawienie","prawdopodobny krywający"]} rows={rows}/>:<p className="mu">Brak zawodników z danymi Gridiris dla tego meczu.</p>}
      <p className="mu" style={{fontSize:12}}>Udział snapów w podaniach według ustawienia przed snapem (Gridiris, bieżący sezon, minimum 5 snapów). Zielone komórki to ustawienia, w których obrona rywala radzi sobie najsłabiej (ranking z oddanych jardów na trasę; wymaga próbki co najmniej 8 obron). „Prawdopodobny krywający” to obrońca rywala, który w zaimportowanych meczach najczęściej krył odbiorców w głównym ustawieniu tego zawodnika (w nawiasie liczba tras); to wskazówka, a nie pewny przydział. Jego kolor pokazuje, ile separacji zostawia: zielony = dużo, czerwony = mało (percentyl wśród obrońców z min. 15 trasami, liczony gdy jest ich co najmniej 20). Kliknij nazwisko, aby otworzyć kartę zawodnika.</p></section>
  </>;
}

/**
 * Blok „Inni zawodnicy”: średnie oddawane pozycji przez obronę rywala i pojedyncze wyniki zawodników tej
 * pozycji (data, drużyna, pozycja w depth chartcie z dnia meczu).
 */
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

/**
 * Kolorowa plakietka z rankingiem obrony (1 = najlepsza obrona): czerwona do 10. miejsca, pomarańczowa do 22.,
 * dalej zielona.
 */
function Rank({r}){
  const c=r<=10?"var(--bad)":r<=22?"var(--warn)":"var(--ac)";
  return <span style={{display:"inline-block",minWidth:30,textAlign:"center",padding:"1px 9px",borderRadius:999,fontWeight:700,color:c,
    background:`color-mix(in srgb, ${c} 18%, transparent)`}}>{r}</span>;
}

/** Nazwy stref głębokości i stron boiska w mapie stref targetów. */
const ZD={behind:"Za linią",short:"Krótkie 0–9",mid:"Średnie 10–19",deep:"Głębokie 20+"},ZS={left:"lewa",middle:"środek",right:"prawa"};
/** Kolejność 12 stref (głębokość x strona boiska) używana przy podsumowaniach i dla QB. */
const ZORDER=Object.keys(ZD).flatMap(d=>["left","middle","right"].map(s=>`${d}:${s}`));
/** Etykieta strefy, np. „Krótkie 0–9 · lewa”. */
const zname=z=>{const [d,s]=z.split(":");return `${ZD[d]} · ${ZS[s]||s}`};

/** Układ mapy boiska: wysokości rzędów (od najgłębszego do strefy za linią) i szerokości kolumn. */
const ZROWS=[["deep",150],["mid",120],["short",120],["behind",80]],ZCOLS=[["left",.34],["middle",.32],["right",.34]];

/**
 * Mapa boiska ze strefami targetów (bieżący sezon): kolor to ranking obrony rywala w strefie, w środku %
 * targetów zawodnika (dla QB % podań przeciwko obronie), linia wznowienia, legenda i częstotliwość blitzu
 * obrony.
 */
function ZonesBlock({p,opp,ins,pz}){
  if(!ins)return <section className="card"><h2>Strefy targetów</h2><p className="mu">Brak danych bieżącego sezonu. Uruchom ponownie skrypt danych.</p></section>;
  const d=ins.teams?.[opp],bl=d?.blitz,qb=p.pos==="QB",mine=pz?.zones||{};
  const W=520,H=520,L=40,R=12,T=10,gap=6,iw=W-L-R,los=T+ZROWS.slice(0,3).reduce((s,r)=>s+r[1],0);
  const tot=qb?ZORDER.reduce((s,z)=>s+(d?.zones?.[z]?.targets||0),0):Object.values(mine).reduce((s,m)=>s+m.targets,0);
  const cells=[];let y=T;
  ZROWS.forEach(([dk,h])=>{let x=L;ZCOLS.forEach(([sk,w])=>{const z=`${dk}:${sk}`,cw=iw*w,m=mine[z],x0=d?.zones?.[z],val=qb?x0?.targets:m?.targets;
    cells.push({z,x:x+gap/2,y:y+gap/2,w:cw-gap,h:h-gap,m,x0,val:val||0,pct:tot&&val?val/tot*100:null});x+=cw});y+=h});
  const mcol=r=>r==null?null:r<=10?"var(--bad)":r<=22?"var(--warn)":"var(--ac)";
  return <section className="card"><h2>Strefy targetów i obrona {opp} <small>sezon {ins.meta.season}, do tygodnia {ins.meta.through_week}</small></h2>
    {bl&&<p className="mu" style={{margin:"0 0 8px"}}>Blitz {opp}: {bl.pct}% dropbacków (miejsce {bl.rank} w lidze pod względem częstotliwości blitzu)</p>}
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Mapa stref boiska: kolor to ranking obrony, liczba to udział targetów" style={{width:"100%",maxWidth:560,display:"block",margin:"0 auto"}}>
      <rect x="0" y="0" width={W} height={H} rx="14" fill="#0e2a1b"/>
      <line x1={L} x2={L} y1={T} y2={H-T} stroke="#fff" strokeOpacity=".25"/><line x1={W-R} x2={W-R} y1={T} y2={H-T} stroke="#fff" strokeOpacity=".25"/>
      {cells.map(c=>{const r=c.x0?.rank,col=mcol(r),cx=c.x+c.w/2,cy=c.y+c.h/2;
        return <g key={c.z}>
          <title>{`${zname(c.z)}: ${c.val} ${qb?"podań obrony":"targetów"}${c.x0?`, oddane ${c.x0.ypt} jardów/target, EPA ${c.x0.epa}, ranking obrony ${r}`:", brak danych o obronie (min. 5 targetów)"}`}</title>
          <rect x={c.x} y={c.y} width={c.w} height={c.h} rx="8" style={{fill:col?`color-mix(in srgb, ${col} 58%, #0b1f14)`:"#2b3440"}} stroke={col||"#475569"}/>
          <text x={cx} y={cy+6} textAnchor="middle" fontSize="30" fontWeight="700" fill="#fff" style={{fontFamily:"'Barlow Condensed',sans-serif"}}>{c.pct==null?"–":c.pct<10?`${c.pct.toFixed(1)}%`:`${Math.round(c.pct)}%`}</text>
          <text x={cx} y={cy+24} textAnchor="middle" fontSize="12" fill="#fff" fillOpacity=".75">{c.val} {qb?"podań":"tg"}</text>
          {r!=null&&<text x={c.x+c.w-8} y={c.y+17} textAnchor="end" fontSize="12" fontWeight="700" fill="#fff">#{r}</text>}</g>})}
      <line x1={L-6} x2={W-R} y1={los} y2={los} stroke="#7dd3fc" strokeWidth="2" strokeDasharray="6 4"/>
      <text x={W-R-6} y={los-5} textAnchor="end" fontSize="11" fill="#7dd3fc">linia wznowienia</text>
      {[["20",T+ZROWS[0][1]],["10",T+ZROWS[0][1]+ZROWS[1][1]],["0",los]].map(([t,yy])=><text key={t} x={L-8} y={yy+4} textAnchor="end" fontSize="11" fill="#fff" fillOpacity=".6">{t}</text>)}
    </svg>
    <div className="chips" style={{justifyContent:"center",fontSize:12,marginTop:10}}>
      {[["var(--bad)","zły matchup (obrona w top 10)"],["var(--warn)","średni (11–22)"],["var(--ac)","dobry (23–32)"],["#475569","brak danych (<5 targetów)"]].map(([c,t])=>
        <span key={t} className="mu"><span style={{display:"inline-block",width:10,height:10,borderRadius:3,background:c,marginRight:5}}/>{t}</span>)}</div>
    <p className="mu" style={{fontSize:12}}>{qb?`Liczba w środku: odsetek podań przeciwko obronie ${opp} w danej strefie. `:"Liczba w środku: odsetek targetów zawodnika w danej strefie. "}
      Kolor i numer #: ranking obrony {opp} w strefie (1 = najlepsza, wg EPA na target). Atak w górę; strefa = głębokość podania (air yards) × strona boiska, z play-by-play bieżącego sezonu. To przybliżenie ścieżek, a nie ich nazwy.{!qb&&!tot?" Zawodnik nie ma jeszcze targetów w bieżącym sezonie.":""}</p></section>;
}

/** Ścieżki zawodnika na danych FTN z poprzedniego sezonu (używane, gdy brak danych Gridiris). */
function RoutesBlock({p,opp,cov,pc}){
  const d=cov?.teams?.[opp],routes=Object.entries(pc?.routes||{}).sort((a,b)=>b[1].targets-a[1].targets);
  return <section className="card"><h2>Ścieżki zawodnika i obrona {opp} <small>ścieżki przy targetach · dane FTN z sezonu {cov?.meta?.def_season??"–"}</small></h2>
    {p.pos==="QB"||!routes.length?<p className="mu">Brak danych o ścieżkach dla tego zawodnika.</p>:
      <Plain head={["Ścieżka","targety","% targetów","ranking obrony","jardy/target oddane","EPA/target oddane"]} rows={routes.map(([r,v])=>{const x=d?.routes?.[r];
        return [r,v.targets,pc1(v.share),
          x?<Rank r={x.rank}/>:"–",x?x.ypt:"–",x?x.epa:"–"]})}/>}
    <p className="mu" style={{fontSize:12}}>Ranking: 1 = najlepsza obrona przeciw tej ścieżce (najniższe EPA na target). Kolory matchupu: zielony – dobry (miejsca 23–32), pomarańczowy – średni (11–22), czerwony – zły (1–10). Dane FTN obejmują ścieżkę głównego odbiorcy na akcji.</p></section>;
}

/**
 * Tabela usage zawodników drużyny: zakładki Receiving/Rushing, okna Sezon/L5/L3/L1 liczone w meczach drużyny,
 * udział z paskiem, pozycja w depth chartcie i status.
 */
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

/** Koledzy z drużyny zawodnika (z usage i depth chartu, bez niego samego) do filtra składu. */
function matesOf(p,usage,depth){
  const m=new Map();
  (usage?.[p.team]?.players||[]).forEach(x=>m.set(x.player_id,{id:x.player_id,name:x.name,pos:x.pos}));
  POS.forEach(pos=>(depth[p.team]?.[pos]||[]).forEach(x=>m.set(x.player_id,{id:x.player_id,name:x.name,pos})));
  m.delete(p.player_id);
  return [...m.values()].filter(x=>!String(x.id).startsWith("espn_")).sort((a,b)=>POS.indexOf(a.pos)-POS.indexOf(b.pos)||a.name.localeCompare(b.name));
}

/**
 * Główny komponent: ładuje dane, trzyma wybór meczu i zawodnika i przełącza widoki: ekran główny (wybór meczu
 * i depth charty), karta zawodnika (dwie kolumny bloków) oraz podstrona meczu z alignmentem.
 */
export default function App(){
  /**
   * Stan aplikacji: terminarz, depth charty, wybrany mecz i zawodnik, logi, dane obrony, krycia, strefy,
   * kursy, red zone, Gridiris i bieżący widok.
   */
  const [games,setGames]=useState(null),[depth,setDepth]=useState({}),[g,setG]=useState(null),[p,setP]=useState(null),[log,setLog]=useState([]),
    [def,setDef]=useState(null),[cov,setCov]=useState(null),[pc,setPc]=useState(null),[usage,setUsage]=useState(null),[odds,setOdds]=useState(null),[hist,setHist]=useState(null),[ins,setIns]=useState(null),[pz,setPz]=useState(null),[rz,setRz]=useState(null),[gd,setGd]=useState(null),[gp,setGp]=useState(null),[gt,setGt]=useState(null),[gdf,setGdf]=useState(null),[view,setView]=useState("");
  /**
   * Jednorazowe wczytanie wspólnych plików danych (terminarz, depth charty, usage, krycia, kursy, historia
   * linii, red zone, Gridiris).
   */
  useEffect(()=>{get("/data/schedule.json").then(s=>{setGames(s);setG(s[0]||null)}).catch(()=>setGames([]));
    get("/data/depth.json").then(setDepth).catch(()=>{});get("/data/usage.json").then(setUsage).catch(()=>{});
    get("/data/coverage/defense.json").then(setCov).catch(()=>{});get("/data/inseason/defense.json").then(setIns).catch(()=>{});get("/data/redzone.json").then(setRz).catch(()=>{});get("/data/gridiris/defense.json").then(setGd).catch(()=>{});get("/data/gridiris/teams.json").then(setGt).catch(()=>{});get("/data/gridiris/defenders.json").then(setGdf).catch(()=>{});get("/data/odds.json").then(setOdds).catch(()=>{});get("/data/odds_history.json").then(setHist).catch(()=>{})},[]);
  /** Rywal zawodnika w wybranym meczu; pusty, gdy jego drużyna w nim nie gra. */
  const opp=p&&g?(p.team===g.home_team?g.away_team:p.team===g.away_team?g.home_team:""):"";
  /** Po wyborze zawodnika wczytuje jego log meczów, krycia FTN, strefy i dane Gridiris. */
  useEffect(()=>{setLog([]);setPc(null);setPz(null);setGp(null);if(!p)return;
    get(`/data/logs/${p.player_id}.json`).then(setLog).catch(()=>{});get(`/data/coverage/players/${p.player_id}.json`).then(setPc).catch(()=>{});get(`/data/inseason/players/${p.player_id}.json`).then(setPz).catch(()=>{});get(`/data/gridiris/players/${p.player_id}.json`).then(setGp).catch(()=>{})},[p]);
  /** Wczytuje dane obrony rywala (ostatnie mecze) po zmianie rywala. */
  useEffect(()=>{if(opp)get(`/data/defense/${opp}.json`).then(setDef).catch(()=>setDef(null));else setDef(null)},[opp]);
  /**
   * Pozycja zawodnika w depth chartcie jako tekst (np. WR2): z dnia meczu, a gdy jej brak, z obecnego depth
   * chartu.
   */
  const rank=r=>{if(r.depth_rank)return `${r.position}${r.depth_rank}`;
    for(const t of [r.team,...Object.keys(depth)]){const l=depth[t]?.[r.position]||[],i=l.findIndex(x=>x.player_id===r.player_id);
      if(i>=0)return `${r.position}${i+1}`}return "–"};
  /** Otwiera kartę zawodnika, ustawia mecz jego drużyny i przewija stronę na górę. */
  const pick=(x,team,l)=>{setP({player_id:x.player_id,name:x.name,pos:x.pos,team,status:l.s,injury:l.inj});
    const gm=(games||[]).find(m=>m.home_team===team||m.away_team===team);if(gm)setG(gm);setView("");window.scrollTo(0,0)};
  /** Karta depth chartu drużyny z klikalnymi zawodnikami, rangami i statusami. */
  const Depth=({team})=><section className="card"><h2>{team} <small>depth chart</small></h2>{POS.map(pos=><div key={pos} style={{marginBottom:8}}><span className="mu">{pos}</span>
    <div className="chips">{(depth[team]?.[pos]||[]).map((x,i)=><button key={x.player_id} className="chip" onClick={()=>pick({...x,pos},team,{s:x.status,inj:x.injury})}>
      <span className="mu">{pos}{i+1}</span> {x.name}<Badge s={x.status} inj={x.injury}/>{x.usage!=null&&<span className="mu"> {x.usage}</span>}</button>)}</div></div>)}</section>;
  if(!games)return <main><p className="mu">Ładowanie…</p></main>;
  /** Stopka ze źródłami danych, licencją i uwagą o ryzyku. */
  const footer=<footer className="mu" style={{marginTop:32,paddingTop:12,borderTop:"1px solid var(--ln)",fontSize:12}}>
    Źródła danych: statystyki, terminarze i składy – nflverse; dane o rodzajach krycia (coverage) i ścieżkach – FTN Data via nflverse, na licencji{" "}
    <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noopener noreferrer" style={{color:"var(--ac)"}}>CC BY-SA 4.0</a>; alignment, ścieżki i krycie (est.) z bieżącego sezonu – Gridiris (dane NFL Next Gen Stats); depth charty i statusy kontuzji – ESPN.
    Kursy: Superbet (PL) via OddsPapi; mogą różnić się od aktualnych na stronie bukmachera. Aplikacja ma charakter informacyjny i nie gwarantuje wyników zakładów. Hazard wiąże się z ryzykiem, 18+.</footer>;
  if(view==="matchup"&&g)return <main style={{maxWidth:"none"}}><MatchupPage g={g} gd={gd} gt={gt} gdf={gdf} onBack={()=>setView("")} pick={pick}/>{footer}</main>;
  if(p&&g)return <main style={{maxWidth:"none"}}>
    <button className="back" onClick={()=>setP(null)}>← Wróć do meczu {g.away_team} @ {g.home_team}</button>
    <h1>{p.name}<Badge s={p.status} inj={p.injury}/></h1>
    <div className="mu">{p.pos} · {p.team} vs {opp||"–"} · {D(g.gameday,2)}</div>
    <GameOdds gl={odds?.games?.[g.game_id]} gh={hist?.[g.game_id]?.game}/>
    <div className="chips"><button className="chip" onClick={()=>setView("matchup")}>Alignment meczu: gdzie obrona przecieka →</button></div>
    <div className="cols">
      <div className="col">
        <div style={{order:1}}><ChartBlock key={p.player_id} p={p} log={log} g={g} opp={opp} odds={odds} hist={hist} mates={matesOf(p,usage,depth)}/></div>
        <div style={{order:4}}><RedZoneBlock p={p} opp={opp} rz={rz} usage={usage}/></div>
        <div style={{order:5}}><OthersBlock p={p} opp={opp} def={def} rank={rank}/></div>
      </div>
      <div className="col">
        <div style={{order:2}}>{gd&&gp&&p.pos!=="QB"?<CoverageGI p={p} opp={opp} gd={gd} gp={gp}/>:<CoverageBlock p={p} opp={opp} cov={cov} pc={pc}/>}</div>
        <div style={{order:3}}><AlignmentBlock p={p} opp={opp} gd={gd} gp={gp}/></div>
        <div style={{order:6}}><ZonesBlock p={p} opp={opp} ins={ins} pz={pz}/></div>
        <div style={{order:7}}>{gd&&gp?.rt&&Object.keys(gp.rt).length?<RoutesGI p={p} opp={opp} gd={gd} gp={gp}/>:<RoutesBlock p={p} opp={opp} cov={cov} pc={pc}/>}</div>
        <div style={{order:8}}><Usage usage={usage} teams={[p.team]} depth={depth} pick={pick}/></div>
      </div>
    </div>
    {footer}</main>;
  return <main><h1>NFL Edge</h1><p className="mu">Wybierz mecz, a potem zawodnika z depth chartu.</p>
    {!games.length&&<p className="mu">Brak nadchodzących meczów w terminarzu.</p>}
    <div className="chips">{games.map(x=><button key={x.game_id} className="chip" aria-pressed={g?.game_id===x.game_id} onClick={()=>setG(x)}>{x.away_team} @ {x.home_team} <span className="mu">{D(x.gameday,2)}</span></button>)}</div>
    {g&&<div className="chips"><button className="chip" onClick={()=>setView("matchup")}>Alignment meczu: gdzie obrona przecieka →</button></div>}
    {g&&<div className="grid"><Depth team={g.away_team}/><Depth team={g.home_team}/></div>}{footer}</main>;
}