
(function () {
  "use strict";


  function initSidebar() {
    var sidebar = document.getElementById("sidebar");
    var content = document.getElementById("content");
    var topbar = document.getElementById("topbar");
    var toggleBtn = document.getElementById("toggleBtn");
    var mobileBtn = document.getElementById("mobileBtn");
    var overlay = document.getElementById("overlay");

    if (toggleBtn) {
      toggleBtn.addEventListener("click", function () {
        if (sidebar) sidebar.classList.toggle("collapsed");
        if (content) content.classList.toggle("full");
        if (topbar) topbar.classList.toggle("full");
      });
    }
    if (mobileBtn) {
      mobileBtn.addEventListener("click", function () {
        if (sidebar) sidebar.classList.add("mobile-show");
        if (overlay) overlay.classList.add("show");
      });
    }
    if (overlay) {
      overlay.addEventListener("click", function () {
        if (sidebar) sidebar.classList.remove("mobile-show");
        if (overlay) overlay.classList.remove("show");
      });
    }

    if (sidebar) {
      var activeLink = sidebar.querySelector(".nav-link.active");
      if (activeLink) {
        activeLink.scrollIntoView({ block: "center" });
      }
    }
  }


  function initFormValidation() {
    var forms = document.querySelectorAll(".needs-validation");
    Array.prototype.forEach.call(forms, function (form) {
      form.addEventListener(
        "submit",
        function (event) {
          if (!form.checkValidity()) {
            event.preventDefault();
            event.stopPropagation();
          }
          form.classList.add("was-validated");
        },
        false
      );
    });
  }


  function readJSON(id, fallback) {
    var el = document.getElementById(id);
    if (!el) return fallback;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return fallback;
    }
  }

  function currency(val) {
    var n = Number(val || 0);
    return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  }

  function initCharts() {
    if (typeof ApexCharts === "undefined") return;


    var salesEl = document.querySelector("#salesChart");
    if (salesEl) {
      var sales = readJSON("sales-chart-data", { categories: [], revenue: [], orders: [] });
      new ApexCharts(salesEl, {
        chart: {
          type: "area",
          height: 360,
          fontFamily: "Poppins, sans-serif",
          toolbar: { show: false },
          zoom: { enabled: false },
        },
        colors: ["#e66239", "#2e90fa"],
        stroke: { width: [3, 2], curve: "smooth" },
        dataLabels: { enabled: false },
        series: [
          { name: "Revenue", data: sales.revenue },
          { name: "Orders", data: sales.orders },
        ],
        fill: {
          type: "gradient",
          gradient: { shadeIntensity: 1, opacityFrom: 0.35, opacityTo: 0.02, stops: [0, 100] },
        },
        grid: { borderColor: "#eef0f3", strokeDashArray: 4, padding: { left: 8, right: 8 } },
        xaxis: {
          categories: sales.categories,
          tickPlacement: "on",
          axisBorder: { show: false },
          axisTicks: { show: false },
          labels: { style: { colors: "#667085", fontSize: "11px" } },
        },
        yaxis: [
          { labels: { formatter: currency, style: { colors: "#667085" } } },
          {
            opposite: true,
            labels: {
              formatter: function (v) { return Math.round(v); },
              style: { colors: "#667085" },
            },
          },
        ],
        tooltip: { shared: true },
        legend: { position: "top", horizontalAlign: "right", markers: { radius: 12 } },
      }).render();
    }

    var custEl = document.querySelector("#customerChart");
    if (custEl) {
      var cust = readJSON("customer-chart-data", { series: [0, 0] });
      new ApexCharts(custEl, {
        chart: { type: "donut", height: 260, fontFamily: "Poppins, sans-serif" },
        colors: ["#e66239", "#2e90fa"],
        series: cust.series,
        labels: ["New", "Returning"],
        stroke: { width: 0 },
        legend: { position: "bottom", markers: { radius: 12 } },
        dataLabels: {
          enabled: true,
          formatter: function (val) { return Math.round(val) + "%"; },
          style: { fontSize: "12px", fontWeight: 600 },
          dropShadow: { enabled: false },
        },
        plotOptions: {
          pie: {
            donut: {
              size: "70%",
              labels: {
                show: true,
                total: {
                  show: true,
                  label: "Customers",
                  fontSize: "13px",
                  color: "#667085",
                  formatter: function () { return "100%"; },
                },
              },
            },
          },
        },
      }).render();
    }
  }

  // ---- Dynamic inline formsets (product variants / images) ---------------
  function initFormsets() {
    var wraps = document.querySelectorAll("[data-formset]");
    Array.prototype.forEach.call(wraps, function (wrap) {
      var prefix = wrap.getAttribute("data-formset");
      var total = document.getElementById("id_" + prefix + "-TOTAL_FORMS");
      var body = wrap.querySelector("[data-formset-body]");
      var tmpl = wrap.querySelector("template[data-formset-empty]");
      var addBtn = wrap.querySelector("[data-formset-add]");

      if (addBtn && total && body && tmpl) {
        addBtn.addEventListener("click", function () {
          var idx = parseInt(total.value, 10);
          var html = tmpl.innerHTML.replace(/__prefix__/g, idx);
          var holder = document.createElement("tbody");
          holder.innerHTML = html.trim();
          var row = holder.firstElementChild;
          if (row) {
            body.appendChild(row);
            total.value = idx + 1;
          }
        });
      }

      //hide any rows that are already marked for deletion on load (e.g. on validation re-render)
      var deleteCheckboxes = wrap.querySelectorAll("input[name$='-DELETE']");
      Array.prototype.forEach.call(deleteCheckboxes, function (cb) {
        if (cb.checked) {
          var row = cb.closest("tr");
          if (row) {
            row.style.display = "none";
          }
        }
      });

      wrap.addEventListener("click", function (e) {
        //handle row delete/remove
        var btnRemove = e.target.closest ? e.target.closest("[data-row-remove]") : null;
        if (btnRemove) {
          var row = btnRemove.closest("tr");
          if (row) {
            var idInput = row.querySelector("input[name$='-id']");
            var isExisting = idInput && idInput.value;

            if (isExisting) {
              var deleteCheckbox = row.querySelector("input[name$='-DELETE']");
              if (deleteCheckbox) {
                deleteCheckbox.checked = true;
              }
            } else {
              Array.prototype.forEach.call(row.querySelectorAll("input, select, textarea"), function (inp) {
                if (inp.type === "checkbox" || inp.type === "radio") inp.checked = false;
                else if (inp.type !== "hidden") inp.value = "";
              });
            }
            row.style.display = "none";
          }
          return;
        }

        //handle custom replace file button click
        var btnReplace = e.target.closest ? e.target.closest("[data-replace-file-btn]") : null;
        if (btnReplace) {
          var container = btnReplace.closest("[data-existing-file-container]");
          var fileInput = container ? container.querySelector("input[type='file']") : null;
          if (fileInput) {
            fileInput.click();
          }
        }
      });

      wrap.addEventListener("change", function (e) {
        var inp = e.target;

        //only one image can be primary - checking one unchecks all others,
        //like a radio button (product image formset only; matched by name
        //suffix so this has no effect on other formsets, e.g. variants).
        if (inp.type === "checkbox" && inp.checked && /-is_primary$/.test(inp.name || "")) {
          var primaryCheckboxes = wrap.querySelectorAll("input[type='checkbox'][name$='-is_primary']");
          Array.prototype.forEach.call(primaryCheckboxes, function (cb) {
            if (cb !== inp) {
              cb.checked = false;
            }
          });
        }

        if (inp.type === "file" && inp.files && inp.files[0]) {
          var fileUrl = URL.createObjectURL(inp.files[0]);

          //update custom label if inside an existing file container
          var container = inp.closest("[data-existing-file-container]");
          if (container) {
            var label = container.querySelector("[data-file-label]");
            if (label) {
              label.innerHTML = '<i class="ti ti-file-text me-1 text-success"></i>' + inp.files[0].name;
            }
          }

          //image preview logic
          var row = inp.closest("tr");
          var prev = row ? row.querySelector("[data-img-preview]") : null;
          if (prev) {
            if (prev.src && prev.src.startsWith("blob:")) {
              URL.revokeObjectURL(prev.src);
            }
            prev.src = fileUrl;
            prev.classList.remove("d-none");
          }

          //document view button update logic
          var viewContainer = row ? row.querySelector("[data-view-container]") : null;
          if (viewContainer) {
            var viewBtn = viewContainer.querySelector("[data-view-btn]");
            if (viewBtn) {
              if (viewBtn.href && viewBtn.href.startsWith("blob:")) {
                URL.revokeObjectURL(viewBtn.href);
              }
              viewBtn.href = fileUrl;
            } else {
              var placeholder = viewContainer.querySelector("[data-view-placeholder]");
              if (placeholder) {
                placeholder.remove();
              }
              viewContainer.innerHTML = '<a href="' + fileUrl + '" target="_blank" class="btn btn-icon btn-sm btn-light text-info" data-view-btn title="View Document"><i class="ti ti-eye"></i></a>';
            }
          }
        }
      });
    });
  }

  // ---- Product form: base stock field follows the variants table --------
  // A product's own stock_quantity stops being used once it has variants
  // (sales route through each variant's own stock instead - see
  // Product.is_in_stock in catalog/models.py). Keep the base Inventory
  // field read-only while variant rows exist, so the vendor isn't asked to
  // enter stock twice, and hand control straight back the moment the last
  // variant is removed so the field can't be left stale/unreachable.
  function initVariantStockToggle() {
    var variantsWrap = document.querySelector('[data-formset="variants"]');
    var stockInput = document.getElementById("id_stock_quantity");
    var note = document.querySelector("[data-stock-quantity-variant-note]");
    if (!variantsWrap || !stockInput || !note) return;

    var body = variantsWrap.querySelector("[data-formset-body]");
    if (!body) return;

    //the formset always renders one blank "extra" row (extra=1) even for a
    //brand-new product with zero real variants, so merely counting rows in
    //the DOM treats every new product as having variants. A row only
    //represents a real variant once it's an existing saved row (has an id)
    //or the vendor has actually started typing a type/name into it.
    function rowHasData(row) {
      var idInput = row.querySelector("input[name$='-id']");
      var typeInput = row.querySelector("input[name$='-variant_type']");
      var nameInput = row.querySelector("input[name$='-name']");
      return !!(
        (idInput && idInput.value) ||
        (typeInput && typeInput.value.trim()) ||
        (nameInput && nameInput.value.trim())
      );
    }

    function hasLiveVariantData() {
      var rows = body.querySelectorAll("tr");
      for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        if (row.style.display === "none") continue;
        if (rowHasData(row)) return true;
      }
      return false;
    }

    function refresh() {
      var hasVariants = hasLiveVariantData();
      stockInput.readOnly = hasVariants;
      stockInput.classList.toggle("bg-light", hasVariants);
      note.classList.toggle("d-none", !hasVariants);
    }

    refresh();
    //rows get added/removed (or hidden via style.display) by initFormsets -
    //observe rather than hook its handlers directly, so this keeps working
    //regardless of how a row's add/remove is implemented.
    var observer = new MutationObserver(refresh);
    observer.observe(body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["style"],
    });
    //typing into type/name doesn't mutate the DOM (only the input's .value
    //property changes, not its value="" attribute), so the observer above
    //won't see it - listen for that directly too.
    body.addEventListener("input", refresh);
    body.addEventListener("change", refresh);
  }

  function initPage() {
    initSidebar();
    initFormValidation();
    initCharts();
    initFormsets();
    initVariantStockToggle();
    initProductFormPersistFiles();
    initOrderStatusGuard();
  }


  function initOrderStatusGuard() {
    var form = document.getElementById("order-status-form");
    if (!form || form.dataset.cancelGuardBound === "1") return;
    form.dataset.cancelGuardBound = "1";

    var select = form.querySelector('select[name="new_status"]');
    var note = form.querySelector('textarea[name="note"]');
    var noteLabel = form.querySelector("[data-note-label]");
    if (!select) return;

    function syncNoteLabel() {
      if (noteLabel) {
        noteLabel.textContent = select.value === "cancelled" ? "Note (required for cancelling)" : "Note (optional)";
      }
    }
    select.addEventListener("change", syncNoteLabel);
    syncNoteLabel();

    form.addEventListener("submit", function (e) {
      if (select.value !== "cancelled") return;

      if (!note || !note.value.trim()) {
        e.preventDefault();
        if (note) note.focus();
        window.alert("Please add a note explaining why this order is being cancelled.");
        return;
      }

      var confirmed = window.confirm(
        "Cancel this order? This can't be undone here - if the customer " +
        "still wants it, a new order would need to be created. Continue?"
      );
      if (!confirmed) {
        e.preventDefault();
      }
    });
  }


  function initProductFormPersistFiles() {
    var form = document.getElementById("product-form");
    if (!form || form.dataset.ajaxBound === "1") return;
    form.dataset.ajaxBound = "1";
    form.addEventListener("submit", handleProductFormSubmit);
  }

  function handleProductFormSubmit(e) {
    e.preventDefault();
    var formEl = e.currentTarget;
    var submitBtn = formEl.querySelector('button[type="submit"]');


    var pickedFiles = [];
    Array.prototype.forEach.call(formEl.querySelectorAll('input[type="file"]'), function (input) {
      if (input.files && input.files[0]) {
        pickedFiles.push({ name: input.name, file: input.files[0] });
      }
    });

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<i class="ti ti-loader-2 me-1"></i>Saving...';
    }

    fetch(formEl.action, {
      method: "POST",
      body: new FormData(formEl),
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.text().then(function (html) {
          return { html: html, url: response.url };
        });
      })
      .then(function (result) {
        var doc = new DOMParser().parseFromString(result.html, "text/html");
        var newForm = doc.getElementById("product-form");

        if (newForm) {
        
          var imported = document.importNode(newForm, true);
          formEl.parentNode.replaceChild(imported, formEl);

          pickedFiles.forEach(function (entry) {
            var input = imported.querySelector('input[type="file"][name="' + entry.name + '"]');
            if (!input) return;
            var dt = new DataTransfer();
            dt.items.add(entry.file);
            input.files = dt.files;
            input.dispatchEvent(new Event("change", { bubbles: true }));
          });

          initFormsets();
          initVariantStockToggle();
          initProductFormPersistFiles();
          window.scrollTo({ top: 0, behavior: "smooth" });
        } else if (doc.getElementById("sidebar")) {
         
          document.title = doc.title;
          document.body.innerHTML = doc.body.innerHTML;
          window.history.pushState({}, doc.title, result.url);
          initPage();
        } else {
         
          window.location.href = result.url;
        }
      })
      .catch(function () {
        
        formEl.removeEventListener("submit", handleProductFormSubmit);
        formEl.submit();
      });
  }

  document.addEventListener("DOMContentLoaded", initPage);
})();
