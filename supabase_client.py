import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# Utiliser la clé anon comme client principal
supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# -------------------- AUTH --------------------
def register_user(email, password):
    """Crée un compte utilisateur"""
    return supabase.auth.sign_up({"email": email, "password": password})

def login_user(email, password):
    """Connecte un utilisateur"""
    return supabase.auth.sign_in_with_password({"email": email, "password": password})

def get_user_client(access_token):
    """Crée un client Supabase authentifié avec le token utilisateur"""
    try:
        # Créer un nouveau client avec le token utilisateur
        client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        # Définir le header d'autorisation avec le token
        client.postgrest.auth(access_token)
        return client
    except Exception as e:
        print(f"Error creating user client: {e}")
        return supabase

def verify_token(access_token):
    """Vérifie si le token est valide et retourne l'user_id"""
    try:
        user = supabase.auth.get_user(access_token)
        return user.user.id if user and user.user else None
    except Exception as e:
        print(f"Token verification error: {e}")
        return None

# -------------------- CARTS / ORDERS --------------------
def add_to_cart(user_id, product_name, path, product_image, price, qty=1, size=None):
        cart_item = {
            "user_id": user_id,
            "product_name": product_name,
            "path": path,
            "product_image": product_image,
            "price": price,
            "qty": qty,
            "size": size
        }
        return supabase.table("carts").insert(cart_item).execute()

def create_order(payload):
    return supabase.table("orders").insert(payload).execute()

def add_order_items(items):
    return supabase.table("order_items").insert(items).execute()

# -------------------- IMAGES --------------------
def upload_image(file, filename):
    """
    Upload une image produit dans Supabase.
    Note: Pour uploader des images, vous aurez besoin de configurer les politiques de stockage
    """
    try:
        supabase.storage.from_("product-images").upload(filename, file.stream, {"content-type": file.mimetype})
        public_url = f"{SUPABASE_URL}/storage/v1/object/public/product-images/{filename}"
        return public_url
    except Exception as e:
        print("Erreur upload image:", e)
        return None