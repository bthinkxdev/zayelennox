(function () {
  'use strict';

  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';
  var progressEl = document.getElementById('htmx-progress');
  var pageLoader = document.getElementById('jm-loader');
  var pendingGlobalProgress = 0;

  function hidePageLoader() {
    if (!pageLoader || pageLoader.classList.contains('is-done')) {
      return;
    }
    pageLoader.classList.add('is-done');
    window.setTimeout(function () {
      if (pageLoader) {
        pageLoader.setAttribute('hidden', '');
      }
    }, 450);
  }

  function triggeringElementHasIndicator(elt) {
    if (!elt) {
      return false;
    }
    if (elt.getAttribute && elt.getAttribute('hx-indicator')) {
      return true;
    }
    return !!elt.closest('[hx-indicator]');
  }

  function showGlobalProgress() {
    if (!progressEl) {
      return;
    }
    progressEl.hidden = false;
    progressEl.setAttribute('aria-hidden', 'false');
    progressEl.classList.add('is-active');
  }

  function hideGlobalProgress() {
    if (!progressEl || pendingGlobalProgress > 0) {
      return;
    }
    progressEl.classList.remove('is-active');
    progressEl.hidden = true;
    progressEl.setAttribute('aria-hidden', 'true');
  }

  function showHtmxToast() {
    var root = document.getElementById('htmx-toast-root');
    if (!root) {
      return;
    }
    root.hidden = false;
    root.innerHTML =
      '<div class="htmx-toast" role="alert">' +
      '<span class="htmx-toast__message">Something went wrong, please try again.</span>' +
      '<button type="button" class="htmx-toast__close btn-ghost" aria-label="Dismiss">&times;</button>' +
      '</div>';
    var closeBtn = root.querySelector('.htmx-toast__close');
    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        root.hidden = true;
        root.innerHTML = '';
      });
    }
    window.setTimeout(function () {
      if (!root.hidden) {
        root.hidden = true;
        root.innerHTML = '';
      }
    }, 6000);
  }

  document.body.addEventListener('htmx:configRequest', function (event) {
    if (csrfToken) {
      event.detail.headers['X-CSRFToken'] = csrfToken;
    }
  });

  document.body.addEventListener('htmx:beforeRequest', function (event) {
    if (triggeringElementHasIndicator(event.detail.elt)) {
      return;
    }
    pendingGlobalProgress += 1;
    showGlobalProgress();
  });

  document.body.addEventListener('htmx:afterRequest', function (event) {
    if (triggeringElementHasIndicator(event.detail.elt)) {
      return;
    }
    pendingGlobalProgress = Math.max(0, pendingGlobalProgress - 1);
    hideGlobalProgress();
  });

  document.body.addEventListener('htmx:responseError', function (event) {
    console.error('[HTMX] responseError', event.detail);
    showHtmxToast();
  });

  document.body.addEventListener('htmx:sendError', function (event) {
    console.error('[HTMX] sendError', event.detail);
    showHtmxToast();
  });

  window.addEventListener('load', function () {
    window.setTimeout(hidePageLoader, 320);
  });
  // Fallback if load already fired or assets cached
  if (document.readyState === 'complete') {
    window.setTimeout(hidePageLoader, 320);
  } else {
    document.addEventListener('DOMContentLoaded', function () {
      window.setTimeout(function () {
        if (document.readyState === 'complete') {
          hidePageLoader();
        }
      }, 1200);
    });
  }

  function loadCartDrawerIfNeeded() {
    var body = document.getElementById('cart-drawer-body');
    if (!body || body.dataset.drawerHydrated === 'true' || !window.htmx) {
      return;
    }
    var url = body.getAttribute('hx-get');
    if (!url) {
      return;
    }
    htmx.ajax('GET', url, { target: '#cart-drawer-body', swap: 'innerHTML' });
    body.dataset.drawerHydrated = 'true';
  }

  var cartOffcanvas = document.getElementById('cartOffcanvas');
  if (cartOffcanvas) {
    cartOffcanvas.addEventListener('shown.bs.offcanvas', function () {
      loadCartDrawerIfNeeded();
    });
  }

  if (cartOffcanvas && window.bootstrap && window.bootstrap.Offcanvas) {
    var params = new URLSearchParams(window.location.search);
    if (params.get('open_cart') === '1') {
      params.delete('open_cart');
      var cleanedSearch = params.toString();
      var cleanedUrl = window.location.pathname + (cleanedSearch ? '?' + cleanedSearch : '') + window.location.hash;
      window.history.replaceState(window.history.state, '', cleanedUrl);
      bootstrap.Offcanvas.getOrCreateInstance(cartOffcanvas).show();
    }
  }

  document.body.addEventListener('htmx:afterSwap', function (event) {
    if (event.detail.target && event.detail.target.id === 'cart-drawer-body') {
      event.detail.target.dataset.drawerHydrated = 'true';
    }
    if (event.detail.target && event.detail.target.id === 'search-suggestions') {
      initSearchSuggestionsKeyboard();
      updateSearchDropdownState();
    }
  });

  function updateSearchDropdownState() {
    var input = document.getElementById('site-search-input');
    var panel = document.getElementById('search-suggestions-dropdown');
    var results = document.getElementById('search-suggestions');
    if (!input || !panel || !results) {
      return;
    }
    var isOpen = results.innerHTML.trim().length > 0 || panel.querySelector('.htmx-request');
    input.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  }

  function closeSearchSuggestions() {
    var input = document.getElementById('site-search-input');
    var results = document.getElementById('search-suggestions');
    if (!input || !results) {
      return;
    }
    results.innerHTML = '';
    input.setAttribute('aria-expanded', 'false');
    input.focus();
  }

  function initSearchSuggestionsKeyboard() {
    var input = document.getElementById('site-search-input');
    var results = document.getElementById('search-suggestions');
    if (!input || !results) {
      return;
    }
    var links = results.querySelectorAll('.search-suggestion-link');
    links.forEach(function (link, index) {
      link.setAttribute('data-suggestion-index', String(index));
    });
    if (links.length) {
      input.dataset.activeSuggestion = '0';
      links[0].classList.add('is-active');
    } else {
      delete input.dataset.activeSuggestion;
    }
  }

  function setActiveSearchSuggestion(input, links, index) {
    links.forEach(function (link) { link.classList.remove('is-active'); });
    if (index < 0 || index >= links.length) {
      delete input.dataset.activeSuggestion;
      return;
    }
    input.dataset.activeSuggestion = String(index);
    links[index].classList.add('is-active');
    links[index].scrollIntoView({ block: 'nearest' });
  }

  var searchInput = document.getElementById('site-search-input');
  if (searchInput) {
    searchInput.addEventListener('keydown', function (event) {
      var results = document.getElementById('search-suggestions');
      if (!results) {
        return;
      }
      var links = results.querySelectorAll('.search-suggestion-link');
      var activeIndex = parseInt(searchInput.dataset.activeSuggestion || '-1', 10);

      if (event.key === 'Escape') {
        event.preventDefault();
        closeSearchSuggestions();
        return;
      }

      if (!links.length) {
        return;
      }

      if (event.key === 'ArrowDown') {
        event.preventDefault();
        var next = activeIndex < links.length - 1 ? activeIndex + 1 : 0;
        setActiveSearchSuggestion(searchInput, links, next);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        var prev = activeIndex > 0 ? activeIndex - 1 : links.length - 1;
        setActiveSearchSuggestion(searchInput, links, prev);
      } else if (event.key === 'Enter' && activeIndex >= 0 && links[activeIndex]) {
        event.preventDefault();
        window.location.href = links[activeIndex].href;
      }
    });

    searchInput.addEventListener('input', function () {
      if (!searchInput.value.trim()) {
        closeSearchSuggestions();
      }
    });

    searchInput.addEventListener('blur', function () {
      window.setTimeout(function () {
        var results = document.getElementById('search-suggestions');
        if (!results || document.activeElement === searchInput) {
          return;
        }
        if (!results.contains(document.activeElement)) {
          results.innerHTML = '';
          searchInput.setAttribute('aria-expanded', 'false');
        }
      }, 150);
    });
  }

  // Submitting the header search form with an empty query (search button
  // click, or pressing Enter with no suggestion highlighted) used to fall
  // through to a plain GET and land on the "shop all" PLP page
  // (/shop/?category=&q=). An empty search should just stay put instead.
  document.querySelectorAll('form.jm-search').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      var qInput = form.querySelector('input[name="q"]');
      if (!qInput || !qInput.value.trim()) {
        event.preventDefault();
        if (qInput) {
          qInput.focus();
        }
      }
    });
  });

  document.body.addEventListener('htmx:beforeRequest', function (event) {
    if (event.detail.elt && event.detail.elt.id === 'site-search-input') {
      var results = document.getElementById('search-suggestions');
      if (results) {
        results.innerHTML = '';
      }
      updateSearchDropdownState();
    }
  });

  document.body.addEventListener('htmx:afterRequest', function (event) {
    if (event.detail.elt && event.detail.elt.id === 'site-search-input') {
      updateSearchDropdownState();
    }
  });

  function reinitPageScripts() {
    document.querySelectorAll('.thumb-btn').forEach(function (btn) {
      if (btn.dataset.boundThumb) return;
      btn.dataset.boundThumb = '1';
      btn.addEventListener('click', function () {
        var main = document.getElementById('main-pdp-image');
        if (main) main.src = this.getAttribute('data-full');
        document.querySelectorAll('.thumb-btn').forEach(function (b) {
          b.classList.remove('active', 'is-active');
        });
        this.classList.add('active', 'is-active');
      });
    });
  }
  window.reinitPageScripts = reinitPageScripts;

  function applyDocumentLocale(detail) {
    if (!detail || !detail.lang) {
      return;
    }
    document.documentElement.lang = detail.lang;
    document.documentElement.dir = detail.dir || 'ltr';
    var rtlHref = document.body.getAttribute('data-rtl-stylesheet');
    var rtlLink = document.getElementById('rtl-stylesheet');
    if (detail.dir === 'rtl') {
      if (!rtlLink && rtlHref) {
        rtlLink = document.createElement('link');
        rtlLink.id = 'rtl-stylesheet';
        rtlLink.rel = 'stylesheet';
        rtlLink.href = rtlHref;
        document.head.appendChild(rtlLink);
      }
    } else if (rtlLink) {
      rtlLink.remove();
    }
  }

  document.body.addEventListener('preferencesUpdated', function (event) {
    applyDocumentLocale(event.detail);
  });

  document.body.addEventListener('htmx:beforeRequest', function (event) {
    if (event.detail.elt && event.detail.elt.classList.contains('preference-switcher')) {
      sessionStorage.setItem('flowardScrollY', String(window.scrollY));
    }
  });

  document.body.addEventListener('htmx:afterSettle', function (event) {
    if (event.detail.target && event.detail.target.id === 'floward-app-shell') {
      var saved = sessionStorage.getItem('flowardScrollY');
      if (saved !== null) {
        window.scrollTo(0, parseInt(saved, 10));
        sessionStorage.removeItem('flowardScrollY');
      }
      reinitPageScripts();
    }
    if (event.detail.target && event.detail.target.id === 'product-grid') {
      event.detail.target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      reinitPageScripts();
    }
  });

  reinitPageScripts();


  /*
   * Attention coordinator — search nudge pulses on a fixed schedule.
   * Timing plan (page load = 0):
   *   Search preferred: 15s, 55s, 95s (max 3, then stop / stop on search use)
   *   Each effect lasts 8s; after any effect, channel locked for 8s + 30s gap
   *   If a preferred time is busy, it waits until the channel is free
   */
  (function initAttentionEffects() {
    var SHOW_MS = 8000;
    var MIN_GAP_MS = 30000;
    var SEARCH_FIRST_MS = 15000;
    var SEARCH_GAP_MS = 40000;
    var SEARCH_MAX = 3;

    var freeAt = 0;
    var queue = Promise.resolve();
    var searchStopped = false;
    var timers = [];

    var openBtn = document.getElementById('mobile-search-open');
    var nudge = openBtn ? openBtn.closest('.jm-search-nudge') : null;
    var overlay = document.getElementById('mobile-search-overlay');
    var input = document.getElementById('mobile-search-input');
    var clearBtn = document.getElementById('mobile-search-clear');
    var results = document.getElementById('mobile-search-results');

    var NUDGE_STORAGE_DONE = 'jm_search_nudge_done';
    var NUDGE_STORAGE_COUNT = 'jm_search_nudge_count';

    function readSearchCount() {
      try {
        return parseInt(localStorage.getItem(NUDGE_STORAGE_COUNT) || '0', 10) || 0;
      } catch (e) {
        return 0;
      }
    }

    function writeSearchCount(count) {
      try {
        localStorage.setItem(NUDGE_STORAGE_COUNT, String(count));
      } catch (e) {}
    }

    function isSearchDone() {
      try {
        return localStorage.getItem(NUDGE_STORAGE_DONE) === '1'
          || localStorage.getItem('jm_search_nudge_seen') === '1';
      } catch (e) {
        return false;
      }
    }

    function markSearchDone() {
      searchStopped = true;
      if (nudge) {
        nudge.classList.remove('is-active');
        nudge.classList.add('is-done');
      }
      try {
        localStorage.setItem(NUDGE_STORAGE_DONE, '1');
      } catch (e) {}
    }

    function schedule(fn, delay) {
      var id = window.setTimeout(fn, Math.max(0, delay));
      timers.push(id);
      return id;
    }

    function runExclusive(activate, deactivate) {
      queue = queue.then(function () {
        return new Promise(function (resolve) {
          function start() {
            var now = Date.now();
            var wait = Math.max(0, freeAt - now);
            schedule(function () {
              freeAt = Date.now() + SHOW_MS + MIN_GAP_MS;
              activate();
              schedule(function () {
                deactivate();
                resolve();
              }, SHOW_MS);
            }, wait);
          }
          start();
        });
      });
      return queue;
    }

    function requestSearchPulse() {
      if (searchStopped || !nudge || isSearchDone()) return;
      var count = readSearchCount();
      if (count >= SEARCH_MAX) {
        markSearchDone();
        return;
      }
      runExclusive(
        function () {
          if (searchStopped || isSearchDone()) return;
          var next = readSearchCount() + 1;
          writeSearchCount(next);
          nudge.classList.add('is-active');
          if (next >= SEARCH_MAX) {
            schedule(markSearchDone, SHOW_MS + 40);
          }
        },
        function () {
          if (nudge) nudge.classList.remove('is-active');
        }
      );
    }

    function scheduleSearchPulses() {
      if (!nudge || isSearchDone()) {
        if (nudge) nudge.classList.add('is-done');
        searchStopped = true;
        return;
      }
      var count = readSearchCount();
      if (count >= SEARCH_MAX) {
        markSearchDone();
        return;
      }
      var remaining = SEARCH_MAX - count;
      for (var i = 0; i < remaining; i += 1) {
        schedule(requestSearchPulse, SEARCH_FIRST_MS + (i * SEARCH_GAP_MS));
      }
    }

    // Mobile search open/close wiring (kept with attention effects)
    if (overlay && openBtn && input) {
      function openSearch() {
        overlay.classList.add('is-open');
        overlay.setAttribute('aria-hidden', 'false');
        document.body.classList.add('mobile-search-open');
        openBtn.setAttribute('aria-expanded', 'true');
        markSearchDone();
        window.setTimeout(function () {
          input.focus({ preventScroll: true });
        }, 120);
      }

      function closeSearch() {
        overlay.classList.remove('is-open');
        overlay.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('mobile-search-open');
        openBtn.setAttribute('aria-expanded', 'false');
        input.blur();
      }

      function syncClearButton() {
        if (!clearBtn) return;
        clearBtn.hidden = !input.value.trim();
      }

      openBtn.addEventListener('click', openSearch);
      overlay.querySelectorAll('[data-search-dismiss]').forEach(function (el) {
        el.addEventListener('click', closeSearch);
      });
      document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && overlay.classList.contains('is-open')) {
          closeSearch();
        }
      });
      input.addEventListener('input', function () {
        syncClearButton();
        if (!input.value.trim() && results) results.innerHTML = '';
      });
      if (clearBtn) {
        clearBtn.addEventListener('click', function () {
          input.value = '';
          if (results) results.innerHTML = '';
          syncClearButton();
          input.focus({ preventScroll: true });
        });
      }
      document.body.addEventListener('htmx:afterSwap', function (event) {
        if (event.detail.target && event.detail.target.id === 'mobile-search-results') {
          syncClearButton();
        }
      });
    }

    scheduleSearchPulses();
  })();

  document.querySelectorAll('.product-rail-scroll, .chip-scroll').forEach(function (rail) {
    var isDown = false;
    var startX;
    var scrollLeft;
    rail.addEventListener('mousedown', function (e) {
      isDown = true;
      startX = e.pageX - rail.offsetLeft;
      scrollLeft = rail.scrollLeft;
      rail.style.cursor = 'grabbing';
    });
    rail.addEventListener('mouseleave', function () { isDown = false; rail.style.cursor = ''; });
    rail.addEventListener('mouseup', function () { isDown = false; rail.style.cursor = ''; });
    rail.addEventListener('mousemove', function (e) {
      if (!isDown) return;
      e.preventDefault();
      var x = e.pageX - rail.offsetLeft;
      rail.scrollLeft = scrollLeft - (x - startX) * 1.5;
    });
  });
})();

