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
      var qty = qtyInput ? qtyInput.value : '1';
      var queryString = '?quantity=' + qty + (vid ? '&variant_id=' + vid : '');

      fetch(url + queryString)
        .then(function (r) { return r.json(); })
        .then(function (data) {
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

          var stockEl = document.querySelector('.jm-pdp-buybox__stock');
          if (stockEl) {
            stockEl.classList.toggle('is-in', inStock);
            stockEl.classList.toggle('is-out', !inStock);
            if (inStock) {
              stockEl.textContent = 'In stock' + (stock ? ' · ' + stock : '');
            } else {
              stockEl.textContent = 'Out of stock';
            }
          }

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
            var atLimit = inStock && qtyInput && parseInt(qtyInput.value, 10) >= stock;
            qtyLimitMsg.classList.toggle('d-none', !atLimit);
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
