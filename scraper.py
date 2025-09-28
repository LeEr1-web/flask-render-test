"""
Scraper optimisé pour destockenligne.com - Extraction complète
"""
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
import os
import time
from functools import lru_cache

# Configuration
BASE_URL = "https://www.destockenligne.com"
PRICE_MULTIPLIER = float(os.getenv('PRICE_MULTIPLIER', '2.0'))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.8,en-US;q=0.5,en;q=0.3",
}

session = requests.Session()
session.headers.update(HEADERS)

# Cache
PRODUCT_CACHE = {}
CACHE_DURATION = 300

# ----------------- FONCTIONS DE BASE -----------------
def safe_get(url, timeout=12):
    """Récupère le contenu HTML avec gestion d'erreurs améliorée"""
    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"Erreur requête {url}: {e}")
        return ""

def _normalize_href(href, base=BASE_URL):
    """Normalise les URLs"""
    if not href:
        return None
    if href.startswith(('http://', 'https://')):
        return href
    return urljoin(base, href.lstrip('/'))

def _extract_price(price_text):
    """Extrait et applique le multiplicateur de prix de manière robuste"""
    if not price_text:
        return 0.0, ""
    
    # Nettoyage plus agressif du texte de prix
    clean_text = re.sub(r'[^\d,]', '', price_text.strip())
    clean_text = clean_text.replace(',', '.')
    
    # Extraction du premier nombre trouvé
    price_match = re.search(r'(\d+\.?\d*)', clean_text)
    if price_match:
        try:
            price_value = float(price_match.group(1))
            final_price = price_value * PRICE_MULTIPLIER
            return final_price, f"€ {final_price:.2f}"
        except (ValueError, TypeError):
            pass
    
    return 0.0, "Prix non disponible"

# ----------------- EXTRACTION COMPLÈTE -----------------
def _extract_title_improved(soup):
    """Extrait le titre du produit de manière robuste"""
    selectors = ['div.h_name', 'h1', '.product-title', '#bar b', 'title']
    
    for selector in selectors:
        title_tag = soup.select_one(selector)
        if title_tag:
            title = title_tag.get_text(strip=True)
            if title and title not in ['', 'Détail', 'Product']:
                title = re.sub(r'^\s*-\s*', '', title)
                return title
    
    return "Produit sans nom"

def _extract_breadcrumb(soup):
    """Extrait le fil d'Ariane"""
    breadcrumb = []
    bar_div = soup.select_one("div#bar")
    if bar_div:
        # Supprimer les scripts
        for script in bar_div.select("script"):
            script.decompose()
        
        # Extraire les liens
        links = bar_div.select("a")
        for link in links:
            href = link.get("href")
            text = link.get_text(strip=True)
            if href and text:
                breadcrumb.append({
                    "text": text,
                    "path": href,
                    "url": _normalize_href(href)
                })
    
    return breadcrumb

def _extract_prohref_links(soup):
    """Extrait les liens de navigation prohref"""
    prohref_links = []
    prohref_div = soup.select_one("div#prohref")
    if prohref_div:
        for a in prohref_div.select("a"):
            href = a.get("href")
            title = a.get("title") or a.get_text(strip=True)
            if href and title:
                prohref_links.append({
                    "title": title,
                    "path": href,
                    "url": _normalize_href(href)
                })
    return prohref_links

def _extract_pagination_info(soup, current_path, current_page=1):
    """Extrait les informations de pagination complètes"""
    paging = {
        "current": current_page,
        "total": 1,
        "has_next": False,
        "has_prev": False,
        "pages": [],
        "total_items": 0,
        "display_text": "",
        "prev_url": None,
        "next_url": None
    }
    
    showpage_div = soup.select_one("div#showpage")
    if not showpage_div:
        return paging

    # Extraire le texte d'affichage
    display_text = showpage_div.get_text(" ", strip=True)
    paging["display_text"] = display_text
    
    # Extraire le nombre total d'items
    total_match = re.search(r'Total\s*<font[^>]*>(\d+)</font>\s*item', display_text)
    if total_match:
        paging["total_items"] = int(total_match.group(1))
    
    # Extraire la pagination du select
    select = showpage_div.select_one('select[name="page"]')
    if select:
        pages = []
        for option in select.select('option'):
            try:
                page_num = int(option.get('value'))
                pages.append(page_num)
            except (ValueError, TypeError):
                continue
        if pages:
            paging["pages"] = pages
            paging["total"] = max(pages) if pages else 1
    
    # Vérifier les boutons précédent/suivant
    prev_links = showpage_div.select('a:contains("Prev")')
    next_links = showpage_div.select('a:contains("Next")')
    
    paging["has_prev"] = len(prev_links) > 0 and current_page > 1
    paging["has_next"] = len(next_links) > 0 and current_page < paging["total"]
    
    # Construire les URLs de pagination
    base_path = current_path.split('.html')[0]
    base_path = re.sub(r"_[0-9]+$", "", base_path)
    
    if paging["has_prev"]:
        prev_page = current_page - 1
        paging["prev_url"] = f"{base_path}_{prev_page}.html" if prev_page > 1 else f"{base_path}.html"
    
    if paging["has_next"]:
        next_page = current_page + 1
        paging["next_url"] = f"{base_path}_{next_page}.html"
    
    return paging

