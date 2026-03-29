/**
 * Unit test suite for the EPUB → AZW3 KF8 binary writer.
 *
 * Run:  node tests/test_converter.mjs
 *
 * Tests the binary format layer directly with synthetic data.
 * End-to-end EPUB conversion tests are in tests/test_e2e.py (run via uv).
 */

import { readFileSync, writeFileSync } from 'fs';
import { execSync } from 'child_process';
import { TextEncoder, TextDecoder } from 'util';
global.TextEncoder = TextEncoder;
global.TextDecoder = TextDecoder;

// ── Minimal test framework ──────────────────────────────────────────────────

let passed = 0, failed = 0;
const failures = [];

function test(name, fn) {
  try {
    fn();
    console.log(`  ✓ ${name}`);
    passed++;
  } catch (e) {
    console.log(`  ✗ ${name}`);
    console.log(`    ${e.message}`);
    failed++;
    failures.push({ name, error: e.message });
  }
}
const assert  = (c, m) => { if (!c) throw new Error(m || 'Assertion failed'); };
const eq      = (a, b, m) => { if (a !== b) throw new Error(`${m||'eq'}: ${JSON.stringify(a)} !== ${JSON.stringify(b)}`); };
const contains = (s, sub, m) => { if (!s.includes(sub)) throw new Error(`${m||'contains'}: missing ${JSON.stringify(sub)}`); };

// ── Re-implement KF8 helpers (must match docs/index.html exactly) ──────────

const enc = new TextEncoder();
const dec = new TextDecoder();

function concat(...a) {
  const t = a.reduce((n, x) => n + x.length, 0);
  const o = new Uint8Array(t); let p = 0;
  for (const x of a) { o.set(x, p); p += x.length; }
  return o;
}
const u32  = v => { const b=new Uint8Array(4); new DataView(b.buffer).setUint32(0,v>>>0,false); return b; };
const u16  = v => { const b=new Uint8Array(2); new DataView(b.buffer).setUint16(0,v&0xffff,false); return b; };
const fill = (byte, n) => new Uint8Array(n).fill(byte);
const align4 = bytes => { const r=bytes.length%4; return r?concat(bytes,fill(0,4-r)):bytes; };

// Calibre VLQ: high bit on LAST byte (terminator)
function encint(v) {
  v = v >>> 0;
  const b = [];
  while (v > 0) { b.push(v & 0x7f); v >>>= 7; }
  if (!b.length) b.push(0);
  b[0] |= 0x80; b.reverse();
  return new Uint8Array(b);
}
function decint(bytes, pos = 0) {
  let val = 0, consumed = 0;
  for (let i = pos; i < bytes.length; i++) {
    const b = bytes[i]; val = (val << 7) | (b & 0x7f); consumed++;
    if (b & 0x80) break;
  }
  return { val, consumed };
}

function buildExth(records) {
  const parts = records.map(({tag, value}) => {
    const d = typeof value==='string' ? enc.encode(value) : value;
    return concat(u32(tag), u32(8+d.length), d);
  });
  const raw = concat(...parts);
  const pad = 4 - (raw.length % 4);
  return concat(enc.encode('EXTH'), u32(12+raw.length), u32(records.length), raw, fill(0,pad));
}

function buildFdst(flows) {
  return concat(enc.encode('FDST'), u32(12), u32(flows.length),
    concat(...flows.map(f => concat(u32(f.start), u32(f.end)))));
}

const FLIS_RECORD = new Uint8Array([
  0x46,0x4c,0x49,0x53,0x00,0x00,0x00,0x08,0x00,0x41,0x00,0x00,0x00,0x00,0x00,0x00,
  0xff,0xff,0xff,0xff,0x00,0x01,0x00,0x03,0x00,0x00,0x00,0x03,0x00,0x00,0x00,0x01,
  0xff,0xff,0xff,0xff
]);

function buildFcis(textLen) {
  return concat(enc.encode('FCIS'), u32(0x14), u32(0x10), u32(0x02), u32(0x00),
    u32(textLen),  // offset 20
    u32(0x00), u32(0x28), u32(0x00), u32(0x28), u32(0x08),
    new Uint8Array([0x00,0x01,0x00,0x01,0x00,0x00,0x00,0x00]));
}

