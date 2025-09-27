"""
Application Flask avec Supabase Auth et panier utilisateur
Version refactorisée — mêmes fonctionnalités, code simplifié et moins redondant
Multiplicateur de prix toujours appliqué
"""
import os
import json
import stripe
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from urllib.parse import quote_plus, unquote_plus, urljoin, urlparse
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from datetime import datetime

# Local imports
from supabase_client import supabase, register_user, login_user, get_user_client, verify_token
from scraper import get_categories, get_category_products, get_product_details, reload_overrides, safe_get
import scraper as scraper_module

# Charger .env
load_dotenv()

# Configuration Stripe
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
APP_BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5000")
stripe.api_key = STRIPE_SECRET_KEY

# Configuration email (SMTP)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SUPPLIER_EMAIL = os.getenv("SUPPLIER_EMAIL")

# Commission: valeur par défaut 15% si non spécifiée
COMMISSION_RATE = float(os.getenv("COMMISSION_RATE", 0.15))

# MULTIPLICATEUR DE PRIX
PRICE_MULTIPLIER = float(os.getenv("PRICE_MULTIPLIER", "2.0"))

# Flask app
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")

print(f"🔧 Configuration chargée - Multiplicateur de prix: {PRICE_MULTIPLIER}x")

# ----------------- HELPERS -----------------

def get_verified_user():
    """Vérifie le token de session et retourne user_id ou None (et clear session si invalide)"""
    if "access_token" not in session or "user_id" not in session:
        return None
    try:
        actual_user_id = verify_token(session["access_token"])
        if actual_user_id and actual_user_id == session["user_id"]:
            return session["user_id"]
        # token invalid or mismatch -> clear
        session.clear()
    except Exception as e:
        print(f"DEBUG get_verified_user error: {e}")
        session.clear()
    return None

def get_cart_items_for_user(user_id):
    try:
        res = supabase.table("carts").select("*").eq("user_id", user_id).execute()
        return res.data if getattr(res, 'data', None) else []
    except Exception as e:
        print(f"DEBUG get_cart_items_for_user error: {e}")
        return []

# ----------------- CONTEXT PROCESSOR -----------------
@app.context_processor
def inject_user_data():
    """Injecte les données utilisateur et sections dans tous les templates"""
    cart_count = 0
    user_id = get_verified_user()
    if user_id:
        try:
            cart_items = get_cart_items_for_user(user_id)
            cart_count = len(cart_items)
        except Exception as e:
            print(f"DEBUG - Error getting cart count: {e}")
            cart_count = 0

    sections = get_gender_sections()
    return dict(
        base_path='/',
        cart_count=cart_count,
        user_id=session.get('user_id'),
        sections=sections,
        price_multiplier=PRICE_MULTIPLIER
    )

# ----------------- GENDER SECTIONS -----------------
def get_gender_sections():
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
            soup = BeautifulSoup(html, "html.parser")
            div = soup.find("div", id="prohref")
            items = []
            if div:
                for a in div.find_all("a", href=True):
                    name = a.get("title") or a.get_text(strip=True)
                    href = a["href"]
                    if href.startswith("http"):
                        parsed = urlparse(href)
                        href = parsed.path or href
                        if parsed.query:
                            href += "?" + parsed.query
                    image = None
                    img = a.find("img")
                    if img and img.get("src"):
                        image = img.get("src")
                        if image and not image.startswith("http"):
                            image = urljoin(scraper_base, image)
                    
                    # Récupérer le prix original et appliquer le multiplicateur
                    price_text = ""
                    # Essayez de trouver le prix près du lien
                    price_span = a.find_previous("span", class_=lambda x: x and "price" in x.lower()) or a.find_next("span", class_=lambda x: x and "price" in x.lower())
                    if price_span:
                        price_text = price_span.get_text(strip=True)
                    
                    # Appliquer le multiplicateur
                    if price_text:
                        try:
                            clean_price = price_text.replace('€', '').replace(',', '.').strip()
                            price_value = float(clean_price) if clean_price else 0.0
                            multiplied_price = price_value * PRICE_MULTIPLIER
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

# ----------------- ROUTES -----------------
GENDER_PATHS = {
    "homme": "/Chaussures-Homme-c100.html",
    "femme": "/Chaussures-Femme-c101.html",
    "enfant": "/Chaussures-Enfant-c102.html",
}

