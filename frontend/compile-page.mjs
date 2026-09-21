// Build-time adaptation only. Runtime uses native modules, never eval/with.
import {parse} from 'acorn';
import {analyze} from 'eslint-scope';
let input='';for await(const chunk of process.stdin)input+=chunk;
const {code,ids,creator,styleLoader}=JSON.parse(input);
const tree=parse(code,{ecmaVersion:2022,ranges:true});
const edits=[];
for(const node of tree.body){
  if(node.type==='FunctionDeclaration'&&['scheduleRoutePrefetch','scheduleStylePreviewPreload'].includes(node.id.name))
    edits.push([node.body.start,node.body.end,'{}']);
  if(creator&&node.type==='FunctionDeclaration'&&node.id.name==='loadStyleConfigs')
    edits.push([node.start,node.end,styleLoader]);
  if(creator&&node.type==='FunctionDeclaration'&&node.id.name==='applySnapshot'){
    edits.push([node.id.start,node.id.end,'applyLoadedSnapshot']);
  }
}
let adapted=code;
for(const [start,end,text] of edits.sort((a,b)=>b[0]-a[0]))adapted=adapted.slice(0,start)+text+adapted.slice(end);
const ast=parse(adapted,{ecmaVersion:2022,ranges:true,sourceType:'module'});
const scopes=analyze(ast,{ecmaVersion:2022,sourceType:'module'});
const names=[...new Set(scopes.globalScope.through.map(r=>r.identifier.name))].filter(n=>ids.includes(n));
const bindings=names.map(n=>`const ${n}=document.getElementById(${JSON.stringify(n)});`).join('\n');
process.stdout.write(`export function mount({document,window,fetch,location}){\n${bindings}\n${adapted}\nreturn {styleBoot:${creator?'STYLE_BOOT':'null'}};\n}`);
