
Mini Shop - personalization via overrides.json

- Edit overrides.json in project root to hide or modify products.
- Keys should match product paths (example: /Nike-Air-Max-Plus-2025-325542.html)
- Supported fields:
  - hidden: true
  - price: "99.99 €"
  - image: "/static/custom/your.jpg" or full URL

Place custom images in static/custom/ and restart the Flask app to see changes.