@app.route("/")
def home():
    gender = request.args.get("gender", "all")
    categories = get_categories() or {'headers': [], 'brands': []}
    sections = get_gender_sections()
    all_products = []

    if gender == "all":
        for g in ["homme", "femme", "enfant"]:
            path = GENDER_PATHS.get(g)
            try:
                products, _ = get_category_products(path, 1)
                # PLUS BESOIN D'APPLIQUER LE MULTIPLICATEUR - C'EST DÉJÀ FAIT DANS LE SCRAPER
                all_products.extend(products[:4])
            except Exception as e:
                print(f"Error loading {g} products: {e}")
    else:
        if gender in GENDER_PATHS:
            try:
                path = GENDER_PATHS[gender]
                products, _ = get_category_products(path, 1)
                # PLUS BESOIN D'APPLIQUER LE MULTIPLICATEUR
                all_products = products[:12]
            except Exception as e:
                print(f"Error loading {gender} products: {e}")

    return render_template("home.html", categories=categories, sections=sections, gender=gender, products=all_products)

@app.route("/category")
def category():
    path = request.args.get("path")
    if not path:
        return redirect(url_for("home"))
    path = unquote_plus(path)
    try:
        page = int(request.args.get("page", "1"))
    except Exception:
        page = 1

    products = []
    paging = {'current': page, 'total': None, 'has_next': False, 'has_prev': page > 1}
    try:
        res = get_category_products(path, page)
        if isinstance(res, tuple) and len(res) == 2:
            products, paging = res
        elif isinstance(res, list):
            products = res
        # PLUS BESOIN D'APPLIQUER LE MULTIPLICATEUR
    except Exception as e:
        print(f"category route error: {e}")

    categories = get_categories() or {'headers': [], 'brands': []}
    return render_template("category.html", categories=categories, products=products, category_path=path, category_path_enc=quote_plus(path), paging=paging)

@app.route("/product")
def product():
    path = request.args.get("path")
    if not path:
        return redirect(url_for("home"))
    path = unquote_plus(path)
    product_data = get_product_details(path) or {}
    
    # PLUS BESOIN D'APPLIQUER LE MULTIPLICATEUR - C'EST DÉJÀ FAIT DANS LE SCRAPER

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
        "/Chaussures-Enfant-c102.html",
        "/Chaussures-de-Sport-Homme-c103.html",
        "/Chaussures-de-Sport-Femme-c104.html",
        "/Baskets-Homme-c105.html",
        "/Baskets-Femme-c106.html"
    ]

    for path in search_paths:
        for page in range(1, 4):
            try:
                products, paging = get_category_products(path, page)
                # PLUS BESOIN D'APPLIQUER LE MULTIPLICATEUR
                all_products.extend(products)
                if not paging.get('has_next', False):
                    break
            except Exception as e:
                print(f"Error searching in {path} page {page}: {e}")
                break
# ----------------- AUTH -----------------
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
                print(f"DEBUG - User logged in: {res.user.id}")
                flash('✅ Connexion réussie!', 'success')
                return redirect(url_for("home"))
            error = "Échec de connexion"
        except Exception as e:
            print(f"DEBUG - Login error: {e}")
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

# ----------------- CART -----------------
@app.route("/cart")
def cart_view():
    user_id = get_verified_user()
    if not user_id:
        flash('❌ Veuillez vous connecter pour voir votre panier', 'error')
        return redirect(url_for("login"))

    try:
        cart = get_cart_items_for_user(user_id)
        total = 0
        for item in cart:
            try:
                price = float(item.get('price', 0) or 0)
                qty = int(item.get('qty', 1) or 1)
                total += price * qty
            except (ValueError, TypeError):
                continue
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
    name = data.get('name')
    price_str = (data.get('price', '0') or '0').strip().replace('€', '').strip()
    try:
        price = float(price_str.replace(',', '.')) if price_str else 0.0
    except ValueError:
        price = 0.0
    try:
        qty = int(data.get('qty', '1') or 1)
    except ValueError:
        qty = 1
    size = data.get('size', '')
    image = data.get('image', '')
    path = data.get('path', '')

    cart_item = {
        "user_id": user_id,
        "product_name": name,
        "path": path,
        "product_image": image,
        "price": price,
        "qty": qty,
        "size": size
    }
    try:
        res = supabase.table("carts").insert(cart_item).execute()
        if hasattr(res, 'error') and res.error:
            print(f"DEBUG - Supabase error: {res.error}")
            flash('❌ Erreur base de données lors de l\'ajout', 'error')
        elif getattr(res, "data", None):
            flash('✅ Produit ajouté au panier!', 'success')
        else:
            flash('❌ Erreur inconnue lors de l\'ajout au panier', 'error')
    except Exception as e:
        print(f"DEBUG - Error adding to cart: {e}")
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
        print(f"DEBUG - Error removing from cart: {e}")
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
        print(f"DEBUG - Error clearing cart: {e}")
        flash('❌ Erreur lors du vidage du panier', 'error')
    return redirect(url_for('cart_view'))

