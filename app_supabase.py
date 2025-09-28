"""
Application Flask optimisée avec Supabase Auth et panier utilisateur
Version corrigée - toutes les fonctionnalités préservées
"""
import os
import json
import stripe
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from threading import Thread
from datetime import datetime
from urllib.parse import quote_plus, unquote_plus

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from dotenv import load_dotenv

# Configuration
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")

# Constantes globales
CONFIG = {
    'STRIPE_SECRET_KEY': os.getenv("STRIPE_SECRET_KEY"),
    'STRIPE_WEBHOOK_SECRET': os.getenv("STRIPE_WEBHOOK_SECRET"),
    'APP_BASE_URL': os.getenv("BASE_URL", "http://127.0.0.1:5000"),
    'SMTP_SERVER': os.getenv("SMTP_SERVER", "smtp.gmail.com"),
    'SMTP_PORT': int(os.getenv("SMTP_PORT", 587)),
    'SMTP_USER': os.getenv("SMTP_USER"),
    'SMTP_PASS': os.getenv("SMTP_PASS"),
    'SUPPLIER_EMAIL': os.getenv("SUPPLIER_EMAIL"),
    'COMMISSION_RATE': float(os.getenv("COMMISSION_RATE", 0.15)),
    'PRICE_MULTIPLIER': float(os.getenv("PRICE_MULTIPLIER", "2.0"))
}

stripe.api_key = CONFIG['STRIPE_SECRET_KEY']

# Import CORRECT du scraper et Supabase
from supabase_client import supabase, register_user, login_user, get_user_client, verify_token
from scraper import get_categories, get_category_products, get_product_details, reload_overrides, safe_get
import scraper as scraper_module

print(f"🔧 Configuration chargée - Multiplicateur: {CONFIG['PRICE_MULTIPLIER']}x")

# ----------------- CACHE & OPTIMISATIONS -----------------
_cache = {'categories': None, 'last_update': 0, 'gender_sections': None}
CACHE_DURATION = 300

def get_cached_data(key, fetch_func, force_refresh=False):
    """Système de cache générique"""
    current_time = datetime.now().timestamp()
    
    if force_refresh or _cache.get(key) is None or (current_time - _cache.get('last_update', 0) > CACHE_DURATION):
        _cache[key] = fetch_func()
        _cache['last_update'] = current_time
        # Rafraîchissement async pour la prochaine fois
        if not force_refresh:
            Thread(target=lambda: get_cached_data(key, fetch_func, True), daemon=True).start()
    
    return _cache[key]

# ----------------- HELPERS OPTIMISÉES -----------------
def get_verified_user():
    """Vérifie rapidement l'utilisateur"""
    token, user_id = session.get("access_token"), session.get("user_id")
    if not token or not user_id:
        return None
    
    try:
        if verify_token(token) == user_id:
            return user_id
    except Exception:
        session.clear()
    return None

def get_cart_data(user_id):
    """Récupère le panier avec seulement les colonnes nécessaires"""
    try:
        res = supabase.table("carts").select("id,product_name,price,qty,size,product_image").eq("user_id", user_id).execute()
        return res.data or []
    except Exception as e:
        print(f"Erreur panier: {e}")
        return []

def calculate_total(cart_items):
    """Calcule le total du panier"""
    return sum(float(item.get('price', 0) or 0) * int(item.get('qty', 1) or 1) for item in cart_items)

# ----------------- CONTEXT PROCESSOR UNIFIÉ -----------------
@app.context_processor
def inject_global_data():
    """Injecte toutes les données globales en une seule passe"""
    user_id = get_verified_user()
    cart_count = len(get_cart_data(user_id)) if user_id else 0
    
    return {
        'base_path': '/',
        'cart_count': cart_count,
        'user_id': user_id,
        'user_email': session.get('user_email'),
        'sections': get_gender_sections(),
        'price_multiplier': CONFIG['PRICE_MULTIPLIER'],
        'categories': get_categories() or {'headers': [], 'brands': []}
    }

