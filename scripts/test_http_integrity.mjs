import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';import crypto from 'node:crypto';import zlib from 'node:zlib';
const source=fs.readFileSync(new URL('../priority_shadow/dashboard/night-priority-card.js',import.meta.url),'utf8');
for(const mode of ['http','https','no-crypto-object']){
 let Card;const context={HTMLElement:class{attachShadow(){this.shadowRoot={innerHTML:'',querySelectorAll:()=>[],querySelector:()=>({})};}},localStorage:{getItem:()=>null},window:{},requestAnimationFrame:()=>{},customElements:{get:()=>Card,define:(_,v)=>Card=v},console,Date,Intl,Blob,DecompressionStream,TextDecoder,Uint8Array,atob,btoa};
 if(mode==='http')context.crypto={getRandomValues:crypto.webcrypto.getRandomValues.bind(crypto.webcrypto)};if(mode==='https')context.crypto=crypto.webcrypto;
 vm.createContext(context);vm.runInContext(source,context);const fallback=vm.runInContext('NIGHT_SHA256',context),digest=vm.runInContext('NIGHT_DIGEST',context),equal=vm.runInContext('NIGHT_EQUAL_JSON',context);
 for(const text of ['','abc','abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq','a'.repeat(1000000),'Žluťoučký kůň 🐢']){const bytes=Buffer.from(text),expected=crypto.createHash('sha256').update(bytes).digest('hex');assert.equal(fallback(bytes),expected);assert.equal(await digest(bytes),expected);}
 for(const size of [1,31,55,56,63,64,65,127,128,129,1023,65536,2097152]){const bytes=crypto.randomBytes(size),expected=crypto.createHash('sha256').update(bytes).digest('hex');assert.equal(fallback(bytes),expected);assert.equal(await digest(bytes),expected);}
 assert.equal(fallback(Buffer.from('abc')),'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
 assert(equal({a:1,b:{c:2,d:[1,2]}},{b:{d:[1,2],c:2},a:1}));assert(!equal({a:1,b:[1,2]},{a:1,b:[2,1]}));assert(!equal({a:1},{a:2}));assert(!equal({a:1},{a:1,b:null}));
 const card=new Card(),full={nested:{message:'české podklady '.repeat(3000)},number:42,flag:false};const raw=Buffer.from(JSON.stringify(full));const packed={packed_attributes:{encoding:'zlib-json-v1',sha256:crypto.createHash('sha256').update(raw).digest('hex'),unpacked_bytes:raw.length,data:zlib.deflateSync(raw).toString('base64')}};
 assert.deepEqual(JSON.parse(JSON.stringify(await card.decodedAttributes(packed))),full);
 await assert.rejects(()=>card.decodedAttributes({packed_attributes:{...packed.packed_attributes,sha256:'0'.repeat(64)}}));await assert.rejects(()=>card.decodedAttributes({packed_attributes:{...packed.packed_attributes,unpacked_bytes:raw.length-1}}));
 console.log('PASS:',mode,'SHA vectors/random boundary sizes, full decode, invalid hash/length rejection, semantic equality');
}
