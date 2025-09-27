"""
Scraper pour https://www.destockenligne.com
------------------------------------------
Version corrigée pour gérer correctement les pages catégories vs produits
"""
import requests
from bs4 import BeautifulSoup
from functools import lru_cache
from urllib.parse import urljoin, urlparse
import re
import json
import os as _os
import os  # Ajout pour les variables d'environnement

# ----------------- Configuration -----------------
BASE_URL = "https://www.destockenligne.com"

# Multiplicateur de prix depuis les variables d'environnement
PRICE_MULTIPLIER = float(os.environ.get('PRICE_MULTIPLIER', '1.0'))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

session = requests.Session()
session.headers.update(HEADERS)

OVERRIDES_FILE = _os.path.join(_os.path.dirname(__file__), "overrides.json")
try:
    if _os.path.exists(OVERRIDES_FILE):
        with open(OVERRIDES_FILE, "r", encoding="utf-8") as _f:
            OVERRIDES = json.load(_f)
    else:
        OVERRIDES = {}
except Exception as _e:
    print("Error loading overrides.json:", _e)
    OVERRIDES = {}


def _apply_price_multiplier(price_value, price_text):
    """Applique le multiplicateur de prix et retourne le nouveau prix formaté"""
    if price_value > 0:
        new_price_value = price_value * PRICE_MULTIPLIER
        return f"€ {new_price_value:.2f}", new_price_value
    return price_text, price_value


def _normalize_override_image(img):
    if not img:
        return None
    if img.startswith("http://") or img.startswith("https://") or img.startswith("/"):
        return img
    return "/static/custom/" + img


def apply_overrides_to_product(product):
    key = product.get("path") or product.get("url") or ""
    if key.startswith("http"):
        try:
            key = urlparse(key).path or key
        except Exception:
            pass
    candidates = [key, key.lstrip("/")]
    ov = None
    for c in candidates:
        if c in OVERRIDES:
            ov = OVERRIDES[c]
            break

    if not ov:
        # NE PAS appliquer le multiplicateur ici - il est déjà appliqué dans _extract_products_from_category_soup
        return product

    if ov.get("hidden"):
        return None

    if "price" in ov:
        product["new_price_override"] = ov["price"]
        product["new_price"] = ov["price"]
        # Pour les overrides de prix, on ne multiplie pas
    else:
        # Pour les produits avec override mais sans prix override, appliquer le multiplicateur
        if product.get("price_value", 0) > 0:
            product["new_price"], product["price_value"] = _apply_price_multiplier(
                product["price_value"], product["new_price"]
            )

    if "image" in ov:
        product["image_override"] = _normalize_override_image(ov["image"])
        product["image"] = product["image_override"]

    if "images" in ov and isinstance(ov["images"], list) and len(ov["images"]) > 0:
        normalized = []
        for im in ov["images"]:
            ni = _normalize_override_image(im)
            if ni:
                normalized.append(ni)
        if normalized:
            product["_ov_images"] = normalized[:]
            product["image_override"] = normalized[0]
            product["image"] = normalized[0]

    return product


def reload_overrides():
    global OVERRIDES
    try:
        if _os.path.exists(OVERRIDES_FILE):
            with open(OVERRIDES_FILE, "r", encoding="utf-8") as _f:
                OVERRIDES = json.load(_f)
        else:
            OVERRIDES = {}
    except Exception as e:
        print("reload_overrides error:", e)


def safe_get(url, timeout=12):
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


@lru_cache(maxsize=128)
def get_categories():
    try:
        html = safe_get(BASE_URL + "/")
        soup = BeautifulSoup(html, "html.parser")

        sidebar = soup.select_one("div.sideBar_left") or soup.select_one("#leftsideBar")
        headers = []
        brands = []
        if sidebar:
            headers = [h.get_text(strip=True) for h in sidebar.select(".insort0")]
            brands = []
            last_header = ""
            for el in sidebar.find_all(recursive=False):
                for h in el.select(".insort0"):
                    last_header = h.get_text(strip=True)
                for a in el.select(".insort1 a"):
                    href = a.get("href")
                    title = a.get_text(strip=True)
                    if href and title:
                        brands.append({"title": title, "path": href, "header": last_header})
        return {"headers": headers, "brands": brands}
    except Exception as e:
        print("get_categories error:", e)
        return {"headers": [], "brands": []}


def _normalize_href(href, base=BASE_URL):
    if not href:
        return None
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return urljoin(base, href.lstrip("/"))