const EOF_RECORD = new Uint8Array([0xe9,0x8e,0x0d,0x0a]);
const TEXT_RECORD_SIZE = 4096;

function buildTextRecords(text) {
  const bytes = enc.encode(text); const records = []; let pos = 0;
  while (pos < bytes.length) {
    let end = Math.min(pos + TEXT_RECORD_SIZE, bytes.length);
    while (end < bytes.length && (bytes[end] & 0xc0) === 0x80) end++;
    records.push(concat(bytes.slice(pos, end), new Uint8Array([0])));
    pos = end;
  }
  return records.length ? records : [new Uint8Array([0])];
}

const M2S = {1:0,2:1,3:0,4:2,8:3,12:2,16:4,32:5,48:4,64:6,128:7,192:6};

function buildTagx(ts) {
  const b = []; for (const t of ts) b.push(t.num,t.vpe,t.mask,0); b.push(0,0,0,1);
  return concat(enc.encode('TAGX'), u32(12+b.length), u32(1), new Uint8Array(b));
}

function serializeEntry(key, tags, ts) {
  const kb = enc.encode(key); let ctrl = 0;
  for (const t of ts) { const v=tags[t.num]||[]; ctrl|=t.mask&((v.length/t.vpe)<<M2S[t.mask]); }
  const vp = []; for (const t of ts) for (const v of (tags[t.num]||[])) vp.push(encint(v));
  return concat(new Uint8Array([kb.length]), kb, new Uint8Array([ctrl]), ...vp);
}

function buildIndxRecords(entries, ts, cncxRecord) {
  const HDR=192, LIM=0x10000-HDR-1048;
  const blocks=[[]], idxts=[[]], counts=[0], lastKeys=[new Uint8Array(0)];
  for (const e of entries) {
    const eb = serializeEntry(e.key, e.tags, ts);
    const bi = blocks.length-1;
    const used = blocks[bi].reduce((s,b)=>s+b.length,0) + idxts[bi].length*2;
    if (used+eb.length+2>LIM && blocks[bi].length>0) { blocks.push([]); idxts.push([]); counts.push(0); lastKeys.push(new Uint8Array(0)); }
    const ci = blocks.length-1;
    idxts[ci].push(HDR + blocks[ci].reduce((s,b)=>s+b.length,0));
    blocks[ci].push(eb); counts[ci]++; lastKeys[ci] = enc.encode(e.key);
  }
  const dataRecs = [];
  for (let i=0; i<blocks.length; i++) {
    const body = align4(concat(...blocks[i]));
    const idData = new Uint8Array(idxts[i].length*2); const idv = new DataView(idData.buffer);
    idxts[i].forEach((o,j) => idv.setUint16(j*2,o,false));
    const idxtBlock = align4(concat(enc.encode('IDXT'), idData));
    const h=new Uint8Array(HDR); const hv=new DataView(h.buffer);
    h[0]=0x49;h[1]=0x4e;h[2]=0x44;h[3]=0x58;
    hv.setUint32(4,HDR,false); hv.setUint32(12,1,false);
    hv.setUint32(20,HDR+body.length,false); hv.setUint32(24,counts[i],false);
    for (let k=28;k<36;k++) h[k]=0xff;
    dataRecs.push(concat(h, body, idxtBlock));
  }
  const tagx = align4(buildTagx(ts));
  const geom = align4(concat(...blocks.map((_,i)=>concat(new Uint8Array([lastKeys[i].length]),lastKeys[i],u16(counts[i])))));
  let gPos=HDR+tagx.length, gOff=0;
  const hIdxts = blocks.map((_,i)=>{ const o=gPos+gOff; gOff+=1+lastKeys[i].length+2; return o; });
  const hIdxtData = new Uint8Array(hIdxts.length*2); const hidv = new DataView(hIdxtData.buffer);
  hIdxts.forEach((o,i) => hidv.setUint16(i*2,o,false));
  const hIdxt = align4(concat(enc.encode('IDXT'), hIdxtData));
  const hh=new Uint8Array(HDR); const hv2=new DataView(hh.buffer);
  hh[0]=0x49;hh[1]=0x4e;hh[2]=0x44;hh[3]=0x58;
  hv2.setUint32(4,HDR,false); hv2.setUint32(16,2,false);
  hv2.setUint32(20,HDR+tagx.length+geom.length,false); hv2.setUint32(24,dataRecs.length,false);
  hv2.setUint32(28,65001,false); hv2.setUint32(32,0xffffffff,false); hv2.setUint32(36,entries.length,false);
  hv2.setUint32(52,cncxRecord?1:0,false); hv2.setUint32(180,HDR,false);
  return [concat(hh,tagx,geom,hIdxt), ...dataRecs, ...(cncxRecord?[cncxRecord]:[])];
}