# ----------------- CHECKOUT & EMAIL -----------------
@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    user_id = get_verified_user()
    if not user_id:
        return jsonify({"error": "non connecté"}), 403

    try:
        cart = get_cart_items_for_user(user_id)
        if not cart:
            flash('❌ Votre panier est vide', 'error')
            return redirect(url_for('cart_view'))

        line_items = []
        total_amount = 0.0
        for it in cart:
            price = float(it.get("price", 0) or 0)
            qty = int(it.get("qty", 1) or 1)
            total_amount += price * qty
            line_items.append({
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": it.get("product_name", "Produit")},
                    "unit_amount": int(price * 100),
                },
                "quantity": qty
            })

        commission_rate = COMMISSION_RATE
        commission_amount_cents = int(total_amount * commission_rate * 100)
        if commission_amount_cents > 0:
            line_items.append({
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": f"Commission de service ({int(commission_rate*100)}%)"},
                    "unit_amount": commission_amount_cents,
                },
                "quantity": 1
            })

        customer_email = session.get("user_email")
        try:
            user_info = supabase.auth.get_user(session["access_token"])
            if user_info and getattr(user_info, "user", None):
                customer_email = user_info.user.email or customer_email
        except Exception:
            pass

        session_stripe = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=line_items,
            success_url=f"{APP_BASE_URL}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{APP_BASE_URL}/checkout/cancel",
            metadata={
                "user_id": user_id,
                "commission_rate": str(commission_rate)
            },
            shipping_address_collection={
                "allowed_countries": os.getenv("ALLOWED_SHIPPING_COUNTRIES", "FR").split(",")
            },
            customer_email=customer_email
        )
        return redirect(session_stripe.url, code=303)
    except Exception as e:
        print(f"DEBUG - Stripe error: {e}")
        flash('❌ Erreur lors de la création de la session de paiement', 'error')
        return redirect(url_for('cart_view'))

@app.route("/checkout/success")
def checkout_success():
    user_id = get_verified_user()
    if not user_id:
        return redirect(url_for("login"))

    session_id = request.args.get("session_id")
    if not session_id:
        return redirect(url_for('home'))

    try:
        session_stripe = stripe.checkout.Session.retrieve(session_id)
        if getattr(session_stripe, "payment_status", None) in ('paid', 'unpaid'):
            cart = get_cart_items_for_user(user_id)
            customer_email = None
            shipping_address = None
            try:
                if getattr(session_stripe, "customer_details", None):
                    customer_email = session_stripe.customer_details.email
                    shipping_address = session_stripe.customer_details.address
            except Exception:
                pass

            total_amount = float(getattr(session_stripe, "amount_total", 0) or 0) / 100 if getattr(session_stripe, "amount_total", None) else sum(
                (float(it.get("price", 0) or 0) * int(it.get("qty", 1) or 1)) for it in cart
            )
            commission_rate = float(getattr(session_stripe, "metadata", {}) .get("commission_rate", COMMISSION_RATE))
            commission_amount = round(total_amount * commission_rate, 2)

            order_data = {
                "user_id": user_id,
                "stripe_session_id": session_id,
                "total_amount": total_amount,
                "commission_rate": commission_rate,
                "commission_amount": commission_amount,
                "status": "paid",
                "items": cart,
                "customer_email": customer_email,
                "shipping_address": shipping_address
            }

            # Sauvegarde commande
            try:
                print("🔧 DEBUG: Tentative d'insertion dans la table orders...")
                order_res = supabase.table("orders").insert(order_data).execute()
                if hasattr(order_res, "error") and order_res.error:
                    print(f"❌ Erreur Supabase orders: {order_res.error}")
                    backup_order_to_file(order_data)
                else:
                    print("✅ Commande enregistrée dans la base de données")
            except Exception as e:
                print(f"❌ Exception lors de l'insertion: {e}")
                backup_order_to_file(order_data)

            # Envoi e-mail
            try:
                email_sent = send_order_email_to_supplier(order_data)
                if not email_sent:
                    print("⚠️ Email non envoyé, sauvegarde dans fichier")
                    backup_order_to_file(order_data, reason="email_failed")
            except Exception as e:
                print(f"❌ Erreur envoi email: {e}")
                backup_order_to_file(order_data, reason="email_exception")

            # Vider le panier
            try:
                supabase.table("carts").delete().eq("user_id", user_id).execute()
                print("✅ Panier vidé après commande")
            except Exception as e:
                print(f"⚠️ Erreur vidage panier: {e}")

            return render_template("success.html", order=order_data)
        else:
            return redirect(url_for('checkout_cancel'))
    except Exception as e:
        print(f"DEBUG - Checkout success error: {e}")
        return redirect(url_for('home'))