def _extract_products_from_category_soup(soup):
    products = []
    for ul in soup.select("ul.re00"):
        try:
            img_tag = ul.select_one("li.hw1 img")
            info_a = ul.select_one("li.hw2 a")
            old_price_tag = ul.select_one("li.hw2 s")
            spans = ul.select("li.hw2 span")
            new_price_tag = spans[0] if spans else None

            econ = ""
            for sp in spans:
                if "Economie" in sp.get_text():
                    econ = sp.get_text(strip=True)
                    break
            if not econ and len(spans) >= 2:
                econ = spans[-1].get_text(strip=True)

            name = info_a.get_text(strip=True) if info_a else ""
            href = info_a.get("href") if info_a else None

            # Extraire le prix correctement
            new_price_text = new_price_tag.get_text(strip=True) if new_price_tag else ""
            # Nettoyer le prix - supprimer les caractères non numériques sauf , et .
            if new_price_text:
                # Garder seulement les chiffres, points et virgules
                price_clean = re.sub(r'[^\d,.]', '', new_price_text)
                # Remplacer la virgule par un point pour conversion float
                price_clean = price_clean.replace(',', '.')
                try:
                    price_value = float(price_clean) if price_clean else 0.0
                    # Appliquer le multiplicateur de prix UNE SEULE FOIS
                    formatted_price = f"€ {price_value * PRICE_MULTIPLIER:.2f}"
                    price_value *= PRICE_MULTIPLIER  # Mettre à jour la valeur numérique
                except ValueError:
                    price_value = 0.0
                    formatted_price = new_price_text
            else:
                price_value = 0.0
                formatted_price = ""

            prod = {
                "name": name,
                "path": href,
                "url": _normalize_href(href),
                "image": _normalize_href(img_tag["src"]) if img_tag and img_tag.get("src") else None,
                "old_price": old_price_tag.get_text(strip=True) if old_price_tag else "",
                "new_price": formatted_price,
                "price_value": price_value,  # Valeur numérique pour le calcul
                "economy": econ,
            }

            prod = apply_overrides_to_product(prod)
            if prod:
                products.append(prod)
        except Exception as e:
            print(f"Error extracting product: {e}")
            continue
    return products


def is_category_page(soup):
    """Détermine si la page est une page de catégorie (liste de produits)"""
    return bool(soup.select("ul.re00"))


def is_product_page(soup):
    """Détermine si la page est une page de produit détaillé"""
    return bool(soup.select("div.views_pics, a#zoom1, select[name='hw_sizeone']"))


@lru_cache(maxsize=256)
def get_category_products(path, page=1):
    try:
        if page <= 1:
            page_path = path
        else:
            base = path.split(".html")[0]
            base = re.sub(r"_[0-9]+$", "", base)
            page_path = f"{base}_{page}.html"

        html = safe_get(_normalize_href(page_path))
        soup = BeautifulSoup(html, "html.parser")
        products = _extract_products_from_category_soup(soup)

        paging = {"current": page, "total": None, "has_next": False, "has_prev": False}
        showpage = soup.select_one("#showpage") or soup.find(class_="showpage")
        if showpage:
            sel = showpage.find("select")
            if sel:
                try:
                    opts = sel.find_all("option")
                    paging["total"] = int(opts[-1].get("value", len(opts)))
                except Exception:
                    pass
            text = showpage.get_text(" ", strip=True)
            m = re.search(r"(\d+)\s*Page", text)
            if m:
                paging["total"] = int(m.group(1))
        if paging["total"] and page < paging["total"]:
            paging["has_next"] = True
        if page > 1:
            paging["has_prev"] = True

        return products, paging
    except Exception as e:
        print("get_category_products error:", e)
        return [], {"current": page, "total": None, "has_next": False, "has_prev": page > 1}


