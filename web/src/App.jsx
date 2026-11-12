import {useEffect,useState} from "react";
const get=u=>fetch(u).then(r=>r.ok?r.json():Promise.reject(u));
const POS=["QB","RB","WR","TE"];
const MAIN={QB:["attempts","completions","passing_yards","passing_tds","rushing_yards"],RB:["carries","rushing_yards","targets","receptions","receiving_yards"],
  WR:["targets","receptions","receiving_yards","receiving_tds"],TE:["targets","receptions","receiving_yards","receiving_tds"]};
const avg=(rows,c)=>rows.length?(rows.reduce((a,r)=>a+(r[c]||0),0)/rows.length).toFixed(1):"–";
function Table({rows,cols,first,label}){
  return <div className="t"><table><thead><tr><th>{label}</th>{cols.map(c=><th key={c}>{c.replace("_"," ")}</th>)}</tr></thead><tbody>
    {rows.map((r,i)=><tr key={i}><td>{first(r)}</td>{cols.map(c=><td key={c}>{r[c]}</td>)}</tr>)}
    <tr className="avg"><td>Średnia ({rows.length})</td>{cols.map(c=><td key={c}>{avg(rows,c)}</td>)}</tr></tbody></table></div>;
}
export default function App(){
  const [games,setGames]=useState(null),[depth,setDepth]=useState({}),[g,setG]=useState(null),[p,setP]=useState(null),[log,setLog]=useState([]),[def,setDef]=useState(null);
  useEffect(()=>{get("/data/schedule.json").then(s=>{setGames(s);setG(s[0]||null)}).catch(()=>setGames([]));get("/data/depth.json").then(setDepth).catch(()=>{})},[]);
  const opp=p&&g?(p.team===g.home_team?g.away_team:g.home_team):"";
  useEffect(()=>{if(p)get(`/data/logs/${p.player_id}.json`).then(setLog).catch(()=>setLog([]))},[p]);
  useEffect(()=>{if(opp)get(`/data/defense/${opp}.json`).then(setDef).catch(()=>setDef(null));else setDef(null)},[opp]);
  const cols=p?MAIN[p.pos]:[];
  const vsOpp=log.filter(r=>r.opponent_team===opp);
  const others=def?def.recent.filter(r=>r.position===p?.pos&&r.player_display_name!==p?.name):[];
  const Depth=({team})=><div><h2>{team}</h2>{POS.map(pos=><div key={pos} style={{marginBottom:6}}><b>{pos}</b><div>
    {(depth[team]?.[pos]||[]).map((x,i)=>{const on=p?.player_id===x.player_id;
      return <button key={x.player_id} aria-pressed={on} onClick={()=>setP({player_id:x.player_id,name:x.name,pos,team,status:x.status,injury:x.injury})}
        style={{marginRight:6,marginTop:6,fontWeight:on?700:400,borderColor:on?"var(--tu)":undefined}}>{pos}{i+1} {x.name}{x.status&&<b title={x.injury} style={{marginLeft:6,color:["Q","D","DTD"].includes(x.status)?"#b26a00":"#c0392b"}}>{x.status}</b>}{x.usage!=null&&<span className="mu"> {x.usage}</span>}</button>})}</div></div>)}</div>;
  if(!games)return <main><p className="mu">Ładowanie…</p></main>;
  return <main>
    <h1>NFL Edge</h1>
    {!games.length&&<p className="mu">Brak nadchodzących meczów w terminarzu.</p>}
    <div>{games.map(x=><button key={x.game_id} aria-pressed={g?.game_id===x.game_id} onClick={()=>{setG(x);setP(null);setLog([])}}
      style={{marginRight:6,marginBottom:6,fontWeight:g?.game_id===x.game_id?700:400}}>{x.away_team} @ {x.home_team} <span className="mu">{x.gameday}</span></button>)}</div>
    {g&&<div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(300px,1fr))",gap:16}}><Depth team={g.away_team}/><Depth team={g.home_team}/></div>}
    {g&&!p&&<p className="mu">Wybierz zawodnika z depth chartu. Statusy: Q – wątpliwy, D – mało prawdopodobny, OUT – nie zagra, IR – lista kontuzjowanych.</p>}
    {p&&<><h2>{p.name} – log meczów</h2>{p.status&&<p style={{color:"#c0392b"}}>Status: {p.status}{p.injury?` (${p.injury})`:""}</p>}
      <Table rows={[...log].reverse()} cols={cols} label="Mecz" first={r=>`${r.season} T${r.week} vs ${r.opponent_team}`}/>
      <h2>{p.name} przeciwko {opp} (historia)</h2>
      {vsOpp.length?<Table rows={vsOpp} cols={cols} label="Mecz" first={r=>`${r.season} T${r.week}`}/>:<p className="mu">Brak meczów przeciwko {opp} w pobranych sezonach.</p>}</>}
    {p&&def&&<><h2>Obrona {opp} – średnio oddaje pozycji {p.pos} (ostatnie 8 meczów)</h2>
      <Table rows={[def.allowed[p.pos]||{}]} cols={cols} label="Na mecz" first={()=>"Suma pozycji"}/>
      <h2>Inni {p.pos} przeciwko {opp}</h2>
      <Table rows={others} cols={cols} label="Zawodnik" first={r=>`${r.player_display_name} (T${r.week})`}/></>}
  </main>;
}