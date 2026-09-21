import {parse} from 'acorn';
let code='';for await(const chunk of process.stdin)code+=chunk;
code=JSON.parse(code);
const ast=parse(code,{ecmaVersion:'latest',sourceType:'module'}),found=[];
function walk(node){
 if(!node||typeof node!=='object')return;
 if(['ImportDeclaration','ExportNamedDeclaration','ExportAllDeclaration','ImportExpression'].includes(node.type)&&node.source?.type==='Literal')found.push([[...code.slice(0,node.source.start)].length,[...code.slice(0,node.source.end)].length,node.source.value]);
 for(const value of Object.values(node)){if(Array.isArray(value))value.forEach(walk);else if(value&&typeof value==='object')walk(value)}
}
walk(ast);process.stdout.write(JSON.stringify(found));
