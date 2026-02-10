let currentUser = localStorage.getItem('selectedUser') || 'josip';

document.querySelectorAll('.toggle-btn').forEach(btn => {
  if (btn.dataset.user === currentUser) btn.classList.add('active');
  
  btn.addEventListener('click', () => {
    currentUser = btn.dataset.user;
    localStorage.setItem('selectedUser', currentUser);
    document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    loadData();
  });
});

function loadData(){
  document.getElementById('results').innerHTML='<div class="loading"><div class="spinner"></div>Učitavam podatke...</div>';
  fetch(`/api/check?user=${currentUser}`)
  .then(response=>response.json())
  .then(data=>{
    if(!data.success)throw new Error(data.error||'Nepoznata greška');
    const cacheStatus=data.cached?`💾 Cached podaci (${data.last_update})`:`🔄 Osvježeno (${data.last_update})`;
    let html=`<div class="date-banner">📅 ${data.day}, ${data.date}</div><div class="cache-info ${data.cached?'cached':''}">${cacheStatus}</div><div class="summary"><div class="summary-card open"><div class="number">${data.summary.open}</div><div class="label">RADI</div></div><div class="summary-card closed"><div class="number">${data.summary.closed}</div><div class="label">ZATVORENO</div></div></div>`;
    data.stores.forEach(store=>{
      const icon=store.open?'✅':'❌';
      const statusClass=store.open?'open':'closed';
      html+=`<div class="store"><div class="store-icon">${icon}</div><div class="store-info"><div class="store-chain">${store.chain}</div><div class="store-name">${store.name}</div><span class="store-hours ${statusClass}">${store.hours}</span></div></div>`;
    });
    document.getElementById('results').innerHTML=html;
  })
  .catch(error=>{
    document.getElementById('results').innerHTML=`<div class="error"><strong>⚠️ Greška:</strong><br>${error.message}</div>`;
  });
}

loadData();