# ----------------- FONCTIONS MÉTIERS CORRIGÉES -----------------
def get_gender_sections():
    """Récupère les sections par genre - VERSION CORRECTE"""
    pages = {
        "homme": "/Chaussures-Homme-c100.html",
        "femme": "/Chaussures-Femme-c101.html",
        "enfant": "/Chaussures-Enfant-c102.html",
    }
    out = {}
    scraper_base = getattr(scraper_module, "BASE_URL", "https://www.destockenligne.com")
    
    for key, path in pages.items():
        try:
            html = safe_get(scraper_module._normalize_href(path, base=scraper_base))
            soup = scraper_module.BeautifulSoup(html, "html.parser")
            div = soup.find("div", id="prohref")
            items = []
            if div:
                for a in div.find_all("a", href=True):
                    name = a.get("title") or a.get_text(strip=True)
                    href = a["href"]
                    if href.startswith("http"):
                        parsed = scraper_module.urlparse(href)
                        href = parsed.path or href
                        if parsed.query:
                            href += "?" + parsed.query
                    image = None
                    img = a.find("img")
                    if img and img.get("src"):
                        image = img.get("src")
                        if image and not image.startswith("http"):
                            image = scraper_module.urljoin(scraper_base, image)
                    
                    # Récupérer le prix original
                    price_text = ""
                    price_span = a.find_previous("span", class_=lambda x: x and "price" in x.lower()) or a.find_next("span", class_=lambda x: x and "price" in x.lower())
                    if price_span:
                        price_text = price_span.get_text(strip=True)
                    
                    # Appliquer le multiplicateur
                    if price_text:
                        try:
                            clean_price = price_text.replace('€', '').replace(',', '.').strip()
                            price_value = float(clean_price) if clean_price else 0.0
                            multiplied_price = price_value * CONFIG['PRICE_MULTIPLIER']
                            display_price = f"€ {multiplied_price:.2f}"
                        except (ValueError, TypeError):
                            display_price = price_text
                    else:
                        display_price = ""
                    
                    items.append({
                        "name": name, 
                        "path": href, 
                        "image": image,
                        "display_price": display_price,
                        "original_price": price_text
                    })
            out[key] = items
        except Exception as e:
            print(f"get_gender_sections error for {key}: {e}")
            out[key] = []
    return out

def process_order_payment(user_id, cart_items):
    """Traite le paiement et crée la session Stripe"""
    if not cart_items:
        raise ValueError("Panier vide")
    
    line_items, total = [], 0.0
    for item in cart_items:
        price, qty = float(item.get('price', 0) or 0), int(item.get('qty', 1) or 1)
        total += price * qty
        line_items.append({
            "price_data": {
                "currency": "eur",
                "product_data": {"name": item.get("product_name", "Produit")},
                "unit_amount": int(price * 100),
            },
            "quantity": qty
        })
    
    # Ajouter la commission
    commission = int(total * CONFIG['COMMISSION_RATE'] * 100)
    if commission > 0:
        line_items.append({
            "price_data": {
                "currency": "eur",
                "product_data": {"name": f"Commission ({int(CONFIG['COMMISSION_RATE']*100)}%)"},
                "unit_amount": commission,
            },
            "quantity": 1
        })
    
    return stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="payment",
        line_items=line_items,
        success_url=f"{CONFIG['APP_BASE_URL']}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{CONFIG['APP_BASE_URL']}/checkout/cancel",
        metadata={"user_id": user_id, "commission_rate": str(CONFIG['COMMISSION_RATE'])},
        shipping_address_collection={"allowed_countries": os.getenv("ALLOWED_SHIPPING_COUNTRIES", "FR").split(",")},
        customer_email=session.get("user_email")
    )

def send_order_email(order_data):
    """Envoie l'email de commande optimisé"""
    if not CONFIG['SMTP_USER'] or not CONFIG['SMTP_PASS']:
        print("❌ Configuration SMTP manquante")
        return False
    
    try:
        items_text = "\n".join([
            f"- {item.get('qty', 1)} x {item.get('product_name', 'Produit')} ({item.get('size', '')}) - {float(item.get('price', 0)):.2f}€"
            for item in order_data.get('items', [])
        ])
        
        body = f"""
Nouvelle commande - {order_data.get('stripe_session_id', 'N/A')}
Client: {order_data.get('customer_email', 'Non renseigné')}
Total: {order_data.get('total_amount', 0):.2f}€
Commission: {order_data.get('commission_amount', 0):.2f}€

Articles:
{items_text}

Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """.strip()
        
        msg = MIMEMultipart()
        msg["From"] = CONFIG['SMTP_USER']
        msg["To"] = CONFIG['SUPPLIER_EMAIL'] or order_data.get('customer_email')
        msg["Subject"] = f"Commande {order_data.get('stripe_session_id', '')}"
        msg.attach(MIMEText(body, "plain"))
        
        with smtplib.SMTP(CONFIG['SMTP_SERVER'], CONFIG['SMTP_PORT'], timeout=10) as server:
            server.starttls()
            server.login(CONFIG['SMTP_USER'], CONFIG['SMTP_PASS'])
            server.send_message(msg)
        
        print("✅ Email envoyé")
        return True
    except Exception as e:
        print(f"❌ Erreur email: {e}")
        return False

