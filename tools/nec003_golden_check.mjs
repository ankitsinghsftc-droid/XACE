// Independent BigInt implementation of the NEC-003 wire/numeric golden contract.
// This is a test oracle, not an engine editor reader or shipping materializer.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';

const check = (condition) => { if (!condition) throw new Error('invalid numeric contract'); };
const S = 1000000n, L = 8192000000n;
const i64 = n => { check(n >= -(1n << 63n) && n < (1n << 63n)); return n; };
function decimal(text) {
  check(typeof text === 'string' && text.length <= 96 && /^-?(0|[1-9][0-9]*)(\.[0-9]+)?$/.test(text));
  const places = text.includes('.') ? text.split('.')[1].length : 0;
  return [BigInt(text.replace('.', '')), 10n ** BigInt(places)];
}
function fixed([numerator, denominator]) {
  const sign = numerator < 0n ? -1n : 1n;
  numerator = (numerator < 0n ? -numerator : numerator) * S;
  let q = numerator / denominator;
  const r = numerator % denominator;
  if (2n*r > denominator || (2n*r === denominator && q % 2n !== 0n)) q++;
  return [i64(sign*q), r !== 0n];
}
const negate = ([n,d]) => [-n,d];
function normalize(engine, kind, value) {
  check(['godot','unity','unreal'].includes(engine));
  if (kind === 'int64') {
    check(typeof value === 'string' && /^(0|-?[1-9][0-9]*)$/.test(value) && value.length <= 20);
    return {value:i64(BigInt(value)).toString(), losses:[]};
  }
  const axes = kind === 'rotation' ? ['x','y','z','w'] : ['x','y','z'];
  check(Object.keys(value).sort().join() === axes.slice().sort().join());
  let numbers = axes.map(k=>decimal(value[k]));
  if (engine === 'unity') {
    if (['position','offset','normal'].includes(kind)) numbers[2] = negate(numbers[2]);
    if (kind === 'rotation') { numbers[0] = negate(numbers[0]); numbers[1] = negate(numbers[1]); }
  }
  if (engine === 'unreal') {
    const [x,y,z,w] = numbers;
    numbers = kind === 'rotation' ? [negate(y),negate(z),x,w] :
      [y,z,['position','offset','normal'].includes(kind) ? negate(x) : x];
    if (['position','offset','size'].includes(kind)) numbers = numbers.map(([n,d])=>[n,d*100n]);
  }
  const pairs = numbers.map(fixed);
  let raw = pairs.map(p=>p[0]);
  if (['position','offset','size'].includes(kind)) check(raw.every(n=>n>=-L && n<=L));
  if (kind === 'size') check(raw.every(n=>n>0n));
  if (kind === 'scale') check(raw.every(n=>n!==0n));
  if (['normal','rotation'].includes(kind)) {
    const error = raw.reduce((a,n)=>a+n*n,0n)-S*S;
    check(error>=-4n*S && error<=4n*S);
  }
  if (kind === 'rotation') {
    const first = [raw[3],...raw.slice(0,3)].find(n=>n!==0n);
    if (first < 0n) raw = raw.map(n=>-n);
  }
  return {value:Object.fromEntries(axes.map((k,i)=>[k,raw[i].toString()])),
          losses:axes.filter((_,i)=>pairs[i][1])};
}
function canonical(value) {
  if (Array.isArray(value)) return '['+value.map(canonical).join(',')+']';
  if (value !== null && typeof value === 'object')
    return '{'+Object.keys(value).sort().map(k=>canonical(k)+':'+canonical(value[k])).join(',')+'}';
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
}
const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const outputs = fixture.map(row=> {
  let result;
  try { result = normalize(row.engine,row.kind,row.value); }
  catch (error) { assert.equal(row.reject,true); return {rejected:true}; }
  assert.notEqual(row.reject,true);
  assert.deepEqual(result,{value:row.expected,losses:row.losses});
  return result;
});
const bytes = canonical(outputs);
const snapshot = process.argv[3] ? canonical(JSON.parse(fs.readFileSync(process.argv[3], 'utf8'))) : null;
console.log(JSON.stringify({cases:outputs.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex'),outputs,
  snapshot_sha256:snapshot === null ? null : crypto.createHash('sha256').update(snapshot).digest('hex')}));
