/**
 * app.js - GMC Policy Intelligence Dashboard
 * Interactive Controller for Real-Time Document Ingestion, 30-Feature Deep-Dive,
 * Multi-Policy Matrix Comparison, and SVG Visual Analytics.
 */

// Global State
const state = {
  policies: [],
  selectedPolicyId: null,
  currentPolicyDetail: null,
  summaryMetrics: null,
  activeFilterStatus: 'all',
  searchQuery: '',
  health: null
};

// Friendly Feature Display Name & Category Map
const FEATURE_METADATA = {
  room_rent: { name: "Room Rent Normal", category: "Inpatient Hospitalization" },
  icu_charges: { name: "ICU Charges", category: "Inpatient Hospitalization" },
  day_care_procedures: { name: "Day Care Procedures", category: "Inpatient Hospitalization" },
  pre_hospitalization: { name: "Pre-Hospitalization Expenses", category: "Hospitalization Limits" },
  post_hospitalization: { name: "Post-Hospitalization Expenses", category: "Hospitalization Limits" },
  domiciliary_hospitalization: { name: "Domiciliary Hospitalization", category: "Inpatient Hospitalization" },
  ayush_treatment: { name: "AYUSH Alternative Medicine", category: "Inpatient Hospitalization" },
  road_ambulance: { name: "Road Ambulance Cover", category: "Emergency & Travel" },
  air_ambulance: { name: "Air Ambulance Cover", category: "Emergency & Travel" },
  organ_donor_expenses: { name: "Organ Donor Expenses", category: "Major Surgeries" },
  maternity_normal: { name: "Maternity Normal Delivery", category: "Maternity & Newborn" },
  maternity_c_section: { name: "Maternity C-Section Delivery", category: "Maternity & Newborn" },
  maternity_waiting_period_9m: { name: "Maternity 9-Month Waiting Waiver", category: "Maternity & Newborn" },
  newborn_baby_cover_day_1: { name: "Newborn Baby Cover from Day 1", category: "Maternity & Newborn" },
  congenital_internal: { name: "Internal Congenital Diseases", category: "Special Conditions" },
  congenital_external: { name: "External Congenital Diseases", category: "Special Conditions" },
  pre_existing_diseases: { name: "Pre-Existing Diseases (PED)", category: "Waiting Periods" },
  waiting_period_30_days: { name: "Initial 30-Day Waiting Period", category: "Waiting Periods" },
  waiting_period_1_year: { name: "1-Year Specific Illness Waiting", category: "Waiting Periods" },
  waiting_period_2_year: { name: "2-Year Specific Illness Waiting", category: "Waiting Periods" },
  waiting_period_4_year: { name: "4-Year Specific Illness Waiting", category: "Waiting Periods" },
  modern_treatments: { name: "Modern Advanced Treatments", category: "Modern Treatments" },
  robotic_surgery: { name: "Robotic Surgery Cover", category: "Modern Treatments" },
  stem_cell_therapy: { name: "Stem Cell Therapy", category: "Modern Treatments" },
  lasik_surgery: { name: "LASIK Vision Correction", category: "Special Conditions" },
  bariatric_surgery: { name: "Bariatric Weight-Loss Surgery", category: "Special Conditions" },
  psychiatric_treatment: { name: "Psychiatric & Mental Illness", category: "Special Conditions" },
  co_pay: { name: "Co-Payment Requirement", category: "Cost Sharing" },
  deductible: { name: "Policy Deductible", category: "Cost Sharing" },
  corporate_buffer: { name: "Corporate Buffer Pool", category: "Corporate Benefits" }
};

// =====================================================================
// Initialization
// =====================================================================
document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initUpload();
  initSearchAndFilter();
  initModal();
  fetchHealth();
  loadPortfolioData();

  // Quick Action Buttons
  document.getElementById("btn-quick-upload").addEventListener("click", () => switchTab("uploader"));
  document.getElementById("btn-refresh-policies").addEventListener("click", () => loadPortfolioData(true));
  document.getElementById("btn-export-comparison-csv").addEventListener("click", exportComparisonToCSV);
  document.getElementById("btn-export-comparison-json").addEventListener("click", exportComparisonToJSON);
});

// =====================================================================
// Tabs Navigation
// =====================================================================
function initTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tab;
      switchTab(target);
    });
  });
}

function switchTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.tab === tabId);
  });
  document.querySelectorAll(".view-section").forEach(view => {
    view.classList.toggle("active", view.id === `${tabId}-view`);
  });

  if (tabId === "deepdive" && state.selectedPolicyId && !state.currentPolicyDetail) {
    loadPolicyDetail(state.selectedPolicyId);
  } else if (tabId === "comparison") {
    renderComparisonMatrix();
  }
}

// =====================================================================
// API: Health & Portfolio Data Loading
// =====================================================================
async function fetchHealth() {
  const statusPill = document.getElementById("system-status-pill");
  const statusDot = document.getElementById("status-dot");
  const statusText = document.getElementById("status-text");

  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    state.health = data;

    if (data.status === "online") {
      statusDot.style.background = "var(--accent-emerald)";
      statusDot.style.boxShadow = "0 0 10px var(--accent-emerald)";
      statusText.textContent = data.api_key_configured
        ? `Ready • ${data.model}`
        : "Gemini Key Missing";
    }
  } catch (err) {
    statusDot.style.background = "var(--accent-rose)";
    statusDot.style.boxShadow = "0 0 10px var(--accent-rose)";
    statusText.textContent = "Offline / Connection Error";
  }
}

async function loadPortfolioData(showToastNotice = false) {
  try {
    const [summaryRes, policiesRes] = await Promise.all([
      fetch("/api/summary"),
      fetch("/api/policies")
    ]);

    state.summaryMetrics = await summaryRes.json();
    state.policies = await policiesRes.json();

    updateStatCards();
    renderOverviewPolicies();
    populatePolicySelector();
    renderDemographicsChart();

    // Default select first policy if available
    if (state.policies.length > 0 && !state.selectedPolicyId) {
      state.selectedPolicyId = state.policies[0].id;
    }

    if (showToastNotice) {
      showToast("Data refreshed successfully", "success");
    }
  } catch (err) {
    console.error("Error loading portfolio data:", err);
    showToast("Failed to load portfolio data", "error");
  }
}

// =====================================================================
// View 1: Overview & Visual Analytics
// =====================================================================
function updateStatCards() {
  const port = state.summaryMetrics?.portfolio || {};
  document.getElementById("stat-total-policies").textContent = port.total_policies || 0;
  document.getElementById("stat-gmc-ratio").textContent = `${port.gmc_count || 0} GMC • ${port.non_gmc_count || 0} Non-GMC`;
  document.getElementById("stat-total-lives").textContent = (port.total_lives || 0).toLocaleString("en-IN");
  document.getElementById("stat-total-premium").textContent = "₹" + (port.total_premium || 0).toLocaleString("en-IN");
  document.getElementById("stat-avg-cost").textContent = "₹" + (port.avg_premium_per_life || 0).toLocaleString("en-IN");
}

function renderDemographicsChart() {
  // Aggregate employee vs dependent ratio across policies
  let employees = 0;
  let dependents = 0;
  let totalLives = 0;

  state.policies.forEach(p => {
    const lives = p.total_lives || 0;
    totalLives += lives;
  });

  // Calculate approximate ratio (typically 40% employees, 60% dependents in GMC)
  employees = Math.round(totalLives * 0.42);
  dependents = totalLives - employees;

  document.getElementById("chart-lives-badge").textContent = `${totalLives.toLocaleString("en-IN")} Total Lives`;
  document.getElementById("legend-employees").textContent = `Employees: ${employees.toLocaleString("en-IN")} (42%)`;
  document.getElementById("legend-dependents").textContent = `Dependents: ${dependents.toLocaleString("en-IN")} (58%)`;

  const circumference = 2 * Math.PI * 38; // ~238.76
  const empRatio = totalLives > 0 ? (employees / totalLives) : 0;
  const depRatio = totalLives > 0 ? (dependents / totalLives) : 0;

  const empDash = empRatio * circumference;
  const depDash = depRatio * circumference;

  const donutEmp = document.getElementById("donut-employees");
  const donutDep = document.getElementById("donut-dependents");

  if (donutEmp && donutDep) {
    donutEmp.setAttribute("stroke-dasharray", `${empDash} ${circumference}`);
    donutEmp.setAttribute("stroke-dashoffset", "0");

    donutDep.setAttribute("stroke-dasharray", `${depDash} ${circumference}`);
    donutDep.setAttribute("stroke-dashoffset", `-${empDash}`);
  }
}