def backup_order_to_file(order_data, reason="database_error"):
    """Sauvegarde la commande dans un fichier JSON en cas d'échec"""
    try:
        backup_data = {
            "timestamp": datetime.now().isoformat(),
            "reason": reason,
            "order": order_data
        }
        with open("orders_backup.json", "a", encoding="utf-8") as f:
            f.write(json.dumps(backup_data, ensure_ascii=False) + "\n")
        print(f"✅ Commande sauvegardée dans orders_backup.json (raison: {reason})")
        return True
    except Exception as e:
        print(f"❌ Erreur sauvegarde fichier: {e}")
        return False

@app.route("/checkout/cancel")
def checkout_cancel():
    return render_template("cancel.html")

def send_order_email_to_supplier(order_data):
    """
    Envoie un email au fournisseur et au client avec le détail de la commande.
    Retourne True si réussi, False sinon.
    """
    print("🔧 DEBUG: Début envoi email...")
    server = None
    try:
        subject = f"Nouvelle commande - {order_data.get('stripe_session_id', 'N/A')}"
        items = order_data.get("items", []) or []

        items_text_lines = []
        for it in items:
            try:
                qty = int(it.get("qty", 1))
            except Exception:
                qty = 1
            try:
                price = float(it.get("price", 0))
            except Exception:
                price = 0
            name = it.get("product_name", "Produit")
            size = it.get("size", "")
            size_part = f" ({size})" if size else ""
            items_text_lines.append(f"- {qty} x {name}{size_part} — {price} € chacun")

        items_text = "\n".join(items_text_lines) if items_text_lines else "Aucun article"

        customer_email = order_data.get("customer_email") or session.get("user_email") or "Non renseigné"

        shipping = order_data.get("shipping_address")
        if shipping and isinstance(shipping, dict):
            address_lines = [str(shipping.get(f)) for f in ("line1", "line2", "postal_code", "city", "state", "country") if shipping.get(f)]
            shipping_text = ", ".join(address_lines)
        else:
            shipping_text = str(shipping) if shipping else "Non renseignée"

        commission_rate = order_data.get("commission_rate", COMMISSION_RATE)
        commission_amount = order_data.get("commission_amount", 0)

        body = f"""
Nouvelle commande reçue

ID session Stripe: {order_data.get('stripe_session_id', 'N/A')}
Client: {customer_email}
Adresse de livraison: {shipping_text}

Articles:
{items_text}

Total payé: {order_data.get('total_amount', 0)} €
Commission ({int(float(commission_rate)*100)}%): {commission_amount} €

Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

⚠️ NOTE: Les prix affichés incluent déjà le multiplicateur (x{PRICE_MULTIPLIER})
"""

        msg = MIMEMultipart()
        msg["From"] = SMTP_USER or "no-reply@example.com"

        recipients = []
        if SUPPLIER_EMAIL:
            recipients.append(SUPPLIER_EMAIL)
        if customer_email and "@" in str(customer_email):
            recipients.append(customer_email)

        if not recipients:
            print("❌ Aucun destinataire configuré")
            return False

        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if not SMTP_USER or not SMTP_PASS:
            print("❌ Configuration SMTP manquante")
            return False

        print(f"🔧 DEBUG: Connexion au serveur SMTP {SMTP_SERVER}:{SMTP_PORT} en tant que {SMTP_USER}")

        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, recipients, msg.as_string())
            print(f"✅ Email envoyé à: {recipients}")
            return True
        except smtplib.SMTPAuthenticationError as e:
            print(f"❌ Erreur d'authentification SMTP: {e}")
            print("💡 Conseil: Utilisez Mailtrap pour les tests - https://mailtrap.io/")
            return False
        except Exception as e:
            print(f"❌ Erreur SMTP: {e}")
            return False
    except Exception as e:
        print(f"❌ Erreur générale envoi email: {e}")
        return False
    finally:
        try:
            if server:
                server.quit()
        except Exception:
            pass

