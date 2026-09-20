// Execute the production clock expression at several frame rates.
import fs from 'node:fs';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../static/singularity/workbench.js',import.meta.url),'utf8');
const expression=source.match(/const dt=([^;]+);last=now;/)[1];
const step=new Function('now','last',`return ${expression}`);
for(const fps of [60,30,10,5]){
 let time=0,last=1000;
 for(let i=1;i<=fps*10;i++){const now=1000+i*1000/fps;time+=step(now,last);last=now;}
 assert.ok(Math.abs(time-10)<.001,`${fps} fps advances ${time}s instead of 10s`);
}
console.log('Production animation clock preserves elapsed time at 5–60 fps');