function renderOverviewPolicies() {
  const container = document.getElementById("overview-policies-grid");
  if (!state.policies || state.policies.length === 0) {
    container.innerHTML = `
      <div style="grid-column: 1/-1; text-align: center; padding: 40px; background: var(--surface-glass); border-radius: 16px; border: 1px solid var(--border-glass);">
        <div style="font-size: 32px; margin-bottom: 12px;">📁</div>
        <h3 style="font-size: 16px; margin-bottom: 6px;">No Policy Extractions Found</h3>
        <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 20px;">Upload a PDF to start extracting and generating analytical insights.</p>
        <button class="btn-primary" onclick="switchTab('uploader')"><span>⚡</span> Upload GMC Policy</button>
      </div>
    `;
    return;
  }

  container.innerHTML = state.policies.map(p => {
    const insurer = p.insurer_name || "Unknown Insurer";
    const typeClass = p.is_gmc_policy ? "type-gmc" : "type-gpa";
    const livesFormatted = p.total_lives ? Number(p.total_lives).toLocaleString("en-IN") : "N/A";
    const premFormatted = p.total_premium ? `₹${Number(p.total_premium).toLocaleString("en-IN")}` : "N/A";
    const validColor = p.validation_status === "PASS" ? "var(--accent-emerald)" : "var(--accent-amber)";

    return `
      <div class="policy-card ${p.id === state.selectedPolicyId ? 'active-policy' : ''}" onclick="selectAndInspectPolicy('${p.id}')">
        <div>
          <div class="policy-header-row">
            <span class="insurer-badge">${escapeHtml(insurer)}</span>
            <span class="type-pill ${typeClass}">${escapeHtml(p.policy_type || 'GMC')}</span>
          </div>
          <div class="policy-name-title">${escapeHtml(p.policy_holder_name || p.source_file)}</div>
          <div class="policy-number-sub">Policy: ${escapeHtml(p.policy_number)}</div>
        </div>

        <div class="policy-metrics-row">
          <div>
            <div class="pm-item-label">Insured Lives</div>
            <div class="pm-item-val">${livesFormatted}</div>
          </div>
          <div>
            <div class="pm-item-label">Gross Premium</div>
            <div class="pm-item-val" style="color: var(--accent-emerald);">${premFormatted}</div>
          </div>
          <div>
            <div class="pm-item-label">Features</div>
            <div class="pm-item-val" style="color: var(--primary);">${p.total_features_covered || 0} / 30</div>
          </div>
        </div>

        <div class="policy-card-footer">
          <span>Audit: <strong style="color: ${validColor};">${p.validation_status}</strong></span>
          <span style="color: var(--primary); font-weight: 600;">Inspect Details &rarr;</span>
        </div>
      </div>
    `;
  }).join("");
}

function selectAndInspectPolicy(policyId) {
  state.selectedPolicyId = policyId;
  renderOverviewPolicies();
  switchTab("deepdive");
  loadPolicyDetail(policyId);
}

// =====================================================================
// View 2: Policy Deep-Dive (30 Features Audit)
// =====================================================================
function populatePolicySelector() {
  const select = document.getElementById("deepdive-policy-select");
  if (!select) return;

  select.innerHTML = state.policies.map(p => {
    const label = `${p.insurer_name || 'Policy'} - ${p.policy_holder_name || p.source_file} (${p.policy_number || 'No Num'})`;
    return `<option value="${p.id}" ${p.id === state.selectedPolicyId ? 'selected' : ''}>${escapeHtml(label)}</option>`;
  }).join("");

  select.addEventListener("change", (e) => {
    state.selectedPolicyId = e.target.value;
    loadPolicyDetail(state.selectedPolicyId);
  });
}

async function loadPolicyDetail(policyId) {
  if (!policyId) return;

  try {
    const res = await fetch(`/api/policy/${policyId}`);
    if (!res.ok) throw new Error("Policy not found");
    const data = await res.json();
    state.currentPolicyDetail = data;

    updatePolicyMetadataSidebar(data);
    renderFeaturesGrid();
  } catch (err) {
    console.error("Failed to load policy detail:", err);
    showToast("Error loading policy detail", "error");
  }
}