# ----------------- TEST ROUTES -----------------
@app.route("/test-email")
def test_email():
    """Route pour tester l'envoi d'email"""
    try:
        test_order = {
            "stripe_session_id": "test_123",
            "items": [
                {"product_name": "Produit Test", "price": 50, "qty": 1, "size": "42"},
                {"product_name": "Autre Produit", "price": 30, "qty": 2, "size": "38"}
            ],
            "total_amount": 110,
            "commission_rate": 0.15,
            "commission_amount": 16.5,
            "customer_email": "labicheerwan12@gmail.com",
            "shipping_address": {"line1": "123 Test", "city": "Paris", "country": "FR"}
        }

        success = send_order_email_to_supplier(test_order)
        if success:
            return "✅ Email de test envoyé avec succès!"
        else:
            return "❌ Échec de l'envoi d'email - vérifiez la configuration SMTP"
    except Exception as e:
        return f"❌ Erreur: {str(e)}"

@app.route("/test-database")
def test_database():
    """Route pour tester la connexion à la base de données"""
    try:
        res = supabase.table("carts").select("*").execute()
        carts_count = len(res.data) if getattr(res, 'data', None) else 0
        orders_res = supabase.table("orders").select("*").limit(1).execute()
        orders_ok = not (hasattr(orders_res, 'error') and orders_res.error)
        return f"""
        <h1>Test Base de Données</h1>
        <p>✅ Connexion Supabase: OK</p>
        <p>✅ Table carts: OK ({carts_count} éléments)</p>
        <p>{"✅" if orders_ok else "❌"} Table orders: {"OK" if orders_ok else "ERREUR"}</p>
        <p><strong>Multiplicateur de prix actuel: {PRICE_MULTIPLIER}x</strong></p>
        <p><a href="/">Retour</a></p>
        """
    except Exception as e:
        return f"❌ Erreur base de données: {str(e)}"

# ----------------- Stripe webhook -----------------
@app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        print("Webhook error (signature):", e)
        return "", 400

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        session_id = session_obj.get("id")
        print("✅ Webhook: checkout.session.completed", session_id)

        try:
            session_stripe = stripe.checkout.Session.retrieve(session_id)
            user_id = session_stripe.metadata.get("user_id") if getattr(session_stripe, "metadata", None) else None

            if user_id:
                try:
                    cart = get_cart_items_for_user(user_id)
                except Exception as e:
                    print("Erreur récupération panier pour webhook:", e)
                    cart = []

                total_amount = float(getattr(session_stripe, "amount_total", 0) or 0) / 100 if getattr(session_stripe, "amount_total", None) else sum(
                    (float(it.get("price", 0) or 0) * int(it.get("qty", 1) or 1)) for it in cart
                )
                commission_rate = float(getattr(session_stripe, "metadata", {}) .get("commission_rate", COMMISSION_RATE))
                commission_amount = round(total_amount * commission_rate, 2)

                order_data = {
                    "user_id": user_id,
                    "stripe_session_id": session_id,
                    "total_amount": total_amount,
                    "commission_rate": commission_rate,
                    "commission_amount": commission_amount,
                    "status": "paid",
                    "items": cart,
                    "customer_email": getattr(getattr(session_stripe, "customer_details", None), "email", None),
                    "shipping_address": getattr(getattr(session_stripe, "customer_details", None), "address", None)
                }

                try:
                    supabase.table("orders").insert(order_data).execute()
                except Exception as e:
                    print("Erreur insertion order via webhook:", e)
                    backup_order_to_file(order_data, "webhook_error")

                try:
                    send_order_email_to_supplier(order_data)
                except Exception as e:
                    print("Erreur envoi email via webhook:", e)

                try:
                    supabase.table("carts").delete().eq("user_id", user_id).execute()
                except Exception as e:
                    print("Erreur vidage panier via webhook:", e)
        except Exception as e:
            print("Erreur traitement webhook checkout.session.completed:", e)

    return "", 200

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