# ----------------- ROUTES PRINCIPALES CORRIGÉES -----------------
@app.route("/")
def home():
    gender = request.args.get("gender", "all")
    categories = get_categories() or {'headers': [], 'brands': []}
    sections = get_gender_sections()
    all_products = []

    GENDER_PATHS = {
        "homme": "/Chaussures-Homme-c100.html",
        "femme": "/Chaussures-Femme-c101.html",
        "enfant": "/Chaussures-Enfant-c102.html",
    }

    if gender == "all":
        for g in ["homme", "femme", "enfant"]:
            path = GENDER_PATHS.get(g)
            try:
                products, _ = get_category_products(path, 1)
                all_products.extend(products[:4])
            except Exception as e:
                print(f"Error loading {g} products: {e}")
    else:
        if gender in GENDER_PATHS:
            try:
                path = GENDER_PATHS[gender]
                products, _ = get_category_products(path, 1)
                all_products = products[:12]
            except Exception as e:
                print(f"Error loading {gender} products: {e}")

    return render_template("home.html", categories=categories, sections=sections, 
                         gender=gender, products=all_products)

@app.route("/category")
def category():
    path = request.args.get("path")
    if not path:
        return redirect(url_for("home"))
    
    path = unquote_plus(path)
    page = max(1, int(request.args.get("page", 1)))
    
    try:
        products, paging = get_category_products(path, page)
    except Exception as e:
        print(f"category route error: {e}")
        products, paging = [], {'current': page, 'total': 1, 'has_next': False, 'has_prev': page > 1}
    
    categories = get_categories() or {'headers': [], 'brands': []}
    return render_template("category.html", categories=categories, products=products, 
                         category_path=path, category_path_enc=quote_plus(path), paging=paging)

@app.route("/product")
def product():
    path = request.args.get("path")
    if not path:
        return redirect(url_for("home"))
    
    path = unquote_plus(path)
    product_data = get_product_details(path) or {}
    
    categories = get_categories() or {'headers': [], 'brands': []}
    sections = get_gender_sections()
    return render_template("product.html", categories=categories, product=product_data, sections=sections)

@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return redirect(url_for("home"))

    categories = get_categories() or {"headers": [], "brands": []}
    all_products = []

    search_paths = [
        "/Chaussures-Homme-c100.html",
        "/Chaussures-Femme-c101.html",
        "/Chaussures-Enfant-c102.html"
    ]

    for path in search_paths:
        for page in range(1, 3):  # Limité à 2 pages pour la performance
            try:
                products, paging = get_category_products(path, page)
                all_products.extend(products)
                if not paging.get('has_next', False):
                    break
            except Exception as e:
                print(f"Error searching in {path} page {page}: {e}")
                break

    # Filtrer les produits
    query_terms = query.lower().split()
    results = []

    for product in all_products:
        product_name = product.get("name", "").lower()
        
        if query.lower() in product_name:
            results.append(product)
            continue
            
        match_count = sum(1 for term in query_terms if len(term) > 2 and term in product_name)
        if match_count > 0:
            results.append(product)

    # Éviter les doublons
    seen_names = set()
    unique_results = []
    for product in results:
        if product.get('name') not in seen_names:
            seen_names.add(product.get('name'))
            unique_results.append(product)

    return render_template("search.html", 
                         categories=categories, 
                         results=unique_results, 
                         query=query, 
                         results_count=len(unique_results))

# ----------------- AUTHENTIFICATION -----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        try:
            res = register_user(email, password)
            if getattr(res, "user", None):
                flash('✅ Inscription réussie! Vous pouvez maintenant vous connecter.', 'success')
                return redirect(url_for("login"))
            error = "Erreur d'inscription, veuillez réessayer."
        except Exception as e:
            if "User already registered" in str(e):
                error = "Cet email est déjà enregistré. Veuillez vous connecter."
            else:
                error = f"Erreur: {e}"
    return render_template("register.html", error=error)

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        try:
            res = login_user(email, password)
            if getattr(res, "session", None):
                session["access_token"] = res.session.access_token
                session["user_id"] = res.user.id
                session["user_email"] = res.user.email
                flash('✅ Connexion réussie!', 'success')
                return redirect(url_for("home"))
            error = "Échec de connexion"
        except Exception as e:
            if "Invalid login credentials" in str(e):
                error = "Email ou mot de passe incorrect."
            else:
                error = f"Erreur: {e}"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    flash('✅ Déconnexion réussie!', 'success')
    return redirect(url_for("home"))

