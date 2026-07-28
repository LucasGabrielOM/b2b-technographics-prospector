const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char]));
const initials = (value) => String(value || 'LP').split(/\s+/).filter(Boolean).slice(0,2).map((part) => part[0]).join('').toUpperCase();
const state = { identity: null, mapsConfigured: false, running: false, startedAt: null, timer: null };

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

function splitValues(value) {
  return String(value || '').split(',').map((item) => item.trim()).filter(Boolean);
}

function applyIdentity(identity) {
  state.identity = identity;
  document.body.dataset.role = identity.role;
  byId('profileName').textContent = identity.display_name;
  byId('profileRole').textContent = identity.is_admin ? 'Administrador' : 'Usuário comercial';
  byId('profileAvatar').textContent = initials(identity.display_name);
  byId('workspaceInitial').textContent = initials(identity.display_name).slice(0,1);
  if (!identity.is_admin) location.replace('/dashboard');
}

function selectAudience(audience) {
  byId('audience').value = audience;
  document.querySelectorAll('.audience-tab').forEach((tab) => tab.classList.toggle('active',tab.dataset.audience===audience));
  byId('schoolFields').classList.toggle('hidden',audience!=='schools');
  byId('companyFields').classList.toggle('hidden',audience!=='companies');
  byId('sourceSummary').textContent = audience==='schools' ? 'Censo Escolar INEP 2025' : 'Sites e diretórios públicos';
  const city = audience==='schools' ? (splitValues(byId('schoolCities').value)[0] || 'Florianópolis') : byId('companyCity').value;
  const stateName = audience==='schools' ? (splitValues(byId('schoolStates').value)[0] || 'SC') : byId('companyState').value;
  byId('mapsQuery').value = audience==='schools'
    ? `escolas particulares em ${city} ${stateName}`
    : `${splitValues(byId('companySegments').value)[0] || 'empresas'} em ${city} ${stateName}`;
}

function runPayload() {
  const audience = byId('audience').value;
  if (audience === 'schools') {
    return {
      audience,
      states: splitValues(byId('schoolStates').value),
      cities: splitValues(byId('schoolCities').value),
      limit: Number(byId('schoolLimit').value),
      require_phone: byId('requirePhone').checked,
      validate_cnpj: byId('validateCnpj').checked,
      use_google_maps: byId('useGoogleMapsSchool').checked,
      only_new: true,
      segments: ['educacao'],
    };
  }
  return {
    audience,
    city: byId('companyCity').value.trim(),
    state: byId('companyState').value.trim(),
    segments: splitValues(byId('companySegments').value),
    limit: Number(byId('companyLimit').value),
    min_score: Number(byId('minScore').value),
    include_complaints: byId('includeComplaints').checked,
    only_new: true,
  };
}

function setRunState(kind, title, copy) {
  byId('runStatusBadge').className = `status-badge ${kind}`;
  byId('runStatusBadge').textContent = kind==='running' ? 'Executando' : kind==='success' ? 'Concluído' : kind==='error' ? 'Falhou' : 'Aguardando';
  byId('runStatus').className = `run-status ${kind}`;
  byId('runStatus').innerHTML = `<span class="status-orbit"><i></i></span><h3>${escapeHtml(title)}</h3><p>${escapeHtml(copy)}</p>`;
}

function startTimer() {
  state.startedAt = Date.now();
  clearInterval(state.timer);
  state.timer = setInterval(() => {
    const seconds = Math.floor((Date.now()-state.startedAt)/1000);
    const label = seconds < 60 ? `${seconds}s` : `${Math.floor(seconds/60)}min ${seconds%60}s`;
    setRunState('running','Pesquisa em andamento',`Consultando as fontes e bloqueando duplicidades · ${label}`);
  },1000);
}