const SKEL_T = [{num:1,vpe:1,mask:3},{num:6,vpe:2,mask:12}];
const CHUNK_T = [{num:2,vpe:1,mask:1},{num:3,vpe:1,mask:2},{num:4,vpe:1,mask:4},{num:6,vpe:2,mask:8}];

function buildCncx(selectors) {
  const parts=[], offsets=[]; let byteOff=0;
  for (const sel of selectors) {
    const sb=enc.encode(sel); offsets.push(byteOff);
    const lv=encint(sb.length); parts.push(lv,sb); byteOff+=lv.length+sb.length;
  }
  return { record: align4(concat(...parts)), offsets };
}

function buildPalmDoc(title, records) {
  const now=Math.floor(Date.now()/1000), nRec=records.length, hdrSize=78+8*nRec+2;
  const h=new Uint8Array(hdrSize); const dv=new DataView(h.buffer);
  const t=title.replace(/[^\x20-\x7e]/g,'?').replace(/ /g,'_').slice(0,31);
  for (let i=0;i<t.length;i++) h[i]=t.charCodeAt(i);
  dv.setUint32(36,now,false); dv.setUint32(40,now,false);
  h[60]=0x42;h[61]=0x4f;h[62]=0x4f;h[63]=0x4b;h[64]=0x4d;h[65]=0x4f;h[66]=0x42;h[67]=0x49;
  dv.setUint32(68,2*nRec-1,false); dv.setUint16(76,nRec,false);
  let off=hdrSize;
  for (let i=0;i<nRec;i++) {
    dv.setUint32(78+i*8,off,false); h[78+i*8+4]=0;
    const uid=2*i; h[78+i*8+5]=(uid>>16)&0xff; h[78+i*8+6]=(uid>>8)&0xff; h[78+i*8+7]=uid&0xff;
    off+=records[i].length;
  }
  return concat(h, ...records);
}

