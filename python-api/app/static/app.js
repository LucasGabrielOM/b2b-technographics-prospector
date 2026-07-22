'use strict';

const state = { leads: [], filtered: [], page: 1, perPage: 15, quick: 'all' };
const el = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const digits = (value) => String(value || '').replace(/\D/g, '');
const hasContact = (lead) => Boolean(lead.contact_whatsapp || lead.contact_email || lead.contact_phone);
const companyName = (lead) => lead.company_name || lead.company || lead.domain || 'Empresa sem nome';
const score = (lead) => Number(lead.lead_score ?? lead.score ?? 0);
const labels = {
  status: { discovered: 'Novo', enriched: 'Enriquecido', drafted: 'Rascunho', approved: 'Aprovado', sent: 'Enviado', suppressed: 'Suprimido' },
  temperature: { hot: 'Quente', warm: 'Morno', cold: 'Frio' }
};

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
  if (!response.ok) {
    let detail = `Erro ${response.status}`;
    try { const body = await response.json(); detail = body.detail || detail; } catch (_) { /* resposta sem JSON */ }
    throw new Error(detail);
  }
  return response.json();
}

function showNotice(message, isError = false) {
  el('notice').textContent = message;
  el('notice').className = `notice${isError ? ' error' : ''}`;
  window.setTimeout(() => el('notice').classList.add('hidden'), 4000);
}

function renderStats() {
  const leads = state.leads;
  const cards = [
    ['Leads no pipeline', leads.length, 'Empresas únicas encontradas', '◎', '#6758e8', '#eeecff'],
    ['Oportunidades quentes', leads.filter((l) => l.temperature === 'hot').length, 'Prioridade para sua equipe', '↗', '#e44747', '#fff0ed'],
    ['Contatos disponíveis', leads.filter(hasContact).length, 'WhatsApp, e-mail ou telefone', '✦', '#12a06a', '#e8f8f0'],
    ['Abordagens enviadas', leads.filter((l) => l.status === 'sent').length, 'Contatos registrados', '✓', '#10a6bd', '#e8f8fb']
  ];
  el('stats').innerHTML = cards.map(([title, value, detail, icon, color, tint]) => `
    <article class="metric" style="--color:${color};--tint:${tint}">
      <div class="metric-top"><span>${title}</span><span class="metric-icon">${icon}</span></div>
      <strong>${value}</strong><small>${detail}</small>
    </article>`).join('');
}

function renderCharts() {
  const leads = state.leads;
  const total = leads.length || 1;
  const contact = leads.filter(hasContact).length;
  const hot = leads.filter((l) => l.temperature === 'hot').length;
  const sent = leads.filter((l) => l.status === 'sent').length;
  const stages = [
    ['Mapeados', leads.length, '#6758e8'], ['Com contato', contact, '#10a6bd'],
    ['Quentes', hot, '#f79009'], ['Enviados', sent, '#12a06a']
  ];
  el('pipelineChart').innerHTML = stages.map(([label, value, color]) => {
    const percentage = Math.round((value / total) * 100);
    return `<div class="pipe-item"><div class="pipe-label"><span>${label}</span><strong>${value}</strong></div><div class="bar"><i style="--bar:${color};--width:${percentage}%"></i></div><small>${percentage}% da base</small></div>`;
  }).join('');

  const whatsapp = leads.filter((l) => l.contact_whatsapp).length;
  const email = leads.filter((l) => l.contact_email).length;
  const phone = leads.filter((l) => l.contact_phone).length;
  const coverage = Math.round((contact / total) * 100);
  el('channelsChart').innerHTML = `<div class="ring" style="--pct:${coverage}%"><div><strong>${coverage}%</strong><small>COBERTURA</small></div></div><div class="channel-list">
    <div class="channel"><span><i style="background:#12a06a"></i>WhatsApp</span><strong>${whatsapp}</strong></div>
    <div class="channel"><span><i style="background:#6758e8"></i>E-mail</span><strong>${email}</strong></div>
    <div class="channel"><span><i style="background:#f79009"></i>Telefone</span><strong>${phone}</strong></div>
  </div>`;
}

function applyFilters(resetPage = true) {
  const query = el('search').value.trim().toLowerCase();
  const temperature = el('temperature').value;
  const status = el('status').value;
  state.filtered = state.leads.filter((lead) => {
    const searchable = [companyName(lead), lead.domain, lead.crm, lead.location, lead.sector].join(' ').toLowerCase();
    const quickMatch = state.quick === 'all' ||
      (state.quick === 'hot' && lead.temperature === 'hot') ||
      (state.quick === 'contact' && hasContact(lead)) ||
      (state.quick === 'pending' && lead.status !== 'sent');
    return (!query || searchable.includes(query)) && (!temperature || lead.temperature === temperature) && (!status || lead.status === status) && quickMatch;
  });
  state.filtered.sort((a, b) => score(b) - score(a));
  if (resetPage) state.page = 1;
  renderTable();
}

