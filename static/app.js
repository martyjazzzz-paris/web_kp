const rowsContainer = document.getElementById("rows");
const rowTemplate = document.getElementById("row-template");
const addRowButton = document.getElementById("add-row");
const vatModeSelect = document.querySelector('select[name="vat_mode"]');
const templateTypeSelect = document.querySelector('select[name="template_type"]');
const signatureCheckbox = document.getElementById("include-signature");
const deliveryAddressInput = document.querySelector('input[name="delivery_address"]');
const subtotalNode = document.getElementById("subtotal");
const vatNode = document.getElementById("vat-amount");
const totalNode = document.getElementById("total");
const paymentLabelNode = document.getElementById("payment-label");
const applyRoundingInput = document.getElementById("apply-rounding-input");
const applyRoundingBtn = document.getElementById("apply-rounding-btn");
const roundingStateTextNode = document.getElementById("rounding-state-text");
const sendEmailForm = document.getElementById("send-email-form");
const mailProgressNode = document.getElementById("mail-progress");
const mailProgressTextNode = document.getElementById("mail-progress-text");
const ingestButton = document.getElementById("ingest-mail-btn");
const ingestResultTextNode = document.getElementById("ingest-result-text");
const MAIL_CIRCLE = 97.39;

function parseNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function roundUpToStep(value, step) {
  const safeValue = parseNumber(value);
  const safeStep = parseNumber(step);
  if (!safeStep || safeStep <= 0) return safeValue;
  return Math.ceil(safeValue / safeStep) * safeStep;
}

function recalc() {
  if (!rowsContainer) return;
  let markupRate = 0;
  let paymentLabel = "Наличные";
  if (vatModeSelect?.value === "without_vat") {
    markupRate = 0.17;
    paymentLabel = "Без НДС";
  } else if (vatModeSelect?.value === "with_vat") {
    markupRate = 0.35;
    paymentLabel = "НДС 22%";
  }

  let baseSubtotal = 0;
  const shouldRound = Boolean(applyRoundingInput?.value) && markupRate > 0;
  let onlineTotalRaw = 0;
  let onlineTotalRounded = 0;

  rowsContainer.querySelectorAll(".row-item").forEach((row) => {
    const qtyInput = row.querySelector('input[name="qty"]');
    const priceInput = row.querySelector('input[name="price"]');
    const amountInput = row.querySelector(".amount");

    const qty = parseNumber(qtyInput?.value);
    const price = parseNumber(priceInput?.value);
    const baseAmount = qty * price;
    const adjustedUnitPriceRaw = price * (1 + markupRate);
    const rowAmountRaw = qty * adjustedUnitPriceRaw;
    const rowAmountRounded = roundUpToStep(rowAmountRaw, 1000);
    baseSubtotal += baseAmount;
    onlineTotalRaw += rowAmountRaw;
    onlineTotalRounded += rowAmountRounded;

    // In nomenclature rows always show raw (non-rounded) values.
    if (amountInput) amountInput.value = rowAmountRaw.toFixed(2);
  });

  const total = shouldRound ? onlineTotalRounded : onlineTotalRaw;
  const markupAmount = total - baseSubtotal;

  if (subtotalNode) subtotalNode.textContent = baseSubtotal.toFixed(2);
  if (vatNode) vatNode.textContent = markupAmount.toFixed(2);
  if (totalNode) totalNode.textContent = total.toFixed(2);
  if (paymentLabelNode) paymentLabelNode.textContent = paymentLabel;
  if (applyRoundingBtn) {
    applyRoundingBtn.style.display = markupRate > 0 ? "inline-block" : "none";
  }
  if (roundingStateTextNode) {
    if (markupRate <= 0) {
      roundingStateTextNode.textContent = "Округление доступно только для режимов с наценкой.";
    } else {
      roundingStateTextNode.textContent = shouldRound ? "Округление включено." : "Округление выключено.";
    }
  }
}

function resetRounding() {
  if (applyRoundingInput) {
    applyRoundingInput.value = "";
  }
}

function bindRowEvents(scope) {
  const buttons = scope.querySelectorAll(".remove-row");
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      if (rowsContainer.children.length === 1) {
        return;
      }
      button.closest(".row-item").remove();
      recalc();
    });
  });

  const watchedInputs = scope.querySelectorAll('input[name="qty"], input[name="price"]');
  watchedInputs.forEach((input) => {
    input.addEventListener("input", () => {
      resetRounding();
      recalc();
    });
  });

  const stepButtons = scope.querySelectorAll(".step-btn");
  stepButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const row = btn.closest(".row-item");
      if (!row) return;
      const targetName = btn.dataset.target;
      if (!targetName) return;
      const input = row.querySelector(`input[name="${targetName}"]`);
      if (!input) return;
      const step = parseNumber(input.dataset.stepper || input.step || "1") || 1;
      const min = input.min === "" ? null : parseNumber(input.min);
      let value = parseNumber(input.value);
      value += btn.classList.contains("step-plus") ? step : -step;
      if (min !== null && value < min) value = min;
      input.value = String(value);
      resetRounding();
      recalc();
    });
  });
}

function syncSignatureAvailability() {
  if (signatureCheckbox) {
    // Keep checkbox interactive for all templates.
    signatureCheckbox.removeAttribute("disabled");
    signatureCheckbox.disabled = false;
  }
  if (deliveryAddressInput) {
    // Address entry must stay available regardless of template.
    deliveryAddressInput.removeAttribute("disabled");
    deliveryAddressInput.removeAttribute("readonly");
    deliveryAddressInput.disabled = false;
    deliveryAddressInput.readOnly = false;
  }
}