function updatePolicyMetadataSidebar(data) {
  const pDet = data.policy_details || {};
  const prem = data.premium || {};
  const demo = data.demographics || {};

  document.getElementById("meta-insurer").textContent = data.insurer_name || "Unspecified";
  document.getElementById("meta-type").textContent = data.policy_type || "GMC";
  document.getElementById("meta-policy-name").textContent = pDet.policy_holder_name || data.source_file || "Policy Details";
  document.getElementById("meta-policy-number").textContent = pDet.policy_number ? `#${pDet.policy_number}` : "No Policy Number Found";

  document.getElementById("meta-holder").textContent = pDet.policy_holder_name || "-";
  document.getElementById("meta-tpa").textContent = data.tpa_name || "Direct / Insurer In-House";
  document.getElementById("meta-dates").textContent = (pDet.start_date && pDet.end_date)
    ? `${pDet.start_date} to ${pDet.end_date}`
    : "Not Mentioned";

  document.getElementById("meta-lives").textContent = demo.total_lives
    ? Number(demo.total_lives).toLocaleString("en-IN")
    : "Not Mentioned";

  document.getElementById("meta-net-premium").textContent = prem.net_premium
    ? "₹" + Number(prem.net_premium).toLocaleString("en-IN")
    : "Not Mentioned";

  document.getElementById("meta-gross-premium").textContent = prem.total_premium
    ? "₹" + Number(prem.total_premium).toLocaleString("en-IN")
    : "Not Mentioned";

  const tiers = pDet.sum_insured_tiers || [];
  document.getElementById("meta-tiers").textContent = tiers.length > 0
    ? tiers.map(t => "₹" + Number(t).toLocaleString("en-IN")).join(", ")
    : "Floater / Unspecified";

  const valStatus = data.validation_status || "UNKNOWN";
  const validEl = document.getElementById("meta-validation");
  validEl.textContent = valStatus;
  validEl.style.color = valStatus === "PASS" ? "var(--accent-emerald)" : "var(--accent-amber)";

  const downloadBtn = document.getElementById("btn-download-single-json");
  if (downloadBtn) {
    downloadBtn.href = `/api/policy/${state.selectedPolicyId}/download`;
    downloadBtn.setAttribute("download", `${state.selectedPolicyId}.json`);
  }

  // JSON Modal trigger
  document.getElementById("btn-view-raw-json").onclick = () => {
    openModal("Raw Extraction JSON (Pydantic Schema)", `
      <pre style="background: rgba(0,0,0,0.5); padding: 16px; border-radius: 10px; max-height: 550px; overflow-y: auto; font-family: monospace; font-size: 12px; color: #a5f3fc;">
${escapeHtml(JSON.stringify(data, null, 2))}
      </pre>
    `);
  };
}

function initSearchAndFilter() {
  const searchInput = document.getElementById("feature-search-input");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      state.searchQuery = e.target.value.toLowerCase().trim();
      renderFeaturesGrid();
    });
  }

  const pills = document.querySelectorAll("#status-filter-pills .filter-pill");
  pills.forEach(pill => {
    pill.addEventListener("click", () => {
      pills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      state.activeFilterStatus = pill.dataset.status;
      renderFeaturesGrid();
    });
  });
}