function leadSummary(lead) {
  const channel = lead.contact_whatsapp ? 'WhatsApp' : lead.contact_email ? 'E-mail' : lead.contact_phone ? 'Telefone' : 'Sem contato';
  return `<div class="run-result-item">
    <span>${escapeHtml(initials(lead.company_name || lead.domain).slice(0,1))}</span>
    <div><strong>${escapeHtml(lead.company_name || lead.domain)}</strong><small>${escapeHtml(lead.location || 'Local não informado')} · ${channel}</small></div>
    <b>${Number(lead.lead_score || 0)}</b>
  </div>`;
}

function renderRunResults(result) {
  const leads = result.leads || [];
  byId('runResults').classList.remove('hidden');
  byId('runResults').innerHTML = `
    <div class="result-total"><strong>${leads.length}</strong><span>novos leads adicionados</span></div>
    <div>${leads.slice(0,5).map(leadSummary).join('')}</div>
    ${leads.length > 5 ? `<p class="more-results">+ ${leads.length-5} resultados disponíveis na central</p>` : ''}
    <a class="button button-primary" href="/leads">Abrir novos leads</a>`;
}

async function runProspecting(event) {
  event.preventDefault();
  if (state.running) return;
  state.running = true;
  byId('runProspecting').disabled = true;
  byId('runProspecting').querySelector('span').textContent = 'Executando pesquisa…';
  byId('runResults').classList.add('hidden');
  notify('');
  setRunState('running','Preparando a pesquisa','Validando público, região e limites antes de consultar as fontes.');
  startTimer();
  try {
    const result = await api('/api/v1/prospecting/run',{method:'POST',body:JSON.stringify(runPayload())});
    clearInterval(state.timer);
    renderRunResults(result);
    if (result.created_count) {
      setRunState('success','Pesquisa concluída',`${result.created_count} novos leads foram adicionados sem duplicar a base.`);
      notify(`${result.created_count} novos leads adicionados à central.`);
    } else {
      setRunState('success','Nenhum lead novo nesta rodada',result.message || 'Os resultados encontrados já estavam na base ou não atenderam aos filtros escolhidos.');
      notify(result.message || 'A execução terminou corretamente, mas não encontrou leads novos.');
    }
  } catch (error) {
    clearInterval(state.timer);
    setRunState('error','A pesquisa não terminou',error.message);
    notify(error.message,true);
  } finally {
    state.running = false;
    byId('runProspecting').disabled = false;
    byId('runProspecting').querySelector('span').textContent = 'Iniciar prospecção';
  }
}

function updateMapsSku() {
  const reviews = byId('mapsReviews').checked;
  if (reviews) byId('mapsContacts').checked = true;
  const contacts = byId('mapsContacts').checked;
  byId('mapsSku').textContent = reviews
    ? 'Text Search Enterprise + Atmosphere · franquia de 1.000 eventos/mês · até 5 avaliações por relevância'
    : contacts
      ? 'Text Search Enterprise · franquia de 1.000 eventos/mês'
      : 'Text Search Pro · franquia de 5.000 eventos/mês';
}

function renderMapsResults(data) {
  const places = data.places || [];
  byId('mapsResults').innerHTML = places.length ? `
    <div class="maps-result-head"><strong>${places.length} locais encontrados</strong><span>${escapeHtml(data.sku)}</span></div>
    ${places.map((place) => `
      <article class="place-result">
        <div><strong>${escapeHtml(place.name || 'Local sem nome')}</strong><small>${escapeHtml(place.address || 'Endereço não informado')}</small></div>
        <div class="place-meta">
          ${place.rating ? `<span>★ ${escapeHtml(place.rating)} · ${escapeHtml(place.review_count || 0)} avaliações</span>` : ''}
          ${place.phone ? `<span>${escapeHtml(place.phone)}</span>` : ''}
          ${place.website ? `<a href="${escapeHtml(place.website)}" target="_blank" rel="noopener">Site ↗</a>` : ''}
          ${place.google_maps_url ? `<a href="${escapeHtml(place.google_maps_url)}" target="_blank" rel="noopener">Google Maps ↗</a>` : ''}
        </div>
        ${place.reviews?.length ? `<div class="review-samples"><span>Amostra por relevância</span>${place.reviews.slice(0,2).map((review) => `<blockquote><b>${escapeHtml(review.rating || '')}★ · ${escapeHtml(review.published || '')}</b><p>${escapeHtml(review.text || 'Avaliação sem texto')}</p></blockquote>`).join('')}</div>` : ''}
      </article>`).join('')}` : '<div class="maps-empty">Nenhum local retornado para esta consulta.</div>';
}

