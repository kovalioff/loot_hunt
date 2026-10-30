from loot_hunt.affiliate import AffiliateTransformer


def test_amazon_tag_injection_for_regions():
    transformer = AffiliateTransformer(
        amazon_tags={"pl": "loothunt-pl-21", "de": "loothunt-de-21", "uk": "loothunt-uk-21"}
    )

    # Amazon PL
    url_pl = "https://www.amazon.pl/dp/B08N5WRWNW"
    transformed_pl = transformer.transform(url_pl)
    assert transformed_pl == "https://www.amazon.pl/dp/B08N5WRWNW?tag=loothunt-pl-21"

    # Amazon DE
    url_de = "https://www.amazon.de/dp/B08N5WRWNW?psc=1"
    transformed_de = transformer.transform(url_de)
    assert "tag=loothunt-de-21" in transformed_de
    assert "psc=1" in transformed_de

    # Amazon UK
    url_uk = "https://www.amazon.co.uk/dp/B08N5WRWNW"
    transformed_uk = transformer.transform(url_uk)
    assert transformed_uk == "https://www.amazon.co.uk/dp/B08N5WRWNW?tag=loothunt-uk-21"


def test_amazon_replaces_existing_tag():
    transformer = AffiliateTransformer(amazon_tags={"de": "my-new-tag-21"})
    url = "https://www.amazon.de/dp/B08N5WRWNW?ref=xyz&tag=old-tag-20"
    transformed = transformer.transform(url)
    assert "tag=my-new-tag-21" in transformed
    assert "old-tag-20" not in transformed
    assert "ref=xyz" in transformed


def test_allegro_prefix_transformation():
    transformer = AffiliateTransformer(allegro_prefix="https://track.convertiser.com/click?url=")
    url = "https://allegro.pl/oferta/gra-xbox-12345"
    transformed = transformer.transform(url)
    assert transformed.startswith("https://track.convertiser.com/click?url=")
    assert "allegro.pl%2Foferta" in transformed


def test_awin_template_transformation():
    transformer = AffiliateTransformer(
        awin_template="https://www.awin1.com/cread.php?awinmid=123&ued={url}"
    )
    url = "https://www.mediamarkt.de/de/product/_sony-playstation-5-123.html"
    transformed = transformer.transform(url)
    assert transformed.startswith("https://www.awin1.com/cread.php?awinmid=123&ued=")
    assert "mediamarkt.de" in transformed


def test_untracked_domains_left_intact():
    transformer = AffiliateTransformer()
    url = "https://www.randomshop.eu/item/123"
    assert transformer.transform(url) == url
    assert transformer.transform(None) is None