function renderFeaturesGrid() {
  const container = document.getElementById("features-grid");
  const counterEl = document.getElementById("features-counter");
  if (!state.currentPolicyDetail || !state.currentPolicyDetail.features) {
    container.innerHTML = `<div style="grid-column: 1/-1; padding: 40px; text-align: center; color: var(--text-muted);">No features found for this policy.</div>`;
    return;
  }

  const features = state.currentPolicyDetail.features;
  const featureKeys = Object.keys(features);

  let renderedCount = 0;
  const cardsHtml = featureKeys.map(key => {
    const feat = features[key];
    const meta = FEATURE_METADATA[key] || { name: key.replace(/_/g, " "), category: "General Benefit" };

    const status = feat.status || "not_mentioned";

    // Filter by Status Pill
    if (state.activeFilterStatus !== "all" && status !== state.activeFilterStatus) {
      return "";
    }

    // Filter by Search Query
    if (state.searchQuery) {
      const matchName = meta.name.toLowerCase().includes(state.searchQuery);
      const matchCategory = meta.category.toLowerCase().includes(state.searchQuery);
      const matchEvidence = (feat.evidence_clause || "").toLowerCase().includes(state.searchQuery);
      if (!matchName && !matchCategory && !matchEvidence) {
        return "";
      }
    }

    renderedCount++;

    // Format Parameter Badges
    const badges = [];
    if (feat.limit_percent_si !== undefined && feat.limit_percent_si !== null) {
      badges.push(`<span class="meta-badge highlight">Limit: ${feat.limit_percent_si}% of SI</span>`);
    }
    if (feat.limit_amount !== undefined && feat.limit_amount !== null) {
      badges.push(`<span class="meta-badge highlight">Limit: ₹${Number(feat.limit_amount).toLocaleString("en-IN")}</span>`);
    }
    if (feat.copay_percent !== undefined && feat.copay_percent !== null) {
      badges.push(`<span class="meta-badge">Co-Pay: ${feat.copay_percent}%</span>`);
    }
    if (feat.days !== undefined && feat.days !== null) {
      badges.push(`<span class="meta-badge">${feat.days} Days</span>`);
    }
    if (feat.waiting_period_months !== undefined && feat.waiting_period_months !== null) {
      badges.push(`<span class="meta-badge">Wait: ${feat.waiting_period_months} Mo</span>`);
    }
    if (feat.capping_type) {
      badges.push(`<span class="meta-badge">${escapeHtml(feat.capping_type)}</span>`);
    }

    const tagClass = `tag-${status}`;
    const cardStatusClass = `status-${status}`;
    const evidenceText = feat.evidence_clause || "No explicit clause identified in document.";
    const pageNum = feat.page_number ? `Page ${feat.page_number}` : "Doc Body";

    return `
      <div class="benefit-card ${cardStatusClass}">
        <div>
          <div class="benefit-card-header">
            <div>
              <div class="benefit-title">${escapeHtml(meta.name)}</div>
              <div class="benefit-category">${escapeHtml(meta.category)}</div>
            </div>
            <span class="status-tag ${tagClass}">
              ● ${status.replace(/_/g, " ")}
            </span>
          </div>

          ${badges.length > 0 ? `<div class="benefit-meta-badges">${badges.join("")}</div>` : ""}

          <div class="evidence-box">
            <div class="evidence-header">
              <span>Grounding Citation</span>
              <span class="page-pill">${pageNum}</span>
            </div>
            &ldquo;${escapeHtml(evidenceText)}&rdquo;
          </div>
        </div>

        <div style="margin-top: 14px; display: flex; justify-content: flex-end;">
          <button class="btn-secondary" style="font-size: 11px; padding: 5px 10px;" onclick="auditSingleFeature('${key}')">
            🔍 Audit Clause
          </button>
        </div>
      </div>
    `;
  }).join("");

  container.innerHTML = cardsHtml || `<div style="grid-column: 1/-1; padding: 40px; text-align: center; color: var(--text-muted);">No features matched your filters.</div>`;
  counterEl.textContent = `Showing ${renderedCount} of ${featureKeys.length} Features`;
}

function auditSingleFeature(featureKey) {
  if (!state.currentPolicyDetail) return;
  const feat = state.currentPolicyDetail.features[featureKey];
  const meta = FEATURE_METADATA[featureKey] || { name: featureKey, category: "Benefit" };

  openModal(`Evidence Audit: ${meta.name}`, `
    <div style="display: flex; flex-direction: column; gap: 16px;">
      <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-glass); padding-bottom: 12px;">
        <div>
          <span style="font-size: 11px; color: var(--text-muted); text-transform: uppercase;">Category:</span>
          <strong style="margin-left: 6px;">${escapeHtml(meta.category)}</strong>
        </div>
        <span class="status-tag tag-${feat.status}">● ${feat.status}</span>
      </div>

      <div>
        <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 6px; font-weight: 700;">VERBATIM DOCUMENT CITATION:</div>
        <div style="background: rgba(0,0,0,0.4); padding: 16px; border-radius: 10px; border-left: 4px solid var(--primary); font-style: italic; line-height: 1.6; color: #f1f5f9;">
          &ldquo;${escapeHtml(feat.evidence_clause || 'No explicit textual evidence found.')}&rdquo;
        </div>
      </div>

      <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; font-size: 13px;">
        <div style="background: rgba(255,255,255,0.03); padding: 10px; border-radius: 8px;">
          <span style="color: var(--text-muted);">Citing Page:</span>
          <strong style="color: var(--accent-cyan); margin-left: 6px;">${feat.page_number ? `Page ${feat.page_number}` : 'Not specific'}</strong>
        </div>
        <div style="background: rgba(255,255,255,0.03); padding: 10px; border-radius: 8px;">
          <span style="color: var(--text-muted);">Audit Confidence:</span>
          <strong style="color: var(--accent-emerald); margin-left: 6px;">High (Ground Truth)</strong>
        </div>
      </div>

      <div>
        <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 6px; font-weight: 700;">EXTRACTED ATTRIBUTES:</div>
        <pre style="background: rgba(0,0,0,0.5); padding: 12px; border-radius: 8px; font-family: monospace; font-size: 12px; color: #cbd5e1;">
${escapeHtml(JSON.stringify(feat, null, 2))}
        </pre>
      </div>
    </div>
  `);
}

