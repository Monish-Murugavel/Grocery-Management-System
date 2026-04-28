# app.py — Grocery API using FastAPI + SQLite (no server needed)
import sqlite3
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List

DB_PATH = "grocery.db"
app = FastAPI(title="Grocery (SQLite, single-file)")

# ---------- request models ----------
class ProductIn(BaseModel):
    serial_no: str
    name: str
    price: float = Field(ge=0)

class CustomerIn(BaseModel):
    phone: str     # primary key
    name: str

class BillItem(BaseModel):
    serial_no: str
    qty: int = Field(gt=0)

class BillIn(BaseModel):
    phone: str
    items: List[BillItem]

CREDIT_RATE = 0.05  # 5% earned credit from amount actually paid

# ---------- DB helpers ----------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    con = db()
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS products (
          serial_no TEXT PRIMARY KEY,
          name      TEXT NOT NULL,
          price     REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS customers (
          uid    INTEGER PRIMARY KEY AUTOINCREMENT,
          phone  TEXT UNIQUE NOT NULL,
          name   TEXT NOT NULL,
          credit REAL NOT NULL DEFAULT 0.0
        );
    """)
    con.commit()
    con.close()

init_db()

# ---------- PRODUCTS ----------
@app.post("/products")
def add_product(p: ProductIn):
    con = db(); cur = con.cursor()
    cur.execute("SELECT 1 FROM products WHERE serial_no=?", (p.serial_no,))
    if cur.fetchone():
        con.close()
        raise HTTPException(400, "serial_no already exists")
    cur.execute("INSERT INTO products(serial_no,name,price) VALUES (?,?,?)",
                (p.serial_no, p.name, p.price))
    con.commit(); con.close()
    return {"message": "product added"}

@app.post("/customers")
def add_customer(c: CustomerIn):
    con = db(); cur = con.cursor()
    try:
        cur.execute("INSERT INTO customers(phone,name) VALUES (?,?)", (c.phone, c.name))
        con.commit()
        return {"message": "customer added"}
    except sqlite3.IntegrityError:
        raise HTTPException(400, "phone already exists")
    finally:
        con.close()

@app.get("/products")
def list_products():
    con = db(); cur = con.cursor()
    cur.execute("SELECT serial_no,name,price FROM products ORDER BY name")
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows

# ---------- CUSTOMERS ----------


@app.get("/customers")
def list_customers():
    con = db(); cur = con.cursor()
    cur.execute("SELECT uid,phone,name,credit FROM customers ORDER BY uid DESC")
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows

# ---------- BILL (use credit, then earn new credit) ----------
@app.post("/bill")
def create_bill(b: BillIn):
    con = db(); cur = con.cursor()
    try:
        # lock-ish: use a transaction
        con.isolation_level = "IMMEDIATE"

        cur.execute("SELECT phone,credit FROM customers WHERE phone=?", (b.phone,))
        cust = cur.fetchone()
        if not cust:
            raise HTTPException(404, "customer not found")

        subtotal = 0.0
        for item in b.items:
            cur.execute("SELECT price FROM products WHERE serial_no=?", (item.serial_no,))
            prod = cur.fetchone()
            if not prod:
                raise HTTPException(404, f"product {item.serial_no} not found")
            subtotal += float(prod["price"]) * item.qty

        available_credit = float(cust["credit"])
        used_credit = min(available_credit, subtotal)
        amount_to_pay = round(subtotal - used_credit, 2)
        earned_credit = round(amount_to_pay * CREDIT_RATE, 2)
        new_credit = round(available_credit - used_credit + earned_credit, 2)

        cur.execute("UPDATE customers SET credit=? WHERE phone=?", (new_credit, b.phone))
        con.commit()

        return {
            "subtotal": round(subtotal, 2),
            "used_credit": round(used_credit, 2),
            "amount_to_pay": amount_to_pay,
            "earned_credit": earned_credit,
            "customer_new_credit": new_credit
        }
    except HTTPException:
        con.rollback()
        raise
    finally:
        con.close()
