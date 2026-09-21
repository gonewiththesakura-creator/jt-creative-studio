import fs from 'node:fs';
import {parse} from 'acorn';
const root=new URL('../',import.meta.url),manifest=JSON.parse(fs.readFileSync(new URL('static/app-manifest.json',root),'utf8'));
let count=0;
for(const [route,name] of [['/','index'],['/realism','realism'],['/video','video']]){
 const html=fs.readFileSync(new URL(`static/${name}.html`,root),'utf8');
 const source=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n');
 const output=fs.readFileSync(new URL(manifest.pages[route].module.slice(1),root),'utf8');
 const before=parse(source,{ecmaVersion:2022}),after=parse(output,{ecmaVersion:2022,sourceType:'module'}).body[0].declaration.body;
 const functions=new Map(after.body.filter(n=>n.type==='FunctionDeclaration').map(n=>[n.id.name,output.slice(n.start,n.end)]));
 for(const node of before.body.filter(n=>n.type==='FunctionDeclaration')){
  const name=node.id.name;
  if(['loadStyleConfigs','applySnapshot','scheduleRoutePrefetch','scheduleStylePreviewPreload'].includes(name))continue;
  if(source.slice(node.start,node.end).replaceAll('\r\n','\n')!==functions.get(name)?.replaceAll('\r\n','\n'))throw Error(`Business function changed: ${route} ${name}`);
  count++;
 }
}
console.log(`${count} business function bodies unchanged by packaging`);
