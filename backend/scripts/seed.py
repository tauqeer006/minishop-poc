"""Idempotent development seed data. Run as: python -m scripts.seed

Creates 1 admin, 2 customers, 8 products and a few sample orders (only if missing).
Credentials come from environment (development defaults are documented in README/.env.example).
Refuses to seed with default passwords when ENVIRONMENT=production."""
import asyncio
import os
import sys
from datetime import timedelta

from app import database
from app.config import settings
from app.utils.security import hash_password
from app.utils.serialization import utcnow

ADMIN_EMAIL = os.getenv("SEED_ADMIN_EMAIL", "admin@minishop.dev")
ADMIN_PASSWORD = os.getenv("SEED_ADMIN_PASSWORD", "Admin@12345")
CUSTOMER_PASSWORD = os.getenv("SEED_CUSTOMER_PASSWORD", "Customer@12345")

USERS = [
    ("usr_seed_admin", "Admin User", ADMIN_EMAIL, ADMIN_PASSWORD, "admin"),
    ("usr_seed_cust1", "Alice Customer", "customer1@minishop.dev", CUSTOMER_PASSWORD, "customer"),
    ("usr_seed_cust2", "Bob Customer", "customer2@minishop.dev", CUSTOMER_PASSWORD, "customer"),
]

# (id, name, description, price in cents, stock)
PRODUCTS = [
    ("prd_seed_001", "Wireless Mouse", "Ergonomic 2.4GHz wireless mouse with silent clicks.", 2499, 120),
    ("prd_seed_002", "Mechanical Keyboard", "Hot-swappable mechanical keyboard, tactile switches.", 8999, 60),
    ("prd_seed_003", "USB-C Hub", "7-in-1 USB-C hub: HDMI, USB 3.0, SD card, PD charging.", 3999, 90),
    ("prd_seed_004", "Laptop Stand", "Adjustable aluminium laptop stand.", 2999, 75),
    ("prd_seed_005", "Bluetooth Speaker", "Portable water-resistant Bluetooth speaker.", 4999, 50),
    ("prd_seed_006", "External SSD", "1TB portable NVMe SSD, USB 3.2 Gen 2.", 10999, 40),
    ("prd_seed_007", "Webcam", "1080p webcam with built-in microphone.", 5499, 55),
    ("prd_seed_008", "Wireless Headphones", "Over-ear ANC wireless headphones, 30h battery.", 12999, 35),
]


async def main() -> None:
    if settings.environment == "production" and (
        ADMIN_PASSWORD == "Admin@12345" or CUSTOMER_PASSWORD == "Customer@12345"
    ):
        print("Refusing to seed default credentials in production.", file=sys.stderr)
        sys.exit(1)

    db = database.init_db()
    await database.wait_for_primary()
    await database.ensure_indexes(db)
    now = utcnow()

    for uid, name, email, pw, role in USERS:
        if await db.users.find_one({"email": email}) is None:  # never overwrite existing users
            await db.users.insert_one({"_id": uid, "name": name, "email": email,
                                       "password_hash": await hash_password(pw), "role": role, "created_at": now})

    for pid, name, desc, price, stock in PRODUCTS:
        await db.products.update_one(
            {"_id": pid},
            {"$setOnInsert": {"name": name, "description": desc, "price": price, "stock_quantity": stock,
                              "is_active": True, "version": 1, "created_at": now, "updated_at": now}},
            upsert=True)

    prod = {p[0]: p for p in PRODUCTS}

    def order(oid, user, lines, status, days_ago):
        created = now - timedelta(days=days_ago)
        items = [{"product_id": pid, "product_name": prod[pid][1], "quantity": q,
                  "unit_price": prod[pid][3], "subtotal": prod[pid][3] * q} for pid, q in lines]
        history = [{"status": "PENDING", "at": created, "by": user, "note": "Order placed",
                    "workflow_execution_id": None}]
        if status != "PENDING":
            history.append({"status": status, "at": created + timedelta(hours=2), "by": "usr_seed_admin",
                            "note": "Seed data", "workflow_execution_id": None})
        return {"_id": oid, "user_id": user, "items": items, "total_amount": sum(i["subtotal"] for i in items),
                "status": status, "idempotency_key": f"seed-key-{oid}", "request_fingerprint": f"seed-{oid}",
                "workflow_id": f"wf-order-processing-{oid}", "created_at": created, "updated_at": created,
                "status_history": history}

    samples = [
        order("ORD-SEED-0001", "usr_seed_cust1", [("prd_seed_001", 1), ("prd_seed_003", 2)], "DELIVERED", 12),
        order("ORD-SEED-0002", "usr_seed_cust1", [("prd_seed_006", 1)], "SHIPPED", 3),
        order("ORD-SEED-0003", "usr_seed_cust2", [("prd_seed_002", 1), ("prd_seed_004", 1)], "PENDING", 1),
    ]
    for o in samples:
        await db.orders.update_one({"_id": o["_id"]}, {"$setOnInsert": o}, upsert=True)

    print("seed complete (idempotent): 1 admin, 2 customers, 8 products, 3 sample orders")
    await database.close_db()


if __name__ == "__main__":
    asyncio.run(main())