// Featured brands rail: arrow scrolling + auto-hide disabled state
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.brand-rail').forEach((rail) => {
    const track = rail.querySelector('[data-brand-track]');
    const prevBtn = rail.querySelector('[data-brand-scroll="prev"]');
    const nextBtn = rail.querySelector('[data-brand-scroll="next"]');
    if (!track || !prevBtn || !nextBtn) return;

    const scrollByCard = (dir) => {
      const card = track.querySelector('.brand-card');
      const gap = 20;
      const distance = card ? card.offsetWidth + gap : 220;
      track.scrollBy({ left: dir * distance * 2, behavior: 'smooth' });
    };

    prevBtn.addEventListener('click', () => scrollByCard(-1));
    nextBtn.addEventListener('click', () => scrollByCard(1));

    const updateArrowState = () => {
      const maxScroll = track.scrollWidth - track.clientWidth - 1;
      prevBtn.disabled = track.scrollLeft <= 0;
      nextBtn.disabled = track.scrollLeft >= maxScroll || maxScroll <= 0;
    };

    track.addEventListener('scroll', updateArrowState, { passive: true });
    window.addEventListener('resize', updateArrowState);
    updateArrowState();
  });
});
/* Desert Star: product rail arrows, quick view, wishlist, search category */
(function () {
  'use strict';

  function initRailArrows(root) {
    (root || document).querySelectorAll('.jm-featured__rail').forEach(function (rail) {
      if (rail.dataset.jmRailReady === '1') return;
      var track = rail.querySelector('[data-rail-track]');
      var prevBtn = rail.querySelector('[data-rail-scroll="prev"]');
      var nextBtn = rail.querySelector('[data-rail-scroll="next"]');
      if (!track || !prevBtn || !nextBtn) return;
      rail.dataset.jmRailReady = '1';

      function scrollByDir(dir) {
        var styles = window.getComputedStyle(track);
        var gap = parseFloat(styles.columnGap || styles.gap) || 16;
        var item = track.querySelector('.product-rail-item');
        var colWidth = item ? item.getBoundingClientRect().width : 240;
        track.scrollBy({ left: dir * (colWidth + gap) * 2, behavior: 'smooth' });
      }

      function updateState() {
        var maxScroll = track.scrollWidth - track.clientWidth - 1;
        prevBtn.disabled = track.scrollLeft <= 0;
        nextBtn.disabled = track.scrollLeft >= maxScroll || maxScroll <= 0;
      }

      prevBtn.addEventListener('click', function () { scrollByDir(-1); });
      nextBtn.addEventListener('click', function () { scrollByDir(1); });
      track.addEventListener('scroll', updateState, { passive: true });
      window.addEventListener('resize', updateState);
      updateState();
    });
  }

  // Set by openQuickView() on each open so the Quick View modal's own Add
  // to Cart button can defer to the same variant picker the product card
  // uses (openVariantModal) - Quick View has no variant data of its own,
  // it just borrows the source card's hidden .jm-variant-options-template.
  var qvActiveCard = null;
  var qvActiveVariantBtn = null;

  function openQuickView(card) {
    var modalEl = document.getElementById('jmQuickViewModal');
    if (!modalEl || !window.bootstrap) return;
    var img = document.getElementById('jm-qv-image');
    var title = document.getElementById('jmQuickViewTitle');
    var price = document.getElementById('jm-qv-price');
    var stock = document.getElementById('jm-qv-stock');
    var badge = document.getElementById('jm-qv-badge');
    var pdp = document.getElementById('jm-qv-pdp');
    var productId = document.getElementById('jm-qv-product-id');

    if (img) {
      img.src = card.dataset.productImage || '';
      img.alt = card.dataset.productName || '';
    }
    if (title) title.textContent = card.dataset.productName || '';
    if (price) price.textContent = card.dataset.productPrice || '';
    if (stock) stock.textContent = card.dataset.productStock || '';
    if (badge) {
      if (card.dataset.productBadge) {
        badge.hidden = false;
        badge.textContent = card.dataset.productBadge;
      } else {
        badge.hidden = true;
      }
    }
    if (pdp) pdp.href = card.dataset.productUrl || '#';
    if (productId) productId.value = card.dataset.productId || '';

    var inCart = card.dataset.inCart === 'true';
    var inStock = card.dataset.inStock === 'true';
    var qvCartForm = document.getElementById('jm-qv-cart');
    var qvViewCart = document.getElementById('jm-qv-view-cart');
    var qvAddBtn = document.getElementById('jm-qv-add-btn');

    // Same reference point product_card.html uses to decide whether this
    // product needs a variant picker: the ATC button in the card's own
    // cart form gets data-jm-variant-atc when product.variant_list exists.
    qvActiveCard = card;
    qvActiveVariantBtn = card.querySelector('[data-jm-variant-atc]');

    if (qvAddBtn) {
      qvAddBtn.disabled = !inStock;
      qvAddBtn.textContent = inStock
        ? (qvAddBtn.dataset.labelInStock || qvAddBtn.textContent)
        : (qvAddBtn.dataset.labelOutStock || qvAddBtn.textContent);
    }

    if (qvCartForm && qvViewCart) {
      if (inCart) {
        qvCartForm.classList.add('d-none');
        qvViewCart.classList.remove('d-none');
      } else {
        qvCartForm.classList.remove('d-none');
        qvViewCart.classList.add('d-none');
      }
    }

    bootstrap.Modal.getOrCreateInstance(modalEl).show();
  }

  function formatMoney(symbol, amount) {
    var value = parseFloat(amount);
    if (isNaN(value)) return '';
    return (symbol ? symbol + ' ' : '') + value.toFixed(2).replace(/\.00$/, '');
  }

  // Renders the selected-variant summary (name, price, discount, stock) in
  // the variant picker modal and syncs the hidden variant_id/submit state.
  function renderVariantSummary(opts) {
    var titleEl = document.getElementById('jmVariantModalTitle');
    var subtitleEl = document.getElementById('jm-vm-subtitle');
    var priceEl = document.getElementById('jm-vm-price');
    var mrpEl = document.getElementById('jm-vm-mrp');
    var discountEl = document.getElementById('jm-vm-discount');
    var stockEl = document.getElementById('jm-vm-stock');
    var submitBtn = document.getElementById('jm-vm-submit');
    var variantIdInput = document.getElementById('jm-vm-variant-id');

    if (titleEl) titleEl.textContent = opts.productName || '';

    if (subtitleEl) {
      var typeLabel = opts.variantType
        ? opts.variantType.charAt(0).toUpperCase() + opts.variantType.slice(1)
        : 'Option';
      subtitleEl.innerHTML = '';
      subtitleEl.appendChild(document.createTextNode(typeLabel + ': '));
      var strong = document.createElement('strong');
      strong.textContent = opts.variantName || '';
      subtitleEl.appendChild(strong);
    }

    if (priceEl) priceEl.textContent = formatMoney(opts.symbol, opts.price);

    if (mrpEl) mrpEl.textContent = opts.discount > 0 ? formatMoney(opts.symbol, opts.mrp) : '';
    if (discountEl) discountEl.textContent = opts.discount > 0 ? (opts.discount + '% OFF') : '';

    if (stockEl) {
      stockEl.classList.remove('is-low', 'is-ok');
      if (!opts.inStock) {
        stockEl.textContent = 'Out of stock';
        stockEl.classList.add('is-low');
      } else if (opts.stock > 0 && opts.stock <= 5) {
        stockEl.textContent = 'Only ' + opts.stock + ' left';
        stockEl.classList.add('is-low');
      } else {
        stockEl.textContent = 'In Stock';
        stockEl.classList.add('is-ok');
      }
    }

    if (variantIdInput) variantIdInput.value = opts.variantId || '';
    if (submitBtn) submitBtn.disabled = !opts.inStock;
  }

  function selectVariantOption(optionsContainer, btn) {
    if (!btn || btn.disabled) return;
    optionsContainer.querySelectorAll('.jm-variant-option').forEach(function (b) {
      b.classList.remove('is-selected');
    });
    btn.classList.add('is-selected');

    renderVariantSummary({
      variantId: btn.getAttribute('data-variant-id') || '',
      variantName: btn.getAttribute('data-variant-name') || '',
      variantType: btn.getAttribute('data-variant-type') || '',
      price: btn.getAttribute('data-price') || '0',
      mrp: btn.getAttribute('data-mrp') || '0',
      discount: parseInt(btn.getAttribute('data-discount') || '0', 10),
      stock: parseInt(btn.getAttribute('data-stock') || '0', 10),
      inStock: btn.getAttribute('data-in-stock') === 'true',
      symbol: optionsContainer.getAttribute('data-currency-symbol') || '',
      productName: optionsContainer.getAttribute('data-product-name') || ''
    });
  }

  function openVariantModal(card, triggerBtn) {
    var modalEl = document.getElementById('jmVariantModal');
    if (!modalEl || !window.bootstrap) return;

    var form = triggerBtn.closest('form');
    var template = form ? form.querySelector('.jm-variant-options-template') : null;
    if (!template) return;

    var optionsContainer = document.getElementById('jm-vm-options');
    var productIdInput = document.getElementById('jm-vm-product-id');

    if (optionsContainer) {
      optionsContainer.setAttribute('data-currency-symbol', template.getAttribute('data-currency-symbol') || '');
      optionsContainer.setAttribute('data-product-name', template.getAttribute('data-product-name') || card.dataset.productName || '');
      optionsContainer.innerHTML = '';
      optionsContainer.appendChild(template.content.cloneNode(true));
    }
    if (productIdInput) productIdInput.value = card.dataset.productId || '';

    if (optionsContainer) {
      // Default to the cheapest in-stock option (falling back to the
      // cheapest overall if none are in stock), matching the "From <price>"
      // shown on the card and the PDP's default variant.
      var optionButtons = optionsContainer.querySelectorAll('.jm-variant-option');
      var defaultBtn = null;
      var bestPrice = Infinity;
      for (var i = 0; i < optionButtons.length; i++) {
        if (optionButtons[i].getAttribute('data-in-stock') === 'true') {
          var price = parseFloat(optionButtons[i].getAttribute('data-price')) || 0;
          if (price < bestPrice) {
            bestPrice = price;
            defaultBtn = optionButtons[i];
          }
        }
      }
      if (!defaultBtn) {
        bestPrice = Infinity;
        for (var j = 0; j < optionButtons.length; j++) {
          var anyPrice = parseFloat(optionButtons[j].getAttribute('data-price')) || 0;
          if (anyPrice < bestPrice) {
            bestPrice = anyPrice;
            defaultBtn = optionButtons[j];
          }
        }
      }
      if (defaultBtn) selectVariantOption(optionsContainer, defaultBtn);
    }

    bootstrap.Modal.getOrCreateInstance(modalEl).show();
  }

  function setWishFilled(svg, filled) {
    if (!svg) return;
    svg.setAttribute('fill', filled ? 'currentColor' : 'none');
  }

  // Remember the last known add/remove per product so we can correct stale
  // wish-heart buttons on pages restored from the back/forward cache (see
  // resyncWishlistButtonsFromStorage below). Keyed per-product-id rather
  // than as one big blob so concurrent tabs can't clobber each other.
  var WISHLIST_LS_PREFIX = 'jm:wishlist:';

  function setWishlistLocalState(productId, added) {
    try {
      localStorage.setItem(WISHLIST_LS_PREFIX + productId, added ? '1' : '0');
    } catch (e) {
      // localStorage unavailable (private browsing etc.) - safe to ignore,
      // this is only a best-effort correction for the bfcache case.
    }
  }

  function getWishlistLocalState(productId) {
    try {
      var v = localStorage.getItem(WISHLIST_LS_PREFIX + productId);
      return v === null ? null : v === '1';
    } catch (e) {
      return null;
    }
  }

  function applyWishButtonState(btn, active) {
    btn.classList.toggle('is-active', active);
    btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    setWishFilled(btn.querySelector('svg'), active);
  }

  function syncWishlistChrome(detail) {
    var added = !!(detail && detail.added);
    var productId = detail && detail.product_id != null ? String(detail.product_id) : '';
    if (!productId) return;

    setWishlistLocalState(productId, added);

    document.querySelectorAll('.jm-product-card__wish').forEach(function (btn) {
      var form = btn.closest('form');
      var input = form ? form.querySelector('input[name="product_id"]') : null;
      if (!input || String(input.value) !== productId) return;
      applyWishButtonState(btn, added);
    });

    document.querySelectorAll('[data-jm-wish-btn]').forEach(function (btn) {
      if (String(btn.getAttribute('data-product-id') || '') !== productId) return;
      applyWishButtonState(btn, added);
    });
  }

  
  function resyncWishlistButtonsFromStorage() {
    document.querySelectorAll('.jm-product-card__wish').forEach(function (btn) {
      var form = btn.closest('form');
      var input = form ? form.querySelector('input[name="product_id"]') : null;
      var productId = input ? input.value : '';
      if (!productId) return;
      var stored = getWishlistLocalState(productId);
      if (stored !== null) {
        applyWishButtonState(btn, stored);
      }
    });

    document.querySelectorAll('[data-jm-wish-btn]').forEach(function (btn) {
      var productId = btn.getAttribute('data-product-id') || '';
      if (!productId) return;
      var stored = getWishlistLocalState(productId);
      if (stored !== null) {
        applyWishButtonState(btn, stored);
      }
    });
  }

  window.addEventListener('pageshow', function (event) {
    if (event.persisted) {
      resyncWishlistButtonsFromStorage();
    }
  });

  document.addEventListener('click', function (event) {
    var qvBtn = event.target.closest('[data-jm-quick-view]');
    if (qvBtn) {
      var card = qvBtn.closest('.jm-product-card');
      if (card) openQuickView(card);
      return;
    }

    // Quick View's own Add to Cart button - if the product has variants,
    // defer to the same variant picker the product card uses instead of
    // adding the base product directly (Quick View has no variant_id
    // field of its own).
    var qvAddClick = event.target.closest('#jm-qv-add-btn');
    if (qvAddClick && qvActiveVariantBtn) {
      event.preventDefault();
      var qvModalEl = document.getElementById('jmQuickViewModal');
      if (qvModalEl && window.bootstrap) {
        bootstrap.Modal.getOrCreateInstance(qvModalEl).hide();
      }
      openVariantModal(qvActiveCard, qvActiveVariantBtn);
      return;
    }

    var variantBtn = event.target.closest('[data-jm-variant-atc]');
    if (variantBtn) {
      var variantCard = variantBtn.closest('.jm-product-card');
      if (variantCard) {
        event.preventDefault();
        openVariantModal(variantCard, variantBtn);
      }
      return;
    }

    var variantOptionBtn = event.target.closest('.jm-variant-option');
    if (variantOptionBtn) {
      var optionsContainer = document.getElementById('jm-vm-options');
      if (optionsContainer && optionsContainer.contains(variantOptionBtn)) {
        selectVariantOption(optionsContainer, variantOptionBtn);
      }
    }
  });

  document.addEventListener('DOMContentLoaded', function () {
    initRailArrows(document);
  });

  document.body.addEventListener('htmx:afterSwap', function () {
    initRailArrows(document);
  });

  document.body.addEventListener('wishlistUpdated', function (event) {
    var detail = event.detail || {};
    syncWishlistChrome(detail);

    if (detail.added === false && window.location.pathname.indexOf('/wishlist') !== -1) {
      var productId = detail.product_id;
      if (productId) {
        document.querySelectorAll('.jm-product-card__wish').forEach(function (btn) {
          var form = btn.closest('form');
          var input = form ? form.querySelector('input[name="product_id"]') : null;
          if (input && String(input.value) === String(productId)) {
            var gridItem = btn.closest('.product-grid-item');
            if (gridItem) {
              gridItem.style.transition = 'opacity 0.3s ease';
              gridItem.style.opacity = '0';
              setTimeout(function() {
                gridItem.remove();
                var gridInner = document.querySelector('.product-grid-inner');
                if (gridInner && gridInner.children.length === 0) {
                  // Swap in the empty-wishlist state in place instead of a
                  // full page reload, so there's no navigation/flash at all.
                  var emptyTemplate = document.getElementById('wishlist-empty-template');
                  if (emptyTemplate && emptyTemplate.content) {
                    gridInner.replaceWith(emptyTemplate.content.cloneNode(true));
                  } else {
                    window.location.reload();
                  }
                }
              }, 300);
            }
          }
        });
      }
    }
  });

  document.body.addEventListener('cartItemAdded', function (event) {
    var detail = event.detail || {};
    var productId = detail.product_id ? String(detail.product_id) : '';
    if (!productId) return;

    document.querySelectorAll('.jm-product-card[data-product-id="' + productId + '"]').forEach(function (card) {
      card.dataset.inCart = 'true';
      var form = card.querySelector('form.jm-product-card__cart');
      if (form && !form.classList.contains('d-none')) {
        var viewCartLink = document.createElement('a');
        var cartUrl = '/cart/';
        var existingLink = document.querySelector('a[href*="/cart/"]');
        if (existingLink) {
            cartUrl = existingLink.getAttribute('href');
        }

        viewCartLink.href = cartUrl;
        viewCartLink.className = 'btn btn-outline-floward jm-product-card__atc jm-product-card__atc--in-cart mt-auto jm-dynamic-view-cart';
        viewCartLink.innerHTML = '<span>View Cart</span>';

        form.classList.add('d-none');
        form.parentNode.insertBefore(viewCartLink, form.nextSibling);
      }
    });

    var qvProductId = document.getElementById('jm-qv-product-id');
    if (qvProductId && qvProductId.value === productId) {
      var qvCartForm = document.getElementById('jm-qv-cart');
      var qvViewCart = document.getElementById('jm-qv-view-cart');
      if (qvCartForm && qvViewCart) {
        qvCartForm.classList.add('d-none');
        qvViewCart.classList.remove('d-none');
      }
    }
  });

  document.body.addEventListener('cartItemRemoved', function (event) {
    var detail = event.detail || {};
    var productId = detail.product_id ? String(detail.product_id) : '';
    if (!productId) return;

    document.querySelectorAll('.jm-product-card[data-product-id="' + productId + '"]').forEach(function (card) {
      card.dataset.inCart = 'false';
      var viewCartLink = card.querySelector('.jm-dynamic-view-cart');
      if (viewCartLink) {
        viewCartLink.remove();
      }
      var form = card.querySelector('form.jm-product-card__cart');
      if (form) {
        form.classList.remove('d-none');
      }
    });

    var qvProductId = document.getElementById('jm-qv-product-id');
    if (qvProductId && qvProductId.value === productId) {
      var qvCartForm = document.getElementById('jm-qv-cart');
      var qvViewCart = document.getElementById('jm-qv-view-cart');
      if (qvCartForm && qvViewCart) {
        qvCartForm.classList.remove('d-none');
        qvViewCart.classList.add('d-none');
      }
    }
  });

  // Note: we deliberately do NOT force a full page.reload() here when a page
  // is restored from the back/forward cache (event.persisted). Doing so
  // causes a visible flash of the stale cached page followed by a reload on
  // every browser back/forward navigation site-wide. The header/nav cart and
  // wishlist count badges already refresh themselves via
  // hx-trigger="... pageshow from:window", and resyncWishlistButtonsFromStorage
  // (registered above) corrects any stale wish-heart button state on product
  // cards - so a full reload is never needed here.
})();