function buildAzw3(chapters, title='Test Book') {
  let hbo=0;
  const idxParts = chapters.map((ch,i) => {
    const hB=enc.encode(ch.skelHead).length, tB=enc.encode(ch.skelTail).length, cB=enc.encode(ch.content).length;
    const p={chapterIndex:i,chunkCount:1,skelHeadByteLen:hB,skelTailByteLen:tB,contentByteLen:cB,flowStart:hbo,firstAid:ch.firstAid||1};
    hbo+=hB+tB+cB; return p;
  });
  const fullText = chapters.map(c=>c.skelHead+c.skelTail+c.content).join('');
  const textLen = enc.encode(fullText).length;
  const textRecs = buildTextRecords(fullText);
  const recs = [new Uint8Array(0)]; for (const r of textRecs) recs.push(r);
  const dl=recs.slice(1).reduce((s,r)=>s+r.length,0); if (dl%4) recs.push(fill(0,4-(dl%4)));
  const firstNonText=recs.length;
  const skelRecs=buildIndxRecords(idxParts.map((p,i)=>({key:`SKEL${String(i).padStart(10,'0')}`,tags:{1:[p.chunkCount,p.chunkCount],6:[p.flowStart,p.skelHeadByteLen+p.skelTailByteLen,p.flowStart,p.skelHeadByteLen+p.skelTailByteLen]}})),SKEL_T,null);
  const skelIdx=recs.length; for (const r of skelRecs) recs.push(r);
  const {record:cncxRec,offsets}=buildCncx(idxParts.map(p=>`P-//*[@aid='${p.firstAid}']`));
  const chunkRecs=buildIndxRecords(idxParts.map((p,i)=>({key:String(p.flowStart+p.skelHeadByteLen-1).padStart(10,'0'),tags:{2:[offsets[i]],3:[p.chapterIndex],4:[0],6:[p.flowStart+p.skelHeadByteLen+p.skelTailByteLen,p.contentByteLen]}})),CHUNK_T,cncxRec);
  const chunkIdx=recs.length; for (const r of chunkRecs) recs.push(r);
  const fdstRec=recs.length; recs.push(buildFdst([{start:0,end:hbo}]));
  const flisRec=recs.length; recs.push(FLIS_RECORD);
  const fcisRec=recs.length; recs.push(buildFcis(textLen)); recs.push(EOF_RECORD);
  const exthB=buildExth([{tag:503,value:title},{tag:501,value:'EBOK'},{tag:524,value:'en'}]);
  const titleB=enc.encode(title);
  const H=280; const h=new Uint8Array(H); const dv=new DataView(h.buffer);
  let p=0; dv.setUint16(p,1,false);p+=2;p+=2; dv.setUint32(p,textLen>>>0,false);p+=4;
  dv.setUint16(p,textRecs.length,false);p+=2; dv.setUint16(p,TEXT_RECORD_SIZE,false);p+=2;
  p+=4; h[p]=0x4d;h[p+1]=0x4f;h[p+2]=0x42;h[p+3]=0x49;p+=4;
  dv.setUint32(p,264,false);p+=4; dv.setUint32(p,2,false);p+=4; dv.setUint32(p,65001,false);p+=4;
  dv.setUint32(p,0xdeadbeef,false);p+=4; dv.setUint32(p,8,false);p+=4;
  dv.setUint32(p,0xffffffff,false);p+=4; dv.setUint32(p,0xffffffff,false);p+=4;
  for(let i=0;i<8;i++){dv.setUint32(p,0xffffffff,false);p+=4;}
  dv.setUint32(p,firstNonText,false);p+=4; dv.setUint32(p,H+exthB.length,false);p+=4;
  dv.setUint32(p,titleB.length,false);p+=4; dv.setUint32(p,9,false);p+=4;
  p+=8; dv.setUint32(p,8,false);p+=4; dv.setUint32(p,0xffffffff,false);p+=4;
  p+=16; dv.setUint32(p,0x50,false);p+=4; p+=32;
  dv.setUint32(p,0xffffffff,false);p+=4; dv.setUint32(p,0xffffffff,false);p+=4; p+=12; p+=8;
  dv.setUint32(p,fdstRec,false);p+=4; dv.setUint32(p,fdstRec,false);p+=4;
  dv.setUint32(p,fcisRec,false);p+=4; dv.setUint32(p,1,false);p+=4;
  dv.setUint32(p,flisRec,false);p+=4; dv.setUint32(p,1,false);p+=4;
  p+=8; dv.setUint32(p,0xffffffff,false);p+=4; p+=4;
  for(let i=0;i<8;i++) h[p++]=0xff;
  dv.setUint32(p,1,false);p+=4; dv.setUint32(p,0xffffffff,false);p+=4;
  dv.setUint32(p,chunkIdx,false);p+=4; dv.setUint32(p,skelIdx,false);p+=4;
  dv.setUint32(p,0xffffffff,false);p+=4; dv.setUint32(p,0xffffffff,false);p+=4;
  h[p]=0xff;h[p+1]=0xff;h[p+2]=0xff;h[p+3]=0xff;p+=4;p+=4;
  h[p]=0xff;h[p+1]=0xff;h[p+2]=0xff;h[p+3]=0xff;p+=4;p+=4;
  recs[0] = concat(h, exthB, titleB, fill(0,8192));
  return buildPalmDoc(title, recs);
}

function calibreMeta(path) {
  try { return execSync(`ebook-meta "${path}" 2>&1`, {encoding:'utf8'}); } catch(e) { return ''; }
}
function calibreConvert(from, to) {
  try { const r=execSync(`ebook-convert "${from}" "${to}" 2>&1`,{encoding:'utf8',timeout:60000}); return {ok:!r.includes('Traceback'),raw:r}; }
  catch(e) { return {ok:false,raw:e.message}; }
}

// ════════════════════════════════════════════════════════════════════════════
// TESTS
// ════════════════════════════════════════════════════════════════════════════

