(function () {
  var variantSelect = document.getElementById('variant-select');
  if (variantSelect) {
    variantSelect.addEventListener('change', function () {
      var url = this.getAttribute('data-price-url');
      var vid = this.value;
      
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
          var symbol = variantSelect.getAttribute('data-currency-symbol') || '';
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
