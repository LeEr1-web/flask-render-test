
# Mini Shop (Scraper + Flask + Supabase)

Ce dépôt contient une application Flask simple qui utilise un **scraper** (requests + BeautifulSoup)
pour extraire des catégories/produits d'un site cible, et une variante `app_supabase.py` qui
intègre Supabase (auth, storage, DB) et Stripe Checkout.

## Structure
- `app.py` : application Flask sans Supabase (local).
- `app_supabase.py` : application Flask avec intégration Supabase et Stripe.
- `scraper.py` : fonctions de scraping (get_categories, get_category_products, get_product_details).
- `supabase_client.py` : création du client Supabase côté serveur.
- `supabase_utils.py` : utilitaires pour auth / storage / orders (utilise le client).
- `templates/` et `static/` : templates Jinja2 et CSS.
- `overrides.json` : corrections locales de produits.

## Prérequis
- Python 3.10+ recommandé
- Créez un virtuelenv : `python -m venv .venv && source .venv/bin/activate`
- Installez les dépendances : `pip install -r requirements.txt`
- Copiez `.env.example` en `.env` et remplissez les variables (SUPABASE_URL, SUPABASE_SERVICE_KEY, STRIPE_..., SECRET_KEY, ...)

## Lancer en local
1. Sans Supabase (test rapide) :
```bash
export FLASK_APP=app.py
export FLASK_ENV=development
python app.py
```
Puis ouvrez http://127.0.0.1:5000

2. Avec Supabase (nécessite les clés) :
```bash
cp .env.example .env
# remplir .env
python app_supabase.py
```

## Points notés pendant l'audit (à lire)
- Le projet **attend** des variables d'environnement (Supabase + Stripe). J'ai ajouté `.env.example`.
- `requirements.txt` était dupliqué / désordonné — j'ai nettoyé et fixé des versions minimales.
- `supabase_utils.py` utilisait `create_client` directement ; je l'ai modifié pour réutiliser le client central `supabase_client.supabase`.
- Pas de tests automatisés fournis et pas d'intégration CI. Je recommande d'ajouter quelques tests unitaires pour `scraper.py`.
- Il faut configurer les buckets Supabase (`product-images`, `config`, `exports`) et les tables (`orders`, `order_items`, `carts`) attendues par le code.

## Améliorations suggérées (prioritaires)
1. Ajouter des tests unitaires pour `scraper.py` (mock responses).
2. Ajouter un script `docker-compose` / `Dockerfile` pour faciliter le déploiement.
3. Restreindre la clé service de Supabase côté serveur et éviter de l'exposer au client.
4. Ajouter la gestion d'erreurs autour des appels réseau dans `scraper.py` (timeouts, retries).
5. Ajouter un scheduler / caching pour limiter les requêtes de scraping en production.

## Auteur
Modifications automatiques apportées par l'audit du projet.
