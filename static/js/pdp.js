(function () {
  var variantOptions = document.getElementById('pdp-variant-options');
  if (variantOptions) {
    variantOptions.addEventListener('click', function (event) {
      var btn = event.target.closest('.jm-variant-option');
      if (!btn || !variantOptions.contains(btn) || btn.disabled) return;

      variantOptions.querySelectorAll('.jm-variant-option').forEach(function (b) {
        b.classList.remove('is-selected');
      });
      btn.classList.add('is-selected');

      var url = variantOptions.getAttribute('data-price-url');
      var vid = btn.getAttribute('data-variant-id') || '';

      document.querySelectorAll('.pdp-variant-id-input').forEach(function(input) {
        input.value = vid;
      });

      var qtyInput = document.getElementById('pdp-qty');
      if (qtyInput) {
        qtyInput.value = 1;
      }
      document.querySelectorAll('.pdp-qty-input').forEach(function (input) {
        input.value = 1;
      });
      var qtyLimitMsgReset = document.getElementById('pdp-qty-limit-msg');
      if (qtyLimitMsgReset) qtyLimitMsgReset.classList.add('d-none');

      var qty = '1';
      var queryString = '?quantity=' + qty + (vid ? '&variant_id=' + vid : '');

      fetch(url + queryString)
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.media && data.media.length) {
            var galleryRoot = document.querySelector('[data-jm-pdp-gallery]');
            var track = galleryRoot ? galleryRoot.querySelector('[data-gallery-track]') : null;

            if (track) {
              track.innerHTML = '';
              data.media.forEach(function (item, idx) {
                var slide = document.createElement('div');
                slide.className = 'jm-pdp-gallery__slide' + (idx === 0 ? ' is-active' : '');
                slide.setAttribute('data-gallery-slide', '');
                if (item.type === 'video') {
                  var video = document.createElement('video');
                  video.className = 'jm-pdp-gallery__image object-fit-contain';
                  video.setAttribute('data-gallery-video', '');
                  video.src = item.url;
                  if (item.poster) video.poster = item.poster;
                  video.muted = true;
                  video.loop = true;
                  video.playsInline = true;
                  video.controls = true;
                  video.preload = 'metadata';
                  slide.appendChild(video);
                } else {
                  var img = document.createElement('img');
                  img.className = 'jm-pdp-gallery__image zoom-image object-fit-contain';
                  img.src = item.url;
                  img.alt = item.alt || '';
                  if (idx === 0) {
                    img.width = 800;
                    img.height = 800;
                    img.setAttribute('fetchpriority', 'high');
                  } else {
                    img.loading = 'lazy';
                  }
                  slide.appendChild(img);
                }
                track.appendChild(slide);
              });
            }

            var thumbsWrap = galleryRoot ? galleryRoot.querySelector('.jm-pdp-gallery__thumbs') : null;
            if (galleryRoot && !thumbsWrap) {
              thumbsWrap = document.createElement('div');
              thumbsWrap.className = 'jm-pdp-gallery__thumbs';
              thumbsWrap.setAttribute('role', 'list');
              galleryRoot.appendChild(thumbsWrap);
            }
            if (thumbsWrap) {
              thumbsWrap.innerHTML = '';
              data.media.forEach(function (item, idx) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'jm-pdp-gallery__thumb thumb-btn' + (idx === 0 ? ' is-active active' : '');
                btn.setAttribute('data-index', String(idx));
                btn.setAttribute('role', 'listitem');
                var thumbSrc = item.poster || (item.type === 'video' ? '' : item.url);
                if (thumbSrc) {
                  btn.innerHTML = '<img src="' + thumbSrc + '" alt="" width="72" height="72" class="object-fit-cover" loading="lazy">';
                } else {
                  btn.innerHTML = '<span class="jm-pdp-gallery__thumb-placeholder"><svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg></span>';
                }
                if (item.type === 'video') {
                  btn.innerHTML += '<span class="jm-pdp-gallery__thumb-badge"><svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg></span>';
                }
                thumbsWrap.appendChild(btn);
              });
            }

            if (typeof window.reinitPageScripts === 'function') {
              window.reinitPageScripts();
            }
          }

          var el = document.getElementById('pdp-price');
          var elSticky = document.getElementById('pdp-sticky-price');
          var retailContainer = document.getElementById('pdp-retail-price-container');
          var symbol = variantOptions.getAttribute('data-currency-symbol') || '';
          var elPriceValue = document.getElementById('pdp-price-value');
          
          if (elPriceValue) {
            elPriceValue.textContent = symbol + ' ' + parseFloat(data.price).toFixed(2).replace(/\.00$/, '');
          }
          
          if (retailContainer) {
            if (data.is_tier_active === 'true') {
              retailContainer.classList.remove("d-none");
            } else {
              retailContainer.classList.add("d-none");
            }
          }
          if (elSticky) elSticky.textContent = symbol + ' ' + parseFloat(data.price).toFixed(2).replace(/\.00$/, '');
          var elRetail = document.getElementById('pdp-retail-price');
          if (elRetail && data.retail_price) {
            elRetail.textContent = symbol + ' ' + parseFloat(data.retail_price).toFixed(2).replace(/\.00$/, '');
          }
          var elRetailVal = document.getElementById('pdp-retail-price-val');
          if (elRetailVal && data.retail_price) {
            elRetailVal.value = data.retail_price;
          }

          if (data.is_in_cart !== undefined) {
            var addGroup = document.getElementById('pdp-add-to-cart-group');
            var viewGroup = document.getElementById('pdp-view-cart-group');
            var stickyAdd = document.getElementById('sticky-buy-form');
            var stickyView = document.getElementById('pdp-sticky-view-cart-btn');

            if (data.is_in_cart) {
              if (addGroup) addGroup.classList.add('d-none');
              if (viewGroup) viewGroup.classList.remove('d-none');
              if (stickyAdd) stickyAdd.classList.add('d-none');
              if (stickyView) stickyView.classList.remove('d-none');
            } else {
              if (addGroup) addGroup.classList.remove('d-none');
              if (viewGroup) viewGroup.classList.add('d-none');
              if (stickyAdd) stickyAdd.classList.remove('d-none');
              if (stickyView) stickyView.classList.add('d-none');
            }
          }

          var inStock = data.is_in_stock === 'true';
          var stock = parseInt(data.stock_quantity, 10);
          if (isNaN(stock)) stock = 0;
          var isLowStock = data.is_low_stock === 'true';

          var stockEl = document.querySelector('.jm-pdp-buybox__stock');
          if (stockEl) {
            stockEl.classList.toggle('is-in', inStock);
            stockEl.classList.toggle('is-out', !inStock);
            
            stockEl.classList.toggle('d-none', isLowStock);
            stockEl.textContent = inStock ? 'In stock' : 'Out of stock';
          }

          var lowStockAlert = document.getElementById('pdp-low-stock-alert');
          var lowStockCount = document.getElementById('pdp-low-stock-count');
          if (lowStockAlert) lowStockAlert.classList.toggle('d-none', !isLowStock);
          if (lowStockCount) lowStockCount.textContent = stock;

          var qtyStepperWrap = document.querySelector('.jm-pdp-qty');
          if (qtyStepperWrap) qtyStepperWrap.classList.toggle('d-none', !inStock);

          if (qtyInput) {
            qtyInput.setAttribute('max', stock || 1);
            if (inStock && parseInt(qtyInput.value, 10) > stock) {
              qtyInput.value = stock || 1;
              document.querySelectorAll('.pdp-qty-input').forEach(function (i) { i.value = qtyInput.value; });
            }
          }

          var qtyLimitMsg = document.getElementById('pdp-qty-limit-msg');
          if (qtyLimitMsg) {

            qtyLimitMsg.classList.add('d-none');
            qtyLimitMsg.textContent = 'Only ' + (stock || 1) + ' items available in stock.';
          }

          document.querySelectorAll(
            '#buy-form button[type="submit"], #buy-now-form button[type="submit"], ' +
            '#sticky-buy-form button[type="submit"], #sticky-buy-now-form button[type="submit"]'
          ).forEach(function (btn) {
            btn.disabled = !inStock;
          });

          var addLabelBtn = document.querySelector('#buy-form button[type="submit"]');
          if (addLabelBtn) addLabelBtn.textContent = inStock ? 'Add to Cart' : 'Unavailable';

          var stickyAddLabelBtn = document.querySelector('#sticky-buy-form button[type="submit"]');
          if (stickyAddLabelBtn) stickyAddLabelBtn.textContent = inStock ? 'Add' : 'Unavailable';
        });
    });
  }

  var citySelect = document.getElementById('delivery-city');
  if (citySelect) {
    citySelect.addEventListener('change', function () {
      if (!this.value) {
        return;
      }
      var url = this.getAttribute('data-estimate-url') + '?city=' + encodeURIComponent(this.value);
      fetch(url)
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var el = document.getElementById('delivery-estimate-text');
          if (el) el.textContent = 'Delivery: ' + data.label + ' to ' + data.city;
        });
    });
  }
})();
