'use strict';

const state = { leads: [], filtered: [], page: 1, perPage: 15, quick: 'all', selectedId: null, identity: null, users: [] };
const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[char]));
const onlyDigits = (value) => String(value || '').replace(/\D/g, '');
const leadName = (lead) => lead.company_name || lead.company || lead.domain || 'Lead sem nome';
const leadScore = (lead) => Number(lead.lead_score ?? lead.score ?? 0);
const hasContact = (lead) => Boolean(lead.contact_whatsapp || lead.contact_email || lead.contact_phone);
const initials = (value) => String(value || 'LP').split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase();
const statusLabels = { discovered:'Novo', enriched:'Enriquecido', drafted:'Rascunho', approved:'Aprovado', sent:'Contatado', suppressed:'Suprimido' };
const temperatureLabels = { hot:'Quente', warm:'Morno', cold:'Frio' };

function safeUrl(value, fallback = '#') {
  if (!value) return fallback;
  try {
    const url = new URL(String(value).startsWith('http') ? value : `https://${value}`);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : fallback;
  } catch (_) { return fallback; }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    headers: { 'Content-Type':'application/json', ...(options.headers || {}) },
  });
  if (!response.ok) {
    let message = `Erro ${response.status}`;
    try { message = (await response.json()).detail || message; } catch (_) {}
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

function notify(message, error = false) {
  const notice = byId('notice');
  notice.textContent = message;
  notice.className = `notice${error ? ' error' : ''}`;
  window.setTimeout(() => notice.classList.add('hidden'), 4200);
}

function applyIdentity(identity) {
  state.identity = identity;
  document.body.dataset.role = identity.role;
  byId('profileName').textContent = identity.display_name || identity.username;
  byId('profileRole').textContent = identity.is_admin ? 'Administrador' : 'Usuário comercial';
  byId('profileAvatar').textContent = initials(identity.display_name || identity.username);
  byId('workspaceInitial').textContent = initials(identity.display_name || identity.username).slice(0, 1);
  if (identity.is_admin) {
    byId('heroEyebrow').textContent = 'VISÃO DO ADMINISTRADOR';
    byId('heroTitle').textContent = 'Sua operação comercial, inteira em uma única visão.';
    byId('heroSubtitle').textContent = 'Acompanhe volume, qualidade, cobertura de contatos e o trabalho da equipe sem perder o contexto de cada oportunidade.';
  } else {
    byId('heroEyebrow').textContent = 'MINHA ÁREA COMERCIAL';
    byId('heroTitle').textContent = `Olá, ${(identity.display_name || identity.username).split(' ')[0]}. Sua fila está pronta.`;
    byId('heroSubtitle').textContent = 'Comece pelos leads prioritários, registre cada abordagem e mantenha sua rotina organizada.';
  }
}

function icon(name) {
  const icons = {
    leads:'<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0m2-12v6m-3-3h6"/></svg>',
    hot:'<svg viewBox="0 0 24 24"><path d="M12 22c4 0 7-3 7-7 0-3-2-5-4-7 0 3-2 4-3 4 1-5-2-8-5-10 0 5-3 7-3 12 0 4 3 8 8 8z"/></svg>',
    contact:'<svg viewBox="0 0 24 24"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/></svg>',
    sent:'<svg viewBox="0 0 24 24"><path d="m4 12 5 5L20 6"/></svg>',
  };
  return icons[name] || icons.leads;
}

function renderStats() {
  const leads = state.leads;
  const contacts = leads.filter(hasContact).length;
  const hot = leads.filter((lead) => lead.temperature === 'hot').length;
  const sent = leads.filter((lead) => lead.status === 'sent').length;
  const coverage = Math.round((contacts / (leads.length || 1)) * 100);
  const cards = [
    ['Leads na base', leads.length, 'oportunidades únicas', 'leads', '#4f8ff7', '#eaf2ff'],
    ['Alta prioridade', hot, 'prontos para revisão', 'hot', '#e49621', '#fff4df'],
    ['Com contato', contacts, `${coverage}% de cobertura`, 'contact', '#35c99a', '#e2f8f0'],
    ['Já contatados', sent, 'abordagens registradas', 'sent', '#7b61e8', '#efebff'],
  ];
  byId('stats').innerHTML = cards.map(([label,value,detail,iconName,tone,soft]) => `
    <article class="metric" style="--tone:${tone};--tone-soft:${soft}">
      <div class="metric-head"><span class="metric-label">${label}</span><span class="metric-icon">${icon(iconName)}</span></div>
      <strong>${value}</strong><small>${detail}</small>
    </article>`).join('');
  byId('navLeadCount').textContent = leads.length;
  byId('heroLeadCount').textContent = leads.length;
  byId('heroHotCount').textContent = `${hot} quentes`;
  byId('heroCoverage').textContent = `${coverage}%`;
}

function bestReason(lead) {
  const reasons = Array.isArray(lead.score_reasons) ? lead.score_reasons : [];
  const useful = reasons.find((reason) => /responsável|CNPJ|CRM|telefone|e-mail|dor|oportunidade/i.test(reason));
  return useful || lead.pain_summary || (lead.lead_type === 'school'
    ? 'Escola particular ativa em base oficial, com canal público para contato.'
    : 'Lead qualificado com dados públicos e contexto comercial disponível.');
}

function contactLabel(lead) {
  if (lead.contact_whatsapp) return 'WhatsApp disponível';
  if (lead.contact_email) return 'E-mail disponível';
  if (lead.contact_phone) return 'Telefone disponível';
  return 'Contato em validação';
}

function renderFocus() {
  const candidates = state.leads.filter(hasContact).sort((a,b) => leadScore(b) - leadScore(a)).slice(0,3);
  byId('focusLeads').innerHTML = candidates.length ? candidates.map((lead) => `
    <article class="focus-card">
      <div class="focus-top">
        <div class="focus-company"><span class="company-logo">${escapeHtml(initials(leadName(lead)).slice(0,1))}</span><div><strong>${escapeHtml(leadName(lead))}</strong><span>${escapeHtml(lead.location || lead.sector || 'Local não informado')}</span></div></div>
        <span class="score-badge"><i></i>${leadScore(lead)} pts</span>
      </div>
      <p class="focus-reason">${escapeHtml(bestReason(lead))}</p>
      <div class="focus-foot"><span class="focus-contact">${icon('contact')}${escapeHtml(contactLabel(lead))}</span><button class="focus-action" data-details="${lead.id}">Ver oportunidade →</button></div>
    </article>`).join('') : '<article class="focus-card"><p class="focus-reason">Nenhuma oportunidade com contato disponível nesta visualização.</p></article>';
}

function renderCharts() {
  const leads = state.leads;
  const total = leads.length || 1;
  const stages = [
    ['Mapeados', leads.length, '#4f8ff7'],
    ['Com contato', leads.filter(hasContact).length, '#35c99a'],
    ['Quentes', leads.filter((lead) => lead.temperature === 'hot').length, '#e49621'],
    ['Contatados', leads.filter((lead) => lead.status === 'sent').length, '#7b61e8'],
  ];
  byId('pipelineChart').innerHTML = stages.map(([label,value,color]) => {
    const percentage = Math.round((value / total) * 100);
    return `<div class="stage"><div class="stage-label"><span>${label}</span><strong>${value}</strong></div><div class="stage-bar"><i style="--bar:${color};--w:${percentage}%"></i></div><small>${percentage}% da base</small></div>`;
  }).join('');
  const contacts = leads.filter(hasContact).length;
  const coverage = Math.round((contacts / total) * 100);
  const channels = [
    ['WhatsApp', leads.filter((lead) => lead.contact_whatsapp).length, '#35c99a'],
    ['E-mail', leads.filter((lead) => lead.contact_email).length, '#7b61e8'],
    ['Telefone', leads.filter((lead) => lead.contact_phone).length, '#4f8ff7'],
  ];
  byId('channelsChart').innerHTML = `<div class="donut" style="--pct:${coverage}%"><div><strong>${coverage}%</strong><span>COBERTURA</span></div></div><div class="channel-list">${channels.map(([label,value,color]) => `<div class="channel-item"><span><i style="background:${color}"></i>${label}</span><strong>${value}</strong></div>`).join('')}</div>`;
  const mix = {};
  leads.forEach((lead) => {
    const label = lead.lead_type === 'school' ? 'Escolas' : (lead.sector || 'Outros');
    mix[label] = (mix[label] || 0) + 1;
  });
  const rows = Object.entries(mix).sort((a,b) => b[1] - a[1]).slice(0,6);
  const max = Math.max(1, ...rows.map((row) => row[1]));
  byId('mixChart').innerHTML = rows.map(([label,count]) => `<div class="mix-row"><span title="${escapeHtml(label)}">${escapeHtml(label)}</span><div class="mix-track"><i style="--w:${Math.round(count/max*100)}%"></i></div><strong>${count}</strong></div>`).join('');
}

function outreachMessage(lead) {
  if (lead.lead_type === 'school') return `Olá! Sou Lucas Gabriel, da equipe de projetos. Trabalhamos com soluções SaaS e automação para instituições de ensino. Posso falar com a pessoa responsável por tecnologia ou administração da ${leadName(lead)}?`;
  if (lead.crm) return `Olá! Sou Lucas Gabriel, da equipe de projetos. Identificamos uma oportunidade de automação relacionada ao ${lead.crm} na ${leadName(lead)}. Posso falar com a pessoa responsável pelo CRM ou pelos processos comerciais?`;
  return `Olá! Sou Lucas Gabriel, da equipe de projetos. Trabalhamos com implantação de CRM e automação de atendimento. Posso falar com a pessoa responsável pelos processos comerciais da ${leadName(lead)}?`;
}

function contactLinks(lead) {
  const whatsapp = onlyDigits(lead.contact_whatsapp);
  const maps = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${leadName(lead)} ${lead.location || ''}`)}`;
  const realDomain = lead.domain && !String(lead.domain).endsWith('.school') ? lead.domain : null;
  return {
    site: safeUrl(lead.website_url || realDomain, maps),
    maps,
    whatsapp: whatsapp.length >= 12 && !whatsapp.includes('0800') ? `https://api.whatsapp.com/send/?phone=${encodeURIComponent(`+${whatsapp}`)}&text=${encodeURIComponent(outreachMessage(lead))}` : null,
    email: lead.contact_email ? `mailto:${encodeURIComponent(lead.contact_email)}?subject=${encodeURIComponent(`Contato com ${leadName(lead)}`)}&body=${encodeURIComponent(outreachMessage(lead))}` : null,
    phone: lead.contact_phone ? `tel:${onlyDigits(lead.contact_phone)}` : null,
  };
}

function applyFilters(resetPage = true) {
  const query = byId('search').value.trim().toLowerCase();
  const temperature = byId('temperature').value;
  const status = byId('status').value;
  state.filtered = state.leads.filter((lead) => {
    const searchable = [leadName(lead), lead.domain, lead.crm, lead.location, lead.sector, lead.opportunity_type, lead.contact_name, lead.contact_email].join(' ').toLowerCase();
    const quickMatch = state.quick === 'all'
      || (state.quick === 'hot' && lead.temperature === 'hot')
      || (state.quick === 'contact' && hasContact(lead))
      || (state.quick === 'pending' && lead.status !== 'sent');
    return (!query || searchable.includes(query)) && (!temperature || lead.temperature === temperature) && (!status || lead.status === status) && quickMatch;
  }).sort((a,b) => leadScore(b) - leadScore(a));
  if (resetPage) state.page = 1;
  renderTable();
}

function actionForLead(lead, links) {
  if (links.whatsapp) return `<a class="action primary" href="${links.whatsapp}" target="_blank" rel="noopener" data-contact="whatsapp" data-id="${lead.id}">WhatsApp</a>`;
  if (links.email) return `<a class="action primary" href="${links.email}" data-contact="email" data-id="${lead.id}">E-mail</a>`;
  if (links.phone) return `<a class="action primary" href="${links.phone}" data-contact="phone" data-id="${lead.id}">Ligar</a>`;
  return `<a class="action" href="${links.site}" target="_blank" rel="noopener">Pesquisar</a>`;
}

function leadRow(lead) {
  const name = leadName(lead);
  const links = contactLinks(lead);
  const contact = lead.contact_name || lead.contact_whatsapp || lead.contact_phone || lead.contact_email || 'Não localizado';
  const contactSub = lead.contact_name ? (lead.contact_role || lead.contact_email || lead.contact_phone || '') : (lead.contact_email || '');
  const sourceLabel = lead.website_url || (lead.lead_type === 'school' ? `INEP ${String(lead.external_id || '').replace('inep:','')}` : lead.domain);
  const opportunity = lead.opportunity_type || (lead.crm ? `Otimização de ${lead.crm}` : 'Oportunidade consultiva');
  return `<tr>
    <td><div class="company-cell"><span class="company-avatar">${escapeHtml(initials(name).slice(0,1))}</span><div><strong title="${escapeHtml(name)}">${escapeHtml(name)}</strong><a href="${links.site}" target="_blank" rel="noopener">${escapeHtml(sourceLabel || 'Abrir localização')}</a></div></div></td>
    <td><div class="potential"><span class="score">${leadScore(lead)}</span><span class="temperature ${escapeHtml(lead.temperature || 'cold')}">${escapeHtml(temperatureLabels[lead.temperature] || 'Sem nota')}</span></div></td>
    <td><div class="opportunity"><strong>${escapeHtml(opportunity)}</strong><small>${escapeHtml(lead.location || lead.sector || 'Local não informado')}</small></div></td>
    <td><div class="contact-cell"><strong>${escapeHtml(contact)}</strong><small>${escapeHtml(contactSub)}</small></div></td>
    <td><span class="status ${escapeHtml(lead.status || 'discovered')}">${escapeHtml(statusLabels[lead.status] || 'Novo')}</span></td>
    <td><div class="row-actions">${actionForLead(lead,links)}<button type="button" class="action" data-details="${lead.id}">Detalhes</button><button type="button" class="more-button" data-edit="${lead.id}" aria-label="Editar ${escapeHtml(name)}">•••</button></div></td>
  </tr>`;
}

function renderTable() {
  const total = state.filtered.length;
  const pages = Math.max(1, Math.ceil(total / state.perPage));
  state.page = Math.min(state.page, pages);
  const start = (state.page - 1) * state.perPage;
  const end = Math.min(start + state.perPage, total);
  byId('leadRows').innerHTML = state.filtered.slice(start,end).map(leadRow).join('');
  byId('empty').classList.toggle('hidden', total > 0);
  byId('resultSummary').textContent = `${total} ${total === 1 ? 'oportunidade encontrada' : 'oportunidades encontradas'}`;
  byId('pageInfo').textContent = total ? `Exibindo ${start + 1}–${end} de ${total}` : 'Nenhum resultado';
  byId('prevPage').disabled = state.page <= 1;
  byId('nextPage').disabled = state.page >= pages;
}

function openDrawer(id) {
  const lead = state.leads.find((item) => Number(item.id) === Number(id));
  if (!lead) return;
  state.selectedId = lead.id;
  const links = contactLinks(lead);
  const reasons = Array.isArray(lead.score_reasons) ? lead.score_reasons : [];
  const technicalLabel = lead.lead_type === 'school' ? 'Cadastro oficial' : 'CRM detectado';
  const technicalValue = lead.lead_type === 'school' ? 'INEP 2025' : (lead.crm || 'Não detectado');
  byId('drawerTitle').textContent = leadName(lead);
  byId('drawerDomain').textContent = lead.website_url || (lead.lead_type === 'school' ? `Código ${lead.external_id || 'INEP'}` : lead.domain);
  byId('drawerDomain').href = links.site;
  byId('drawerContent').innerHTML = `
    <div class="drawer-score">
      <div class="drawer-pill"><span>Potencial</span><strong>${leadScore(lead)}/100</strong></div>
      <div class="drawer-pill"><span>Prioridade</span><strong>${escapeHtml(temperatureLabels[lead.temperature] || 'Sem nota')}</strong></div>
      <div class="drawer-pill"><span>Status</span><strong>${escapeHtml(statusLabels[lead.status] || 'Novo')}</strong></div>
      <div class="drawer-pill"><span>Tipo</span><strong>${escapeHtml(lead.lead_type === 'school' ? 'Escola' : 'Empresa')}</strong></div>
    </div>
    <section class="detail-section"><h3>Dados da oportunidade</h3><div class="detail-grid">
      <div class="detail-item"><span>Setor</span><strong>${escapeHtml(lead.sector || 'Não informado')}</strong></div>
      <div class="detail-item"><span>Localização</span><strong>${escapeHtml(lead.location || 'Não informada')}</strong></div>
      <div class="detail-item"><span>${technicalLabel}</span><strong>${escapeHtml(technicalValue)}</strong></div>
      <div class="detail-item"><span>Oportunidade</span><strong>${escapeHtml(lead.opportunity_type || 'Consultiva')}</strong></div>
    </div></section>
    <section class="detail-section"><h3>Contato</h3><div class="detail-grid">
      <div class="detail-item"><span>Responsável</span><strong>${escapeHtml(lead.contact_name || 'Não localizado')}</strong></div>
      <div class="detail-item"><span>Cargo</span><strong>${escapeHtml(lead.contact_role || 'Não informado')}</strong></div>
      <div class="detail-item"><span>E-mail</span><strong>${escapeHtml(lead.contact_email || 'Não localizado')}</strong></div>
      <div class="detail-item"><span>WhatsApp / telefone</span><strong>${escapeHtml(lead.contact_whatsapp || lead.contact_phone || 'Não localizado')}</strong></div>
    </div></section>
    ${lead.pain_summary ? `<section class="detail-section"><h3>Oportunidade identificada</h3><p class="detail-copy">${escapeHtml(lead.pain_summary)}</p>${lead.pain_source ? `<a href="${safeUrl(lead.pain_source)}" target="_blank" rel="noopener">Ver fonte pública →</a>` : ''}</section>` : ''}
    <section class="detail-section"><h3>Por que este lead recebeu essa nota?</h3><div class="reason-list">${reasons.length ? reasons.map((reason) => `<div class="reason">${escapeHtml(reason)}</div>`).join('') : '<div class="reason">Pontuação calculada com base em contato, aderência e sinais públicos.</div>'}</div></section>
    ${lead.notes ? `<section class="detail-section"><h3>Observações</h3><p class="detail-copy">${escapeHtml(lead.notes)}</p></section>` : ''}`;
  byId('drawerActions').innerHTML = `
    ${links.whatsapp ? `<a class="button button-primary" href="${links.whatsapp}" target="_blank" rel="noopener" data-contact="whatsapp" data-id="${lead.id}">Abrir WhatsApp</a>` : ''}
    ${links.email ? `<a class="button button-light" href="${links.email}" data-contact="email" data-id="${lead.id}">Enviar e-mail</a>` : ''}
    ${links.phone ? `<a class="button button-light" href="${links.phone}" data-contact="phone" data-id="${lead.id}">Ligar</a>` : ''}
    <button class="button button-light" type="button" data-edit="${lead.id}">Editar</button>
    ${lead.status === 'sent' ? `<button class="button button-light" type="button" data-reopen="${lead.id}">Reabrir</button>` : `<button class="button button-light" type="button" data-sent="${lead.id}">Marcar contatado</button>`}`;
  byId('drawerBackdrop').classList.remove('hidden');
  byId('leadDrawer').classList.add('open');
  byId('leadDrawer').setAttribute('aria-hidden','false');
}

function closeDrawer() {
  byId('leadDrawer').classList.remove('open');
  byId('leadDrawer').setAttribute('aria-hidden','true');
  byId('drawerBackdrop').classList.add('hidden');
}

function openEditor(id) {
  const lead = state.leads.find((item) => Number(item.id) === Number(id));
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
  byId('editor').showModal();
}

async function loadLeads() {
  byId('refresh').disabled = true;
  try {
    const data = await api('/api/v1/leads?limit=1000');
    state.leads = Array.isArray(data) ? data : [];
    renderStats(); renderFocus(); renderCharts(); applyFilters();
    byId('lastUpdate').textContent = `Atualizado às ${new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})}`;
  } catch (error) {
    notify(`Não foi possível carregar os leads: ${error.message}`, true);
    byId('resultSummary').textContent = 'Falha ao conectar com a base.';
  } finally { byId('refresh').disabled = false; }
}

async function markContacted(id, channel) {
  try {
    await api(`/api/v1/leads/${id}/mark-contacted`, {method:'POST',body:JSON.stringify({channel})});
    await loadLeads(); notify('Contato registrado no pipeline.');
  } catch (error) { notify(error.message,true); }
}

async function reopenLead(id) {
  try {
    await api(`/api/v1/leads/${id}/reopen`,{method:'POST'});
    closeDrawer(); await loadLeads(); notify('Lead reaberto.');
  } catch (error) { notify(error.message,true); }
}

function exportCsv() {
  const columns = ['Empresa','Identificador','Local','Tipo','CRM','Score','Prioridade','Responsável','E-mail','WhatsApp','Telefone','Status'];
  const rows = state.filtered.map((lead) => [leadName(lead),lead.external_id || lead.domain,lead.location,lead.opportunity_type,lead.crm,leadScore(lead),lead.temperature,lead.contact_name,lead.contact_email,lead.contact_whatsapp,lead.contact_phone,lead.status]);
  const csv = [columns,...rows].map((row) => row.map((value) => `"${String(value ?? '').replace(/"/g,'""')}"`).join(',')).join('\n');
  const url = URL.createObjectURL(new Blob([`\ufeff${csv}`],{type:'text/csv;charset=utf-8'}));
  const link = document.createElement('a'); link.href=url; link.download=`leads-${new Date().toISOString().slice(0,10)}.csv`; link.click(); URL.revokeObjectURL(url);
}

function renderUsers() {
  const adminRow = `<div class="user-row"><div class="user-info"><span>${escapeHtml(initials(state.identity.display_name))}</span><div><strong>${escapeHtml(state.identity.display_name)}</strong><small>${escapeHtml(state.identity.username)} · administrador principal</small></div></div><span class="role-pill">Administrador</span><span class="active-pill">Ativo</span><div></div></div>`;
  const rows = state.users.map((user) => `<div class="user-row">
    <div class="user-info"><span>${escapeHtml(initials(user.display_name))}</span><div><strong>${escapeHtml(user.display_name)}</strong><small>${escapeHtml(user.username)}</small></div></div>
    <span class="role-pill">${user.role === 'admin' ? 'Administrador' : 'Comercial'}</span>
    <span class="active-pill${user.active ? '' : ' off'}">${user.active ? 'Ativo' : 'Desativado'}</span>
    <div class="user-actions"><button class="action" data-user-password="${user.id}">Nova senha</button><button class="action" data-user-toggle="${user.id}" data-active="${user.active}">${user.active ? 'Desativar' : 'Ativar'}</button></div>
  </div>`).join('');
  byId('userList').innerHTML = adminRow + (rows || '<div class="user-row"><div class="user-info"><div><strong>Nenhum usuário comercial</strong><small>Crie a primeira credencial para sua equipe.</small></div></div></div>');
}

async function loadUsers() {
  if (!state.identity?.is_admin) return;
  try { state.users = await api('/api/v1/admin/users'); renderUsers(); }
  catch (error) { notify(`Não foi possível carregar usuários: ${error.message}`,true); }
}

function resetFilters() {
  byId('filters').reset(); state.quick='all';
  document.querySelectorAll('.quick').forEach((button) => button.classList.toggle('active',button.dataset.quick === 'all'));
  applyFilters();
}

function handleLeadActions(event) {
  const target = event.target.closest('[data-details],[data-edit],[data-sent],[data-reopen],[data-contact]');
  if (!target) return;
  if (target.dataset.details) openDrawer(target.dataset.details);
  if (target.dataset.edit) openEditor(target.dataset.edit);
  if (target.dataset.sent) markContacted(target.dataset.sent,'manual');
  if (target.dataset.reopen) reopenLead(target.dataset.reopen);
  if (target.dataset.contact) window.setTimeout(() => markContacted(target.dataset.id,target.dataset.contact),500);
}

function toggleMobileMenu(open) {
  byId('sidebar').classList.toggle('open',open);
  byId('mobileOverlay').classList.toggle('hidden',!open);
}

byId('filters').addEventListener('submit',(event)=>{event.preventDefault();applyFilters();});
byId('search').addEventListener('input',()=>applyFilters());
byId('temperature').addEventListener('change',()=>applyFilters());
byId('status').addEventListener('change',()=>applyFilters());
byId('clearFilters').addEventListener('click',resetFilters);
byId('emptyClear').addEventListener('click',resetFilters);
document.querySelectorAll('.quick').forEach((button)=>button.addEventListener('click',()=>{state.quick=button.dataset.quick;document.querySelectorAll('.quick').forEach((item)=>item.classList.toggle('active',item===button));applyFilters();}));
byId('prevPage').addEventListener('click',()=>{if(state.page>1){state.page-=1;renderTable();}});
byId('nextPage').addEventListener('click',()=>{if(state.page*state.perPage<state.filtered.length){state.page+=1;renderTable();}});
byId('refresh').addEventListener('click',loadLeads);
byId('heroRefresh').addEventListener('click',loadLeads);
byId('exportCsv').addEventListener('click',exportCsv);
byId('leadRows').addEventListener('click',handleLeadActions);
byId('focusLeads').addEventListener('click',handleLeadActions);
byId('drawerActions').addEventListener('click',handleLeadActions);
byId('closeDrawer').addEventListener('click',closeDrawer);
byId('drawerBackdrop').addEventListener('click',closeDrawer);
byId('menuToggle').addEventListener('click',()=>toggleMobileMenu(true));
byId('mobileOverlay').addEventListener('click',()=>toggleMobileMenu(false));
document.querySelectorAll('.nav-link').forEach((link)=>link.addEventListener('click',()=>toggleMobileMenu(false)));
byId('closeEditor').addEventListener('click',()=>byId('editor').close());
byId('cancelEdit').addEventListener('click',()=>byId('editor').close());
byId('editForm').addEventListener('submit',async(event)=>{
  event.preventDefault();
  const id=byId('leadId').value;
  const payload={company_name:byId('companyName').value||null,sector:byId('sector').value||null,contact_name:byId('contactName').value||null,contact_role:byId('contactRole').value||null,contact_email:byId('contactEmail').value||null,contact_whatsapp:byId('contactWhatsapp').value||null,contact_phone:byId('contactPhone').value||null,notes:byId('notes').value||null};
  try{await api(`/api/v1/leads/${id}`,{method:'PATCH',body:JSON.stringify(payload)});byId('editor').close();await loadLeads();notify('Lead atualizado com sucesso.');}
  catch(error){notify(error.message,true);}
});
byId('openUserDialog').addEventListener('click',()=>byId('userDialog').showModal());
byId('closeUserDialog').addEventListener('click',()=>byId('userDialog').close());
byId('cancelUser').addEventListener('click',()=>byId('userDialog').close());
byId('userForm').addEventListener('submit',async(event)=>{
  event.preventDefault();
  try{
    await api('/api/v1/admin/users',{method:'POST',body:JSON.stringify({display_name:byId('newDisplayName').value,username:byId('newUsername').value,password:byId('newPassword').value,role:'user'})});
    byId('userForm').reset();byId('userDialog').close();await loadUsers();notify('Credencial criada. O usuário já pode entrar.');
  }catch(error){notify(error.message,true);}
});
byId('userList').addEventListener('click',async(event)=>{
  const toggle=event.target.closest('[data-user-toggle]');
  const password=event.target.closest('[data-user-password]');
  try{
    if(toggle){await api(`/api/v1/admin/users/${toggle.dataset.userToggle}`,{method:'PATCH',body:JSON.stringify({active:toggle.dataset.active!=='true'})});await loadUsers();notify('Acesso atualizado.');}
    if(password){const value=window.prompt('Digite a nova senha temporária (mínimo de 8 caracteres):');if(!value)return;await api(`/api/v1/admin/users/${password.dataset.userPassword}/reset-password`,{method:'POST',body:JSON.stringify({password:value})});notify('Senha atualizada.');}
  }catch(error){notify(error.message,true);}
});
byId('logoutBtn').addEventListener('click',async()=>{try{await api('/api/v1/auth/logout',{method:'POST'});}finally{location.replace('/login');}});

(async function start(){
  try{
    const identity=await api('/api/v1/auth/me');
    applyIdentity(identity);
    await Promise.all([loadLeads(),loadUsers()]);
    window.setInterval(loadLeads,90000);
  }catch(_){location.replace('/login?next=/dashboard');}
})();
