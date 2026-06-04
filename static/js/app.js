/* ═══════════════════════════════════════════════════════════════
   SANDY DASHBOARD v2 · App Logic
   ECA MEDIA BO · 2026
═══════════════════════════════════════════════════════════════ */

const App = {
  usuario: null,
  esAdmin: false,
  leads: [],
  filtrosActivos: {},
  seccionActual: 'dashboard',

  // ── INIT ──────────────────────────────────────────────────────
  async init() {
    const me = await fetch('/api/me').then(r => r.json());
    if (me.autenticado) {
      this.usuario = me.usuario;
      this.esAdmin = me.es_admin;
      this.mostrarApp();
    } else {
      this.mostrarLogin();
    }
  },

  // ── AUTH ──────────────────────────────────────────────────────
  mostrarLogin() {
    document.getElementById('login-screen').classList.remove('hidden');
    document.getElementById('app').classList.add('hidden');
    document.getElementById('login-usuario').focus();
  },

  mostrarApp() {
    document.getElementById('login-screen').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');

    // usuario UI
    document.getElementById('user-name-sidebar').textContent = this.usuario;
    document.getElementById('user-role-sidebar').textContent = this.esAdmin ? 'Administrador' : 'Viewer';
    document.getElementById('user-avatar').textContent = this.usuario[0].toUpperCase();

    // mostrar secciones admin
    if (this.esAdmin) {
      ['admin-only-export', 'admin-only-upload', 'admin-only-meta'].forEach(id => {
        document.getElementById(id).style.display = '';
      });
    }

    this.bindEvents();
    this.cargarFiltros();
    this.cargarStats();
    this.checkMetaStatus();
    this.cargarLeads();
  },

  // ── EVENTS ────────────────────────────────────────────────────
  bindEvents() {
    // Login form
    document.getElementById('login-form').addEventListener('submit', e => {
      e.preventDefault();
      this.login();
    });

    // Logout
    document.getElementById('logout-btn').addEventListener('click', () => this.logout());

    // Sidebar toggle
    document.getElementById('sidebar-toggle').addEventListener('click', () => {
      document.getElementById('sidebar').classList.toggle('collapsed');
    });

    // Mobile menu
    document.getElementById('mobile-menu-btn').addEventListener('click', () => {
      document.getElementById('sidebar').classList.toggle('mobile-open');
    });

    // Nav items
    document.querySelectorAll('.nav-item[data-section]').forEach(btn => {
      btn.addEventListener('click', () => {
        this.navegarA(btn.dataset.section);
        document.getElementById('sidebar').classList.remove('mobile-open');
      });
    });

    // Refresh
    document.getElementById('refresh-btn').addEventListener('click', () => {
      this.cargarLeads(true);
      this.cargarStats();
    });

    // Filtros
    document.getElementById('btn-aplicar-filtros').addEventListener('click', () => this.cargarLeads());
    document.getElementById('btn-limpiar-filtros').addEventListener('click', () => this.limpiarFiltros());
    document.getElementById('filter-busqueda').addEventListener('keydown', e => {
      if (e.key === 'Enter') this.cargarLeads();
    });

    // Export rápido
    document.getElementById('quick-export-excel').addEventListener('click', () => exportar('excel'));
    document.getElementById('quick-export-csv').addEventListener('click', () => exportar('csv'));
    document.getElementById('quick-export-pdf').addEventListener('click', () => exportar('pdf'));
    document.getElementById('quick-export-html').addEventListener('click', () => exportar('html'));

    // Upload
    const fileInput = document.getElementById('file-input');
    const dropArea = document.getElementById('upload-drop-area');

    fileInput.addEventListener('change', () => this.subirArchivos(fileInput.files));

    dropArea.addEventListener('dragover', e => { e.preventDefault(); dropArea.classList.add('drag-over'); });
    dropArea.addEventListener('dragleave', () => dropArea.classList.remove('drag-over'));
    dropArea.addEventListener('drop', e => {
      e.preventDefault();
      dropArea.classList.remove('drag-over');
      this.subirArchivos(e.dataTransfer.files);
    });

    // Meta
    document.getElementById('btn-guardar-meta').addEventListener('click', () => this.guardarMeta());
    document.getElementById('btn-sync-meta').addEventListener('click', () => this.syncMeta());
  },

  // ── NAVEGACIÓN ────────────────────────────────────────────────
  navegarA(seccion) {
    this.seccionActual = seccion;

    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    document.querySelector(`.nav-item[data-section="${seccion}"]`).classList.add('active');

    document.querySelectorAll('.section').forEach(s => s.classList.add('hidden'));
    document.getElementById(`section-${seccion}`).classList.remove('hidden');

    const titulos = {
      dashboard: ['Dashboard', 'Resumen general de leads'],
      leads: ['Leads', 'Lista filtrable de todos los leads'],
      exportar: ['Exportar', 'Descarga reportes en distintos formatos'],
      subir: ['Subir Archivos', 'Carga archivos CSV o Excel'],
      meta: ['Meta Ads', 'Conexión con Facebook & Instagram Ads'],
    };
    const [t, s] = titulos[seccion] || ['', ''];
    document.getElementById('page-title').textContent = t;
    document.getElementById('page-subtitle').textContent = s;
  },

  // ── LOGIN / LOGOUT ────────────────────────────────────────────
  async login() {
    const usuario = document.getElementById('login-usuario').value;
    const contrasena = document.getElementById('login-password').value;
    const errDiv = document.getElementById('login-error');
    const btnText = document.getElementById('login-btn-text');
    const spinner = document.getElementById('login-spinner');

    errDiv.classList.add('hidden');
    btnText.classList.add('hidden');
    spinner.classList.remove('hidden');

    try {
      const resp = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ usuario, contrasena }),
      });
      const data = await resp.json();
      if (data.ok) {
        this.usuario = data.usuario;
        this.esAdmin = data.es_admin;
        this.mostrarApp();
      } else {
        errDiv.classList.remove('hidden');
      }
    } catch (e) {
      errDiv.classList.remove('hidden');
    } finally {
      btnText.classList.remove('hidden');
      spinner.classList.add('hidden');
    }
  },

  async logout() {
    await fetch('/api/logout', { method: 'POST' });
    this.usuario = null;
    this.esAdmin = false;
    this.leads = [];
    this.mostrarLogin();
  },

  // ── DATOS ─────────────────────────────────────────────────────
  async cargarFiltros() {
    try {
      const data = await fetch('/api/filtros').then(r => r.json());
      this.poblarSelect('filter-proyecto', data.proyectos);
      this.poblarSelect('filter-presupuesto', data.presupuestos);
      this.poblarSelect('filter-credito', data.creditos);
      this.poblarSelect('filter-plataforma', data.plataformas);
      this.poblarSelect('filter-campana', data.campanas);
    } catch (e) { console.warn('Error cargando filtros:', e); }
  },

  poblarSelect(id, opciones) {
    const sel = document.getElementById(id);
    sel.innerHTML = '';
    opciones.forEach(op => {
      const opt = document.createElement('option');
      opt.value = op;
      opt.textContent = op;
      sel.appendChild(opt);
    });
  },

  async cargarLeads(forzar = false) {
    this.mostrarCargando('Cargando leads...');
    try {
      const params = new URLSearchParams();
      if (forzar) params.set('forzar', 'true');

      const proyecto = this.getSelectValues('filter-proyecto');
      if (proyecto.length) params.set('proyecto', proyecto.join('|'));

      const presupuesto = this.getSelectValues('filter-presupuesto');
      if (presupuesto.length) params.set('presupuesto', presupuesto.join('|'));

      const credito = this.getSelectValues('filter-credito');
      if (credito.length) params.set('credito', credito.join('|'));

      const plataforma = this.getSelectValues('filter-plataforma');
      if (plataforma.length) params.set('plataforma', plataforma.join('|'));

      const campana = this.getSelectValues('filter-campana');
      if (campana.length) params.set('campana', campana.join('|'));

      const busqueda = document.getElementById('filter-busqueda').value.trim();
      if (busqueda) params.set('busqueda', busqueda);

      const fi = document.getElementById('filter-fecha-inicio').value;
      const ff = document.getElementById('filter-fecha-fin').value;
      if (fi) params.set('fecha_inicio', fi);
      if (ff) params.set('fecha_fin', ff);

      const data = await fetch(`/api/leads?${params}`).then(r => r.json());
      this.leads = data.leads || [];

      document.getElementById('leads-badge').textContent = this.leads.length;
      document.getElementById('leads-count-label').textContent = `${this.leads.length} leads encontrados`;

      if (data.ultima_actualizacion) {
        document.getElementById('last-update').textContent = `Actualizado: ${data.ultima_actualizacion}`;
      }

      this.renderTabla();

      // Guardar filtros activos para exportaciones
      this.filtrosActivos = { proyecto: proyecto.join('|'), presupuesto: presupuesto.join('|'),
        credito: credito.join('|'), plataforma: plataforma.join('|'),
        campana: campana.join('|'), busqueda };

    } catch (e) {
      toast('Error cargando leads', 'error');
    } finally {
      this.ocultarCargando();
    }
  },

  getSelectValues(id) {
    const sel = document.getElementById(id);
    return Array.from(sel.selectedOptions).map(o => o.value);
  },

  limpiarFiltros() {
    ['filter-proyecto','filter-presupuesto','filter-credito','filter-plataforma','filter-campana'].forEach(id => {
      const sel = document.getElementById(id);
      Array.from(sel.options).forEach(o => o.selected = false);
    });
    document.getElementById('filter-busqueda').value = '';
    document.getElementById('filter-fecha-inicio').value = '';
    document.getElementById('filter-fecha-fin').value = '';
    this.cargarLeads();
  },

  // ── TABLA ─────────────────────────────────────────────────────
  renderTabla() {
    const tbody = document.getElementById('leads-tbody');

    if (!this.leads.length) {
      tbody.innerHTML = `<tr><td colspan="10" class="table-empty">
        <div class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>
          <p>No se encontraron leads con esos filtros</p>
        </div>
      </td></tr>`;
      return;
    }

    const filas = this.leads.map((lead, i) => {
      const nombre = esc(lead['Nombre completo'] || '');
      const tel = esc(lead['Teléfono'] || '');
      const correo = esc(lead['Correo'] || '');
      const pres = esc(lead['Presupuesto'] || '');
      const cred = esc(lead['Tipo de Crédito'] || '');
      const proy = esc(lead['Proyecto'] || '');
      const plat = (lead['Plataforma'] || '').toLowerCase();
      const fecha = esc((lead['Fecha de Creación'] || '').toString().slice(0, 10));

      const badgeClass = plat.includes('instagram') ? 'badge-instagram' : 'badge-facebook';
      const badgeLabel = plat.includes('instagram') ? 'Instagram' : 'Facebook';

      let btnWA = '<span class="no-phone">Sin teléfono</span>';
      if (tel && tel !== 'None' && tel !== 'nan') {
        const msg = encodeURIComponent(`Hola ${nombre}! 👋 Vi tu interés en ${proy}. Presupuesto: ${pres}, Crédito: ${cred}. ¿Te comparto más detalles?`);
        btnWA = `<a href="https://wa.me/${tel}?text=${msg}" target="_blank" class="btn-wa">💬 WhatsApp</a>`;
      }

      return `<tr class="fade-in">
        <td class="td-num">${i + 1}</td>
        <td class="td-name">${nombre}</td>
        <td class="td-phone">${tel}</td>
        <td class="td-email" title="${correo}">${correo}</td>
        <td class="td-budget">${pres}</td>
        <td>${cred}</td>
        <td>${proy}</td>
        <td><span class="badge-platform ${badgeClass}">${badgeLabel}</span></td>
        <td class="td-date">${fecha}</td>
        <td>${btnWA}</td>
      </tr>`;
    }).join('');

    tbody.innerHTML = filas;
  },

  // ── STATS / CHARTS ────────────────────────────────────────────
  async cargarStats() {
    try {
      const data = await fetch('/api/stats').then(r => r.json());

      document.getElementById('kpi-total').textContent = data.total.toLocaleString();
      document.getElementById('kpi-hoy').textContent = data.hoy.toLocaleString();
      document.getElementById('kpi-semana').textContent = data.semana.toLocaleString();
      document.getElementById('kpi-proyectos').textContent = data.proyectos;

      this.renderChart('chart-proyecto', data.por_proyecto, 'bar', 'Leads por Proyecto');
      this.renderChart('chart-plataforma', data.por_plataforma, 'pie', 'Plataforma');
      this.renderChart('chart-presupuesto', data.por_presupuesto, 'bar', 'Leads por Presupuesto');
      this.renderChart('chart-credito', data.por_credito, 'bar', 'Tipo de Crédito');

    } catch (e) { console.warn('Error cargando stats:', e); }
  },

  renderChart(containerId, datos, tipo, titulo) {
    const el = document.getElementById(containerId);
    if (!el || !datos || !datos.length) return;

    const labels = datos.map(d => d.label);
    const values = datos.map(d => d.value);
    const GOLD = '#C9A961';
    const COLORS = ['#C9A961','#4db8ff','#22c55e','#a855f7','#f97316','#ef4444','#06b6d4','#84cc16'];

    const layout = {
      paper_bgcolor: 'transparent',
      plot_bgcolor: 'transparent',
      font: { family: 'Inter, sans-serif', color: '#6b6b8a', size: 11 },
      margin: { t: 10, r: 10, b: 60, l: 40 },
      showlegend: tipo === 'pie',
      legend: { font: { color: '#e8e8f0', size: 11 }, bgcolor: 'transparent' },
      xaxis: {
        gridcolor: '#1e1e2e',
        tickfont: { color: '#6b6b8a', size: 10 },
        tickangle: -35,
      },
      yaxis: {
        gridcolor: '#1e1e2e',
        tickfont: { color: '#6b6b8a' },
      },
    };

    const config = { responsive: true, displayModeBar: false };

    if (tipo === 'bar') {
      Plotly.newPlot(el, [{
        x: labels, y: values,
        type: 'bar',
        marker: { color: GOLD, opacity: .85 },
        hovertemplate: '%{x}<br><b>%{y}</b><extra></extra>',
      }], layout, config);
    } else {
      Plotly.newPlot(el, [{
        labels, values,
        type: 'pie',
        hole: .4,
        marker: { colors: COLORS },
        textfont: { color: '#e8e8f0', size: 11 },
        hovertemplate: '%{label}<br><b>%{value}</b> (%{percent})<extra></extra>',
      }], { ...layout, margin: { t: 10, r: 10, b: 10, l: 10 } }, config);
    }
  },

  // ── UPLOAD ────────────────────────────────────────────────────
  async subirArchivos(files) {
    if (!files || !files.length) return;

    this.mostrarCargando('Subiendo archivos...');
    const formData = new FormData();
    Array.from(files).forEach(f => formData.append('files', f));

    try {
      const resp = await fetch('/api/upload', { method: 'POST', body: formData });
      const data = await resp.json();

      const resultsDiv = document.getElementById('upload-results');
      resultsDiv.classList.remove('hidden');
      resultsDiv.innerHTML = data.resultados.map(r => `
        <div class="upload-result-item ${r.ok ? 'ok' : 'err'}">
          <span style="font-size:16px">${r.ok ? '✅' : '❌'}</span>
          <span><strong>${esc(r.archivo)}</strong> — ${r.ok ? 'Subido correctamente' : esc(r.error || 'Error')}</span>
        </div>
      `).join('');

      const ok = data.resultados.filter(r => r.ok).length;
      if (ok > 0) {
        toast(`${ok} archivo(s) subido(s) correctamente`, 'success');
        setTimeout(() => {
          this.cargarLeads(true);
          this.cargarStats();
          this.cargarFiltros();
        }, 1000);
      }
    } catch (e) {
      toast('Error al subir archivos', 'error');
    } finally {
      this.ocultarCargando();
    }
  },

  // ── META ADS ──────────────────────────────────────────────────
  async checkMetaStatus() {
    try {
      const data = await fetch('/api/meta/status').then(r => r.json());
      const dot = document.getElementById('meta-status-dot');
      const badge = document.getElementById('meta-badge');
      const statusText = document.getElementById('meta-connection-status');

      if (data.conectado) {
        dot.className = 'status-dot green';
        badge.className = 'meta-badge badge-connected';
        badge.textContent = 'Conectado';
        statusText.textContent = 'Conectado a Meta Ads';
      } else {
        dot.className = 'status-dot red';
        badge.className = 'meta-badge badge-disconnected';
        badge.textContent = 'Desconectado';
        statusText.textContent = 'Sin conexión a Meta Ads';
      }
    } catch (e) {}
  },

  async guardarMeta() {
    const token = document.getElementById('meta-token-input').value.trim();
    const account = document.getElementById('meta-account-input').value.trim();
    const msgDiv = document.getElementById('meta-msg');

    if (!token) { toast('Ingresa un token', 'error'); return; }

    try {
      const resp = await fetch('/api/meta/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, ad_account: account }),
      });
      const data = await resp.json();
      msgDiv.classList.remove('hidden', 'ok', 'err');
      if (data.ok) {
        msgDiv.classList.add('ok');
        msgDiv.textContent = '✅ Token guardado correctamente';
        this.checkMetaStatus();
        toast('Meta Ads conectado', 'success');
      } else {
        msgDiv.classList.add('err');
        msgDiv.textContent = `❌ Error: ${data.error}`;
      }
    } catch (e) {
      toast('Error guardando token', 'error');
    }
  },

  async syncMeta() {
    this.mostrarCargando('Sincronizando desde Meta Ads...');
    try {
      const resp = await fetch('/api/meta/sync', { method: 'POST' });
      const data = await resp.json();
      if (data.ok) {
        toast(`✅ ${data.total} leads sincronizados desde Meta Ads`, 'success');
        this.cargarLeads();
        this.cargarStats();
      } else {
        toast(`Error: ${data.error}`, 'error');
      }
    } catch (e) {
      toast('Error sincronizando', 'error');
    } finally {
      this.ocultarCargando();
    }
  },

  // ── LOADING ───────────────────────────────────────────────────
  mostrarCargando(texto = 'Cargando...') {
    document.getElementById('loading-text').textContent = texto;
    document.getElementById('loading-overlay').classList.remove('hidden');
  },
  ocultarCargando() {
    document.getElementById('loading-overlay').classList.add('hidden');
  },
};

// ── EXPORTACIONES ────────────────────────────────────────────────
function exportar(tipo) {
  const filtros = encodeURIComponent(JSON.stringify(App.filtrosActivos));
  const url = `/api/export/${tipo}?filtros=${filtros}`;
  const a = document.createElement('a');
  a.href = url;
  a.click();
  toast(`Generando ${tipo.toUpperCase()}...`, 'info');
}

// ── TOAST ────────────────────────────────────────────────────────
function toast(mensaje, tipo = 'info', duracion = 3500) {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  const icons = { success: '✅', error: '❌', info: 'ℹ️' };
  el.className = `toast ${tipo}`;
  el.innerHTML = `<span>${icons[tipo] || 'ℹ️'}</span><span>${esc(mensaje)}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateX(20px)';
    el.style.transition = '.3s ease';
    setTimeout(() => el.remove(), 300);
  }, duracion);
}

// ── ESCAPE HTML ──────────────────────────────────────────────────
function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── START ────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => App.init());