function outreachMessage(lead) {
  const name = companyName(lead);
  if (lead.crm) return `Olá! Sou Lucas Gabriel, da equipe de projetos. Identificamos uma oportunidade de automação relacionada ao ${lead.crm} na ${name}. Podemos falar com a pessoa responsável pelos processos comerciais ou pelo CRM?`;
  return `Olá! Sou Lucas Gabriel, da equipe de projetos. Trabalhamos com implantação de CRM e automação de atendimento. Podemos falar com a pessoa responsável pelos processos comerciais ou pelo pós-venda da ${name}?`;
}

function linksFor(lead) {
  const phone = digits(lead.contact_whatsapp);
  const validWhatsapp = phone.length >= 12 && !phone.includes('0800');
  return {
    site: lead.domain ? `https://${encodeURI(String(lead.domain).replace(/^https?:\/\//, ''))}` : null,
    whatsapp: validWhatsapp ? `https://api.whatsapp.com/send/?phone=${encodeURIComponent(`+${phone}`)}&text=${encodeURIComponent(outreachMessage(lead))}` : null,
    email: lead.contact_email ? `mailto:${encodeURIComponent(lead.contact_email)}?subject=${encodeURIComponent(`Automação para ${companyName(lead)}`)}&body=${encodeURIComponent(outreachMessage(lead))}` : null
  };
}

function rowTemplate(lead) {
  const name = companyName(lead);
  const links = linksFor(lead);
  const contact = lead.contact_name || lead.contact_whatsapp || lead.contact_phone || lead.contact_email || 'Contato não localizado';
  const subcontact = lead.contact_name ? (lead.contact_role || lead.contact_email || '') : (lead.contact_email || '');
  return `<tr>
    <td><div class="company"><span class="avatar">${escapeHtml(name.charAt(0).toUpperCase())}</span><div><strong>${escapeHtml(name)}</strong>${links.site ? `<a href="${links.site}" target="_blank" rel="noopener">${escapeHtml(lead.domain)}</a>` : ''}</div></div></td>
    <td><div class="score-wrap"><span class="score">${score(lead)}</span><span class="temp ${escapeHtml(lead.temperature || 'cold')}">${escapeHtml(labels.temperature[lead.temperature] || 'Sem nota')}</span></div></td>
    <td><span class="tech">${escapeHtml(lead.crm || 'Não detectado')}</span><span class="location">${escapeHtml(lead.location || lead.opportunity_type || 'Local não informado')}</span></td>
    <td><div class="contact"><strong>${escapeHtml(contact)}</strong><small>${escapeHtml(subcontact)}</small></div></td>
    <td><span class="status ${escapeHtml(lead.status)}">${escapeHtml(labels.status[lead.status] || lead.status || 'Novo')}</span></td>
    <td><div class="actions">
      ${links.site ? `<a class="action" href="${links.site}" target="_blank" rel="noopener">Site</a>` : ''}
      ${links.whatsapp ? `<a class="action wa" href="${links.whatsapp}" target="_blank" rel="noopener" data-contact="whatsapp" data-id="${lead.id}">WhatsApp</a>` : ''}
      ${links.email ? `<a class="action mail" href="${links.email}" data-contact="email" data-id="${lead.id}">E-mail</a>` : ''}
      <button class="action" type="button" data-edit="${lead.id}">Editar</button>
      ${lead.status === 'sent' ? `<button class="action" type="button" data-reopen="${lead.id}">Reabrir</button>` : `<button class="action" type="button" data-sent="${lead.id}">Marcar enviado</button>`}
    </div></td>
  </tr>`;
}

function renderTable() {
  const total = state.filtered.length;
  const pages = Math.max(1, Math.ceil(total / state.perPage));
  state.page = Math.min(state.page, pages);
  const start = (state.page - 1) * state.perPage;
  const end = Math.min(start + state.perPage, total);
  el('leadRows').innerHTML = state.filtered.slice(start, end).map(rowTemplate).join('');
  el('empty').classList.toggle('hidden', total !== 0);
  el('resultSummary').textContent = `${total} ${total === 1 ? 'empresa encontrada' : 'empresas encontradas'} para prospectar`;
  el('pageInfo').textContent = total ? `Exibindo ${start + 1}–${end} de ${total}` : 'Nenhum resultado';
  el('prevPage').disabled = state.page <= 1;
  el('nextPage').disabled = state.page >= pages;
}

