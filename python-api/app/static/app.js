'use strict';

const state = { leads: [], filtered: [], page: 1, perPage: 15, quick: 'all', selectedId: null };
const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const onlyDigits = (value) => String(value || '').replace(/\D/g, '');
const hasContact = (lead) => Boolean(lead.contact_whatsapp || lead.contact_email || lead.contact_phone);
const leadName = (lead) => lead.company_name || lead.company || lead.domain || 'Empresa sem nome';
const leadScore = (lead) => Number(lead.lead_score ?? lead.score ?? 0);
const statusLabels = { discovered: 'Novo', enriched: 'Enriquecido', drafted: 'Rascunho', approved: 'Aprovado', sent: 'Enviado', suppressed: 'Suprimido' };
const temperatureLabels = { hot: 'Quente', warm: 'Morno', cold: 'Frio' };

function safeUrl(value, fallback = '#') {
  if (!value) return fallback;
  try { const url = new URL(String(value).startsWith('http') ? value : `https://${value}`); return ['http:', 'https:'].includes(url.protocol) ? url.href : fallback; }
  catch (_) { return fallback; }
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
  if (!response.ok) {
    let message = `Erro ${response.status}`;
    try { const body = await response.json(); message = body.detail || message; } catch (_) { /* resposta sem JSON */ }
    throw new Error(message);
  }
  return response.json();
}

function notify(message, error = false) {
  byId('notice').textContent = message;
  byId('notice').className = `notice${error ? ' error' : ''}`;
  window.setTimeout(() => byId('notice').classList.add('hidden'), 3800);
}

function renderStats() {
  const leads = state.leads;
  const contacts = leads.filter(hasContact).length;
  const cards = [
    ['Leads mapeados', leads.length, 'empresas únicas', '◎', '#7047eb', '#f0ecff'],
    ['Oportunidades quentes', leads.filter((lead) => lead.temperature === 'hot').length, 'prioridade máxima', '↗', '#d64545', '#fff0ef'],
    ['Com contato', contacts, `${Math.round((contacts / (leads.length || 1)) * 100)}% da sua base`, '◇', '#079b67', '#e8f8f1'],
    ['CRM detectado', leads.filter((lead) => lead.crm).length, 'sinais tecnológicos', '⌘', '#05a9c6', '#e8f9fc'],
    ['Já abordados', leads.filter((lead) => lead.status === 'sent').length, 'contatos registrados', '✓', '#e68a00', '#fff6df']
  ];
  byId('stats').innerHTML = cards.map(([label, value, detail, icon, tone, soft]) => `<article class="stat" style="--tone:${tone};--soft:${soft}"><div class="stat-top"><span class="stat-label">${label}</span><span class="stat-icon">${icon}</span></div><strong>${value}</strong><small class="${label === 'Com contato' ? 'good' : ''}">${detail}</small></article>`).join('');
  byId('navLeadCount').textContent = leads.length;
}

function renderCharts() {
  const leads = state.leads;
  const total = leads.length || 1;
  const stages = [
    ['Mapeados', leads.length, '#7047eb'],
    ['Com contato', leads.filter(hasContact).length, '#05a9c6'],
    ['Quentes', leads.filter((lead) => lead.temperature === 'hot').length, '#e68a00'],
    ['Enviados', leads.filter((lead) => lead.status === 'sent').length, '#079b67']
  ];
  byId('pipelineChart').innerHTML = stages.map(([label, value, color]) => { const percentage = Math.round((value / total) * 100); return `<div class="stage"><div class="stage-label"><span>${label}</span><strong>${value}</strong></div><div class="stage-bar"><i style="--bar:${color};--w:${percentage}%"></i></div><small>${percentage}% da base</small></div>`; }).join('');

  const contacts = leads.filter(hasContact).length;
  const coverage = Math.round((contacts / total) * 100);
  const channelData = [['WhatsApp', leads.filter((lead) => lead.contact_whatsapp).length, '#079b67'], ['E-mail', leads.filter((lead) => lead.contact_email).length, '#7047eb'], ['Telefone', leads.filter((lead) => lead.contact_phone).length, '#e68a00']];
  byId('channelsChart').innerHTML = `<div class="donut" style="--pct:${coverage}%"><div><strong>${coverage}%</strong><span>COBERTURA</span></div></div><div class="channel-list">${channelData.map(([label, value, color]) => `<div class="channel-item"><span><i style="background:${color}"></i>${label}</span><strong>${value}</strong></div>`).join('')}</div>`;

  const crmCounts = {};
  leads.forEach((lead) => { const crm = lead.crm || 'Não detectado'; crmCounts[crm] = (crmCounts[crm] || 0) + 1; });
  const crms = Object.entries(crmCounts).sort((a, b) => b[1] - a[1]).slice(0, 5);
  const maxCrm = Math.max(1, ...crms.map((item) => item[1]));
  byId('crmChart').innerHTML = crms.map(([crm, count]) => `<div class="crm-row"><span title="${escapeHtml(crm)}">${escapeHtml(crm)}</span><div class="crm-track"><i style="--w:${Math.round((count / maxCrm) * 100)}%"></i></div><strong>${count}</strong></div>`).join('');
}