# ----------------- GESTION DU PANIER -----------------
@app.route("/cart")
def cart_view():
    user_id = get_verified_user()
    if not user_id:
        flash('❌ Veuillez vous connecter pour voir votre panier', 'error')
        return redirect(url_for("login"))

    try:
        cart = get_cart_data(user_id)
        total = calculate_total(cart)
        categories = get_categories() or {'headers': [], 'brands': []}
        return render_template("cart.html", categories=categories, cart=cart, total=total)
    except Exception as e:
        print(f"DEBUG - Cart view error: {e}")
        return render_template("cart.html", cart=[], total=0, error="Erreur lors du chargement du panier")

@app.route("/cart/add", methods=["POST"])
def cart_add():
    user_id = get_verified_user()
    if not user_id:
        flash('❌ Veuillez vous connecter pour ajouter au panier', 'error')
        return redirect(url_for("login"))

    data = request.form
    print(f"DEBUG - Données reçues: {dict(data)}")  # Debug
    
    try:
        # Validation des données requises
        if not data.get('name') or not data.get('price'):
            flash('❌ Données produit manquantes', 'error')
            return redirect(request.referrer or url_for('home'))

        # Conversion du prix
        price_str = data.get('price', '0').replace('€', '').replace(',', '.').strip()
        try:
            price = float(price_str) if price_str else 0.0
        except ValueError:
            price = 0.0

        # Conversion de la quantité
        try:
            qty = int(data.get('qty', 1))
        except ValueError:
            qty = 1

        cart_item = {
            "user_id": user_id,
            "product_name": data.get('name'),
            "path": data.get('path', ''),
            "product_image": data.get('image', ''),
            "price": price,
            "qty": qty,
            "size": data.get('size', 'Unique')
        }

        print(f"DEBUG - Insertion panier: {cart_item}")  # Debug

        # Insertion dans Supabase
        result = supabase.table("carts").insert(cart_item).execute()
        
        if hasattr(result, 'error') and result.error:
            flash('❌ Erreur base de données lors de l\'ajout', 'error')
            print(f"DEBUG - Erreur Supabase: {result.error}")
        else:
            flash('✅ Produit ajouté au panier!', 'success')

    except Exception as e:
        print(f"DEBUG - Error adding to cart: {e}")
        flash(f'❌ Erreur: {str(e)}', 'error')

    return redirect(request.referrer or url_for('home'))

    data = request.form
    try:
        cart_item = {
            "user_id": user_id,
            "product_name": data.get('name'),
            "path": data.get('path', ''),
            "product_image": data.get('image', ''),
            "price": float(data.get('price', '0').replace('€', '').replace(',', '.')) or 0.0,
            "qty": int(data.get('qty', 1)) or 1,
            "size": data.get('size', '')
        }
        
        supabase.table("carts").insert(cart_item).execute()
        flash('✅ Produit ajouté au panier!', 'success')
    except Exception as e:
        flash(f'❌ Erreur: {str(e)}', 'error')
    
    return redirect(request.referrer or url_for('home'))

@app.route("/cart/remove/<item_id>", methods=["POST"])
def cart_remove(item_id):
    user_id = get_verified_user()
    if not user_id:
        flash('❌ Veuillez vous connecter', 'error')
        return redirect(url_for("login"))
    
    try:
        supabase.table("carts").delete().eq("id", item_id).eq("user_id", user_id).execute()
        flash('✅ Produit retiré du panier', 'success')
    except Exception as e:
        flash('❌ Erreur lors de la suppression', 'error')
    return redirect(url_for('cart_view'))

@app.route("/cart/clear", methods=["POST"])
def cart_clear():
    user_id = get_verified_user()
    if not user_id:
        flash('❌ Veuillez vous connecter', 'error')
        return redirect(url_for("login"))
    
    try:
        supabase.table("carts").delete().eq("user_id", user_id).execute()
        flash('✅ Panier vidé', 'success')
    except Exception as e:
        flash('❌ Erreur lors du vidage du panier', 'error')
    return redirect(url_for('cart_view'))