def _extract_main_image_improved(soup):
    """Extrait l'image principale"""
    img_selectors = [
        'div.views_pics img',
        'a#zoom1 img',
        'img.abc',
        '.main-image img',
        'img[src*="/pic/"]',
        'img[src*="/product/"]'
    ]
    
    for selector in img_selectors:
        img_tag = soup.select_one(selector)
        if img_tag and img_tag.get('src'):
            return _normalize_href(img_tag['src'])
    
    return None

def _extract_sizes_improved(soup):
    """Extrait les tailles disponibles"""
    size_selectors = [
        'select[name="hw_sizeone"]',
        'select[name="hw_size"]',
        '.size-select'
    ]
    
    sizes = []
    for selector in size_selectors:
        size_select = soup.select_one(selector)
        if size_select:
            for option in size_select.select('option'):
                value = option.get('value', '').strip()
                if value and value not in ['', 'Taille', 'Size']:
                    sizes.append(value)
            if sizes:
                break
    
    return sizes if sizes else ["Unique"]

def _extract_products_from_soup(soup):
    """Extrait les produits d'une page de catégorie"""
    products = []
    for ul in soup.select("ul.re00"):
        try:
            img_tag = ul.select_one("li.hw1 img")
            info_a = ul.select_one("li.hw2 a")
            old_price_tag = ul.select_one("li.hw2 s")
            spans = ul.select("li.hw2 span")
            new_price_tag = spans[0] if spans else None

            # Économie
            econ = ""
            for sp in spans:
                if "Economie" in sp.get_text():
                    econ = sp.get_text(strip=True)
                    break
            if not econ and len(spans) >= 2:
                econ = spans[-1].get_text(strip=True)

            name = info_a.get_text(strip=True) if info_a else ""
            href = info_a.get("href") if info_a else None

            # Extraction du prix
            new_price_text = new_price_tag.get_text(strip=True) if new_price_tag else ""
            price_value, formatted_price = _extract_price(new_price_text)

            products.append({
                "name": name,
                "path": href,
                "url": _normalize_href(href),
                "image": _normalize_href(img_tag["src"]) if img_tag and img_tag.get("src") else None,
                "old_price": old_price_tag.get_text(strip=True) if old_price_tag else "",
                "new_price": formatted_price,
                "price_value": price_value,
                "economy": econ,
            })
        except Exception as e:
            print(f"Erreur extraction produit: {e}")
            continue
            
    return products

# ----------------- SCRAPING PRINCIPAL AMÉLIORÉ -----------------
@lru_cache(maxsize=128)
def get_categories():
    """Récupère les catégories"""
    try:
        html = safe_get(BASE_URL + "/")
        if not html:
            return {"headers": [], "brands": []}
            
        soup = BeautifulSoup(html, "html.parser")
        sidebar = soup.select_one("div.sideBar_left") or soup.select_one("#leftsideBar")
        
        if not sidebar:
            return {"headers": [], "brands": []}
        
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
                    brands.append({
                        "title": title, 
                        "path": href, 
                        "header": last_header
                    })
        
        return {"headers": headers, "brands": brands}
    except Exception as e:
        print(f"Erreur catégories: {e}")
        return {"headers": [], "brands": []}

def get_category_products(path, page=1):
    """Récupère les produits d'une catégorie avec pagination"""
    try:
        # Construction URL paginée
        if page > 1:
            base = path.split(".html")[0]
            base = re.sub(r"_[0-9]+$", "", base)
            page_path = f"{base}_{page}.html"
        else:
            page_path = path

        html = safe_get(_normalize_href(page_path))
        if not html:
            return [], {"current": page, "total": 1, "has_next": False}
            
        soup = BeautifulSoup(html, "html.parser")
        products = _extract_products_from_soup(soup)
        
        # Pagination complète
        paging = _extract_pagination_info(soup, path, page)
        
        return products, paging
        
    except Exception as e:
        print(f"Erreur produits catégorie {path}: {e}")
        return [], {"current": page, "total": 1, "has_next": False}

