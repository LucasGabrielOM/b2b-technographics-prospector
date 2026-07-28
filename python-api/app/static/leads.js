const byId = (id) => document.getElementById(id);
const state = { leads: [], filtered: [], identity: null, page: 1, perPage: 15, quick: 'all', selectedId: null };
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char]));
const initials = (value) => String(value || 'LP').split(/\s+/).filter(Boolean).slice(0,2).map((part) => part[0]).join('').toUpperCase();
const onlyDigits = (value) => String(value || '').replace(/\D/g,'');
const leadName = (lead) => lead.company_name || lead.domain || 'Lead sem nome';
const leadScore = (lead) => Number(lead.lead_score || 0);
const hasContact = (lead) => Boolean(lead.contact_whatsapp || lead.contact_email || lead.contact_phone);
const statusLabels = {discovered:'Novo',enriched:'Enriquecido',drafted:'Rascunho',approved:'Aprovado',sent:'Contatado',suppressed:'Suprimido'};
const temperatureLabels = {hot:'Quente',warm:'Morno',cold:'Frio'};

async function api(path, options = {}) {
  const response = await fetch(path, {credentials:'same-origin',headers:{'Content-Type':'application/json'},...options});
  if (!response.ok) {
    let message = `Erro ${response.status}`;
    try { message = (await response.json()).detail || message; } catch (_) {}
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function notify(message, error = false) {
  const notice = byId('notice');
  notice.textContent = message;
  notice.classList.toggle('hidden',!message);
  notice.style.borderColor = error ? '#f3c6ce' : '#bee9da';
  notice.style.background = error ? '#fff0f3' : '#edfbf6';
  notice.style.color = error ? '#9c3446' : '#0c7456';
}

function safeUrl(value, fallback = '#') {
  if (!value) return fallback;
  try {
    const url = new URL(/^https?:\/\//i.test(value) ? value : `https://${value}`);
    return ['http:','https:'].includes(url.protocol) ? url.href : fallback;
  } catch (_) { return fallback; }
}

function mapsUrl(lead) {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${leadName(lead)} ${lead.location || ''}`)}`;
}

function whatsappUrl(lead, message = '') {
  const digits = onlyDigits(lead.contact_whatsapp);
  if (![12,13].includes(digits.length) || digits.includes('0800')) return null;
  const base = lead.whatsapp_url || `https://api.whatsapp.com/send/?phone=${encodeURIComponent(`+${digits}`)}`;
  return message ? `${base}&text=${encodeURIComponent(message)}` : base;
}

function sourceUrl(lead) {
  const realDomain = lead.domain && !String(lead.domain).endsWith('.school') ? lead.domain : null;
  return safeUrl(lead.website_url || realDomain || lead.discovery_source, mapsUrl(lead));
}

function applyIdentity(identity) {
  state.identity = identity;
  document.body.dataset.role = identity.role;
  byId('profileName').textContent = identity.display_name;
  byId('profileRole').textContent = identity.is_admin ? 'Administrador' : 'Usuário comercial';
  byId('profileAvatar').textContent = initials(identity.display_name);
  byId('workspaceInitial').textContent = initials(identity.display_name).slice(0,1);
}

function defaultSubject(lead) {
  return lead.lead_type === 'school'
    ? `Tecnologia e automação para ${leadName(lead)}`
    : `Uma ideia para a operação da ${leadName(lead)}`;
}

function defaultMessage(lead) {
  const firstName = lead.contact_name ? ` ${lead.contact_name.split(/\s+/)[0]}` : '';
  if (lead.lead_type === 'school') {
    return `Olá${firstName}! Sou Lucas Gabriel, da equipe de projetos.\n\nTrabalhamos com soluções SaaS e automação para instituições de ensino, ajudando a organizar atendimento, processos e tarefas administrativas.\n\nGostaria de entender como a ${leadName(lead)} faz essa gestão hoje. Posso falar com a pessoa responsável por tecnologia ou administração?`;
  }
  if (lead.crm) {
    return `Olá${firstName}! Sou Lucas Gabriel, da equipe de projetos.\n\nIdentificamos sinais públicos de uso do ${lead.crm} na ${leadName(lead)}. Trabalhamos com integrações e automações para reduzir tarefas manuais e melhorar o acompanhamento comercial.\n\nPosso falar com a pessoa responsável pelo CRM ou pelos processos comerciais?`;
  }
  const publicSignal = lead.pain_summary
    ? '\n\nAo analisar sinais públicos de atendimento, vimos uma oportunidade de melhorar a organização dos canais e dos retornos, sem presumir detalhes internos da operação.'
    : '';
  return `Olá${firstName}! Sou Lucas Gabriel, da equipe de projetos.\n\nTrabalhamos com implantação de CRM e automação de atendimento para organizar retornos, tarefas e oportunidades.${publicSignal}\n\nPosso falar com a pessoa responsável pelos processos comerciais da ${leadName(lead)}?`;
}

function contactQuality(lead) {
  const channels = [];
  if (lead.contact_whatsapp) channels.push(['WhatsApp','verified']);
  if (lead.contact_email) channels.push(['E-mail','verified']);
  if (lead.contact_phone) channels.push(['Telefone','']);
  return channels;
}

function qualificationSummary(lead) {
  if (lead.lead_type === 'school') {
    if (lead.contact_email && lead.contact_name) return 'Escola privada, responsável e e-mail público';
    if (lead.contact_email) return 'Escola privada com e-mail público';
    if (lead.contact_phone) return 'Escola privada com telefone oficial';
    return 'Escola privada no INEP 2025';
  }
  if (lead.crm && lead.pain_summary) return `CRM ${lead.crm} e sinal público de dor`;
  if (lead.crm) return `CRM ${lead.crm} detectado`;
  if (lead.pain_summary) return 'Sinal público de oportunidade';
  return 'Aderência ao público-alvo';
}

function renderSummary() {
  const total = state.leads.length;
  const hot = state.leads.filter((lead) => lead.temperature === 'hot').length;
  const contacts = state.leads.filter(hasContact).length;
  const coverage = Math.round((contacts/(total||1))*100);
  byId('leadSummaryCards').innerHTML = [
    ['Total',total,'leads únicos'],['Prioridade',hot,'quentes'],['Cobertura',`${coverage}%`,'com contato'],
  ].map(([label,value,caption]) => `<article class="mini-stat"><span>${label}</span><strong>${value}</strong><small>${caption}</small></article>`).join('');
  byId('navLeadCount').textContent = total;
  byId('sidebarCoverage').textContent = `${coverage}% com contato`;
}

function applyFilters(resetPage = true) {
  const query = byId('search').value.trim().toLowerCase();
  const type = byId('leadType').value;
  const temperature = byId('temperature').value;
  const status = byId('status').value;
  state.filtered = state.leads.filter((lead) => {
    const searchable = [leadName(lead),lead.domain,lead.location,lead.sector,lead.crm,lead.contact_name,lead.contact_email,lead.contact_phone].join(' ').toLowerCase();
    const quickMatch = state.quick === 'all'
      || (state.quick === 'hot' && lead.temperature === 'hot')
      || (state.quick === 'contact' && hasContact(lead))
      || (state.quick === 'email' && Boolean(lead.contact_email))
      || (state.quick === 'pending' && lead.status !== 'sent');
    return (!query || searchable.includes(query)) && (!type || lead.lead_type === type) && (!temperature || lead.temperature === temperature) && (!status || lead.status === status) && quickMatch;
  }).sort((a,b) => {
    const qualityA = (a.contact_whatsapp?4:0)+(a.contact_email?3:0)+(a.contact_name?2:0)+(a.contact_phone?1:0);
    const qualityB = (b.contact_whatsapp?4:0)+(b.contact_email?3:0)+(b.contact_name?2:0)+(b.contact_phone?1:0);
    return leadScore(b)-leadScore(a) || qualityB-qualityA;
  });
  if (resetPage) state.page = 1;
  renderTable();
}

function leadRow(lead) {
  const channels = contactQuality(lead);
  const scoreColor = lead.temperature === 'hot' ? '#e99a2a' : lead.temperature === 'warm' ? '#4f8ff7' : '#c8d1da';
  const mainContact = lead.contact_name || lead.contact_email || 'Contato não localizado';
  const contactDetail = [
    lead.contact_whatsapp ? `WhatsApp: ${lead.contact_whatsapp}` : null,
    lead.contact_phone ? `Telefone: ${lead.contact_phone}` : null,
  ].filter(Boolean).join(' · ') || (lead.contact_role || 'Sem telefone público');
  return `<tr>
    <td><div class="company-cell"><span class="company-avatar">${escapeHtml(initials(leadName(lead)).slice(0,1))}</span><div><strong title="${escapeHtml(leadName(lead))}">${escapeHtml(leadName(lead))}</strong><small>${escapeHtml(lead.location || lead.sector || 'Local não informado')} · ${lead.lead_type === 'school' ? 'Escola' : 'Empresa'}</small></div></div></td>
    <td><div class="qualification"><span class="score-ring" style="--score-color:${scoreColor}">${leadScore(lead)}</span><div><strong>${escapeHtml(temperatureLabels[lead.temperature] || 'Revisar')}</strong><small>${escapeHtml(qualificationSummary(lead))}</small></div></div></td>
    <td><div class="contact-cell"><strong>${escapeHtml(mainContact)}</strong><small>${escapeHtml(contactDetail)}</small><div class="contact-badges">${channels.length ? channels.map(([label,kind]) => `<span class="contact-badge ${kind}">${label}</span>`).join('') : '<span class="contact-badge">Sem canal</span>'}</div></div></td>
    <td><span class="status ${escapeHtml(lead.status)}">${escapeHtml(statusLabels[lead.status] || 'Novo')}</span></td>
    <td><div class="row-actions"><button class="action primary" data-message="${lead.id}">${hasContact(lead) ? 'Preparar contato' : 'Revisar lead'}</button><button class="action" data-details="${lead.id}">Detalhes</button><button class="more-button" data-edit="${lead.id}" aria-label="Editar ${escapeHtml(leadName(lead))}">•••</button></div></td>
  </tr>`;
}

function renderTable() {
  const total = state.filtered.length;
  const pages = Math.max(1,Math.ceil(total/state.perPage));
  state.page = Math.min(state.page,pages);
  const start = (state.page-1)*state.perPage;
  const end = Math.min(start+state.perPage,total);
  byId('leadRows').innerHTML = state.filtered.slice(start,end).map(leadRow).join('');
  byId('empty').classList.toggle('hidden',total>0);
  byId('resultSummary').textContent = `${total} ${total===1?'oportunidade encontrada':'oportunidades encontradas'}`;
  byId('pageInfo').textContent = total ? `Exibindo ${start+1}–${end} de ${total}` : 'Nenhum resultado';
  byId('prevPage').disabled = state.page<=1;
  byId('nextPage').disabled = state.page>=pages;
}

function closeDrawer() {
  byId('leadDrawer').classList.remove('open');
  byId('leadDrawer').setAttribute('aria-hidden','true');
  byId('drawerBackdrop').classList.add('hidden');
}

function openDrawer(id) {
  const lead = state.leads.find((item) => Number(item.id)===Number(id));
  if (!lead) return;
  state.selectedId = lead.id;
  const reasons = Array.isArray(lead.score_reasons) ? lead.score_reasons : [];
  const evidence = Array.isArray(lead.evidence) ? lead.evidence : [];
  byId('drawerTitle').textContent = leadName(lead);
  byId('drawerSource').textContent = lead.website_url || (lead.lead_type==='school' ? `Cadastro ${lead.external_id || 'INEP'}` : lead.domain);
  byId('drawerSource').href = sourceUrl(lead);
  byId('drawerContent').innerHTML = `
    <div class="drawer-score">
      <div class="drawer-pill"><span>Potencial</span><strong>${leadScore(lead)}/100</strong></div>
      <div class="drawer-pill"><span>Prioridade</span><strong>${escapeHtml(temperatureLabels[lead.temperature] || 'Revisar')}</strong></div>
      <div class="drawer-pill"><span>Status</span><strong>${escapeHtml(statusLabels[lead.status] || 'Novo')}</strong></div>
    </div>
    <section class="detail-section"><h3>Oportunidade</h3><div class="detail-grid">
      <div class="detail-item"><span>Tipo</span><strong>${lead.lead_type==='school'?'Escola particular':'Empresa'}</strong></div>
      <div class="detail-item"><span>Localização</span><strong>${escapeHtml(lead.location || 'Não informada')}</strong></div>
      <div class="detail-item"><span>Oportunidade</span><strong>${escapeHtml(lead.opportunity_type || 'Prospecção consultiva')}</strong></div>
      <div class="detail-item"><span>CRM</span><strong>${escapeHtml(lead.crm || 'Não detectado')}</strong></div>
    </div></section>
    <section class="detail-section"><h3>Contato público</h3><div class="detail-grid">
      <div class="detail-item"><span>Responsável</span><strong>${escapeHtml(lead.contact_name || 'Não localizado')}</strong></div>
      <div class="detail-item"><span>Cargo</span><strong>${escapeHtml(lead.contact_role || 'Não informado')}</strong></div>
      <div class="detail-item"><span>E-mail</span><strong>${escapeHtml(lead.contact_email || 'Não localizado')}</strong></div>
      <div class="detail-item"><span>WhatsApp confirmado no site</span><strong>${escapeHtml(lead.contact_whatsapp || 'Não localizado')}</strong></div>
      <div class="detail-item"><span>Telefone público</span><strong>${escapeHtml(lead.contact_phone || 'Não localizado')}</strong></div>
    </div></section>
    ${lead.pain_summary ? `<section class="detail-section"><h3>Sinal identificado</h3><p class="detail-copy">${escapeHtml(lead.pain_summary)}</p>${lead.pain_source?`<a href="${safeUrl(lead.pain_source)}" target="_blank" rel="noopener">Ver fonte pública →</a>`:''}</section>`:''}
    <section class="detail-section"><h3>Por que recebeu essa nota?</h3><div class="reason-list">${reasons.length?reasons.map((reason)=>`<div class="reason">${escapeHtml(reason)}</div>`).join(''):'<div class="reason">Pontuação baseada em contato, aderência e fontes públicas.</div>'}</div></section>
    <section class="detail-section"><h3>Fontes consultadas</h3><div class="reason-list">${evidence.length?evidence.map((item)=>`<div class="reason">${escapeHtml(item.technology || item.type || 'Fonte pública')} · ${escapeHtml(item.source || lead.discovery_source || '')}</div>`).join(''):`<div class="reason">${escapeHtml(lead.discovery_source || 'Fonte não informada')}</div>`}</div></section>
    ${lead.notes?`<section class="detail-section"><h3>Observações</h3><p class="detail-copy">${escapeHtml(lead.notes)}</p></section>`:''}`;
  const directWhatsapp = whatsappUrl(lead,lead.email_body || defaultMessage(lead));
  byId('drawerActions').innerHTML = `<button class="button button-primary" data-message="${lead.id}">${hasContact(lead)?'Preparar contato':'Revisar contato'}</button>${directWhatsapp?`<a class="button button-whatsapp" href="${directWhatsapp}" target="_blank" rel="noopener">Abrir WhatsApp direto</a>`:''}<a class="button button-light" href="${mapsUrl(lead)}" target="_blank" rel="noopener">Ver no Maps</a><button class="button button-light" data-edit="${lead.id}">Editar lead</button>${lead.status==='sent'?`<button class="button button-light" data-reopen="${lead.id}">Reabrir</button>`:''}`;
  byId('drawerBackdrop').classList.remove('hidden');
  byId('leadDrawer').classList.add('open');
  byId('leadDrawer').setAttribute('aria-hidden','false');
}

function openEditor(id) {
  const lead = state.leads.find((item)=>Number(item.id)===Number(id));
  if (!lead) return;
  closeDrawer();
  byId('leadId').value = lead.id;
  byId('editTitle').textContent = leadName(lead);
  byId('companyName').value = lead.company_name || '';
  byId('sector').value = lead.sector || '';
  byId('contactName').value = lead.contact_name || '';
  byId('contactRole').value = lead.contact_role || '';
  byId('contactEmail').value = lead.contact_email || '';
  byId('contactWhatsapp').value = lead.contact_whatsapp || '';
  byId('contactPhone').value = lead.contact_phone || '';
  byId('notes').value = lead.notes || '';
  byId('leadEditor').showModal();
}

function updateMessageActions(lead) {
  const body = byId('messageBody').value;
  const subject = byId('messageSubject').value;
  const whatsapp = whatsappUrl(lead,body);
  const emailAction = byId('emailAction');
  const whatsappAction = byId('whatsappAction');
  const phoneAction = byId('phoneAction');
  emailAction.classList.toggle('hidden',!lead.contact_email);
  whatsappAction.classList.toggle('hidden',!whatsapp);
  phoneAction.classList.toggle('hidden',!lead.contact_phone);
  if (lead.contact_email) emailAction.href = `mailto:${encodeURIComponent(lead.contact_email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  if (whatsapp) whatsappAction.href = whatsapp;
  if (lead.contact_phone) phoneAction.href = `tel:${onlyDigits(lead.contact_phone)}`;
  const available = [lead.contact_whatsapp&&'WhatsApp',lead.contact_email&&'e-mail',lead.contact_phone&&'telefone'].filter(Boolean);
  byId('messageChannel').textContent = available.length ? `Disponível: ${available.join(', ')}` : 'Nenhum canal confirmado';
  byId('messageCount').textContent = `${body.length} caracteres`;
  byId('contactWarning').classList.toggle('hidden',available.length>0);
  byId('contactWarning').textContent = available.length ? '' : 'Este lead ainda não tem WhatsApp, e-mail ou telefone confirmado. Edite os dados antes de enviar.';
}

function openMessage(id) {
  const lead = state.leads.find((item)=>Number(item.id)===Number(id));
  if (!lead) return;
  closeDrawer();
  byId('messageLeadId').value = lead.id;
  byId('messageTitle').textContent = leadName(lead);
  byId('messageSubject').value = lead.email_subject || defaultSubject(lead);
  byId('messageBody').value = lead.email_body || defaultMessage(lead);
  updateMessageActions(lead);
  byId('messageDialog').showModal();
}

async function saveMessage(showNotice = true) {
  const id = byId('messageLeadId').value;
  const lead = state.leads.find((item)=>Number(item.id)===Number(id));
  if (!lead) return;
  const payload = {email_subject:byId('messageSubject').value||null,email_body:byId('messageBody').value||null};
  const updated = await api(`/api/v1/leads/${id}`,{method:'PATCH',body:JSON.stringify(payload)});
  Object.assign(lead,updated);
  if (showNotice) notify('Mensagem salva como rascunho.');
}

async function markContacted(id, channel) {
  try {
    await api(`/api/v1/leads/${id}/mark-contacted`,{method:'POST',body:JSON.stringify({channel})});
    await loadLeads(false); notify('Contato registrado no pipeline.');
  } catch (error) { notify(error.message,true); }
}

async function reopenLead(id) {
  try { await api(`/api/v1/leads/${id}/reopen`,{method:'POST'}); closeDrawer(); await loadLeads(false); notify('Lead reaberto.'); }
  catch (error) { notify(error.message,true); }
}

async function loadLeads(openFromUrl = true) {
  byId('refresh').disabled = true;
  try {
    state.leads = await api('/api/v1/leads?limit=1000');
    renderSummary(); applyFilters(false);
    byId('lastUpdate').textContent = `Atualizado às ${new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})}`;
    if (openFromUrl) {
      const id = new URLSearchParams(location.search).get('lead');
      if (id) openDrawer(id);
    }
  } catch (error) { notify(`Não foi possível carregar os leads: ${error.message}`,true); }
  finally { byId('refresh').disabled = false; }
}

function resetFilters() {
  byId('filters').reset(); state.quick='all';
  document.querySelectorAll('.quick').forEach((button)=>button.classList.toggle('active',button.dataset.quick==='all'));
  applyFilters();
}

function handleActions(event) {
  const target = event.target.closest('[data-details],[data-edit],[data-message],[data-reopen]');
  if (!target) return;
  if (target.dataset.details) openDrawer(target.dataset.details);
  if (target.dataset.edit) openEditor(target.dataset.edit);
  if (target.dataset.message) openMessage(target.dataset.message);
  if (target.dataset.reopen) reopenLead(target.dataset.reopen);
}

function exportCsv() {
  const columns=['Nome','Tipo','Identificador','Local','Score','Prioridade','Responsável','E-mail','WhatsApp','Telefone','Status'];
  const rows=state.filtered.map((lead)=>[leadName(lead),lead.lead_type,lead.external_id||lead.domain,lead.location,leadScore(lead),lead.temperature,lead.contact_name,lead.contact_email,lead.contact_whatsapp,lead.contact_phone,lead.status]);
  const csv=[columns,...rows].map((row)=>row.map((value)=>`"${String(value??'').replace(/"/g,'""')}"`).join(',')).join('\n');
  const url=URL.createObjectURL(new Blob([`\ufeff${csv}`],{type:'text/csv;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download=`leads-${new Date().toISOString().slice(0,10)}.csv`;link.click();URL.revokeObjectURL(url);
}

function toggleMobileMenu(open) {
  byId('sidebar').classList.toggle('open',open);
  byId('mobileOverlay').classList.toggle('hidden',!open);
}

byId('search').addEventListener('input',()=>applyFilters());
byId('leadType').addEventListener('change',()=>applyFilters());
byId('temperature').addEventListener('change',()=>applyFilters());
byId('status').addEventListener('change',()=>applyFilters());
byId('clearFilters').addEventListener('click',resetFilters);
byId('emptyClear').addEventListener('click',resetFilters);
document.querySelectorAll('.quick').forEach((button)=>button.addEventListener('click',()=>{state.quick=button.dataset.quick;document.querySelectorAll('.quick').forEach((item)=>item.classList.toggle('active',item===button));applyFilters();}));
byId('prevPage').addEventListener('click',()=>{if(state.page>1){state.page-=1;renderTable();}});
byId('nextPage').addEventListener('click',()=>{if(state.page*state.perPage<state.filtered.length){state.page+=1;renderTable();}});
byId('refresh').addEventListener('click',()=>loadLeads(false));
byId('exportCsv').addEventListener('click',exportCsv);
byId('leadRows').addEventListener('click',handleActions);
byId('drawerActions').addEventListener('click',handleActions);
byId('closeDrawer').addEventListener('click',closeDrawer);
byId('drawerBackdrop').addEventListener('click',closeDrawer);
byId('menuToggle').addEventListener('click',()=>toggleMobileMenu(true));
byId('mobileOverlay').addEventListener('click',()=>toggleMobileMenu(false));
byId('closeEditor').addEventListener('click',()=>byId('leadEditor').close());
byId('cancelEdit').addEventListener('click',()=>byId('leadEditor').close());
byId('editForm').addEventListener('submit',async(event)=>{
  event.preventDefault();
  const id=byId('leadId').value;
  const payload={company_name:byId('companyName').value||null,sector:byId('sector').value||null,contact_name:byId('contactName').value||null,contact_role:byId('contactRole').value||null,contact_email:byId('contactEmail').value||null,contact_whatsapp:byId('contactWhatsapp').value||null,contact_phone:byId('contactPhone').value||null,notes:byId('notes').value||null};
  try { await api(`/api/v1/leads/${id}`,{method:'PATCH',body:JSON.stringify(payload)}); byId('leadEditor').close(); await loadLeads(false); notify('Lead atualizado com sucesso.'); }
  catch (error) { notify(error.message,true); }
});
byId('closeMessage').addEventListener('click',()=>byId('messageDialog').close());
byId('messageBody').addEventListener('input',()=>{const lead=state.leads.find((item)=>Number(item.id)===Number(byId('messageLeadId').value));if(lead)updateMessageActions(lead);});
byId('messageSubject').addEventListener('input',()=>{const lead=state.leads.find((item)=>Number(item.id)===Number(byId('messageLeadId').value));if(lead)updateMessageActions(lead);});
byId('saveDraft').addEventListener('click',async()=>{try{await saveMessage();}catch(error){notify(error.message,true);}});
['emailAction','whatsappAction','phoneAction'].forEach((id)=>byId(id).addEventListener('click',async()=>{
  const leadId=byId('messageLeadId').value;
  const channel=id==='emailAction'?'email':id==='whatsappAction'?'whatsapp':'phone';
  try { await saveMessage(false); window.setTimeout(()=>markContacted(leadId,channel),350); } catch(error) { notify(error.message,true); }
}));
byId('logoutBtn').addEventListener('click',async()=>{try{await api('/api/v1/auth/logout',{method:'POST'});}finally{location.replace('/login');}});

(async function start(){
  try {
    applyIdentity(await api('/api/v1/auth/me'));
    const params = new URLSearchParams(location.search);
    const quick = params.get('quick');
    if (['hot','contact','email','pending'].includes(quick)) {
      state.quick=quick;
      document.querySelectorAll('.quick').forEach((item)=>item.classList.toggle('active',item.dataset.quick===quick));
    }
    await loadLeads();
    window.setInterval(()=>loadLeads(false),90000);
  } catch (_) { location.replace('/login?next=/leads'); }
})();
