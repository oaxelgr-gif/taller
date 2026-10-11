/* =====================================================================
   SGT-Mecánico · JS principal
   Tema, drawer, toasts, confirmaciones, formularios AJAX, tablas en vivo,
   modales de edición y gráfica de barras (SVG, sin dependencias).
   ===================================================================== */
(function () {
  "use strict";

  const $ = (sel, ctx) => (ctx || document).querySelector(sel);
  const $$ = (sel, ctx) => Array.from((ctx || document).querySelectorAll(sel));
  const MXN = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN" });
  const csrf = () => ($('meta[name="csrf-token"]') || {}).content || "";

  function store(op, key, val) {
    try {
      if (op === "get") return window.localStorage.getItem(key);
      if (op === "set") window.localStorage.setItem(key, val);
    } catch (_) { /* almacenamiento no disponible */ }
    return null;
  }
  function flash(op, val) {
    try {
      if (op === "get") { const v = sessionStorage.getItem("sgt_toast"); sessionStorage.removeItem("sgt_toast"); return v; }
      sessionStorage.setItem("sgt_toast", JSON.stringify(val));
    } catch (_) { /* ignorar */ }
    return null;
  }

  /* ---- Tema claro / oscuro ------------------------------------------------ */
  function aplicarTema(t) {
    document.documentElement.setAttribute("data-bs-theme", t);
    $$("[data-theme-toggle] i").forEach((i) => { i.className = t === "dark" ? "bi bi-sun" : "bi bi-moon-stars"; });
  }
  aplicarTema(document.documentElement.getAttribute("data-bs-theme") || "dark");
  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-theme-toggle]")) return;
    const nuevo = document.documentElement.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
    aplicarTema(nuevo);
    store("set", "sgt_tema", nuevo);
  });

  /* ---- Drawer móvil ---------------------------------------------------------- */
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-drawer-toggle]")) { document.body.classList.toggle("drawer-open"); return; }
    if (e.target.closest(".drawer-backdrop") || (document.body.classList.contains("drawer-open") && e.target.closest(".sidebar a.nav-link-glass"))) {
      document.body.classList.remove("drawer-open");
    }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") document.body.classList.remove("drawer-open"); });

  /* ---- Toasts ----------------------------------------------------------------- */
  const ICONOS = { success: "bi-check-circle-fill", danger: "bi-x-octagon-fill", warning: "bi-exclamation-triangle-fill", info: "bi-info-circle-fill" };
  function toast(mensaje, tipo, ms) {
    tipo = ICONOS[tipo] ? tipo : (tipo === "error" ? "danger" : "info");
    let cont = $("#toasts");
    if (!cont) { cont = document.createElement("div"); cont.id = "toasts"; cont.setAttribute("aria-live", "polite"); document.body.appendChild(cont); }
    const t = document.createElement("div");
    t.className = "toast-glass " + tipo;
    t.setAttribute("role", tipo === "danger" ? "alert" : "status");
    t.innerHTML = '<i class="bi ' + ICONOS[tipo] + '"></i><div class="msg"></div><button type="button" class="cerrar" aria-label="Cerrar">&times;</button>';
    t.querySelector(".msg").textContent = mensaje;
    const quitar = () => { t.classList.add("saliendo"); setTimeout(() => t.remove(), 300); };
    t.querySelector(".cerrar").addEventListener("click", quitar);
    cont.appendChild(t);
    setTimeout(quitar, ms || (tipo === "danger" ? 7000 : 4500));
  }

  /* ---- Confirmación en cristal -------------------------------------------------- */
  function confirmar(mensaje, opciones) {
    opciones = opciones || {};
    const el = $("#modalConfirmar");
    if (!el || !window.bootstrap) return Promise.resolve(window.confirm(mensaje));
    $("#confirmarTitulo", el).textContent = opciones.titulo || "Confirmar acción";
    $("#confirmarMensaje", el).textContent = mensaje;
    const ok = $("#confirmarOk", el);
    ok.textContent = opciones.boton || "Confirmar";
    ok.className = "btn " + (opciones.peligro ? "btn-danger" : "btn-primary");
    const modal = window.bootstrap.Modal.getOrCreateInstance(el);
    return new Promise((resolve) => {
      let respondido = false;
      const fin = (v) => { if (respondido) return; respondido = true; ok.removeEventListener("click", alAceptar); el.removeEventListener("hidden.bs.modal", alCerrar); resolve(v); };
      const alAceptar = () => { fin(true); modal.hide(); };
      const alCerrar = () => fin(false);
      ok.addEventListener("click", alAceptar);
      el.addEventListener("hidden.bs.modal", alCerrar);
      modal.show();
    });
  }

  /* ---- Peticiones ----------------------------------------------------------------- */
  async function pedir(url, opciones) {
    opciones = opciones || {};
    const cabeceras = Object.assign({ "X-Requested-With": "XMLHttpRequest", Accept: "application/json", "X-CSRFToken": csrf() }, opciones.headers || {});
    let resp;
    try {
      resp = await fetch(url, Object.assign({ credentials: "same-origin" }, opciones, { headers: cabeceras }));
    } catch (err) {
      if (err.name === "AbortError") throw err;
      return { ok: false, mensaje: "No hay conexión con el servidor. Revisa la red e inténtalo de nuevo." };
    }
    if (resp.redirected && resp.url.indexOf("/login") !== -1) { window.location.href = resp.url; return { ok: false, mensaje: "Sesión expirada." }; }
    let datos = null;
    try { datos = await resp.json(); } catch (_) { /* respuesta no JSON */ }
    if (!datos) datos = { ok: resp.ok, mensaje: resp.ok ? "" : "Ocurrió un error inesperado (" + resp.status + ")." };
    datos._status = resp.status;
    return datos;
  }
  const postJSON = (url, cuerpo) => pedir(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo || {}) });

  /* ---- Formularios AJAX ------------------------------------------------------------- */
  document.addEventListener("submit", async (e) => {
    const form = e.target.closest("form[data-ajax]");
    if (!form) return;
    e.preventDefault();
    if (form.dataset.enviando === "1") return;
    if (form.hasAttribute("data-validate") && !form.checkValidity()) {
      form.classList.add("was-validated");
      const malo = $(":invalid", form);
      if (malo) malo.focus();
      toast("Revisa los campos marcados en el formulario.", "warning");
      return;
    }
    if (form.dataset.confirm) {
      const ok = await confirmar(form.dataset.confirm, { titulo: form.dataset.confirmTitulo, boton: form.dataset.confirmBoton, peligro: form.hasAttribute("data-peligro") });
      if (!ok) return;
    }
    const antes = new CustomEvent("sgt:antes-enviar", { cancelable: true, detail: { form } });
    if (!form.dispatchEvent(antes)) return;

    const boton = e.submitter || $('button[type="submit"]', form);
    form.dataset.enviando = "1";
    if (boton) boton.classList.add("loading");
    const datos = await pedir(form.getAttribute("action") || window.location.href, { method: (form.method || "POST").toUpperCase(), body: new FormData(form) });
    form.dataset.enviando = "0";
    if (boton) boton.classList.remove("loading");

    if (datos.ok) {
      const modal = form.closest(".modal");
      if (modal && window.bootstrap) window.bootstrap.Modal.getOrCreateInstance(modal).hide();
      if (form.dataset.onSuccess === "none") {
        toast(datos.mensaje || "Listo.", "success");
        form.dispatchEvent(new CustomEvent("sgt:ok", { detail: datos, bubbles: true }));
        return;
      }
      if (datos.mensaje) flash("set", { mensaje: datos.mensaje, tipo: "success" });
      if (datos.redirect && form.dataset.onSuccess !== "reload") window.location.href = datos.redirect;
      else window.location.reload();
    } else {
      toast(datos.mensaje || "No se pudo completar la acción.", "danger");
      form.dispatchEvent(new CustomEvent("sgt:error", { detail: datos, bubbles: true }));
    }
  });

  /* ---- Modales de alta/edición (rellenan el formulario con data-edit) ----------------- */
  document.addEventListener("show.bs.modal", (ev) => {
    const modal = ev.target;
    if (!modal.hasAttribute("data-form-modal")) return;
    const form = $("form", modal);
    if (!form) return;
    form.reset();
    form.classList.remove("was-validated");
    const disparador = ev.relatedTarget;
    let datos = null;
    if (disparador && disparador.dataset.edit) { try { datos = JSON.parse(disparador.dataset.edit); } catch (_) { datos = null; } }
    const titulo = $(".modal-title", modal);
    if (titulo) titulo.textContent = datos ? (modal.dataset.tituloEditar || "Editar") : (modal.dataset.tituloNuevo || "Nuevo");
    $$("[data-solo-nuevo]", modal).forEach((n) => { n.classList.toggle("d-none", !!datos); });
    $$("[data-solo-edicion]", modal).forEach((n) => { n.classList.toggle("d-none", !datos); });
    $$("[data-requerido-nuevo]", modal).forEach((n) => { n.required = !datos; });
    if (datos) {
      Object.keys(datos).forEach((k) => {
        const campos = $$('[name="' + k + '"]', form);
        const hayCheck = campos.some((c) => c.type === "checkbox");
        campos.forEach((c) => {
          if (c.type === "checkbox") c.checked = datos[k] === true || datos[k] === "1" || datos[k] === 1 || datos[k] === "on";
          else if (hayCheck && c.type === "hidden") return;
          else c.value = datos[k] === null || datos[k] === undefined ? "" : datos[k];
        });
      });
    }
  });
  document.addEventListener("shown.bs.modal", (ev) => {
    const primero = $("input:not([type=hidden]):not([readonly]), select, textarea", ev.target);
    if (primero && ev.target.hasAttribute("data-form-modal")) primero.focus({ preventScroll: true });
  });

  /* ---- Tablas y filtros en vivo (sin recargar la página) ---------------------------------- */
  function debounce(fn, ms) { let t; return function () { const a = arguments; clearTimeout(t); t = setTimeout(() => fn.apply(null, a), ms); }; }

  function iniciarVivo(form) {
    const destino = $(form.dataset.target);
    if (!destino) return;
    let control = null;
    async function cargar(urlBase, params) {
      if (control) control.abort();
      control = new AbortController();
      const busqueda = form.querySelector(".search-box");
      if (busqueda) busqueda.classList.add("busy");
      const visible = new URL(urlBase, window.location.href);
      params.forEach((v, k) => { if (v !== "") visible.searchParams.set(k, v); });
      const pedido = new URL(visible);
      pedido.searchParams.set("partial", "1");
      try {
        const resp = await fetch(pedido, { signal: control.signal, credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" } });
        if (resp.redirected && resp.url.indexOf("/login") !== -1) { window.location.href = resp.url; return; }
        if (!resp.ok) throw new Error("http " + resp.status);
        destino.innerHTML = await resp.text();
        history.replaceState(null, "", visible.pathname + visible.search);
        destino.dispatchEvent(new CustomEvent("sgt:tabla", { bubbles: true }));
      } catch (err) {
        if (err.name !== "AbortError") toast("No se pudo actualizar la lista.", "danger");
      } finally {
        if (busqueda) busqueda.classList.remove("busy");
      }
    }
    const recolectar = () => {
      const p = new URLSearchParams();
      new FormData(form).forEach((v, k) => { if (k !== "csrf_token" && String(v).trim() !== "") p.set(k, String(v).trim()); });
      return p;
    };
    const base = form.getAttribute("action") || window.location.pathname;
    const lanzar = () => cargar(base, recolectar());
    form.addEventListener("submit", (e) => { e.preventDefault(); lanzar(); });
    form.addEventListener("input", debounce((e) => { if (e.target.matches("input[type=search], input[type=text]")) lanzar(); }, 320));
    form.addEventListener("change", (e) => { if (e.target.matches("select, input[type=date], input[type=checkbox]")) lanzar(); });
    form.addEventListener("click", (e) => {
      const limpiar = e.target.closest("[data-limpiar]");
      if (limpiar) { e.preventDefault(); form.reset(); $$("input:not([type=hidden]), select", form).forEach((c) => { if (c.type !== "checkbox") c.value = ""; }); lanzar(); }
    });
    destino.addEventListener("click", (e) => {
      const a = e.target.closest("a[data-pagina]");
      if (!a) return;
      e.preventDefault();
      const u = new URL(a.href, window.location.href);
      cargar(u.pathname, u.searchParams);
      const r = destino.getBoundingClientRect();
      if (r.top < 0) window.scrollTo({ top: window.scrollY + r.top - 90, behavior: "smooth" });
    });
  }
  $$("form[data-live]").forEach(iniciarVivo);

  /* ---- Gráfica de barras SVG ------------------------------------------------------------------ */
  function compacto(v) { if (v >= 1e6) return "$" + (v / 1e6).toFixed(1) + "M"; if (v >= 1e3) return "$" + (v / 1e3).toFixed(v >= 1e4 ? 0 : 1) + "k"; return "$" + Math.round(v); }
  function dibujarBarras(cont) {
    let serie = [];
    try { serie = JSON.parse(cont.dataset.serie || "[]"); } catch (_) { serie = []; }
    const max = Math.max.apply(null, serie.map((s) => s.valor).concat([0]));
    if (!serie.length || max <= 0) {
      cont.innerHTML = '<div class="vacio" style="padding:2rem 1rem"><div class="ilustracion" style="width:64px;height:64px;font-size:1.7rem;border-radius:20px"><i class="bi bi-bar-chart"></i></div><p class="mb-0">Aún no hay ingresos registrados en este periodo.</p></div>';
      return;
    }
    const W = 640, H = 240, m = { t: 14, r: 8, b: 30, l: 46 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const paso = iw / serie.length, ancho = Math.min(34, paso * 0.62);
    const techo = max * 1.12;
    let svg = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Ingresos por día"><defs><linearGradient id="gradBarra" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5eb1ff"/><stop offset="1" stop-color="#6366f1"/></linearGradient></defs>';
    [0, 0.5, 1].forEach((f) => {
      const y = m.t + ih - ih * f * (max / techo);
      svg += '<line class="grid" x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + y + '" y2="' + y + '"/><text x="' + (m.l - 8) + '" y="' + (y + 3) + '" text-anchor="end">' + compacto(max * f) + "</text>";
    });
    serie.forEach((s, i) => {
      const h = Math.max(s.valor > 0 ? 3 : 0, (s.valor / techo) * ih);
      const x = m.l + paso * i + (paso - ancho) / 2, y = m.t + ih - h;
      svg += '<rect class="barra" x="' + x + '" y="' + y + '" width="' + ancho + '" height="' + h + '" rx="6"><title>' + s.fecha + " · " + MXN.format(s.valor) + "</title></rect>";
      if (serie.length <= 8 || i % 2 === 0) svg += '<text x="' + (x + ancho / 2) + '" y="' + (H - 10) + '" text-anchor="middle">' + s.fecha + "</text>";
    });
    cont.innerHTML = svg + "</svg>";
  }
  $$("[data-chart-bars]").forEach(dibujarBarras);

  /* ---- Varios ---------------------------------------------------------------------------------------- */
  document.addEventListener("click", (e) => { if (e.target.closest("[data-print]")) { e.preventDefault(); window.print(); } });
  requestAnimationFrame(() => { $$(".progreso > i[data-w]").forEach((b) => { b.style.width = b.dataset.w + "%"; }); });

  /* Mensajes flash del servidor y mensajes diferidos tras una redirección */
  document.addEventListener("DOMContentLoaded", () => {
    const pend = flash("get");
    if (pend) { try { const p = JSON.parse(pend); toast(p.mensaje, p.tipo); } catch (_) { /* ignorar */ } }
    const cont = $("#flash-data");
    if (cont) { try { JSON.parse(cont.dataset.mensajes || "[]").forEach((m) => toast(m[1], m[0])); } catch (_) { /* ignorar */ } }
  });

  window.SGT = { toast, confirmar, pedir, postJSON, MXN, debounce, csrf };
})();
