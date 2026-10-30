from loot_hunt.extractors.microdata import (
    extract_datalayer,
    extract_omnibus_price,
    extract_product_microdata,
    extract_schema_json_ld,
)

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Konsola Sony PS5 Slim",
  "gtin13": "0711719577232",
  "offers": {
    "@type": "Offer",
    "price": "2099.00",
    "priceCurrency": "PLN",
    "availability": "https://schema.org/InStock"
  }
}
</script>
<script>
window.dataLayer = window.dataLayer || [];
dataLayer.push({
  "ecommerce": {
    "detail": {
      "products": [{
        "name": "Konsola Sony PS5 Slim",
        "price": 2099.00,
        "brand": "Sony"
      }]
    }
  }
});
</script>
</head>
<body>
  <div data-omnibus-price="2499.00">
    Najniższa cena z 30 dni: 2 499,00 zł
  </div>
</body>
</html>
"""


def test_schema_json_ld_extraction():
    data = extract_schema_json_ld(SAMPLE_HTML)
    assert data["title"] == "Konsola Sony PS5 Slim"
    assert data["price"] == 2099.0
    assert data["ean"] == "0711719577232"
    assert data["in_stock"] is True


def test_omnibus_price_extraction():
    omni = extract_omnibus_price(SAMPLE_HTML)
    assert omni == 2499.0


def test_datalayer_extraction():
    gtm = extract_datalayer(SAMPLE_HTML)
    assert gtm["brand"] == "Sony"
    assert gtm["price"] == 2099.0


def test_full_microdata_fair_discount():
    res = extract_product_microdata(SAMPLE_HTML)
    assert res.ean == "0711719577232"
    assert res.current_price == 2099.0
    assert res.omnibus_price == 2499.0
    assert res.fair_discount_pct == 16.0  # (2499 - 2099) / 2499 * 100
    assert not res.is_fake_discount