/* Desert Star: sticky header offset + mobile trust auto-slide */
(function () {
  'use strict';

  function syncHeaderStickyOffset() {
    var header = document.querySelector('.site-header.jm-header');
    if (!header) return;
    var height = Math.ceil(header.getBoundingClientRect().height);
    if (height > 0) {
      document.documentElement.style.setProperty('--jm-header-sticky-offset', height + 'px');
    }
  }

  function initTrustAutoSlide(root) {
    var track = (root || document).querySelector('[data-jm-trust-track]');
    if (!track || track.dataset.jmTrustReady === '1') return;
    track.dataset.jmTrustReady = '1';

    var timer = null;
    var paused = false;
    var mq = window.matchMedia('(max-width: 991.98px)');

    function step() {
      if (paused || !mq.matches) return;
      var item = track.querySelector('.jm-trust__item');
      if (!item) return;
      var gap = 8;
      var distance = item.getBoundingClientRect().width + gap;
      var maxScroll = track.scrollWidth - track.clientWidth - 2;
      if (maxScroll <= 0) return;
      if (track.scrollLeft >= maxScroll) {
        track.scrollTo({ left: 0, behavior: 'smooth' });
      } else {
        track.scrollBy({ left: distance, behavior: 'smooth' });
      }
    }

    function start() {
      stop();
      if (!mq.matches) return;
      timer = window.setInterval(step, 3200);
    }

    function stop() {
      if (timer) {
        window.clearInterval(timer);
        timer = null;
      }
    }

    ['pointerdown', 'touchstart', 'mouseenter', 'focusin'].forEach(function (evt) {
      track.addEventListener(evt, function () { paused = true; }, { passive: true });
    });
    ['pointerup', 'touchend', 'mouseleave', 'focusout'].forEach(function (evt) {
      track.addEventListener(evt, function () { paused = false; }, { passive: true });
    });

    if (typeof mq.addEventListener === 'function') {
      mq.addEventListener('change', start);
    } else if (typeof mq.addListener === 'function') {
      mq.addListener(start);
    }

    start();
  }

  document.addEventListener('DOMContentLoaded', function () {
    syncHeaderStickyOffset();
    initTrustAutoSlide(document);
  });

  window.addEventListener('resize', syncHeaderStickyOffset);
  window.addEventListener('load', syncHeaderStickyOffset);

  document.addEventListener('click', function (event) {
    var link = event.target.closest('[data-jm-scroll-target]');
    if (!link) return;
    var id = link.getAttribute('data-jm-scroll-target');
    var target = id ? document.getElementById(id) : null;
    if (!target) return;
    event.preventDefault();
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (history.replaceState) {
      history.replaceState(null, '', '#' + id);
    }
  });

  // Leaf-vine heading ornaments: reveal each one only as its section scrolls
  // into view, instead of every copy animating together on page load.
  document.addEventListener('DOMContentLoaded', function () {
    var vines = document.querySelectorAll('.leaf-vine');
    if (!vines.length) return;

    if (typeof IntersectionObserver === 'undefined') {
      vines.forEach(function (vine) { vine.classList.add('is-visible'); });
      return;
    }

    var observer = new IntersectionObserver(function (entries, obs) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        obs.unobserve(entry.target);
      });
    }, { threshold: 0.2, rootMargin: '0px 0px -10% 0px' });

    vines.forEach(function (vine) { observer.observe(vine); });
  });
})();
