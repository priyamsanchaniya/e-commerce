import random
from db import fetch_one, fetch_all, execute_query


BRANDS = [
    "Boat", "Noise", "Samsung", "Sony", "Apple", "Realme", "OnePlus", "Mi",
    "Puma", "Nike", "Adidas", "Levis", "H&M", "Zara",
    "Prestige", "Philips", "Havells", "LG", "Whirlpool",
    "Redragon", "HP", "Dell", "Lenovo", "Asus"
]

PRODUCTS_BY_CATEGORY = {
    "Electronics": [
        "Wireless Headphones", "Bluetooth Speaker", "Smart Watch", "Gaming Mouse",
        "Mechanical Keyboard", "Power Bank", "Earbuds", "USB Cable",
        "Laptop Stand", "Webcam", "Mobile Charger", "Fitness Band"
    ],
    "Fashion": [
        "Cotton T-Shirt", "Running Shoes", "Denim Jeans", "Hoodie",
        "Casual Shirt", "Sports Shorts", "Leather Belt", "Sneakers",
        "Track Pants", "Jacket", "Cap", "Sunglasses"
    ],
    "Books": [
        "Python Programming Book", "Data Structures Book", "Web Development Guide",
        "Machine Learning Basics", "Database Management Book", "JavaScript Handbook",
        "Cyber Security Guide", "Cloud Computing Book", "AI Fundamentals"
    ],
    "Home Appliances": [
        "Electric Kettle", "Mixer Grinder", "Table Fan", "Iron",
        "Water Bottle", "LED Lamp", "Rice Cooker", "Toaster",
        "Air Fryer", "Room Heater", "Vacuum Cleaner"
    ]
}


def ensure_categories():
    """
    Ensures required categories exist.
    Returns list of categories from DB.
    """
    categories = fetch_all("SELECT category_id, name FROM categories WHERE is_active = TRUE")

    if categories:
        return categories

    default_categories = ["Electronics", "Fashion", "Books", "Home Appliances"]

    for cat in default_categories:
        execute_query(
            "INSERT INTO categories (name, image, is_active) VALUES (%s, %s, TRUE)",
            (cat, f"{cat.lower().replace(' ', '_')}.jpg")
        )

    return fetch_all("SELECT category_id, name FROM categories WHERE is_active = TRUE")


def seed_products(target_count=200):
    """
    Adds products until total active products reach target_count.
    Example: if DB has 3 products and target is 200, it inserts 197 products.
    """
    categories = ensure_categories()

    current = fetch_one("SELECT COUNT(*) AS count FROM products WHERE is_active = TRUE")
    current_count = int(current["count"]) if current else 0

    if current_count >= target_count:
        return {
            "status": "already_done",
            "message": f"Database already has {current_count} products.",
            "inserted": 0,
            "total": current_count
        }

    to_insert = target_count - current_count
    inserted = 0

    for i in range(to_insert):
        category = random.choice(categories)
        category_id = category["category_id"]
        category_name = category["name"]

        possible_items = PRODUCTS_BY_CATEGORY.get(category_name, ["Product"])
        brand = random.choice(BRANDS)
        item_name = random.choice(possible_items)

        name = f"{brand} {item_name} #{current_count + i + 1}"
        description = f"High-quality {item_name.lower()} from {brand}. Best choice for daily use."
        price = random.randint(299, 79999)
        discount_percent = random.choice([0, 5, 10, 12, 15, 18, 20, 25, 30, 35, 40])
        stock_quantity = random.randint(5, 150)
        image = "default.jpg"

        success = execute_query("""
            INSERT INTO products
            (category_id, name, description, price, discount_percent, stock_quantity, brand, image, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
        """, (
            category_id,
            name,
            description,
            price,
            discount_percent,
            stock_quantity,
            brand,
            image
        ))

        if success:
            inserted += 1

    final = fetch_one("SELECT COUNT(*) AS count FROM products WHERE is_active = TRUE")
    final_count = int(final["count"]) if final else current_count + inserted

    return {
        "status": "success",
        "message": f"Inserted {inserted} products successfully.",
        "inserted": inserted,
        "total": final_count
    }