function outreachMessage(lead) {
  if (lead.crm) return `Olá! Sou Lucas Gabriel, da equipe de projetos. Identificamos uma oportunidade de automação relacionada ao ${lead.crm} na ${leadName(lead)}. Podemos falar com a pessoa responsável pelos processos comerciais ou pelo CRM?`;
  return `Olá! Sou Lucas Gabriel, da equipe de projetos. Trabalhamos com implantação de CRM e automação de atendimento. Podemos falar com a pessoa responsável pelos processos comerciais ou pelo pós-venda da ${leadName(lead)}?`;
}

function contactLinks(lead) {
  const phone = onlyDigits(lead.contact_whatsapp);
  const validWhatsapp = phone.length >= 12 && !phone.includes('0800');
  return {
    site: safeUrl(lead.domain),
    whatsapp: validWhatsapp ? `https://api.whatsapp.com/send/?phone=${encodeURIComponent(`+${phone}`)}&text=${encodeURIComponent(outreachMessage(lead))}` : null,
    email: lead.contact_email ? `mailto:${encodeURIComponent(lead.contact_email)}?subject=${encodeURIComponent(`Automação para ${leadName(lead)}`)}&body=${encodeURIComponent(outreachMessage(lead))}` : null
  };
}

function applyFilters(resetPage = true) {
  const query = byId('search').value.trim().toLowerCase();
  const temperature = byId('temperature').value;
  const status = byId('status').value;
  state.filtered = state.leads.filter((lead) => {
    const searchable = [leadName(lead), lead.domain, lead.crm, lead.location, lead.sector, lead.opportunity_type].join(' ').toLowerCase();
    const quickMatch = state.quick === 'all' || (state.quick === 'hot' && lead.temperature === 'hot') || (state.quick === 'contact' && hasContact(lead)) || (state.quick === 'pending' && lead.status !== 'sent');
    return (!query || searchable.includes(query)) && (!temperature || lead.temperature === temperature) && (!status || lead.status === status) && quickMatch;
  }).sort((a, b) => leadScore(b) - leadScore(a));
  if (resetPage) state.page = 1;
  renderTable();
}

