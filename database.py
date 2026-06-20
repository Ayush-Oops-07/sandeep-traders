"""
database.py — Sandeep Traders Business Suite
Production-ready PostgreSQL + SQLite support
Supports:
- Customer Module
- Wholesale/Shoper Module
- Separate invoice/product/ledger flows
- Render PostgreSQL deployment
"""

import os
from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    Numeric,
    Date,
    DateTime,
    Boolean,
    ForeignKey,
    Index,
    Enum as SAEnum
)

from sqlalchemy.orm import (
    declarative_base,
    relationship,
    sessionmaker
)

# ─────────────────────────────────────────────────────────────
# DATABASE URL
# ─────────────────────────────────────────────────────────────

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///sandeep_traders.db"
)

# Render PostgreSQL compatibility
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql+psycopg2://",
        1
    )

# If PostgreSQL but missing driver
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgresql+psycopg2://",
        1
    )

# ─────────────────────────────────────────────────────────────
# ENGINE
# ─────────────────────────────────────────────────────────────

if DATABASE_URL.startswith("sqlite"):

    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )

else:

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=180,
        pool_timeout=30,
        pool_size=5,
        max_overflow=10,
        pool_reset_on_return="commit",
    )

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False
)

Base = declarative_base()

# ─────────────────────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────────────────────

MODULE_TYPES = (
    "customer",
    "shoper"
)

ENTRY_TYPES = (
    "sale",
    "payment",
    "debit",
    "credit",
    "opening",
    "advance_received",   # payment received before invoice exists
    "advance_paid",       # payment given before invoice exists
    "adjustment",         # adjustment entry linking payment to invoice
)

PAYMENT_MODES = (
    "cash",
    "upi",
    "bank_transfer",
    "cheque",
    "other"
)

USER_ROLES = (
    "admin",
    "owner",
    "staff"
)

# Quick payment-entry feature (Issue 1): a payment recorded by staff
# without an invoice. Always RECEIVED (money in) or GIVEN (money out).
PAYMENT_TRANSACTION_TYPES = (
    "RECEIVED",
    "GIVEN"
)

# ISSUE 4: an invoice line is either a real stock-tracked product, or a
# free-text service/charge line (Labour, Driver, Transport, etc.) that
# never touches inventory.
INVOICE_ITEM_TYPES = (
    "inventory",
    "service"
)

_module_type_enum = SAEnum(
    *MODULE_TYPES,
    name="module_type"
)

_entry_type_enum = SAEnum(
    *ENTRY_TYPES,
    name="entry_type"
)

_payment_mode_enum = SAEnum(
    *PAYMENT_MODES,
    name="payment_mode"
)

_user_role_enum = SAEnum(
    *USER_ROLES,
    name="user_role"
)

_payment_txn_type_enum = SAEnum(
    *PAYMENT_TRANSACTION_TYPES,
    name="payment_transaction_type"
)

_invoice_item_type_enum = SAEnum(
    *INVOICE_ITEM_TYPES,
    name="invoice_item_type"
)

