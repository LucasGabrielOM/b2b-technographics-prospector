const byId = (id) => document.getElementById(id);
const state = { leads: [], identity: null, users: [] };
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char]));
const initials = (value) => String(value || 'LP').split(/\s+/).filter(Boolean).slice(0,2).map((part) => part[0]).join('').toUpperCase();
const leadName = (lead) => lead.company_name || lead.domain || 'Lead sem nome';
const leadScore = (lead) => Number(lead.lead_score || 0);
const hasContact = (lead) => Boolean(lead.contact_whatsapp || lead.contact_email || lead.contact_phone);

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
  notice.classList.toggle('hidden', !message);
  notice.style.borderColor = error ? '#f3c6ce' : '#bee9da';
  notice.style.background = error ? '#fff0f3' : '#edfbf6';
  notice.style.color = error ? '#9c3446' : '#0c7456';
}

function icon(name) {
  const icons = {
    leads:'<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0m2-12v6m-3-3h6"/></svg>',
    hot:'<svg viewBox="0 0 24 24"><path d="M13 3s4 4 4 8a5 5 0 1 1-10 0c0-2 1-4 3-6 0 3 2 4 3 4 1-2 0-4 0-6z"/></svg>',
    contact:'<svg viewBox="0 0 24 24"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/></svg>',
    sent:'<svg viewBox="0 0 24 24"><path d="m4 12 5 5L20 6"/></svg>',
  };
  return icons[name] || icons.leads;
}

function applyIdentity(identity) {
  state.identity = identity;
  document.body.dataset.role = identity.role;
  byId('profileName').textContent = identity.display_name;
  byId('profileRole').textContent = identity.is_admin ? 'Administrador' : 'Usuário comercial';
  byId('profileAvatar').textContent = initials(identity.display_name);
  byId('workspaceInitial').textContent = initials(identity.display_name).slice(0,1);
  if (!identity.is_admin) {
    const firstName = identity.display_name.split(/\s+/)[0];
    byId('heroEyebrow').textContent = 'SUA ROTINA COMERCIAL';
    byId('heroTitle').textContent = `Olá, ${firstName}. Veja onde sua atenção vale mais hoje.`;
    byId('heroSubtitle').textContent = 'Acompanhe prioridades, contatos disponíveis e abordagens já registradas em uma visão simples.';
  }
}

function renderStats() {
  const total = state.leads.length;
  const hot = state.leads.filter((lead) => lead.temperature === 'hot').length;
  const contacts = state.leads.filter(hasContact).length;
  const sent = state.leads.filter((lead) => lead.status === 'sent').length;
  const coverage = Math.round((contacts / (total || 1)) * 100);
  const metrics = [
    ['Leads na base', total, 'oportunidades únicas', 'leads', '#4f8ff7', '#edf4ff'],
    ['Alta prioridade', hot, 'prontos para revisão', 'hot', '#e99a2a', '#fff5df'],
    ['Com contato', contacts, `${coverage}% de cobertura`, 'contact', '#23af81', '#e8faf4'],
    ['Já contatados', sent, 'abordagens registradas', 'sent', '#7d67e8', '#f0edff'],
  ];
  byId('stats').innerHTML = metrics.map(([label,value,caption,key,color,soft]) => `
    <article class="metric" style="--metric-color:${color};--metric-soft:${soft}">
      <div class="metric-head"><span class="metric-label">${label}</span><span class="metric-icon">${icon(key)}</span></div>
      <strong>${value}</strong><p>${caption}</p>
    </article>`).join('');
  byId('navLeadCount').textContent = total;
  byId('heroLeadCount').textContent = contacts;
  byId('heroHotCount').textContent = hot;
  byId('heroCoverage').textContent = `${coverage}%`;
}

function summaryFor(lead) {
  if (lead.contact_whatsapp) return 'WhatsApp confirmado';
  if (lead.contact_email) return 'E-mail público disponível';
  if (lead.contact_phone) return 'Telefone público disponível';
  return lead.lead_type === 'school' ? 'Escola privada no INEP 2025' : 'Aguardando contato';
}

function renderFocus() {
  const leads = state.leads.filter(hasContact).sort((a,b) => leadScore(b) - leadScore(a)).slice(0,5);
  byId('focusLeads').innerHTML = leads.length ? leads.map((lead) => `
    <div class="focus-item">
      <span class="focus-avatar">${escapeHtml(initials(leadName(lead)).slice(0,1))}</span>
      <div class="focus-copy"><strong>${escapeHtml(leadName(lead))}</strong><small>${escapeHtml(lead.location || lead.sector || 'Local não informado')} · ${escapeHtml(summaryFor(lead))}</small></div>
      <div class="focus-score"><b>${leadScore(lead)}</b><span>${lead.temperature === 'hot' ? 'quente' : lead.temperature === 'warm' ? 'morno' : 'revisar'}</span></div>
      <a href="/leads?lead=${lead.id}">Ver contexto e preparar abordagem →</a>
    </div>`).join('') : '<div class="empty"><h3>Nenhum lead com contato disponível</h3><p>Execute o workflow para alimentar sua base.</p></div>';
}