def get_product_details(path, page=1):
    """Récupère les détails d'un produit - VERSION COMPLÈTE"""
    try:
        # Construction URL
        if page > 1:
            base = path.split(".html")[0]
            base = re.sub(r"_[0-9]+$", "", base)
            page_path = f"{base}_{page}.html"
        else:
            page_path = path

        full_url = _normalize_href(page_path)
        html = safe_get(full_url)
        
        if not html:
            return {}
            
        soup = BeautifulSoup(html, "html.parser")

        # Vérification type de page
        is_category = bool(soup.select("ul.re00")) and not bool(soup.select("div.views_pics, select[name='hw_sizeone']"))
        
        if is_category:
            # Extraction titre de catégorie
            category_title = ""
            bar_div = soup.select_one("div#bar")
            if bar_div:
                b_tag = bar_div.select_one("b")
                if b_tag:
                    category_title = b_tag.get_text(strip=True)
            
            return {
                "is_category": True,
                "category_title": category_title,
                "breadcrumb": _extract_breadcrumb(soup),
                "prohref_links": _extract_prohref_links(soup),
                "products": _extract_products_from_soup(soup),
                "paging": _extract_pagination_info(soup, path, page),
                "path": path
            }

        # EXTRACTION PRODUIT - VERSION COMPLÈTE
        title = _extract_title_improved(soup)
        main_img = _extract_main_image_improved(soup)
        
        # PRIX - EXTRACTION AMÉLIORÉE
        price_text = ""
        # Chercher d'abord dans les balises de prix spécifiques
        price_selectors = [
            'b[style*="color"]',
            'font[color="#FF0000"]',
            'span.price',
            'b.price',
            'b[style]',
            'b'
        ]

        for selector in price_selectors:
            price_tag = soup.select_one(selector)
            if price_tag:
                candidate_text = price_tag.get_text(strip=True)
                # Vérifier que c'est bien un prix (contient des chiffres)
                if re.search(r'\d', candidate_text):
                    price_text = candidate_text
                    break
        
        price_value, formatted_price = _extract_price(price_text)
        
        # Ancien prix
        old_price = ""
        old_price_tag = soup.select_one("s")
        if old_price_tag:
            old_price = old_price_tag.get_text(strip=True)
        
        # Tailles
        sizes = _extract_sizes_improved(soup)
        
        # Options quantité
        qty_options = list(range(1, 11))
        
        # Description
        description = ""
        desc_tag = soup.select_one("#Content .con_bot") or soup.select_one("div#Content") or soup.select_one("div.product_description")
        if desc_tag:
            description = desc_tag.get_text("\n", strip=True)

        # Produits similaires
        related = _extract_products_from_soup(soup)

        result = {
            "is_category": False,
            "title": title,
            "main_img": main_img,
            "old_price": old_price,
            "new_price": formatted_price,
            "price_value": price_value,
            "sizes": sizes,
            "qty_options": qty_options,
            "description": description,
            "related": related,
            "breadcrumb": _extract_breadcrumb(soup),
            "prohref_links": _extract_prohref_links(soup),
            "path": path,
            "url": full_url,
        }

        return result
        
    except Exception as e:
        print(f"Erreur détails produit {path}: {e}")
        return {}
# ----------------- FONCTIONS DE COMPATIBILITÉ -----------------
def reload_overrides():
    """Fonction de compatibilité"""
    pass

if __name__ == "__main__":
    print(f"🔧 Multiplicateur: {PRICE_MULTIPLIER}x")
    
    # Test avec le produit problématique
    test_path = "/Nike-Air-Max-Plus-2025-325541.html"
    print(f"Test extraction: {test_path}")
    
    product_data = get_product_details(test_path)
    if product_data:
        print(f"✅ Titre: {product_data.get('title')}")
        print(f"✅ Prix: {product_data.get('new_price')}")
        print(f"✅ Ancien prix: {product_data.get('old_price')}")
        print(f"✅ Image: {product_data.get('main_img')}")
        print(f"✅ Tailles: {product_data.get('sizes')}")
        print(f"✅ Prohref links: {len(product_data.get('prohref_links', []))}")
        print(f"✅ Breadcrumb: {len(product_data.get('breadcrumb', []))}")
    else:
        print("❌ Produit non trouvé")