console.log('\n── VLQ encoding (Calibre convention) ─────────────────────────');
test('encint(0) = [0x80]',   () => { const r=encint(0);   eq(r[0],0x80); eq(r.length,1); });
test('encint(15) = [0x8f]',  () => { const r=encint(15);  eq(r[0],0x8f); eq(r.length,1); });
test('encint(127) = [0xff]', () => { const r=encint(127); eq(r[0],0xff); eq(r.length,1); });
test('encint(128) = [0x01,0x80]', () => { const r=encint(128); eq(r[0],0x01); eq(r[1],0x80); eq(r.length,2); });
test('encint(300) = [0x02,0xac]', () => { const r=encint(300); eq(r[0],0x02); eq(r[1],0xac); });
test('encint/decint roundtrip for 0..65535', () => {
  for (const v of [0,1,63,64,127,128,255,256,1000,4096,65535]) {
    const {val} = decint(encint(v)); eq(val, v, `roundtrip v=${v}`);
  }
});

console.log('\n── PalmDoc container ──────────────────────────────────────────');
test('magic = BOOKMOBI', () => {
  const d=buildPalmDoc('T',[new Uint8Array(4)]); eq(String.fromCharCode(...d.slice(60,68)),'BOOKMOBI');
});
test('record 0 offset = header size', () => {
  const recs=[new Uint8Array(10)]; const d=buildPalmDoc('T',recs);
  const nR=new DataView(d.buffer).getUint16(76,false);
  eq(new DataView(d.buffer).getUint32(78,false), 78+8*nR+2);
});
test('record offsets are sequential', () => {
  const recs=[new Uint8Array(100),new Uint8Array(200),new Uint8Array(50)];
  const d=buildPalmDoc('T',recs); const dv=new DataView(d.buffer);
  const nR=dv.getUint16(76,false); let exp=78+8*nR+2;
  for(let i=0;i<nR;i++){ eq(dv.getUint32(78+i*8,false),exp); exp+=recs[i].length; }
});
test('unique IDs = 0, 2, 4, …', () => {
  const d=buildPalmDoc('T',[new Uint8Array(1),new Uint8Array(1),new Uint8Array(1)]);
  for(let i=0;i<3;i++){
    const b=d.slice(78+i*8+5,78+i*8+8);
    eq((b[0]<<16)|(b[1]<<8)|b[2], 2*i, `uid rec ${i}`);
  }
});

console.log('\n── MOBI header ────────────────────────────────────────────────');
const CH = [{skelHead:'<html><body aid="0">\n',skelTail:'</body></html>\n',content:'<p aid="1">x</p>',firstAid:1}];
test('MOBI ident at offset +16 of record 0', () => {
  const a=buildAzw3(CH); const dv=new DataView(a.buffer);
  const r0=dv.getUint32(78,false); eq(String.fromCharCode(...a.slice(r0+16,r0+20)),'MOBI');
});
test('header_length = 264', () => {
  const a=buildAzw3(CH); const dv=new DataView(a.buffer);
  eq(dv.getUint32(dv.getUint32(78,false)+20,false),264);
});
test('file_version = 8 (KF8)', () => {
  const a=buildAzw3(CH); const dv=new DataView(a.buffer);
  eq(dv.getUint32(dv.getUint32(78,false)+36,false),8);
});
test('encoding = 65001 (UTF-8)', () => {
  const a=buildAzw3(CH); const dv=new DataView(a.buffer);
  eq(dv.getUint32(dv.getUint32(78,false)+28,false),65001);
});
test('EXTH magic at offset +280 of record 0', () => {
  const a=buildAzw3(CH); const dv=new DataView(a.buffer);
  const r0=dv.getUint32(78,false); eq(String.fromCharCode(...a.slice(r0+280,r0+284)),'EXTH');
});
test('title_offset points to actual title', () => {
  const a=buildAzw3(CH,'My Great Book'); const dv=new DataView(a.buffer);
  const r0=dv.getUint32(78,false);
  const off=dv.getUint32(r0+84,false), len=dv.getUint32(r0+88,false);
  eq(dec.decode(a.slice(r0+off,r0+off+len)),'My Great Book');
});