async function loadLeads() {
  el('refresh').disabled = true;
  el('refresh').textContent = 'Atualizando...';
  try {
    const data = await request('/api/v1/leads?limit=1000');
    state.leads = Array.isArray(data) ? data : (data.items || data.leads || []);
    renderStats(); renderCharts(); applyFilters();
    el('lastUpdate').textContent = new Date().toLocaleString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
  } catch (error) {
    showNotice(`Não foi possível carregar os leads: ${error.message}`, true);
    el('resultSummary').textContent = 'Falha ao conectar com o banco. Tente atualizar.';
    el('stats').innerHTML = '<article class="metric"><strong>—</strong><small>Dados indisponíveis</small></article>';
  } finally {
    el('refresh').disabled = false;
    el('refresh').textContent = 'Atualizar';
  }
}

async function markContacted(id, channel) {
  try { await request(`/api/v1/leads/${id}/mark-contacted`, { method: 'POST', body: JSON.stringify({ channel }) }); await loadLeads(); showNotice('Abordagem registrada no banco.'); }
  catch (error) { showNotice(error.message, true); }
}

async function reopenLead(id) {
  try { await request(`/api/v1/leads/${id}/reopen`, { method: 'POST' }); await loadLeads(); showNotice('Lead reaberto no pipeline.'); }
  catch (error) { showNotice(error.message, true); }
}

function openEditor(id) {
  const lead = state.leads.find((item) => Number(item.id) === Number(id));
  if (!lead) return;
  el('leadId').value = lead.id; el('editTitle').textContent = companyName(lead);
  el('companyName').value = lead.company_name || ''; el('sector').value = lead.sector || '';
  el('contactName').value = lead.contact_name || ''; el('contactRole').value = lead.contact_role || '';
  el('contactEmail').value = lead.contact_email || ''; el('contactWhatsapp').value = lead.contact_whatsapp || '';
  el('contactPhone').value = lead.contact_phone || ''; el('notes').value = lead.notes || '';
  el('editor').showModal();
}

function exportCsv() {
  const columns = ['Empresa', 'Domínio', 'Local', 'CRM', 'Score', 'Temperatura', 'E-mail', 'WhatsApp', 'Telefone', 'Status'];
  const rows = state.filtered.map((lead) => [companyName(lead), lead.domain, lead.location, lead.crm, score(lead), lead.temperature, lead.contact_email, lead.contact_whatsapp, lead.contact_phone, lead.status]);
  const csv = [columns, ...rows].map((row) => row.map((value) => `"${String(value ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
  const url = URL.createObjectURL(new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a'); link.href = url; link.download = `leads-${new Date().toISOString().slice(0, 10)}.csv`; link.click(); URL.revokeObjectURL(url);
}

el('filters').addEventListener('submit', (event) => { event.preventDefault(); applyFilters(); });
el('clearFilters').addEventListener('click', () => { el('filters').reset(); state.quick = 'all'; document.querySelectorAll('.quick').forEach((button) => button.classList.toggle('active', button.dataset.quick === 'all')); applyFilters(); });
document.querySelectorAll('.quick').forEach((button) => button.addEventListener('click', () => { state.quick = button.dataset.quick; document.querySelectorAll('.quick').forEach((item) => item.classList.toggle('active', item === button)); applyFilters(); }));
el('prevPage').addEventListener('click', () => { if (state.page > 1) { state.page -= 1; renderTable(); } });
el('nextPage').addEventListener('click', () => { if (state.page * state.perPage < state.filtered.length) { state.page += 1; renderTable(); } });
el('refresh').addEventListener('click', loadLeads); el('exportCsv').addEventListener('click', exportCsv);
el('leadRows').addEventListener('click', (event) => { const target = event.target.closest('[data-edit],[data-sent],[data-reopen],[data-contact]'); if (!target) return; if (target.dataset.edit) openEditor(target.dataset.edit); if (target.dataset.sent) markContacted(target.dataset.sent, 'manual'); if (target.dataset.reopen) reopenLead(target.dataset.reopen); if (target.dataset.contact) window.setTimeout(() => markContacted(target.dataset.id, target.dataset.contact), 600); });
el('closeEditor').addEventListener('click', () => el('editor').close()); el('cancelEdit').addEventListener('click', () => el('editor').close());
el('editForm').addEventListener('submit', async (event) => { event.preventDefault(); const id = el('leadId').value; const payload = { company_name: el('companyName').value || null, sector: el('sector').value || null, contact_name: el('contactName').value || null, contact_role: el('contactRole').value || null, contact_email: el('contactEmail').value || null, contact_whatsapp: el('contactWhatsapp').value || null, contact_phone: el('contactPhone').value || null, notes: el('notes').value || null }; try { await request(`/api/v1/leads/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }); el('editor').close(); await loadLeads(); showNotice('Lead atualizado com sucesso.'); } catch (error) { showNotice(error.message, true); } });

loadLeads();
window.setInterval(loadLeads, 60000);