# ----------------- CHECKOUT -----------------
@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    user_id = get_verified_user()
    if not user_id:
        return jsonify({"error": "non connecté"}), 403

    try:
        cart_items = get_cart_data(user_id)
        if not cart_items:
            flash('❌ Votre panier est vide', 'error')
            return redirect(url_for('cart_view'))

        session_stripe = process_order_payment(user_id, cart_items)
        return redirect(session_stripe.url, code=303)
    except Exception as e:
        print(f"DEBUG - Stripe error: {e}")
        flash('❌ Erreur lors de la création de la session de paiement', 'error')
        return redirect(url_for('cart_view'))

@app.route("/checkout/success")
def checkout_success():
    user_id = get_verified_user()
    if not user_id or not (session_id := request.args.get("session_id")):
        return redirect(url_for("home"))

    try:
        session_stripe = stripe.checkout.Session.retrieve(session_id)
        if session_stripe.payment_status not in ('paid', 'unpaid'):
            return redirect(url_for('checkout_cancel'))
        
        cart_items = get_cart_data(user_id)
        total = calculate_total(cart_items)
        commission = total * CONFIG['COMMISSION_RATE']
        
        order_data = {
            "user_id": user_id,
            "stripe_session_id": session_id,
            "total_amount": total,
            "commission_rate": CONFIG['COMMISSION_RATE'],
            "commission_amount": commission,
            "status": "paid",
            "items": cart_items,
            "customer_email": getattr(session_stripe.customer_details, 'email', None) if session_stripe.customer_details else session.get("user_email")
        }
        
        # Sauvegarde commande
        try:
            supabase.table("orders").insert(order_data).execute()
        except Exception as e:
            print(f"Erreur sauvegarde commande: {e}")
            # Sauvegarde de fallback...
        
        # Envoi email async
        Thread(target=send_order_email, args=(order_data,), daemon=True).start()
        
        # Vider le panier
        supabase.table("carts").delete().eq("user_id", user_id).execute()
        
        return render_template("success.html", order=order_data)
    except Exception as e:
        print(f"DEBUG - Checkout success error: {e}")
        return redirect(url_for('home'))

@app.route("/checkout/cancel")
def checkout_cancel():
    return render_template("cancel.html")

# ----------------- ROUTES DE TEST -----------------
@app.route("/test-email")
def test_email():
    """Route pour tester l'envoi d'email"""
    try:
        test_order = {
            "stripe_session_id": "test_123",
            "items": [
                {"product_name": "Produit Test", "price": 50, "qty": 1, "size": "42"}
            ],
            "total_amount": 50,
            "commission_amount": 7.5,
            "customer_email": CONFIG['SMTP_USER']
        }

        success = send_order_email(test_order)
        if success:
            return "✅ Email de test envoyé avec succès!"
        else:
            return "❌ Échec de l'envoi d'email"
    except Exception as e:
        return f"❌ Erreur: {str(e)}"

@app.route("/test-database")
def test_database():
    """Route pour tester la connexion à la base de données"""
    try:
        res = supabase.table("carts").select("*").execute()
        carts_count = len(res.data) if res.data else 0
        return f"""
        <h1>Test Base de Données</h1>
        <p>✅ Connexion Supabase: OK</p>
        <p>✅ Table carts: OK ({carts_count} éléments)</p>
        <p><strong>Multiplicateur de prix actuel: {CONFIG['PRICE_MULTIPLIER']}x</strong></p>
        """
    except Exception as e:
        return f"❌ Erreur base de données: {str(e)}"

# ----------------- WEBHOOK -----------------
@app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, CONFIG['STRIPE_WEBHOOK_SECRET'])
    except Exception as e:
        print("Webhook error (signature):", e)
        return "", 400

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        Thread(target=process_webhook_order, args=(session_obj,), daemon=True).start()

    return "", 200

def process_webhook_order(session_obj):
    """Traitement async des webhooks"""
    try:
        user_id = session_obj.metadata.get("user_id")
        if user_id:
            cart_items = get_cart_data(user_id)
            total = calculate_total(cart_items)
            
            order_data = {
                "user_id": user_id,
                "stripe_session_id": session_obj.id,
                "total_amount": total,
                "commission_rate": CONFIG['COMMISSION_RATE'],
                "commission_amount": total * CONFIG['COMMISSION_RATE'],
                "status": "paid",
                "items": cart_items,
                "customer_email": getattr(session_obj.customer_details, 'email', None)
            }
            
            supabase.table("orders").insert(order_data).execute()
            send_order_email(order_data)
            supabase.table("carts").delete().eq("user_id", user_id).execute()
    except Exception as e:
        print(f"Webhook error: {e}")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")