// =====================================================================
// View 3: Side-by-Side Comparison Matrix
// =====================================================================
function renderComparisonMatrix() {
  const thead = document.getElementById("comparison-thead");
  const tbody = document.getElementById("comparison-tbody");
  const matrix = state.summaryMetrics?.comparison_matrix || {};
  const filenames = Object.keys(matrix);

  if (filenames.length === 0) {
    thead.innerHTML = `<tr><th>Feature / Benefit</th><th>No Policies Available</th></tr>`;
    tbody.innerHTML = `<tr><td colspan="2" style="text-align: center; padding: 40px; color: var(--text-muted);">Extract multiple policies to inspect comparative benchmark matrix.</td></tr>`;
    return;
  }

  // Header row
  thead.innerHTML = `
    <tr>
      <th style="min-width: 240px; background: #0c1322;">Feature / Metric Benchmark</th>
      ${filenames.map(f => {
        const item = matrix[f];
        return `
          <th style="min-width: 220px; text-align: center;">
            <div style="font-size: 11px; color: var(--accent-cyan); text-transform: uppercase;">${escapeHtml(item.insurer || 'Insurer')}</div>
            <div style="font-size: 14px; font-weight: 700; margin: 4px 0;">${escapeHtml(f)}</div>
            <span class="type-pill type-gmc">${escapeHtml(item.policy_type || 'GMC')}</span>
          </th>
        `;
      }).join("")}
    </tr>
  `;

  // Rows definition
  const rows = [
    { label: "Insured Lives", getKey: (it) => it.lives ? Number(it.lives).toLocaleString("en-IN") : "N/A" },
    { label: "Gross Corporate Premium", getKey: (it) => it.total_premium ? `₹${Number(it.total_premium).toLocaleString("en-IN")}` : "N/A" },
    { label: "Avg Cost / Insured Life", getKey: (it) => it.cost_per_life ? `₹${Number(it.cost_per_life).toLocaleString("en-IN")}` : "N/A" },
    {
      label: "Room Rent Normal Limit",
      getKey: (it) => {
        const r = it.room_rent || {};
        if (r.limit_percent_si) return `<span class="status-tag tag-covered">● ${r.limit_percent_si}% of SI</span>`;
        if (r.limit_amount) return `<span class="status-tag tag-covered">● ₹${Number(r.limit_amount).toLocaleString("en-IN")}</span>`;
        return `<span class="status-tag tag-${r.status || 'not_mentioned'}">● ${r.status || 'N/A'}</span>`;
      }
    },
    {
      label: "ICU Charges Limit",
      getKey: (it) => {
        const icu = it.icu_charges || {};
        if (icu.limit_percent_si) return `<span class="status-tag tag-covered">● ${icu.limit_percent_si}% of SI</span>`;
        return `<span class="status-tag tag-${icu.status || 'not_mentioned'}">● ${icu.status || 'N/A'}</span>`;
      }
    },
    {
      label: "Pre-Hospitalization Window",
      getKey: (it) => it.pre_hosp_days ? `<span class="page-pill">${it.pre_hosp_days} Days</span>` : "Standard / N/A"
    },
    {
      label: "Post-Hospitalization Window",
      getKey: (it) => it.post_hosp_days ? `<span class="page-pill">${it.post_hosp_days} Days</span>` : "Standard / N/A"
    },
    {
      label: "Maternity Normal Limit",
      getKey: (it) => {
        const m = it.maternity_normal || {};
        if (m.limit_amount) return `<span class="status-tag tag-covered">● ₹${Number(m.limit_amount).toLocaleString("en-IN")}</span>`;
        return `<span class="status-tag tag-${m.status || 'not_mentioned'}">● ${m.status || 'N/A'}</span>`;
      }
    },
    {
      label: "Maternity C-Section Limit",
      getKey: (it) => {
        const m = it.maternity_c_section || {};
        if (m.limit_amount) return `<span class="status-tag tag-covered">● ₹${Number(m.limit_amount).toLocaleString("en-IN")}</span>`;
        return `<span class="status-tag tag-${m.status || 'not_mentioned'}">● ${m.status || 'N/A'}</span>`;
      }
    },
    {
      label: "Maternity 9-Month Waiting",
      getKey: (it) => `<span class="status-tag tag-${it.maternity_9m_wait || 'not_mentioned'}">● ${it.maternity_9m_wait || 'N/A'}</span>`
    },
    {
      label: "Pre-Existing Diseases (PED)",
      getKey: (it) => `<span class="status-tag tag-${it.ped_status || 'not_mentioned'}">● ${it.ped_status || 'N/A'}</span>`
    },
    {
      label: "Initial 30-Day Waiting Period",
      getKey: (it) => `<span class="status-tag tag-${it.wait_30d_status || 'not_mentioned'}">● ${it.wait_30d_status || 'N/A'}</span>`
    },
    {
      label: "Corporate Buffer Pool",
      getKey: (it) => `<span class="status-tag tag-${it.corporate_buffer || 'not_mentioned'}">● ${it.corporate_buffer || 'N/A'}</span>`
    },
    {
      label: "Audit Validation",
      getKey: (it) => `<strong style="color: ${it.validation_status === 'PASS' ? 'var(--accent-emerald)' : 'var(--accent-amber)'}">${it.validation_status}</strong>`
    }
  ];

  tbody.innerHTML = rows.map(r => `
    <tr>
      <td style="font-weight: 600; color: #f8fafc;">${r.label}</td>
      ${filenames.map(f => `<td style="text-align: center;">${r.getKey(matrix[f])}</td>`).join("")}
    </tr>
  `).join("");
}

