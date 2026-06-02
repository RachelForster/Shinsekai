function a(n){return n.split(/[\\/]/).pop()||n}function o(n){const t=n.indexOf("："),e=n.indexOf(":"),r=t>=0&&e>=0?Math.min(t,e):Math.max(t,e);return r>=0?n.slice(r+1).trim():n.trim()}function s(n,t){const e=n.split(/\r?\n/).filter(Boolean);return Array.from({length:t},(r,i)=>o(e[i]??""))}function c(n,t){return t.map((e,r)=>`${n} ${r+1}：${e}`).join(`
`)+(t.length?`
`:"")}export{a as b,c as n,s as t};
