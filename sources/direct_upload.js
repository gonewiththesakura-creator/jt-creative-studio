// Upload credentials remain on the server. This page transfers file chunks only
// to its own authenticated API and resumes an interrupted finalization in place.
const accountMediaUploads=new WeakMap();
async function sendAccountMediaFile(url,file,onProgress){
  const query=new URL(url,location.origin).searchParams,scope=[query.get('workflow'),query.get('input_key')].join(':');
  let uploads=accountMediaUploads.get(file);if(!uploads){uploads=new Map();accountMediaUploads.set(file,uploads)}
  let upload=uploads.get(scope);
  if(!upload){
    const result=await api('/api/upload-start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workflow:query.get('workflow'),input_key:query.get('input_key'),filename:file.name,size:file.size}),signal:AbortSignal.timeout(20000)});
    upload={id:result.upload_id,offset:0};uploads.set(scope,upload);
  }
  try{
    const chunkSize=512*1024;
    while(upload.offset<file.size){
      const end=Math.min(file.size,upload.offset+chunkSize),body=file.slice(upload.offset,end);
      const result=await api('/api/upload-chunk?'+new URLSearchParams({id:upload.id,offset:upload.offset}),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body,signal:AbortSignal.timeout(130000)});
      if(!Number.isInteger(result.offset)||result.offset<=upload.offset||result.offset>file.size)throw Error('上传进度校验失败，请重新选择文件');
      upload.offset=result.offset;onProgress(Math.min(99,Math.floor(upload.offset/file.size*100)));
    }
    onProgress(100);
    const deadline=Date.now()+240000;
    while(Date.now()<deadline){
      const result=await api('/api/upload-finish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({upload_id:upload.id}),signal:AbortSignal.timeout(20000)});
      if(result.uploadToken)return result;
      if(result.status==='error'){uploads.delete(scope);throw Error(result.error||'文件接收失败，请点击继续上传重试')}
      if(result.status!=='processing')throw Error('上传结果尚未确认，请点击继续上传核对');
      await new Promise(resolve=>setTimeout(resolve,1200));
    }
    throw Error('文件接收仍在处理中，请点击继续上传核对');
  }catch(error){if([400,404,410].includes(error.status))uploads.delete(scope);throw error}
}