function leadRow(lead) {
  const name = leadName(lead);
  const links = contactLinks(lead);
  const contact = lead.contact_name || lead.contact_whatsapp || lead.contact_phone || lead.contact_email || 'Não localizado';
  const contactSub = lead.contact_name ? (lead.contact_role || lead.contact_email || '') : (lead.contact_email || '');
  const opportunity = lead.opportunity_type || 'Oportunidade em aberto';
  return `<tr>
    <td><div class="company-cell"><span class="company-avatar">${escapeHtml(name.charAt(0).toUpperCase())}</span><div><strong title="${escapeHtml(name)}">${escapeHtml(name)}</strong><a href="${links.site}" target="_blank" rel="noopener">${escapeHtml(lead.domain)}</a></div></div></td>
    <td><div class="potential"><span class="score">${leadScore(lead)}</span><span class="temperature ${escapeHtml(lead.temperature || 'cold')}">${escapeHtml(temperatureLabels[lead.temperature] || 'Sem nota')}</span></div></td>
    <td><div class="technology"><strong>${escapeHtml(lead.crm || 'Não detectado')}</strong><small>${escapeHtml(opportunity)} · ${escapeHtml(lead.location || lead.sector || 'Local não informado')}</small></div></td>
    <td><div class="contact-cell"><strong>${escapeHtml(contact)}</strong><small>${escapeHtml(contactSub)}</small></div></td>
    <td><span class="status ${escapeHtml(lead.status || 'discovered')}">${escapeHtml(statusLabels[lead.status] || lead.status || 'Novo')}</span></td>
    <td><div class="row-actions">${links.whatsapp ? `<a class="action contact" href="${links.whatsapp}" target="_blank" rel="noopener" data-contact="whatsapp" data-id="${lead.id}">WhatsApp</a>` : links.email ? `<a class="action contact" href="${links.email}" data-contact="email" data-id="${lead.id}">E-mail</a>` : `<a class="action" href="${links.site}" target="_blank" rel="noopener">Site</a>`}<button type="button" class="action primary" data-details="${lead.id}">Ver lead</button><button type="button" class="more-button" data-edit="${lead.id}" aria-label="Editar ${escapeHtml(name)}">•••</button></div></td>
  </tr>`;
}

function renderTable() {
  const total = state.filtered.length;
  const pages = Math.max(1, Math.ceil(total / state.perPage));
  state.page = Math.min(state.page, pages);
  const start = (state.page - 1) * state.perPage;
  const end = Math.min(start + state.perPage, total);
  byId('leadRows').innerHTML = state.filtered.slice(start, end).map(leadRow).join('');
  byId('empty').classList.toggle('hidden', total > 0);
  byId('resultSummary').textContent = `${total} ${total === 1 ? 'empresa pronta' : 'empresas prontas'} para prospecção`;
  byId('pageInfo').textContent = total ? `Exibindo ${start + 1}–${end} de ${total}` : 'Nenhum resultado';
  byId('prevPage').disabled = state.page <= 1;
  byId('nextPage').disabled = state.page >= pages;
}