# ─────────────────────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)

    username = Column(
        String(60),
        unique=True,
        nullable=False,
        index=True
    )

    password_hash = Column(
        String(255),
        nullable=False
    )

    full_name = Column(
        String(120),
        nullable=False,
        default=""
    )

    role = Column(
        _user_role_enum,
        nullable=False,
        default="staff"
    )

    is_active = Column(
        Boolean,
        default=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    last_login = Column(
        DateTime,
        nullable=True
    )

# ─────────────────────────────────────────────────────────────
# PARTIES
# customer & shoper separate via party_type
# ─────────────────────────────────────────────────────────────

class Party(Base):
    __tablename__ = "parties"

    id = Column(Integer, primary_key=True)

    party_type = Column(
        _module_type_enum,
        nullable=False,
        index=True
    )

    name = Column(
        String(200),
        nullable=False
    )

    mobile = Column(String(20))
    mobile2 = Column(String(20))

    address = Column(Text)
    city = Column(String(100))
    gstin = Column(String(30))
    email = Column(String(120))

    opening_balance = Column(
        Numeric(14, 2),
        default=Decimal("0.00")
    )

    balance = Column(
        Numeric(14, 2),
        default=Decimal("0.00")
    )

    is_active = Column(
        Boolean,
        default=True
    )

    notes = Column(Text)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # Relationships
        # Relationships

    ledger_entries = relationship(
        "LedgerEntry",
        back_populates="party",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="LedgerEntry.entry_date, LedgerEntry.id"
    )

    invoices = relationship(
        "Invoice",
        back_populates="party",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    __table_args__ = (

        Index(
            "ix_parties_name",
            "name"
        ),

        Index(
            "ix_parties_type_name",
            "party_type",
            "name"
        ),
    )

# ─────────────────────────────────────────────────────────────
# PRODUCTS
# customer & wholesale separate products
# ─────────────────────────────────────────────────────────────

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)

    party_type = Column(
        _module_type_enum,
        nullable=False,
        default="customer",
        index=True
    )

    name = Column(
        String(200),
        nullable=False,
        index=True
    )

    default_unit = Column(
        String(40),
        nullable=True
    )

    default_rate = Column(
        Numeric(12, 2),
        nullable=True
    )

    # ISSUE 4: stock balance for this product. Only ever decremented by
    # invoice items with item_type="inventory" — service/charge lines
    # (Labour, Driver, Transport, etc.) never touch this. Nullable so
    # existing products created before this feature don't suddenly show
    # a stock of 0 and block sales; a NULL stock means "not tracked".
    stock_qty = Column(
        Numeric(14, 3),
        nullable=True
    )

    is_active = Column(
        Boolean,
        default=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    __table_args__ = (

        Index(
            "ix_products_type_name",
            "party_type",
            "name"
        ),
    )

# ─────────────────────────────────────────────────────────────
# INVOICES
# Separate customer/shoper invoice flow
# ─────────────────────────────────────────────────────────────

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True)

    invoice_number = Column(
        String(60),
        unique=True,
        nullable=False,
        index=True
    )

    party_id = Column(
        Integer,
        ForeignKey("parties.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    party_type = Column(
        _module_type_enum,
        nullable=False
    )

    invoice_date = Column(
        Date,
        nullable=False,
        default=date.today
    )

    due_date = Column(Date)

    subtotal = Column(
        Numeric(14, 2),
        default=Decimal("0.00")
    )

    discount_amount = Column(
        Numeric(14, 2),
        default=Decimal("0.00")
    )

    gst_amount = Column(
        Numeric(14, 2),
        default=Decimal("0.00")
    )

    total_amount = Column(
        Numeric(14, 2),
        default=Decimal("0.00")
    )

    notes = Column(Text)

    is_cancelled = Column(
        Boolean,
        default=False
    )

    created_by = Column(
        Integer,
        ForeignKey("users.id")
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # Relationships

    party = relationship(
        "Party",
        back_populates="invoices"
    )

    items = relationship(
        "InvoiceItem",
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoiceItem.id"
    )

    ledger_entry = relationship(
        "LedgerEntry",
        back_populates="invoice",
        foreign_keys="LedgerEntry.invoice_id",
        uselist=False
    )

# ─────────────────────────────────────────────────────────────
# INVOICE ITEMS
# ─────────────────────────────────────────────────────────────

class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id = Column(Integer, primary_key=True)

    invoice_id = Column(
        Integer,
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    product_name = Column(
        String(200),
        nullable=False
    )

    unit = Column(String(40))

    quantity = Column(
        Numeric(12, 3),
        default=Decimal("0.000")
    )

    rate = Column(
        Numeric(12, 2),
        default=Decimal("0.00")
    )

    discount_pct = Column(
        Numeric(5, 2),
        default=Decimal("0.00")
    )

    gst_pct = Column(
        Numeric(5, 2),
        default=Decimal("0.00")
    )

    total = Column(
        Numeric(14, 2),
        default=Decimal("0.00")
    )

    # ISSUE 4: Service Charges / Manual Amount Entry
    # "inventory" = normal product row (qty * rate, deducts stock, shown
    # with full unit/GST/qty/rate fields).
    # "service"   = a charge line (Labour, Driver, Transport, etc.) — no
    # unit/GST/qty/product-catalog requirements, just a description and a
    # directly-typed amount. Never affects stock or inventory valuation.
    item_type = Column(
        _invoice_item_type_enum,
        nullable=False,
        default="inventory"
    )

    # True once the user manually overrides the auto-calculated
    # qty * rate (with disc/GST) total for an inventory row, OR for any
    # service row (whose amount is always typed directly). When True, the
    # backend must never silently recompute/overwrite `total` from
    # qty/rate — it only changes again if the user explicitly edits qty,
    # rate, or the amount itself.
    is_manual_total = Column(
        Boolean,
        nullable=False,
        default=False
    )

    invoice = relationship(
        "Invoice",
        back_populates="items"
    )

# ─────────────────────────────────────────────────────────────
# LEDGER ENTRIES
# ─────────────────────────────────────────────────────────────

class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id = Column(Integer, primary_key=True)

    party_id = Column(
        Integer,
        ForeignKey("parties.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    entry_date = Column(
        Date,
        nullable=False,
        index=True
    )

    entry_type = Column(
        _entry_type_enum,
        nullable=False
    )

    particulars = Column(
        String(500),
        nullable=False,
        default=""
    )

    debit = Column(
        Numeric(14, 2),
        default=Decimal("0.00")
    )

    credit = Column(
        Numeric(14, 2),
        default=Decimal("0.00")
    )

    running_balance = Column(
        Numeric(14, 2),
        default=Decimal("0.00")
    )

    payment_mode = Column(
        _payment_mode_enum,
        nullable=True
    )

    invoice_id = Column(
        Integer,
        ForeignKey("invoices.id", ondelete="SET NULL"),
        nullable=True
    )

    invoice_number = Column(
        String(60)
    )

    notes = Column(Text)

    created_by = Column(
        Integer,
        ForeignKey("users.id")
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    party = relationship(
        "Party",
        back_populates="ledger_entries"
    )

    invoice = relationship(
        "Invoice",
        back_populates="ledger_entry",
        foreign_keys=[invoice_id]
    )

    __table_args__ = (

        Index(
            "ix_ledger_party_date",
            "party_id",
            "entry_date"
        ),
    )

# ─────────────────────────────────────────────────────────────
# INVOICE ADJUSTMENTS  (Issue 5)
# Links a payment ledger entry to an invoice, recording that a
# previously received/given payment has been "applied" against a
# specific invoice for a given amount. This keeps the original
# payment entry intact in the ledger (for full audit history)
# while generating a matching LedgerEntry with type="adjustment"
# that shows the net adjustment on the invoice side.
# ─────────────────────────────────────────────────────────────

class InvoiceAdjustment(Base):
    __tablename__ = "invoice_adjustments"

    id = Column(Integer, primary_key=True)

    party_id = Column(
        Integer,
        ForeignKey("parties.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # The payment ledger entry being adjusted
    payment_ledger_entry_id = Column(
        Integer,
        ForeignKey("ledger_entries.id", ondelete="CASCADE"),
        nullable=False
    )

    # The invoice it's being applied against (None if creating new)
    invoice_id = Column(
        Integer,
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=True
    )

    # The amount being applied in this adjustment
    amount = Column(
        Numeric(14, 2),
        nullable=False
    )

    adjustment_date = Column(
        Date,
        nullable=False,
        default=date.today
    )

    notes = Column(Text)

    created_by = Column(
        Integer,
        ForeignKey("users.id")
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    # The new adjustment ledger entry generated by this action
    adjustment_ledger_entry_id = Column(
        Integer,
        ForeignKey("ledger_entries.id", ondelete="SET NULL"),
        nullable=True
    )

    party = relationship("Party", foreign_keys=[party_id])
    payment_entry = relationship("LedgerEntry", foreign_keys=[payment_ledger_entry_id])
    invoice = relationship("Invoice", foreign_keys=[invoice_id])
    adjustment_entry = relationship("LedgerEntry", foreign_keys=[adjustment_ledger_entry_id])

# ─────────────────────────────────────────────────────────────
# PAYMENT TRANSACTIONS
# Quick payment entries made by staff WITHOUT an invoice.
# Every row here always has a mirrored LedgerEntry (entry_type="payment")
# so that ledger/balance math has exactly one source of truth.
# ─────────────────────────────────────────────────────────────

class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id = Column(Integer, primary_key=True)

    customer_id = Column(
        Integer,
        ForeignKey("parties.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    payment_type = Column(
        _payment_txn_type_enum,
        nullable=False
    )

    amount = Column(
        Numeric(14, 2),
        nullable=False,
        default=Decimal("0.00")
    )

    payment_mode = Column(
        _payment_mode_enum,
        nullable=False,
        default="cash"
    )

    reference_no = Column(
        String(100),
        nullable=True
    )

    note = Column(Text)

    transaction_date = Column(
        Date,
        nullable=False,
        default=date.today,
        index=True
    )

    ledger_entry_id = Column(
        Integer,
        ForeignKey("ledger_entries.id", ondelete="SET NULL"),
        nullable=True
    )

    created_by = Column(
        Integer,
        ForeignKey("users.id")
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    customer = relationship(
        "Party",
        foreign_keys=[customer_id]
    )

    ledger_entry = relationship(
        "LedgerEntry",
        foreign_keys=[ledger_entry_id]
    )

    __table_args__ = (

        Index(
            "ix_payment_txn_customer_date",
            "customer_id",
            "transaction_date"
        ),
    )

# ─────────────────────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────────────────────

class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True)

    key = Column(
        String(100),
        unique=True,
        nullable=False
    )

    value = Column(Text)

# ─────────────────────────────────────────────────────────────
# INIT DATABASE
# ─────────────────────────────────────────────────────────────

def init_db():

    try:

        Base.metadata.create_all(
            bind=engine,
            checkfirst=True
        )

        print("DATABASE TABLES READY")

    except Exception as e:

        print("DATABASE INIT ERROR")
        print(str(e))