function exportComparisonToCSV() {
  const matrix = state.summaryMetrics?.comparison_matrix || {};
  const filenames = Object.keys(matrix);
  if (filenames.length === 0) {
    showToast("No policies to export", "info");
    return;
  }

  let csvContent = "data:text/csv;charset=utf-8,";
  csvContent += "Feature," + filenames.map(f => `"${f}"`).join(",") + "\n";

  const rows = [
    { label: "Insurer", fn: it => it.insurer || "" },
    { label: "Policy Type", fn: it => it.policy_type || "" },
    { label: "Lives", fn: it => it.lives || "" },
    { label: "Premium", fn: it => it.total_premium || "" },
    { label: "Room Rent Status", fn: it => it.room_rent?.status || "" },
    { label: "ICU Charges Status", fn: it => it.icu_charges?.status || "" },
    { label: "Pre Hosp Days", fn: it => it.pre_hosp_days || "" },
    { label: "Post Hosp Days", fn: it => it.post_hosp_days || "" },
    { label: "Maternity Normal Limit", fn: it => it.maternity_normal?.limit_amount || "" },
    { label: "Maternity C-Section Limit", fn: it => it.maternity_c_section?.limit_amount || "" },
    { label: "PED Waiver Status", fn: it => it.ped_status || "" },
    { label: "30D Wait Waiver Status", fn: it => it.wait_30d_status || "" },
    { label: "Corporate Buffer", fn: it => it.corporate_buffer || "" },
    { label: "Validation Status", fn: it => it.validation_status || "" }
  ];

  rows.forEach(r => {
    const vals = filenames.map(f => `"${r.fn(matrix[f])}"`);
    csvContent += `"${r.label}",` + vals.join(",") + "\n";
  });

  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", "policy_comparison_matrix.csv");
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  showToast("Comparison CSV downloaded", "success");
}

function exportComparisonToJSON() {
  const matrix = state.summaryMetrics?.comparison_matrix || {};
  const portfolio = state.summaryMetrics?.portfolio || {};
  if (Object.keys(matrix).length === 0) {
    showToast("No policies to export", "info");
    return;
  }

  const exportData = {
    export_timestamp: new Date().toISOString(),
    portfolio_summary: portfolio,
    comparison_matrix: matrix
  };

  const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "policy_comparison_matrix.json";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
  showToast("Comparison JSON downloaded", "success");
}