function openDrawer(id) {
  const lead = state.leads.find((item) => Number(item.id) === Number(id));
  if (!lead) return;
  state.selectedId = lead.id;
  const links = contactLinks(lead);
  byId('drawerTitle').textContent = leadName(lead);
  byId('drawerDomain').textContent = lead.domain;
  byId('drawerDomain').href = links.site;
  const reasons = Array.isArray(lead.score_reasons) ? lead.score_reasons : [];
  byId('drawerContent').innerHTML = `<div class="drawer-score"><div class="drawer-pill"><span>Potencial</span><strong>${leadScore(lead)}/100</strong></div><div class="drawer-pill"><span>Temperatura</span><strong>${escapeHtml(temperatureLabels[lead.temperature] || 'Sem nota')}</strong></div><div class="drawer-pill"><span>Status</span><strong>${escapeHtml(statusLabels[lead.status] || lead.status || 'Novo')}</strong></div><div class="drawer-pill"><span>Tipo</span><strong>${escapeHtml(lead.opportunity_type || 'Consultivo')}</strong></div></div>
    <section class="detail-section"><h3>Dados da empresa</h3><div class="detail-grid"><div class="detail-item"><span>Setor</span><strong>${escapeHtml(lead.sector || 'Não informado')}</strong></div><div class="detail-item"><span>Localização</span><strong>${escapeHtml(lead.location || 'Não informada')}</strong></div><div class="detail-item"><span>CRM detectado</span><strong>${escapeHtml(lead.crm || 'Não detectado')}</strong></div><div class="detail-item"><span>Confiança</span><strong>${Math.round(Number(lead.confidence || 0) * 100)}%</strong></div></div></section>
    <section class="detail-section"><h3>Contato</h3><div class="detail-grid"><div class="detail-item"><span>Responsável</span><strong>${escapeHtml(lead.contact_name || 'Não localizado')}</strong></div><div class="detail-item"><span>Cargo</span><strong>${escapeHtml(lead.contact_role || 'Não informado')}</strong></div><div class="detail-item"><span>E-mail</span><strong>${escapeHtml(lead.contact_email || 'Não localizado')}</strong></div><div class="detail-item"><span>WhatsApp / telefone</span><strong>${escapeHtml(lead.contact_whatsapp || lead.contact_phone || 'Não localizado')}</strong></div></div></section>
    ${lead.pain_summary ? `<section class="detail-section"><h3>Oportunidade identificada</h3><p class="detail-copy">${escapeHtml(lead.pain_summary)}</p>${lead.pain_source ? `<p><a href="${safeUrl(lead.pain_source)}" target="_blank" rel="noopener">Ver fonte pública ↗</a></p>` : ''}</section>` : ''}
    <section class="detail-section"><h3>Por que este lead recebeu essa nota?</h3><div class="reason-list">${reasons.length ? reasons.map((reason) => `<div class="reason">${escapeHtml(reason)}</div>`).join('') : '<div class="reason">Pontuação calculada com base em tecnologia, contato e sinais públicos.</div>'}</div></section>
    ${lead.notes ? `<section class="detail-section"><h3>Observações</h3><p class="detail-copy">${escapeHtml(lead.notes)}</p></section>` : ''}`;
  byId('drawerActions').innerHTML = `${links.whatsapp ? `<a class="button button-primary" href="${links.whatsapp}" target="_blank" rel="noopener" data-contact="whatsapp" data-id="${lead.id}">Abrir WhatsApp</a>` : ''}${links.email ? `<a class="button button-secondary" href="${links.email}" data-contact="email" data-id="${lead.id}">Enviar e-mail</a>` : ''}<button class="button button-secondary" type="button" data-edit="${lead.id}">Editar</button>${lead.status === 'sent' ? `<button class="button button-secondary" type="button" data-reopen="${lead.id}">Reabrir</button>` : `<button class="button button-secondary" type="button" data-sent="${lead.id}">Marcar enviado</button>`}`;
  byId('drawerBackdrop').classList.remove('hidden');
  byId('leadDrawer').classList.add('open');
  byId('leadDrawer').setAttribute('aria-hidden', 'false');
}

function closeDrawer() { byId('leadDrawer').classList.remove('open'); byId('leadDrawer').setAttribute('aria-hidden', 'true'); byId('drawerBackdrop').classList.add('hidden'); }

function openEditor(id) {
  const lead = state.leads.find((item) => Number(item.id) === Number(id));
  if (!lead) return;
  closeDrawer();
  byId('leadId').value = lead.id; byId('editTitle').textContent = leadName(lead); byId('companyName').value = lead.company_name || ''; byId('sector').value = lead.sector || ''; byId('contactName').value = lead.contact_name || ''; byId('contactRole').value = lead.contact_role || ''; byId('contactEmail').value = lead.contact_email || ''; byId('contactWhatsapp').value = lead.contact_whatsapp || ''; byId('contactPhone').value = lead.contact_phone || ''; byId('notes').value = lead.notes || '';
  byId('editor').showModal();
}

async function markContacted(id, channel) { try { await api(`/api/v1/leads/${id}/mark-contacted`, { method: 'POST', body: JSON.stringify({ channel }) }); await loadLeads(); notify('Abordagem registrada no pipeline.'); } catch (error) { notify(error.message, true); } }
async function reopenLead(id) { try { await api(`/api/v1/leads/${id}/reopen`, { method: 'POST' }); closeDrawer(); await loadLeads(); notify('Lead reaberto com sucesso.'); } catch (error) { notify(error.message, true); } }

async function loadLeads() {
  byId('refresh').disabled = true; byId('refresh').textContent = 'Atualizando...';
  try {
    const data = await api('/api/v1/leads?limit=1000');
    state.leads = Array.isArray(data) ? data : (data.items || data.leads || []);
    renderStats(); renderCharts(); applyFilters();
    byId('lastUpdate').textContent = `Atualizado às ${new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}`;
  } catch (error) {
    notify(`Não foi possível carregar os leads: ${error.message}`, true);
    byId('resultSummary').textContent = 'Falha ao conectar com o banco. Tente atualizar.';
  } finally { byId('refresh').disabled = false; byId('refresh').innerHTML = '<span>↻</span> Atualizar'; }
}