async function testMaps(event) {
  event.preventDefault();
  if (!state.mapsConfigured) {
    notify('Configure GOOGLE_MAPS_API_KEY no Render antes de testar.',true);
    return;
  }
  byId('testMaps').disabled = true;
  byId('testMaps').textContent = 'Consultando Google Maps…';
  byId('mapsResults').innerHTML = '<div class="maps-empty">Buscando locais…</div>';
  try {
    const result = await api('/api/v1/google-places/preview',{method:'POST',body:JSON.stringify({
      query: byId('mapsQuery').value,
      limit: Number(byId('mapsLimit').value),
      include_contacts: byId('mapsContacts').checked,
      include_reviews: byId('mapsReviews').checked,
    })});
    renderMapsResults(result);
  } catch (error) {
    byId('mapsResults').innerHTML = `<div class="maps-empty error">${escapeHtml(error.message)}</div>`;
  } finally {
    byId('testMaps').disabled = false;
    byId('testMaps').textContent = 'Testar Google Maps';
  }
}

async function loadConfig() {
  const config = await api('/api/v1/prospecting/config');
  state.mapsConfigured = config.google_maps_configured;
  byId('mapsStatus').className = `integration-pill ${state.mapsConfigured ? 'ready' : 'missing'}`;
  byId('mapsStatus').textContent = state.mapsConfigured ? 'Configurada' : 'Não configurada';
  byId('connectionLabel').textContent = state.mapsConfigured ? 'Google Maps conectado' : 'Google Maps opcional';
  byId('useGoogleMapsSchool').checked = state.mapsConfigured;
  byId('useGoogleMapsSchool').disabled = !state.mapsConfigured;
  byId('useGoogleMapsSchool').closest('.check-card').classList.toggle('option-disabled',!state.mapsConfigured);
  if (!state.mapsConfigured) {
    byId('mapsResults').innerHTML = '<div class="maps-empty"><strong>Falta somente a chave do servidor.</strong><br>Ative a Places API (New), crie uma chave restrita e adicione <code>GOOGLE_MAPS_API_KEY</code> no Render.</div>';
  }
}

function toggleMobileMenu(open) {
  byId('sidebar').classList.toggle('open',open);
  byId('mobileOverlay').classList.toggle('hidden',!open);
}

document.querySelectorAll('.audience-tab').forEach((tab) => tab.addEventListener('click',()=>selectAudience(tab.dataset.audience)));
byId('prospectingForm').addEventListener('submit',runProspecting);
byId('mapsForm').addEventListener('submit',testMaps);
byId('mapsContacts').addEventListener('change',updateMapsSku);
byId('mapsReviews').addEventListener('change',updateMapsSku);
byId('menuToggle').addEventListener('click',()=>toggleMobileMenu(true));
byId('mobileOverlay').addEventListener('click',()=>toggleMobileMenu(false));
byId('logoutBtn').addEventListener('click',async()=>{try{await api('/api/v1/auth/logout',{method:'POST'});}finally{location.replace('/login');}});

(async function start() {
  try {
    applyIdentity(await api('/api/v1/auth/me'));
    selectAudience('schools');
    updateMapsSku();
    await loadConfig();
  } catch (_) {
    location.replace('/login?next=/prospecting');
  }
})();