// Hard guard against stale DOM state/cached attributes.
syncSignatureAvailability();

if (addRowButton && rowsContainer && rowTemplate) {
  addRowButton.addEventListener("click", () => {
    const fragment = rowTemplate.content.cloneNode(true);
    rowsContainer.appendChild(fragment);
    bindRowEvents(rowsContainer);
    resetRounding();
    recalc();
  });

  bindRowEvents(rowsContainer);
  vatModeSelect?.addEventListener("change", () => {
    resetRounding();
    recalc();
  });
  templateTypeSelect?.addEventListener("change", syncSignatureAvailability);
  syncSignatureAvailability();
  recalc();
}

if (applyRoundingBtn && applyRoundingInput) {
  applyRoundingBtn.addEventListener("click", () => {
    applyRoundingInput.value = "on";
    recalc();
  });
}

const sendBtnWrap = document.getElementById("send-btn-wrap");
const sendBtnEl = document.getElementById("send-btn");
const sendBtnRingFill = document.getElementById("send-btn-ring-fill");
const sendBtnRingTrack = document.getElementById("send-btn-ring-track");

function getRingPerimeter() {
  if (!sendBtnWrap) return 500;
  const rect = sendBtnWrap.getBoundingClientRect();
  const w = rect.width + 4 - 3;
  const h = rect.height + 4 - 3;
  const r = Math.min(21, h / 2);
  return 2 * (w - 2 * r) + 2 * Math.PI * r;
}

function initRing() {
  if (!sendBtnRingFill || !sendBtnRingTrack || !sendBtnWrap) return;
  const rect = sendBtnWrap.getBoundingClientRect();
  const w = rect.width + 4;
  const h = rect.height + 4;
  [sendBtnRingFill, sendBtnRingTrack].forEach((el) => {
    el.setAttribute("width", String(w - 3));
    el.setAttribute("height", String(h - 3));
  });
  const p = getRingPerimeter();
  sendBtnRingFill.style.strokeDasharray = String(p);
  sendBtnRingFill.style.strokeDashoffset = String(p);
}

function setMailProgress(progress, state = "sending", errorMsg = "") {
  if (!sendBtnRingFill || !sendBtnWrap) return;
  const p = getRingPerimeter();
  const safe = Math.max(0, Math.min(100, progress));
  sendBtnRingFill.style.strokeDasharray = String(p);
  sendBtnRingFill.style.strokeDashoffset = String(p - (p * safe) / 100);

  sendBtnWrap.classList.remove("success", "error");

  if (state === "success") {
    sendBtnWrap.classList.add("success");
    if (sendBtnEl) sendBtnEl.textContent = "Отправлено ✓";
  } else if (state === "error") {
    sendBtnWrap.classList.add("error");
    if (sendBtnEl) sendBtnEl.textContent = errorMsg || "Ошибка отправки";
  }
}

async function pollMailJob(jobId) {
  let progress = 12;
  setMailProgress(progress, "sending");
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    const response = await fetch(`/api/email-status/${jobId}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      setMailProgress(100, "error", "Ошибка статуса");
      return;
    }
    if (data.status === "sent") {
      setMailProgress(100, "success");
      window.setTimeout(() => { window.location.href = "/"; }, 1800);
      return;
    }
    if (data.status === "error") {
      setMailProgress(100, "error", data.error || "Ошибка отправки");
      return;
    }
    progress = Math.min(90, progress + 6);
    setMailProgress(progress, "sending");
  }
  setMailProgress(100, "error", "Таймаут отправки");
}

if (sendEmailForm) {
  sendEmailForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    initRing();
    const formData = new FormData(sendEmailForm);
    if (sendBtnEl) sendBtnEl.disabled = true;
    setMailProgress(5, "sending");

    try {
      const response = await fetch("/send-email-async", { method: "POST", body: formData });
      const data = await response.json();
      if (!response.ok || !data.ok || !data.job_id) {
        setMailProgress(100, "error", data.error || "Не удалось запустить отправку");
        if (sendBtnEl) sendBtnEl.disabled = false;
      } else {
        await pollMailJob(data.job_id);
        if (sendBtnEl) sendBtnEl.disabled = false;
      }
    } catch {
      setMailProgress(100, "error", "Сетевая ошибка");
      if (sendBtnEl) sendBtnEl.disabled = false;
    }
  });
}

const reloadPageBtn = document.getElementById("reload-page-btn");
if (reloadPageBtn) {
  reloadPageBtn.addEventListener("click", () => {
    window.location.reload();
  });
}

if (ingestButton) {
  ingestButton.addEventListener("click", async () => {
    ingestButton.disabled = true;
    if (ingestResultTextNode) {
      ingestResultTextNode.textContent = "Забираем письма из почты...";
    }
    try {
      const response = await fetch("/review/ingest", { method: "POST" });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.error || "не удалось получить письма");
      }
      if (ingestResultTextNode) {
        ingestResultTextNode.textContent =
          data.message || (data.ingested === 0
            ? "Новых писем нет."
            : `Забрано новых писем: ${data.ingested}.`);
      }
    } catch (error) {
      if (ingestResultTextNode) {
        ingestResultTextNode.textContent = `Ошибка ingest: ${error.message || "попробуй еще раз"}`;
      }
    } finally {
      ingestButton.disabled = false;
    }
  });
}