@lru_cache(maxsize=512)
def get_product_details(path):
    try:
        html = safe_get(_normalize_href(path))
        soup = BeautifulSoup(html, "html.parser")

        # Vérifier si c'est une page de catégorie déguisée en produit
        if is_category_page(soup) and not is_product_page(soup):
            # C'est une catégorie, retourner les produits
            products = _extract_products_from_category_soup(soup)
            return {
                "is_category": True,
                "category_title": soup.select_one("div#bar b").get_text(strip=True) if soup.select_one("div#bar b") else "Catégorie",
                "products": products,
                "path": path
            }

        # Sinon, traiter comme un produit normal
        title_tag = soup.select_one("div.h_name") or soup.select_one("#bar b") or soup.select_one("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        main_img = None
        img_tag = (
            soup.select_one("div.views_pics img")
            or soup.select_one("a#zoom1 img")
            or soup.select_one("img.abc")
            or soup.select_one("img[src*='/pic/']")
        )
        if img_tag and img_tag.get("src"):
            main_img = _normalize_href(img_tag["src"])

        thumbs = []
        for img in soup.select("div.views_samll img"):
            src = img.get("src")
            if src:
                thumbs.append(_normalize_href(src))

        old_price_tag = soup.select_one("s")
        new_price_tag = soup.select_one("b[style]") or soup.select_one("b")
        old_price = old_price_tag.get_text(strip=True) if old_price_tag else ""
        new_price_text = new_price_tag.get_text(strip=True) if new_price_tag else ""

        # Nettoyer le prix et appliquer le multiplicateur UNE SEULE FOIS
        if new_price_text:
            price_clean = re.sub(r'[^\d,.]', '', new_price_text)
            price_clean = price_clean.replace(',', '.')
            try:
                price_value = float(price_clean) if price_clean else 0.0
                # Appliquer le multiplicateur
                new_price = f"€ {price_value * PRICE_MULTIPLIER:.2f}"
                price_value *= PRICE_MULTIPLIER
            except ValueError:
                price_value = 0.0
                new_price = new_price_text
        else:
            price_value = 0.0
            new_price = ""

        sizes = []
        sel = soup.select_one("select[name='hw_sizeone']") or soup.select_one("select[name='hw_size']")
        if sel:
            for opt in sel.select("option"):
                val = opt.get("value")
                if val and val.strip() and val != "Taille":
                    sizes.append(val.strip())

        qty_options = list(range(1, 21))

        related = _extract_products_from_category_soup(soup)
        related = [r for r in related if r]

        desc_tag = soup.select_one("#Content .con_bot") or soup.select_one("div#Content") or soup.select_one("div.product_description")
        description = desc_tag.get_text("\n", strip=True) if desc_tag else ""

        result = {
            "is_category": False,
            "title": title,
            "main_img": main_img,
            "thumbs": thumbs,
            "old_price": old_price,
            "new_price": new_price,
            "price_value": price_value,
            "sizes": sizes if sizes else ["Unique"],
            "qty_options": qty_options,
            "related": related,
            "description": description,
            "path": path,
            "url": _normalize_href(path),
        }

        candidates = [path, path.lstrip("/")]
        ov = None
        for c in candidates:
            if c in OVERRIDES:
                ov = OVERRIDES[c]
                break

        if ov:
            if ov.get("hidden"):
                return {}
            if "price" in ov:
                result["new_price_override"] = ov["price"]
                result["new_price"] = ov["price"]
                # Pour les overrides de prix, on ne multiplie pas
            # NE PAS réappliquer le multiplicateur ici car il est déjà appliqué
                    
            if "image" in ov:
                img = _normalize_override_image(ov["image"])
                if img:
                    result["main_img"] = img
            if "images" in ov and isinstance(ov["images"], list) and len(ov["images"]) > 0:
                normalized = []
                for im in ov["images"]:
                    ni = _normalize_override_image(im)
                    if ni:
                        normalized.append(ni)
                if normalized:
                    result["main_img"] = normalized[0]
                    new_thumbs = normalized[1:] if len(normalized) > 1 else []
                    for t in thumbs:
                        if t not in new_thumbs:
                            new_thumbs.append(t)
                    result["thumbs"] = new_thumbs
        # NE PAS appliquer le multiplicateur ici non plus car il est déjà appliqué

        return result
    except Exception as e:
        print("get_product_details error:", e)
        return {}


if __name__ == "__main__":
    print(f"PRICE_MULTIPLIER = {PRICE_MULTIPLIER}")
    print("Test get_categories()")
    print(get_categories())
    print("\nTest get_category_products('/Chaussures-Homme-c100.html') (premiers 5 produits)")
    prods, paging = get_category_products("/Chaussures-Homme-c100.html", page=1)
    print("paging:", paging)
    for p in prods[:5]:
        print(" -", p.get("name"), p.get("path"), p.get("new_price"))
    print("\nTest get_product_details('/Nike-Tn-Requin-s301.html')")
    result = get_product_details("/Nike-Tn-Requin-s301.html")
    if result.get("is_category"):
        print("C'est une catégorie avec", len(result.get("products", [])), "produits")
    else:
        print("C'est un produit unique")
        print("Prix:", result.get("new_price"))