console.log('\n── EXTH metadata ──────────────────────────────────────────────');
test('EXTH record count correct', () => {
  const e=buildExth([{tag:503,value:'T'},{tag:100,value:'A'},{tag:524,value:'en'}]);
  eq(new DataView(e.buffer).getUint32(8,false),3);
});
test('EXTH tag 503 value readable', () => {
  const e=buildExth([{tag:503,value:'Hello World'}]);
  eq(new DataView(e.buffer).getUint32(12,false),503);
  const len=new DataView(e.buffer).getUint32(16,false);
  eq(dec.decode(e.slice(20,12+len)),'Hello World');
});

console.log('\n── FDST table ─────────────────────────────────────────────────');
test('FDST magic', () => eq(String.fromCharCode(...buildFdst([{start:0,end:1}]).slice(0,4)),'FDST'));
test('FDST section_start = 12', () => eq(new DataView(buildFdst([{start:0,end:1}]).buffer).getUint32(4,false),12));
test('FDST flows encoded correctly', () => {
  const f=buildFdst([{start:0,end:500},{start:500,end:800}]); const dv=new DataView(f.buffer);
  eq(dv.getUint32(8,false),2); eq(dv.getUint32(12,false),0); eq(dv.getUint32(16,false),500);
  eq(dv.getUint32(20,false),500); eq(dv.getUint32(24,false),800);
});

console.log('\n── FLIS / FCIS / EOF ──────────────────────────────────────────');
test('FLIS is 36 bytes, magic correct', () => { eq(FLIS_RECORD.length,36); eq(String.fromCharCode(...FLIS_RECORD.slice(0,4)),'FLIS'); });
test('FCIS magic correct', () => eq(String.fromCharCode(...buildFcis(1).slice(0,4)),'FCIS'));
test('FCIS text_length at offset 20', () => {
  const f=buildFcis(12345); eq(new DataView(f.buffer).getUint32(20,false),12345);
});
test('EOF = e9 8e 0d 0a', () => eq(Array.from(EOF_RECORD).join(','),'233,142,13,10'));

console.log('\n── Text record splitting ───────────────────────────────────────');
test('records ≤ 4097 bytes (4096 + trailing 0)', () => {
  for (const r of buildTextRecords('A'.repeat(10000))) assert(r.length<=TEXT_RECORD_SIZE+1,`too large: ${r.length}`);
});
test('trailing byte is always 0', () => {
  for (const r of buildTextRecords('Hello')) eq(r[r.length-1],0);
});
test('UTF-8 multibyte char not split across records', () => {
  // 4093 ASCII + emoji (4 bytes) + 10 ASCII = 4107 bytes
  // emoji starts at byte 4093, spans 4093-4096
  // record 1 should include the full emoji (end advances past continuation bytes)
  const text = 'A'.repeat(4093) + '😀' + 'B'.repeat(10);
  const bytes = enc.encode(text);
  assert(bytes.length === 4107, `expected 4107 bytes, got ${bytes.length}`);
  const recs = buildTextRecords(text);
  eq(recs.length, 2, 'should split into 2 records');
  // Record 0 (without trailing 0) must be valid UTF-8
  try { dec.decode(recs[0].slice(0,-1)); } catch(e) { throw new Error('Record 0 not valid UTF-8'); }
  // Record 0 should contain the full emoji
  contains(dec.decode(recs[0].slice(0,-1)), '😀', 'emoji should be in record 0');
  // Record 1 should contain the B's
  contains(dec.decode(recs[1].slice(0,-1)), 'BBBBBBBBBB', 'B chars in record 1');
});
test('all records concatenate back to original', () => {
  const orig = 'Hello! ' + 'X'.repeat(5000);
  const recs = buildTextRecords(orig);
  const combined = concat(...recs.map(r=>r.slice(0,-1))); // strip trailing 0s
  eq(dec.decode(combined), orig);
});