function resetFilters() { byId('filters').reset(); state.quick = 'all'; document.querySelectorAll('.quick').forEach((button) => button.classList.toggle('active', button.dataset.quick === 'all')); applyFilters(); }

function exportCsv() {
  const columns = ['Empresa', 'Domínio', 'Local', 'Tipo', 'CRM', 'Score', 'Temperatura', 'E-mail', 'WhatsApp', 'Telefone', 'Status'];
  const rows = state.filtered.map((lead) => [leadName(lead), lead.domain, lead.location, lead.opportunity_type, lead.crm, leadScore(lead), lead.temperature, lead.contact_email, lead.contact_whatsapp, lead.contact_phone, lead.status]);
  const csv = [columns, ...rows].map((row) => row.map((value) => `"${String(value ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
  const url = URL.createObjectURL(new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' })); const link = document.createElement('a'); link.href = url; link.download = `leads-${new Date().toISOString().slice(0, 10)}.csv`; link.click(); URL.revokeObjectURL(url);
}

function handleActions(event) {
  const target = event.target.closest('[data-details],[data-edit],[data-sent],[data-reopen],[data-contact]');
  if (!target) return;
  if (target.dataset.details) openDrawer(target.dataset.details);
  if (target.dataset.edit) openEditor(target.dataset.edit);
  if (target.dataset.sent) markContacted(target.dataset.sent, 'manual');
  if (target.dataset.reopen) reopenLead(target.dataset.reopen);
  if (target.dataset.contact) window.setTimeout(() => markContacted(target.dataset.id, target.dataset.contact), 600);
}

byId('todayLabel').textContent = new Date().toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long' });
byId('filters').addEventListener('submit', (event) => { event.preventDefault(); applyFilters(); });
byId('search').addEventListener('input', () => applyFilters()); byId('temperature').addEventListener('change', () => applyFilters()); byId('status').addEventListener('change', () => applyFilters());
byId('clearFilters').addEventListener('click', resetFilters); byId('emptyClear').addEventListener('click', resetFilters);
document.querySelectorAll('.quick').forEach((button) => button.addEventListener('click', () => { state.quick = button.dataset.quick; document.querySelectorAll('.quick').forEach((item) => item.classList.toggle('active', item === button)); applyFilters(); }));
byId('prevPage').addEventListener('click', () => { if (state.page > 1) { state.page -= 1; renderTable(); } }); byId('nextPage').addEventListener('click', () => { if (state.page * state.perPage < state.filtered.length) { state.page += 1; renderTable(); } });
byId('refresh').addEventListener('click', loadLeads); byId('exportCsv').addEventListener('click', exportCsv); byId('leadRows').addEventListener('click', handleActions); byId('drawerActions').addEventListener('click', handleActions);
byId('closeDrawer').addEventListener('click', closeDrawer); byId('drawerBackdrop').addEventListener('click', closeDrawer); byId('menuToggle').addEventListener('click', () => byId('sidebar').classList.toggle('open')); document.querySelectorAll('.nav-link').forEach((link) => link.addEventListener('click', () => byId('sidebar').classList.remove('open')));
byId('closeEditor').addEventListener('click', () => byId('editor').close()); byId('cancelEdit').addEventListener('click', () => byId('editor').close());
byId('editForm').addEventListener('submit', async (event) => { event.preventDefault(); const id = byId('leadId').value; const payload = { company_name: byId('companyName').value || null, sector: byId('sector').value || null, contact_name: byId('contactName').value || null, contact_role: byId('contactRole').value || null, contact_email: byId('contactEmail').value || null, contact_whatsapp: byId('contactWhatsapp').value || null, contact_phone: byId('contactPhone').value || null, notes: byId('notes').value || null }; try { await api(`/api/v1/leads/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }); byId('editor').close(); await loadLeads(); notify('Lead atualizado com sucesso.'); } catch (error) { notify(error.message, true); } });

loadLeads();
window.setInterval(loadLeads, 60000);
