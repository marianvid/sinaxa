"use strict";

$('newProject').onclick=newProject;
$('newSeat').onclick=newSeat;
$('newSession').onclick=createSession;
$('newSessionSmall').onclick=createSession;
$('openMain').onclick=()=>{let team=project()?.sessions.find(x=>x.kind==='team');if(team){sessionId=team.id;selected.clear();refresh()}};
$('toggleProject').onclick=async()=>{let p=project();await api('/api/projects/'+p.id,{method:'PATCH',body:body({state:p.state==='open'?'closed':'open'})});refresh()};
$('clearContext').onclick=async()=>{if(!sessionId)return;await api(`/api/sessions/${sessionId}/context`,{method:'POST',body:body({project:projectId})});await refresh()};
$('clearClosedHistory').onclick=clearAllClosedHistory;
$('sessionMenu').onclick=()=>{let s=session();form('Manage session',`<p>${esc(s.name)} · ${size(s.storage)}</p><label>Agent response timeout (seconds)<input type="number" name="turn_timeout" min="30" max="7200" value="${s.turn_timeout||1800}"></label><label>Maximum agent turns per round<input type="number" name="max_agent_turns" min="1" max="100" value="${s.max_agent_turns||100}"></label>${s.kind==='custom'?'<label><input type="checkbox" name="archive" '+(s.archived?'checked':'')+'> Archived</label><label class="danger"><input type="checkbox" name="remove"> Delete session and all history</label>':''}`,async f=>{if(f.get('remove'))return api(`/api/sessions/${s.id}?project=${projectId}`,{method:'DELETE'}).then(()=>sessionId=null);await api('/api/sessions/'+s.id,{method:'PATCH',body:body({project:projectId,turn_timeout:+f.get('turn_timeout'),max_agent_turns:+f.get('max_agent_turns'),...(s.kind==='custom'?{archived:!!f.get('archive')}:{})})})})};

let searchTimer;
$('search').oninput=()=>{clearTimeout(searchTimer);windowKey='';searchTimer=setTimeout(refresh,250)};
$('messages').onscroll=()=>{let box=$('messages');if(box.scrollTop<80)loadOlder();if(box.scrollHeight-box.scrollTop-box.clientHeight<80)hasNewer?loadNewer():maybeMarkRead()};
window.addEventListener('focus',maybeMarkRead);
document.addEventListener('visibilitychange',maybeMarkRead);

$('attach').onclick=()=>$('files').click();
$('files').onchange=()=>{pending.push(...$('files').files);renderAttachments()};
function renderAttachments(){$('attachments').innerHTML=pending.map((f,i)=>`<span class="attachment">${esc(f.name)} <button data-drop="${i}">×</button></span>`).join('');document.querySelectorAll('[data-drop]').forEach(x=>x.onclick=()=>{pending.splice(+x.dataset.drop,1);renderAttachments()})}
document.querySelectorAll('[data-format]').forEach(button=>button.onclick=()=>{let target=$('message'),mark=button.dataset.format,start=target.selectionStart,end=target.selectionEnd;target.setRangeText(mark+target.value.slice(start,end)+mark,start,end,'end');target.focus()});
function readFile(file){return new Promise((resolve,reject)=>{let reader=new FileReader;reader.onload=()=>resolve({type:file.type,data:reader.result.split(',')[1]});reader.onerror=reject;reader.readAsDataURL(file)})}
$('send').onclick=async()=>{let text=$('message').value.trim();if(!text&&!pending.length)return;let images=await Promise.all(pending.map(readFile));$('message').value='';pending=[];renderAttachments();await api('/api/say',{method:'POST',body:body({project:projectId,session:sessionId,text,images})});refresh();startPoll()};
$('message').onkeydown=event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();$('send').click()}};
function startPoll(){clearInterval(poll);let quiet=0;poll=setInterval(async()=>{let before=(data.messages||[]).length;await refresh();let busy=data.status?.busy?.length;if(!busy&&(data.messages||[]).length===before)quiet++;else quiet=0;if(quiet>2){clearInterval(poll);poll=null}},800)}
document.addEventListener('click',event=>{if(event.target.matches('dialog button[value="cancel"]')){event.preventDefault();event.target.closest('dialog').close('cancel')}});

refresh();