function renderCharts() {
  const total = state.leads.length || 1;
  const contacts = state.leads.filter(hasContact).length;
  const channels = [
    ['WhatsApp', state.leads.filter((lead) => lead.contact_whatsapp).length, '#36c98f'],
    ['E-mail', state.leads.filter((lead) => lead.contact_email).length, '#4f8ff7'],
    ['Telefone', state.leads.filter((lead) => lead.contact_phone).length, '#7d67e8'],
  ];
  byId('channelsChart').innerHTML = `<div class="coverage-number"><strong>${Math.round((contacts / total) * 100)}%</strong><span>da base tem um canal público</span></div>
    <div class="channel-bars">${channels.map(([label,count,color]) => `<div class="channel-row"><span>${label}</span><div class="bar"><i style="width:${Math.round((count/total)*100)}%;--bar-color:${color}"></i></div><strong>${count}</strong></div>`).join('')}</div>`;
  const pipeline = [
    ['Mapeados', state.leads.length, '#4f8ff7'],
    ['Com contato', contacts, '#36c98f'],
    ['Quentes', state.leads.filter((lead) => lead.temperature === 'hot').length, '#e99a2a'],
    ['Contatados', state.leads.filter((lead) => lead.status === 'sent').length, '#7d67e8'],
  ];
  byId('pipelineChart').innerHTML = pipeline.map(([label,count,color]) => `<div class="pipeline-row"><span>${label}</span><div class="bar"><i style="width:${Math.round((count/total)*100)}%;--bar-color:${color}"></i></div><strong>${count}</strong></div>`).join('');
  const mix = new Map();
  state.leads.forEach((lead) => {
    const key = lead.lead_type === 'school' ? 'Escolas' : (lead.sector || 'Empresas');
    mix.set(key,(mix.get(key)||0)+1);
  });
  const groups = [...mix.entries()].sort((a,b)=>b[1]-a[1]).slice(0,5);
  byId('mixChart').innerHTML = groups.length ? groups.map(([label,count],index) => `<div class="mix-row"><span>${escapeHtml(label)}</span><div class="bar"><i style="width:${Math.round((count/total)*100)}%;--bar-color:${['#36c98f','#4f8ff7','#7d67e8','#e99a2a','#8da1b5'][index]}"></i></div><strong>${count}</strong></div>`).join('') : '<div class="empty"><p>Sem dados suficientes.</p></div>';
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

async function loadLeads() {
  byId('refresh').disabled = true;
  try {
    state.leads = await api('/api/v1/leads?limit=1000');
    renderStats(); renderFocus(); renderCharts();
    byId('lastUpdate').textContent = `Atualizado às ${new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})}`;
  } catch (error) { notify(`Não foi possível carregar a base: ${error.message}`,true); }
  finally { byId('refresh').disabled = false; }
}

async function loadUsers() {
  if (!state.identity?.is_admin) return;
  try { state.users = await api('/api/v1/admin/users'); renderUsers(); }
  catch (error) { notify(`Não foi possível carregar usuários: ${error.message}`,true); }
}

function toggleMobileMenu(open) {
  byId('sidebar').classList.toggle('open',open);
  byId('mobileOverlay').classList.toggle('hidden',!open);
}

byId('refresh').addEventListener('click',loadLeads);
byId('menuToggle').addEventListener('click',()=>toggleMobileMenu(true));
byId('mobileOverlay').addEventListener('click',()=>toggleMobileMenu(false));
byId('logoutBtn').addEventListener('click',async()=>{try{await api('/api/v1/auth/logout',{method:'POST'});}finally{location.replace('/login');}});
byId('openUserDialog').addEventListener('click',()=>byId('userDialog').showModal());
byId('closeUserDialog').addEventListener('click',()=>byId('userDialog').close());
byId('cancelUser').addEventListener('click',()=>byId('userDialog').close());
byId('userForm').addEventListener('submit',async(event)=>{
  event.preventDefault();
  try {
    await api('/api/v1/admin/users',{method:'POST',body:JSON.stringify({display_name:byId('newDisplayName').value,username:byId('newUsername').value,password:byId('newPassword').value,role:'user'})});
    event.target.reset(); byId('userDialog').close(); await loadUsers(); notify('Credencial criada com sucesso.');
  } catch (error) { notify(error.message,true); }
});
byId('userList').addEventListener('click',async(event)=>{
  const toggle = event.target.closest('[data-user-toggle]');
  const password = event.target.closest('[data-user-password]');
  try {
    if (toggle) { await api(`/api/v1/admin/users/${toggle.dataset.userToggle}`,{method:'PATCH',body:JSON.stringify({active:toggle.dataset.active!=='true'})}); await loadUsers(); notify('Acesso atualizado.'); }
    if (password) { const value=window.prompt('Digite a nova senha temporária (mínimo de 8 caracteres):'); if(!value)return; await api(`/api/v1/admin/users/${password.dataset.userPassword}/reset-password`,{method:'POST',body:JSON.stringify({password:value})}); notify('Senha atualizada.'); }
  } catch (error) { notify(error.message,true); }
});

(async function start(){
  try {
    applyIdentity(await api('/api/v1/auth/me'));
    await Promise.all([loadLeads(),loadUsers()]);
    window.setInterval(loadLeads,90000);
  } catch (_) { location.replace('/login?next=/dashboard'); }
})();