console.log('\n── CNCX encoding ──────────────────────────────────────────────');
test('CNCX entry readable by Calibre decint', () => {
  const sel = "P-//*[@aid='1']";
  const {record} = buildCncx([sel]);
  const {val:len, consumed} = decint(record);
  eq(len, sel.length);
  eq(dec.decode(record.slice(consumed, consumed+len)), sel);
});
test('CNCX multi-entry offsets correct', () => {
  const {offsets} = buildCncx(["P-//*[@aid='1']", "P-//*[@aid='42']"]);
  eq(offsets[0], 0);
  eq(offsets[1], 16); // 1 (VLQ byte for len=15) + 15 (string)
});
test('Calibre aidtext extraction [12:-2] works', () => {
  for (const [aid, exp] of [['1','1'],['42','42'],['100','100']]) {
    const sel = `P-//*[@aid='${aid}']`;
    eq(sel.slice(12,-2), exp, `aid=${aid}`);
  }
});

console.log('\n── Skeleton/chunk index keys ───────────────────────────────────');
test('chunk keys are unique across chapters with same skeleton', () => {
  // Two chapters with identical skeleton heads → different global insert positions
  const parts = [
    {skelHeadByteLen:131,skelTailByteLen:16,contentByteLen:200,flowStart:0,firstAid:1,chapterIndex:0,chunkCount:1},
    {skelHeadByteLen:131,skelTailByteLen:16,contentByteLen:150,flowStart:347,firstAid:5,chapterIndex:1,chunkCount:1},
  ];
  const keys = parts.map(p => String(p.flowStart+p.skelHeadByteLen-1).padStart(10,'0'));
  assert(keys[0] !== keys[1], `keys must differ: ${keys}`);
  eq(keys[0], '0000000130'); eq(keys[1], '0000000477');
});

console.log('\n── Integration: Calibre round-trip ────────────────────────────');

let aid=1;
const chapters5 = Array.from({length:5},(_,i)=>({
  skelHead:`<?xml version="1.0" encoding="UTF-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Ch${i+1}</title></head><body aid="0">\n`,
  skelTail:'</body></html>\n',
  content:`<h1 aid="${aid++}">Chapter ${i+1}</h1><p aid="${aid++}">Content of chapter ${i+1}. The quick brown fox jumped.</p>`,
  firstAid: aid-2,
}));
const azw3 = buildAzw3(chapters5, 'Five Chapter Test');
const azw3Path = '/tmp/test_five_chapters.azw3';
writeFileSync(azw3Path, azw3);

test('5-chapter AZW3: PDB magic', () => eq(String.fromCharCode(...azw3.slice(60,68)),'BOOKMOBI'));
test('5-chapter AZW3: Calibre reads metadata', () => {
  const out = calibreMeta(azw3Path);
  assert(out.includes('Title'), `Calibre meta failed: ${out.slice(0,200)}`);
  contains(out, 'Five Chapter Test');
});
test('5-chapter AZW3: converts to TXT, all chapters present', () => {
  const {ok, raw} = calibreConvert(azw3Path, '/tmp/test_five.txt');
  assert(ok, `TXT convert failed: ${raw.slice(0,400)}`);
  const txt = readFileSync('/tmp/test_five.txt','utf8');
  for (let i=1;i<=5;i++) contains(txt, `Chapter ${i}`);
});
test('5-chapter AZW3: chunk keys all unique', () => {
  let off=0;
  const keys = chapters5.map(ch=>{
    const hB=enc.encode(ch.skelHead).length;
    const k=String(off+hB-1).padStart(10,'0');
    off+=hB+enc.encode(ch.skelTail).length+enc.encode(ch.content).length;
    return k;
  });
  eq(new Set(keys).size, 5, `non-unique keys: ${keys}`);
});
test('5-chapter AZW3: skel_index and chunk_index != NULL', () => {
  const dv=new DataView(azw3.buffer);
  const r0=dv.getUint32(78,false);
  const skelIdx=dv.getUint32(r0+252,false), chunkIdx=dv.getUint32(r0+248,false);
  assert(skelIdx !== 0xffffffff, 'skel_index is NULL');
  assert(chunkIdx !== 0xffffffff, 'chunk_index is NULL');
});

// ── Results ─────────────────────────────────────────────────────────────────

console.log(`\n${'═'.repeat(60)}`);
console.log(`  ${passed} passed  ${failed} failed`);
if (failures.length) { console.log('\nFailed:'); for (const {name,error} of failures) console.log(`  ✗ ${name}\n    ${error}`); }
console.log();
if (failed > 0) process.exit(1);