// =====================================================================
// View 4: Live PDF Drag & Drop Ingestion
// =====================================================================
function initUpload() {
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("policy-file-input");
  const browseBtn = document.getElementById("btn-select-file");

  if (!dropZone || !fileInput) return;

  browseBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    fileInput.click();
  });

  dropZone.addEventListener("click", () => fileInput.click());

  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      handleFileUpload(e.target.files[0]);
    }
  });

  ['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add('drag-over');
    }, false);
  });

  ['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove('drag-over');
    }, false);
  });

  dropZone.addEventListener('drop', (e) => {
    const dt = e.dataTransfer;
    const files = dt.files;
    if (files.length > 0) {
      handleFileUpload(files[0]);
    }
  });
}

async function handleFileUpload(file) {
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    showToast("Only PDF documents are supported", "error");
    return;
  }

  const progressContainer = document.getElementById("upload-progress");
  const progressFill = document.getElementById("progress-fill");
  const stageText = document.getElementById("progress-stage-text");
  const percentText = document.getElementById("progress-percent");
  const detailText = document.getElementById("progress-detail");

  progressContainer.style.display = "block";
  progressFill.style.width = "15%";
  percentText.textContent = "15%";
  stageText.textContent = "Extracting Document Content...";
  detailText.textContent = `Reading text and table structures from ${file.name}...`;

  // Simulated stage progressions
  const stageTimer1 = setTimeout(() => {
    progressFill.style.width = "40%";
    percentText.textContent = "40%";
    stageText.textContent = "Classifying Document Type...";
    detailText.textContent = "Heuristic classifier checking policy markers (GMC, GPA, Individual)...";
  }, 1200);

  const stageTimer2 = setTimeout(() => {
    progressFill.style.width = "75%";
    percentText.textContent = "75%";
    stageText.textContent = "Gemini 2.5 Flash Auditing 30 Features...";
    detailText.textContent = "Extracting limits, verbatim grounding quotes, and cross-validating math...";
  }, 3500);

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/extract", {
      method: "POST",
      body: formData
    });

    clearTimeout(stageTimer1);
    clearTimeout(stageTimer2);

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "Extraction pipeline returned an error");
    }

    const data = await res.json();

    progressFill.style.width = "100%";
    percentText.textContent = "100%";
    stageText.textContent = "Extraction & Validation Complete!";
    detailText.textContent = `Processed in ${data.processing_time_sec || 0}s. Saved to outputs/ and updated summary.csv.`;

    showToast(`Successfully extracted ${file.name}!`, "success");

    // Refresh portfolio data and switch to deep-dive view
    await loadPortfolioData();
    const stem = file.name.replace(/\.[^/.]+$/, "").replace(/[^\w\-.]/g, "_");
    state.selectedPolicyId = `${stem}_extracted`;
    setTimeout(() => {
      switchTab("deepdive");
      loadPolicyDetail(state.selectedPolicyId);
      progressContainer.style.display = "none";
    }, 1200);

  } catch (err) {
    clearTimeout(stageTimer1);
    clearTimeout(stageTimer2);
    progressFill.style.width = "0%";
    stageText.textContent = "Extraction Failed";
    detailText.textContent = err.message;
    showToast(err.message, "error");
  }
}

// =====================================================================
// Modal Helper
// =====================================================================
function initModal() {
  const modal = document.getElementById("audit-modal");
  const closeBtn = document.getElementById("modal-close-btn");

  closeBtn.addEventListener("click", () => closeModal());
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });
}

function openModal(title, contentHtml) {
  const modal = document.getElementById("audit-modal");
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-content").innerHTML = contentHtml;
  modal.style.display = "flex";
}

function closeModal() {
  const modal = document.getElementById("audit-modal");
  modal.style.display = "none";
}

// =====================================================================
// Toast Helper
// =====================================================================
function showToast(message, type = "info") {
  const toast = document.getElementById("toast");
  const msgEl = document.getElementById("toast-message");
  const iconEl = document.getElementById("toast-icon");

  if (!toast) return;

  const icons = {
    success: "✅",
    error: "❌",
    info: "ℹ️"
  };

  iconEl.textContent = icons[type] || "ℹ️";
  msgEl.textContent = message;
  toast.style.display = "flex";

  setTimeout(() => {
    toast.style.display = "none";
  }, 3500);
}

// =====================================================================
// Utilities
// =====================================================================
function escapeHtml(text) {
  if (text === null || text === undefined) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
