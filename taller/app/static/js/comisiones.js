/* =====================================================================
   SGT-Mecánico · Cálculo automático de comisiones (pre-corte y cierre)
   ===================================================================== */
(function () {
  "use strict";
  const $ = (s, c) => (c || document).querySelector(s);
  const $$ = (s, c) => Array.from((c || document).querySelectorAll(s));
  const S = window.SGT;
  const form = $("#form-corte");
  if (!form) return;

  const selMec = $("#id_mecanico"), fIni = $("#fecha_inicio"), fFin = $("#fecha_fin"), inPct = $("#porcentaje");
  const panelInicial = $("#estado-inicial"), panelRes = $("#resultado"), btnCerrar = $("#btn-cerrar"), btnCalc = $("#btn-calcular");
  let ultimo = null; // último pre-corte recibido del servidor
  let control = null;

  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v) => { const n = parseFloat(v); return isFinite(n) ? n : 0; };
  const iso = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  const pctTxt = (p) => (Math.round(num(p) * 100) / 100).toString().replace(/\.0+$/, "") + "%";

  function estadoVacio() { ultimo = null; panelRes.classList.remove("visible"); panelInicial.classList.remove("d-none"); }

  function pintar(d) {
    ultimo = d;
    panelInicial.classList.add("d-none");
    panelRes.classList.add("visible");
    $("#res-mecanico").textContent = d.mecanico;
    $("#res-ordenes").innerHTML = d.ordenes.length ? d.ordenes.map((o) =>
      '<tr><td data-label="Folio"><a class="fila-link" href="' + esc(o.url) + '">' + esc(o.folio) + "</a></td>" +
      '<td data-label="Fecha">' + esc(o.fecha) + "</td>" +
      '<td data-label="Vehículo">' + esc(o.vehiculo) + '<span class="sub">' + esc(o.cliente) + "</span></td>" +
      '<td data-label="Estado"><span class="estado estado-' + (o.estado === "Entregado" ? "entregado" : "completado") + '">' + esc(o.estado) + "</span></td>" +
      '<td data-label="Total" class="text-end money">' + S.MXN.format(num(o.total)) + "</td></tr>").join("")
      : '<tr><td colspan="5"><div class="vacio" style="padding:1.6rem 1rem"><div class="ilustracion" style="width:64px;height:64px;font-size:1.7rem;border-radius:20px"><i class="bi bi-inbox"></i></div>' +
        "<p class=\"mb-0\">No hay órdenes completadas o entregadas pendientes de liquidar en este periodo.</p></div></td></tr>";
    inPct.placeholder = "Por defecto: " + pctTxt(d.porcentaje_defecto);
    mostrarTotales();
    const aviso = $("#res-aviso");
    if (d.en_curso > 0) {
      aviso.classList.remove("d-none");
      aviso.innerHTML = '<i class="bi bi-exclamation-triangle"></i> ' + d.en_curso + (d.en_curso === 1 ? " orden sigue" : " órdenes siguen") + " en curso: no entran al corte hasta que se completen.";
    } else aviso.classList.add("d-none");
    btnCerrar.disabled = d.cantidad === 0;
  }

  /* El porcentaje se puede ajustar sin volver a consultar al servidor */
  function mostrarTotales() {
    if (!ultimo) return;
    const pct = inPct.value.trim() !== "" ? num(inPct.value) : num(ultimo.porcentaje);
    const comision = Math.round(num(ultimo.total) * pct) / 100;
    $("#res-total").textContent = S.MXN.format(num(ultimo.total));
    $("#res-pct").textContent = pctTxt(pct);
    $("#res-comision").textContent = S.MXN.format(comision);
    $("#total_confirmado").value = ultimo.total;
  }

  async function calcular(silencioso) {
    if (!selMec.value) { estadoVacio(); if (!silencioso) S.toast("Selecciona un mecánico.", "warning"); return; }
    if (!fIni.value || !fFin.value) { if (!silencioso) S.toast("Indica el periodo del corte.", "warning"); return; }
    if (fFin.value < fIni.value) { S.toast("La fecha final no puede ser anterior a la inicial.", "danger"); return; }
    if (control) control.abort();
    btnCalc.classList.add("loading");
    const datos = await S.pedir(form.dataset.calcularUrl, { method: "POST", body: new FormData(form) });
    btnCalc.classList.remove("loading");
    if (!datos.ok) { S.toast(datos.mensaje || "No se pudo calcular el corte.", "danger"); estadoVacio(); return; }
    pintar(datos);
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); calcular(false); });
  selMec.addEventListener("change", () => { inPct.value = ""; calcular(true); });
  [fIni, fFin].forEach((i) => i.addEventListener("change", () => calcular(true)));
  inPct.addEventListener("input", mostrarTotales);

  $$("[data-rango]").forEach((b) => b.addEventListener("click", () => {
    const hoy = new Date();
    const dow = (hoy.getDay() + 6) % 7; // lunes = 0
    let ini, fin;
    if (b.dataset.rango === "semana") { ini = new Date(hoy); ini.setDate(hoy.getDate() - dow); fin = new Date(ini); fin.setDate(ini.getDate() + 6); }
    else if (b.dataset.rango === "pasada") { ini = new Date(hoy); ini.setDate(hoy.getDate() - dow - 7); fin = new Date(ini); fin.setDate(ini.getDate() + 6); }
    else { ini = new Date(hoy.getFullYear(), hoy.getMonth(), 1); fin = new Date(hoy.getFullYear(), hoy.getMonth() + 1, 0); }
    fIni.value = iso(ini); fFin.value = iso(fin);
    calcular(true);
  }));

  /* Cierre: congela el corte y liquida las órdenes */
  btnCerrar.addEventListener("click", async () => {
    if (!ultimo || ultimo.cantidad === 0) return;
    const pct = inPct.value.trim() !== "" ? num(inPct.value) : num(ultimo.porcentaje);
    const comision = S.MXN.format(Math.round(num(ultimo.total) * pct) / 100);
    const ok = await S.confirmar(
      "Se cerrará el corte de " + ultimo.mecanico + " por " + ultimo.cantidad + (ultimo.cantidad === 1 ? " orden" : " órdenes") +
      " (" + S.MXN.format(num(ultimo.total)) + " al " + pctTxt(pct) + " = " + comision + "). El registro será inalterable y las órdenes quedarán liquidadas.",
      { titulo: "Cerrar corte semanal", boton: "Cerrar y congelar", peligro: false });
    if (!ok) return;
    btnCerrar.classList.add("loading");
    const fd = new FormData(form);
    fd.set("porcentaje", String(pct));
    const datos = await S.pedir(form.action, { method: "POST", body: fd });
    btnCerrar.classList.remove("loading");
    if (datos.ok) {
      try { sessionStorage.setItem("sgt_toast", JSON.stringify({ mensaje: datos.mensaje, tipo: "success" })); } catch (_) { /* ignorar */ }
      window.location.href = datos.redirect;
    } else {
      S.toast(datos.mensaje || "No se pudo cerrar el corte.", "danger");
      if (/cambiaron|Vuelve a calcular/.test(datos.mensaje || "")) calcular(true);
    }
  });
})();
