import os
import json
from dotenv import load_dotenv
from urllib.parse import urlparse

# charger .env si présent
load_dotenv()

from supabase_client import supabase, SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_ANON_KEY

# -------------------- AUTH --------------------
def register_user(email, password):
    """Crée un compte utilisateur"""
    return supabase.auth.sign_up({"email": email, "password": password})

def get_user_by_token(access_token):
    """Vérifie un token d'accès et renvoie les infos utilisateur (selon version du client)."""
    try:
        # selon la version de supabase-py, la méthode peut différer
        return supabase.auth.get_user(access_token)
    except Exception:
        try:
            # fallback possible
            return supabase.auth.api.get_user(access_token)
        except Exception as e:
            print("Erreur get_user_by_token:", e)
            return None

# -------------------- CARTS / ORDERS (exemples) --------------------
def save_cart(user_id, cart):
    return supabase.table("carts").insert({"user_id": user_id, "cart": cart}).execute()

def create_order(payload):
    return supabase.table("orders").insert(payload).execute()

def add_order_items(items):
    return supabase.table("order_items").insert(items).execute()

# -------------------- IMAGES --------------------
def upload_image(file, filename):
    """
    Upload une image produit dans Supabase (bucket 'product-images').
    file = objet FileStorage (Flask)
    """
    try:
        supabase.storage.from_("product-images").upload(filename, file.stream, {"content-type": file.mimetype})
        public_url = f"{SUPABASE_URL}/storage/v1/object/public/product-images/{filename}"
        return public_url
    except Exception as e:
        print("Erreur upload image:", e)
        return None
