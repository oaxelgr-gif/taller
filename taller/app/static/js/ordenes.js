/* =====================================================================
   SGT-Mecánico · Órdenes de trabajo
   - Alta: búsqueda AJAX de cliente/vehículo, alta rápida en modal,
     servicios dinámicos con total en vivo.
   - Detalle: autocompletar costo al elegir un servicio del catálogo.
   ===================================================================== */
(function () {
  "use strict";
  const $ = (s, c) => (c || document).querySelector(s);
  const $$ = (s, c) => Array.from((c || document).querySelectorAll(s));
  const S = window.SGT;

  /* ---- Autocompletar costo (formulario "agregar servicio" del detalle) ------- */
  document.addEventListener("change", (e) => {
    const sel = e.target.closest("select[data-autocosto]");
    if (!sel) return;
    const destino = $(sel.dataset.autocosto);
    const op = sel.options[sel.selectedIndex];
    if (destino && op && op.dataset.costo) destino.value = op.dataset.costo;
  });

  /* ---- Formulario de alta ---------------------------------------------------------- */
  const form = $("#form-orden");
  if (!form) return;

  const inputVehiculo = $("#id_vehiculo");
  const bloqueBusqueda = $("#bloque-busqueda");
  const cajaSel = $("#seleccion");
  const resultados = $("#resultados");
  const buscador = $("#buscar-cliente");
  const cajaBusqueda = buscador.closest(".search-box");
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function seleccionar(v, cliente) {
    inputVehiculo.value = v.id;
    $("#sel-vehiculo").textContent = (v.descripcion || "") + (v.placas && (v.descripcion || "").indexOf(v.placas) === -1 ? " · " + v.placas : "");
    $("#sel-cliente").textContent = cliente ? cliente.nombre + (cliente.telefono ? " · " + cliente.telefono : "") : "";
    $("#res-vehiculo").textContent = $("#sel-vehiculo").textContent;
    cajaSel.classList.remove("d-none");
    bloqueBusqueda.classList.add("d-none");
    resultados.innerHTML = "";
    buscador.value = "";
  }
  $("#cambiar-vehiculo").addEventListener("click", () => {
    inputVehiculo.value = "";
    cajaSel.classList.add("d-none");
    bloqueBusqueda.classList.remove("d-none");
    $("#res-vehiculo").textContent = "Sin vehículo";
    buscador.focus();
  });

  /* Búsqueda en tiempo real */
  let controlBusqueda = null;
  let cache = {};
  async function buscar(q) {
    if (q.length < 2) { resultados.innerHTML = ""; return; }
    if (controlBusqueda) controlBusqueda.abort();
    controlBusqueda = new AbortController();
    cajaBusqueda.classList.add("busy");
    try {
      const resp = await fetch(form.dataset.buscarUrl + "?q=" + encodeURIComponent(q), {
        signal: controlBusqueda.signal, credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const datos = await resp.json();
      pintar(datos.resultados || [], q);
    } catch (err) {
      if (err.name !== "AbortError") resultados.innerHTML = '<div class="text-danger small">No se pudo buscar. Intenta de nuevo.</div>';
    } finally {
      cajaBusqueda.classList.remove("busy");
    }
  }
  function pintar(lista, q) {
    cache = {};
    if (!lista.length) {
      resultados.innerHTML = '<div class="resultado text-muted"><i class="bi bi-search"></i> Sin coincidencias para «' + esc(q) + '». Puedes registrarlo como cliente nuevo.</div>';
      return;
    }
    resultados.innerHTML = lista.map((c) => {
      cache[c.id] = c;
      const chips = c.vehiculos.map((v) =>
        '<button type="button" class="veh-chip" data-cliente="' + c.id + '" data-vehiculo="' + v.id + '"><i class="bi bi-car-front"></i> ' + esc(v.descripcion) + "</button>").join("");
      return '<div class="resultado"><div class="cli">' + esc(c.nombre) + ' <span class="text-muted fw-normal small">· ' + esc(c.telefono) + "</span></div>" +
        (chips || '<div class="text-faint small mt-1">Sin vehículos registrados</div>') +
        '<button type="button" class="veh-chip nuevo" data-cliente="' + c.id + '" data-agregar><i class="bi bi-plus-lg"></i> Agregar vehículo</button></div>';
    }).join("");
  }
  buscador.addEventListener("input", S.debounce(() => buscar(buscador.value.trim()), 260));
  resultados.addEventListener("click", (e) => {
    const chip = e.target.closest(".veh-chip");
    if (!chip) return;
    const cliente = cache[chip.dataset.cliente];
    if (!cliente) return;
    if (chip.hasAttribute("data-agregar")) { abrirRapido(cliente); return; }
    const v = cliente.vehiculos.find((x) => String(x.id) === chip.dataset.vehiculo);
    if (v) seleccionar(v, cliente);
  });

  /* Alta rápida (cliente + vehículo, o vehículo de un cliente existente) */
  const modalEl = $("#modalRapido");
  const formRapido = $("#form-rapido");
  function abrirRapido(cliente) {
    formRapido.reset();
    $("#rapido-id-cliente").value = cliente ? cliente.id : "";
    $("#rapido-cliente").classList.toggle("d-none", !!cliente);
    $("#rapido-titulo").textContent = cliente ? "Agregar vehículo a " + cliente.nombre : "Nuevo cliente y vehículo";
    if (cliente) formRapido.dataset.cliente = JSON.stringify({ id: cliente.id, nombre: cliente.nombre, telefono: cliente.telefono });
    else delete formRapido.dataset.cliente;
    window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
  }
  modalEl.addEventListener("show.bs.modal", (ev) => {
    if (ev.relatedTarget && ev.relatedTarget.dataset.modo === "nuevo") {
      formRapido.reset();
      $("#rapido-id-cliente").value = "";
      $("#rapido-cliente").classList.remove("d-none");
      $("#rapido-titulo").textContent = "Nuevo cliente y vehículo";
      delete formRapido.dataset.cliente;
      const q = buscador.value.trim();
      if (q && !/\d/.test(q)) $("#r-nombre").value = q;
    }
  });
  modalEl.addEventListener("shown.bs.modal", () => {
    const primero = $("#rapido-cliente").classList.contains("d-none") ? $("#r-marca") : $("#r-nombre");
    if (primero) primero.focus({ preventScroll: true });
  });

  formRapido.addEventListener("submit", async (e) => {
    e.preventDefault();
    const enCliente = !$("#rapido-cliente").classList.contains("d-none");
    const obligatorios = ["r-marca", "r-modelo", "r-anio", "r-placas"].concat(enCliente ? ["r-nombre", "r-tel"] : []);
    const falta = obligatorios.map((id) => $("#" + id)).find((el) => !el.value.trim());
    if (falta) { falta.focus(); S.toast("Completa los campos obligatorios (*).", "warning"); return; }
    const btn = $('button[type="submit"]', formRapido);
    btn.classList.add("loading");
    const cuerpo = {};
    new FormData(formRapido).forEach((v, k) => { cuerpo[k] = v; });
    const datos = await S.postJSON(form.dataset.rapidoUrl, cuerpo);
    btn.classList.remove("loading");
    if (!datos.ok) { S.toast(datos.mensaje || "No se pudo guardar.", "danger"); return; }
    window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
    S.toast(datos.mensaje, "success");
    seleccionar(datos.vehiculo, datos.cliente);
  });

  /* ---- Servicios dinámicos ------------------------------------------------------------ */
  const contLineas = $("#lineas");
  const plantilla = $("#tpl-linea");
  function limpiarNumero(v) { const n = parseFloat(v); return isFinite(n) ? n : 0; }

  function recalcular() {
    if (!contLineas) return;
    let total = 0, n = 0;
    $$(".linea-servicio", contLineas).forEach((fila) => {
      const sel = $("select", fila);
      const costo = limpiarNumero($('[name="costo[]"]', fila).value);
      const cant = Math.max(1, parseInt($('[name="cantidad[]"]', fila).value, 10) || 1);
      const sub = costo * cant;
      $(".sub", fila).textContent = S.MXN.format(sub);
      if (sel.value) { total += sub; n += 1; }
    });
    $("#total-orden").textContent = S.MXN.format(total);
    $("#res-servicios").textContent = n + (n === 1 ? " servicio" : " servicios");
  }
  function agregarLinea() {
    if (!plantilla) return;
    const nodo = plantilla.content.firstElementChild.cloneNode(true);
    contLineas.appendChild(nodo);
    nodo.style.animation = "entra-pagina .35s ease";
    return nodo;
  }
  if (contLineas) {
    agregarLinea();
    $("#agregar-linea").addEventListener("click", () => { const n = agregarLinea(); if (n) $("select", n).focus(); });
    contLineas.addEventListener("change", (e) => {
      const sel = e.target.closest("select");
      if (sel) {
        const op = sel.options[sel.selectedIndex];
        const fila = sel.closest(".linea-servicio");
        $('[name="costo[]"]', fila).value = op && op.dataset.costo ? op.dataset.costo : "";
      }
      recalcular();
    });
    contLineas.addEventListener("input", recalcular);
    contLineas.addEventListener("click", (e) => {
      const q = e.target.closest("[data-quitar]");
      if (!q) return;
      const fila = q.closest(".linea-servicio");
      if ($$(".linea-servicio", contLineas).length === 1) {
        $("select", fila).value = ""; $('[name="costo[]"]', fila).value = ""; $('[name="cantidad[]"]', fila).value = 1;
      } else fila.remove();
      recalcular();
    });
    recalcular();
  }

  /* ---- Validaciones antes de enviar ------------------------------------------------------ */
  form.addEventListener("sgt:antes-enviar", (e) => {
    if (!inputVehiculo.value) {
      e.preventDefault();
      S.toast("Selecciona o registra el vehículo del cliente (paso 1).", "warning");
      buscador.focus();
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    const f = $("#fecha_ingreso");
    if (f && f.value && f.max && f.value > f.max) {
      // Se compara contra el "ahora" de la carga; el servidor valida contra la hora real.
      const ahora = new Date(); ahora.setMinutes(ahora.getMinutes() - ahora.getTimezoneOffset());
      if (f.value > ahora.toISOString().slice(0, 16)) {
        e.preventDefault(); S.toast("La fecha de ingreso no puede ser futura.", "danger"); f.focus(); return;
      }
    }
    $$(".linea-servicio", contLineas || document).forEach((fila) => {
      const sel = $("select", fila);
      if (sel && !sel.value) fila.remove();
    });
  });

  /* ---- Preselección (desde ?vehiculo=ID) ---------------------------------------------------- */
  let pre = null;
  try { pre = JSON.parse(form.dataset.preseleccion || "null"); } catch (_) { pre = null; }
  if (pre) {
    bloqueBusqueda.classList.add("d-none");
    $("#res-vehiculo").textContent = pre.descripcion + " · " + pre.placas;
  }
})();
