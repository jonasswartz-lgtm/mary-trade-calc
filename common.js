/* Shared by the calculator and the trade log: password gate, crypto, proposal log. */
const $ = s => document.querySelector(s);
const fmt = n => (n>0?"+":n<0?"−":"") + Math.abs(n).toFixed(1);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

/* ---------- password storage + crypto ---------- */
const PWKEY = "maryDeskPw";
const store = {
  get(){ try{ return localStorage.getItem(PWKEY) }catch{ return null } },
  set(v){ try{ localStorage.setItem(PWKEY, v) }catch{} },
  clear(){ try{ localStorage.removeItem(PWKEY) }catch{} }
};
const unb64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const b64 = u8 => { let s=""; u8.forEach(b => s += String.fromCharCode(b)); return btoa(s); };

async function deriveKey(pw, salt, iter){
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(pw), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({name:"PBKDF2", salt, iterations:iter, hash:"SHA-256"}, base, {name:"AES-GCM", length:256}, false, ["encrypt","decrypt"]);
}
async function decrypt(blob, pw){
  const key = await deriveKey(pw, unb64(blob.salt), blob.iter);
  const pt = await crypto.subtle.decrypt({name:"AES-GCM", iv:unb64(blob.iv)}, key, unb64(blob.ct));
  return JSON.parse(new TextDecoder().decode(pt));
}

/* ---------- gate UI ---------- */
const WRONG = ["Wrong. Mary would never.","Nope. Are you even in this league?","Incorrect. The lamb is unimpressed.","Denied. Try the one the Commissioner texted you."];
let wrongCount = 0;
function injectGate(){
  if($("#gate")) return;
  document.body.insertAdjacentHTML("beforeend", `
<div class="gate" id="gate" hidden>
  <form class="gate-card" id="gate-form">
    <div class="gate-sheep">🐑</div>
    <h2>Members only.</h2>
    <p>Mary doesn't talk to strangers. Enter the league password.</p>
    <input id="gate-pw" type="password" autocomplete="current-password" placeholder="Password" aria-label="League password">
    <button class="btn primary" type="submit">Let me in</button>
    <div class="gate-msg" id="gate-msg" aria-live="polite"></div>
  </form>
  <div class="gate-card" id="adam" hidden role="alertdialog" aria-labelledby="adam-q">
    <div class="gate-sheep">🤨</div>
    <h2 id="adam-q">Wait, is this Adam?</h2>
    <p>I hate Adam.</p>
    <div class="adam-btns"><button class="btn primary">No</button> <button class="btn" data-adam="1">…Yes</button></div>
  </div>
</div>`);
}
function adamCheck(){
  return new Promise(done => {
    $("#gate-form").hidden = true;
    const a = $("#adam"); a.hidden = false; a.querySelector("button").focus();
    a.querySelectorAll("button").forEach(b => b.onclick = () => {
      if(b.dataset.adam){ a.querySelector("p").textContent = "Ugh. Fine. Come in."; a.querySelector(".adam-btns").hidden = true; setTimeout(done, 1400); }
      else done();
    });
  });
}
function gate(blob){
  injectGate();
  return new Promise(resolve => {
    const g=$("#gate"), f=$("#gate-form"), i=$("#gate-pw"), m=$("#gate-msg");
    g.hidden = false; i.focus();
    f.onsubmit = async e => {
      e.preventDefault(); m.textContent = "Checking…";
      try{ const d = await decrypt(blob, i.value); store.set(i.value); m.textContent=""; await adamCheck(); g.hidden = true; resolve({data:d, pw:i.value}); }
      catch{ m.textContent = WRONG[wrongCount++ % WRONG.length]; i.select(); }
    };
  });
}
/* Load the encrypted data; use the remembered password or ask for it. */
async function unlock(){
  const r = await fetch("data/players.enc.json", {cache:"no-store"});
  const blob = await r.json();
  const saved = store.get();
  if(saved){ try{ return {data: await decrypt(blob, saved), pw: saved} }catch{ store.clear() } }
  return gate(blob);
}

/* ---------- proposal log (encrypted GitHub issues) ---------- */
const LOG = {
  repo: "jonasswartz-lgtm/mary-trade-calc",
  _key: null,
  async key(pw){
    if(!this._key) this._key = deriveKey(pw, new TextEncoder().encode("mary-desk-log-v1"), 250000);
    return this._key;
  },
  headers(token){
    const h = {"Accept":"application/vnd.github+json"};
    if(token) h.Authorization = "Bearer " + token;
    return h;
  },
  async post(entry, token, pw){
    const key = await this.key(pw);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ct = new Uint8Array(await crypto.subtle.encrypt({name:"AES-GCM", iv}, key, new TextEncoder().encode(JSON.stringify(entry))));
    const body = "🔒 Encrypted Mary Desk trade proposal. Only league members can read it.\n\n```mary\n" + JSON.stringify({v:1, iv:b64(iv), ct:b64(ct)}) + "\n```";
    const r = await fetch(`https://api.github.com/repos/${this.repo}/issues`, {
      method:"POST", headers:{...this.headers(token), "Content-Type":"application/json"},
      body: JSON.stringify({title:`Trade proposal · Week ${entry.wk}`, body, labels:["proposal"]})
    });
    if(!r.ok) throw new Error("log failed: " + r.status);
    return r.json();
  },
  async list(token, pw){
    const key = await this.key(pw), out = [];
    for(let page=1; page<=20; page++){
      const r = await fetch(`https://api.github.com/repos/${this.repo}/issues?labels=proposal&state=all&per_page=100&page=${page}`, {headers:this.headers(token), cache:"no-store"});
      if(!r.ok) throw new Error("list failed: " + r.status);
      const items = await r.json();
      for(const it of items){
        const m = /```mary\n(.+?)\n```/s.exec(it.body || "");
        if(!m) continue;
        try{
          const enc = JSON.parse(m[1]);
          const pt = await crypto.subtle.decrypt({name:"AES-GCM", iv:unb64(enc.iv)}, key, unb64(enc.ct));
          out.push({...JSON.parse(new TextDecoder().decode(pt)), num: it.number, at: it.created_at});
        }catch{ /* not ours or tampered; skip */ }
      }
      if(items.length < 100) break;
    }
    return out.sort((a,b) => b.at.localeCompare(a.at));
  }
};
