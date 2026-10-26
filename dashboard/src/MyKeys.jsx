import React,{useEffect,useState} from 'react';
export default function MyKeys({req}) {
  const [keys,K]=useState([]),[raw,R]=useState(''),[error,E]=useState('');
  async function load(){try{K(await req('/api-keys'));}catch(e){E(e.message)}}
  useEffect(()=>{load()},[]);
  async function issue(){try{const k=await req('/api-keys',{method:'POST'});R(k.raw_key);load()}catch(e){E(e.message)}}
  async function revoke(id){try{await req(`/api-keys/${id}`,{method:'DELETE'});load()}catch(e){E(e.message)}}
  return <div className="panel"><p>Generate your own gateway keys. Copy a new key once and keep it private.</p>{error&&<div className="alert">{error}</div>}<button onClick={issue}>Generate my API key</button>{raw&&<div className="keyresult"><code>{raw}</code><button onClick={()=>navigator.clipboard.writeText(raw)}>Copy</button><button onClick={()=>R('')}>Dismiss</button></div>}{keys.map(k=><div className="row" key={k.id}><div className="grow">{k.key_prefix}… <small>{k.revoked_at?'Revoked':'Active'}</small></div>{!k.revoked_at&&<button onClick={()=>revoke(k.id)}>Revoke</button>}</div>)}</div>
}
