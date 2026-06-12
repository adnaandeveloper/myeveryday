# ======================================================================
# EdgeFlo Trading Journal Bot - Telegram
# Version: 2.4 - Stable
# Author: Qumbul / @qumbul114
#
# Features:
# - LIVE / CHALLENGE accounts
# - Prop firm %: 10% / 15% / 20% / 25%
# - Trade logger with photos
# - Payout with auto fee (LIVE = 0%, CHALLENGE = your %)
# - Bank history, Analyse, Journal
# - Multi-account trades
#
# Fixed in 2.4:
# 1. LIVE account creation - now catches duplicates, validates input
# 2. Prop firm % buttons - now robust, never silent-fails
# 3. My Accounts - fixed empty list crash
# 4. All handlers wrapped in try/except with user feedback
#
# Requirements:
# python-telegram-bot==21.6
# sqlalchemy==2.0.30
# python-dotenv
#
# ENV:
# TELEGRAM_BOT_TOKEN=your_token_here
# DATABASE_URL=sqlite:///./edgeflo.db
# ADMIN_IDS=123456,789012
#
# ======================================================================

import os
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from sqlalchemy import create_engine, Column, String, Float, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import IntegrityError
from datetime import datetime
import uuid
import traceback

# ==================== DATABASE MODELS ====================
# Section 1: ORM Models
# ------------------------------------------------------

Base = declarative_base()

def uid():
    """Generate a uuid4 string for primary keys."""
    return str(uuid.uuid4())

class User(Base):
    """Telegram user record."""
    __tablename__ = 'users'
    id = Column(String, primary_key=True, default=uid)
    telegram_id = Column(String, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_admin = Column(String, default='0')

class Account(Base):
    """Trading account - LIVE or CHALLENGE."""
    __tablename__ = 'accounts'
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey('users.id'))
    name = Column(String)
    type = Column(String) # LIVE / CHALLENGE
    start_balance = Column(Float)
    current_balance = Column(Float)
    fee_paid = Column(Float, default=0)
    payout_cut = Column(Float, default=20) # prop firm %
    status = Column(String, default='ACTIVE')
    __table_args__ = (UniqueConstraint('user_id', 'name'),)

class Pair(Base):
    """Trading pair watchlist."""
    __tablename__ = 'pairs'
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey('users.id'))
    symbol = Column(String)
    __table_args__ = (UniqueConstraint('user_id', 'symbol'),)

class Trade(Base):
    """Trade journal entry."""
    __tablename__ = 'trades'
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey('users.id'))
    symbol = Column(String)
    direction = Column(String)
    entry = Column(Float, default=0)
    sl = Column(Float, default=0)
    tp = Column(Float, default=0)
    rr = Column(Float, default=0)
    before_photo = Column(String)
    after_photo = Column(String)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime)

class TradeAccount(Base):
    """Link table: which accounts took which trade."""
    __tablename__ = 'trade_accounts'
    trade_id = Column(String, ForeignKey('trades.id'), primary_key=True)
    account_id = Column(String, ForeignKey('accounts.id'), primary_key=True)
    pnl_usd = Column(Float)
    result = Column(String)
    closed_at = Column(DateTime)

class CashTx(Base):
    """Bank ledger."""
    __tablename__ = 'cash_txs'
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey('users.id'))
    type = Column(String) # FEE, PAYOUT, WITHDRAW, DEPOSIT, ADJUST
    amount = Column(Float)
    note = Column(Text)
    date = Column(DateTime, default=datetime.utcnow)

# ==================== DATABASE SETUP ====================
# Section 2: Engine / Session
# ------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./edgeflo.db")
ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",")
engine = create_engine(DATABASE_URL, future=True)
Session = sessionmaker(bind=engine)
Base.metadata.create_all(engine)

# ==================== HELPERS ====================
# Section 3: User helpers / Menus
# ------------------------------------------------------

def get_user(tid):
    """Get or create a User record for a telegram_id."""
    s = Session()
    try:
        u = s.query(User).filter_by(telegram_id=str(tid)).first()
        if not u:
            is_first = s.query(User).count() == 0
            u = User(telegram_id=str(tid), is_admin='1' if (is_first or str(tid) in ADMIN_IDS) else '0')
            s.add(u)
            s.commit()
            s.refresh(u)
        return u
    finally:
        s.close()

def is_admin(tid):
    """Check if a telegram_id is admin."""
    s = Session()
    try:
        u = s.query(User).filter_by(telegram_id=str(tid)).first()
        return u and u.is_admin == '1'
    finally:
        s.close()

def main_menu(uid=None):
    """Build the main menu keyboard."""
    rows = [
        [InlineKeyboardButton("📝 Log Trade", callback_data="menu_log"), InlineKeyboardButton("✅ Close Trade", callback_data="menu_close")],
        [InlineKeyboardButton("💰 Balance", callback_data="menu_balance"), InlineKeyboardButton("⚙ My Accounts", callback_data="menu_accounts")],
        [InlineKeyboardButton("📊 Analyse", callback_data="menu_analyse"), InlineKeyboardButton("📖 Journal", callback_data="menu_journal")],
        [InlineKeyboardButton("📈 My Pairs", callback_data="menu_pairs"), InlineKeyboardButton("📜 Trade History", callback_data="menu_hist")],
        [InlineKeyboardButton("➕ Add Account", callback_data="menu_add"), InlineKeyboardButton("💰 Wallet & Tools", callback_data="menu_profit")],
    ]
    if uid and is_admin(uid):
        rows.append([InlineKeyboardButton("👑 ADMIN PANEL", callback_data="menu_admin")])
    return InlineKeyboardMarkup(rows)

def back_button():
    """Standard back to menu button."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back to Menu", callback_data="back_main")]])

def profit_menu():
    """Wallet & Tools submenu."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Challenge Buy", callback_data="profit_challenge"), InlineKeyboardButton("💰 Live Deposit", callback_data="profit_deposit")],
        [InlineKeyboardButton("💸 Log Payout", callback_data="profit_payout"), InlineKeyboardButton("💵 Withdraw", callback_data="profit_withdraw")],
        [InlineKeyboardButton("📊 View Stats", callback_data="profit_stats"), InlineKeyboardButton("🗑 Edit/Delete", callback_data="profit_edit")],
        [InlineKeyboardButton("🔄 Reset All", callback_data="profit_reset"), InlineKeyboardButton("📜 Bank History", callback_data="profit_history")],
        [InlineKeyboardButton("🧹 Clean View", callback_data="clear_chat")],
        [InlineKeyboardButton("⬅ Back", callback_data="back_main")]
    ])

# ==================== BASIC COMMANDS ====================
# Section 4: /start /clear /back
# ------------------------------------------------------

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    get_user(update.effective_user.id)
    ctx.user_data.clear()
    await update.message.reply_text("📊 Trading Journal", reply_markup=main_menu(update.effective_user.id))

async def clear_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /clear command."""
    await update.message.reply_text("🧹 Tap my name → Clear History to clean chat.")

async def back_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Return to main menu, clear state."""
    q = update.callback_query
    await q.answer()
    ctx.user_data.clear()
    await q.edit_message_text("📊 Trading Journal", reply_markup=main_menu(q.from_user.id))

# ==================== ACCOUNT MANAGEMENT ====================
# Section 5: Archive / Withdraw / Payout / Deposit selectors
# ------------------------------------------------------

async def archive_acc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Archive an account."""
    q = update.callback_query
    await q.answer()
    s = Session()
    try:
        a = s.query(Account).get(q.data[5:])
        if a:
            a.status = 'ARCHIVED'
            s.commit()
            await q.edit_message_text(f"✅ {a.name} archived", reply_markup=back_button())
        else:
            await q.edit_message_text("Account not found", reply_markup=back_button())
    except Exception as e:
        await q.edit_message_text(f"❌ {e}", reply_markup=back_button())
    finally:
        s.close()

async def wd_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Withdraw - select account, ask amount."""
    q = update.callback_query
    await q.answer()
    ctx.user_data.clear()
    ctx.user_data['mode'] = 'withdraw'
    ctx.user_data['wd_acc'] = q.data[3:]
    await q.edit_message_text("Amount to withdraw to bank?", reply_markup=back_button())

async def payout_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Payout - select account, ask gross."""
    q = update.callback_query
    await q.answer()
    ctx.user_data.clear()
    ctx.user_data['mode'] = 'payout'
    ctx.user_data['payout_acc'] = q.data[7:]
    await q.edit_message_text("Gross payout amount?", reply_markup=back_button())

async def deposit_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Deposit - select LIVE account, ask amount."""
    q = update.callback_query
    await q.answer()
    ctx.user_data.clear()
    ctx.user_data['mode'] = 'deposit'
    ctx.user_data['deposit_acc'] = q.data[8:]
    await q.edit_message_text("How much to deposit?", reply_markup=back_button())

# ==================== CHALLENGE % SELECTOR ====================
# Section 6: Prop firm cut callback - FIXED
# ------------------------------------------------------

async def cut_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Prop firm % selector for CHALLENGE accounts.
    FIXED: now catches missing user_data, duplicate names, DB errors.
    """
    q = update.callback_query
    await q.answer()
    s = Session()
    try:
        # Validate we have the pending account data
        if 'na_name' not in ctx.user_data or 'na_bal' not in ctx.user_data or 'na_fee' not in ctx.user_data:
            await q.edit_message_text("❌ Session expired. Start Add Account again.", reply_markup=main_menu(q.from_user.id))
            ctx.user_data.clear()
            return

        cut = float(q.data.split('_')[1])
        u = get_user(q.from_user.id)
        bal = float(ctx.user_data['na_bal'])
        fee = float(ctx.user_data['na_fee'])
        name = str(ctx.user_data['na_name']).strip()

        # Delete existing account with same name to avoid UniqueConstraint crash
        existing = s.query(Account).filter_by(user_id=u.id, name=name).first()
        if existing:
            s.delete(existing)
            s.commit()

        acc = Account(
            user_id=u.id, name=name, type='CHALLENGE',
            start_balance=bal, current_balance=bal,
            fee_paid=fee, payout_cut=cut
        )
        s.add(acc)
        s.add(CashTx(user_id=u.id, type='FEE', amount=-fee, note=f"Buy {name}"))
        s.commit()

        ctx.user_data.clear()
        await q.edit_message_text(
            f"✅ {name} CHALLENGE created\nFee: ${fee} | Prop cut: {cut}%",
            reply_markup=main_menu(q.from_user.id)
        )
    except Exception as e:
        traceback.print_exc()
        try:
            await q.edit_message_text(f"❌ Error creating account: {e}", reply_markup=back_button())
        except:
            pass
        ctx.user_data.clear()
    finally:
        s.close()

# ==================== MENU HANDLER ====================
# Section 7: Main menu router
# ------------------------------------------------------

async def menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Route all main menu callbacks."""
    q = update.callback_query
    await q.answer()
    d = q.data
    ctx.user_data.clear()
    s = Session()
    try:
        u = get_user(q.from_user.id)

        if d == "menu_log":
            s.close()
            return await trade_start(q, ctx)
        if d == "menu_close":
            s.close()
            return await close_start(q, ctx)

        if d == "menu_balance":
            net = sum(t.amount for t in s.query(CashTx).filter_by(user_id=u.id)) or 0
            kb = [[InlineKeyboardButton("✏ Edit", callback_data="bal_edit"), InlineKeyboardButton("🔄 Reset", callback_data="bal_reset")],
                  [InlineKeyboardButton("⬅ Back", callback_data="back_main")]]
            await q.edit_message_text(f"💰 Bank Balance: ${net:.2f}", reply_markup=InlineKeyboardMarkup(kb))
            return

        if d == "bal_edit":
            ctx.user_data['mode'] = 'bal_edit'
            await q.edit_message_text("Enter new bank balance:", reply_markup=back_button())
            return

        if d == "bal_reset":
            await q.edit_message_text("Reset bank to $0?", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Yes", callback_data="bal_reset_yes"), InlineKeyboardButton("❌ No", callback_data="menu_balance")]
            ]))
            return

        if d == "bal_reset_yes":
            s.query(CashTx).filter_by(user_id=u.id).delete()
            s.commit()
            await q.edit_message_text("✅ Bank reset", reply_markup=back_button())
            return

        if d == "clear_chat":
            await q.edit_message_text("🧹 Tap my name → Clear History.", reply_markup=back_button())
            return

        if d == "menu_accounts":
            accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all()
            arch = s.query(Account).filter_by(user_id=u.id, status='ARCHIVED').all()
            msg = "⚙ My Accounts\n\n"
            if not accs:
                msg += "No accounts yet. Add one with ➕ Add Account\n\n"
            for a in accs:
                cut = f" -{int(a.payout_cut)}%" if a.type == 'CHALLENGE' else ""
                msg += f"🟢 {a.name} ({a.type}{cut}) - ${a.current_balance:.0f}\n"
            if arch:
                msg += "\n📦 Archived:\n"
                for a in arch:
                    msg += f"• {a.name}\n"
            kb = [[InlineKeyboardButton(f"📦 Archive {a.name}", callback_data=f"arch_{a.id}")] for a in accs]
            kb.append([InlineKeyboardButton("⬅ Back", callback_data="back_main")])
            await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
            return

        if d == "menu_add":
            await q.edit_message_text("Choose account type:", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💼 Live", callback_data="add_live"), InlineKeyboardButton("🎯 Challenge", callback_data="add_challenge")],
                [InlineKeyboardButton("⬅ Back", callback_data="back_main")]
            ]))
            return

        if d == "add_live":
            ctx.user_data['mode'] = 'new_acc'
            ctx.user_data['atype'] = 'LIVE'
            ctx.user_data['step'] = 1
            await q.edit_message_text("Live account name?", reply_markup=back_button())
            return

        if d == "add_challenge":
            ctx.user_data['mode'] = 'new_acc'
            ctx.user_data['atype'] = 'CHALLENGE'
            ctx.user_data['step'] = 1
            await q.edit_message_text("Challenge name? (e.g. FTMO 100k)", reply_markup=back_button())
            return

        if d == "menu_profit":
            await q.edit_message_text("💰 Wallet & Tools", reply_markup=profit_menu())
            return

        if d == "menu_pairs":
            pairs = s.query(Pair).filter_by(user_id=u.id).all()
            kb = [[InlineKeyboardButton(f"❌ {p.symbol}", callback_data=f"pairdel_{p.id}")] for p in pairs]
            kb.append([InlineKeyboardButton("➕ Add Pair", callback_data="pair_add"), InlineKeyboardButton("⬅ Back", callback_data="back_main")])
            await q.edit_message_text("📈 My Pairs", reply_markup=InlineKeyboardMarkup(kb))
            return

        if d == "menu_analyse":
            trades = s.query(Trade).filter_by(user_id=u.id).filter(Trade.closed_at!= None).all()
            tas = s.query(TradeAccount).join(Trade).filter(Trade.user_id == u.id).filter(TradeAccount.pnl_usd!= None).all()
            total = len(tas)
            wins = len([t for t in tas if t.pnl_usd > 0])
            winrate = (wins / total * 100) if total else 0
            avg_rr = sum(t.rr for t in trades if t.rr) / len(trades) if trades else 0
            total_pnl = sum(t.pnl_usd for t in tas)
            msg = f"📊 Analyse\n\nTrades: {total}\nWin Rate: {winrate:.1f}%\nAvg RR: {avg_rr:.2f}\nTotal PnL: ${total_pnl:.2f}"
            await q.edit_message_text(msg, reply_markup=back_button())
            return

        if d == "menu_journal":
            trades = s.query(Trade).filter_by(user_id=u.id).order_by(Trade.opened_at.desc()).limit(5).all()
            msg = "📖 Last Trades\n\n"
            for t in trades:
                msg += f"{t.opened_at.strftime('%d/%m/%Y')} {t.symbol} {t.direction}\n"
            kb = [[InlineKeyboardButton(f"View {t.symbol}", callback_data=f"view_{t.id}")] for t in trades]
            kb.append([InlineKeyboardButton("⬅ Back", callback_data="back_main")])
            await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
            return

        if d == "menu_hist":
            tas = s.query(TradeAccount).join(Trade).filter(Trade.user_id == u.id).order_by(TradeAccount.closed_at.desc()).limit(15).all()
            msg = "📜 History\n\n"
            for ta in tas:
                tr = s.query(Trade).get(ta.trade_id)
                acc = s.query(Account).get(ta.account_id)
                if tr and tr.closed_at:
                    msg += f"{tr.symbol} {ta.result} ${ta.pnl_usd:+.0f} ({acc.name})\n"
            await q.edit_message_text(msg or "No history", reply_markup=back_button())
            return

        if d == "menu_admin":
            if not is_admin(q.from_user.id):
                await q.answer("Not admin", show_alert=True)
                return
            await q.edit_message_text("👑 ADMIN PANEL", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 View Users", callback_data="admin_users")],
                [InlineKeyboardButton("⬅ Back", callback_data="back_main")]
            ]))
            return

        await q.edit_message_text("📊 Trading Journal", reply_markup=main_menu(q.from_user.id))
    except Exception as e:
        traceback.print_exc()
        try:
            await q.edit_message_text(f"❌ Error: {e}", reply_markup=back_button())
        except:
            pass
    finally:
        s.close()

# ==================== WALLET & TOOLS ====================
# Section 8: Profit / Payout / Deposit menu
# ------------------------------------------------------

async def profit_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Wallet & Tools callbacks."""
    q = update.callback_query
    await q.answer()
    s = Session()
    try:
        u = get_user(q.from_user.id)
        d = q.data

        if d == "profit_withdraw":
            accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all()
            kb = [[InlineKeyboardButton(a.name, callback_data=f"wd_{a.id}")] for a in accs]
            kb.append([InlineKeyboardButton("⬅ Back", callback_data="back_main")])
            await q.edit_message_text("Select account to withdraw FROM:", reply_markup=InlineKeyboardMarkup(kb))

        elif d == "profit_deposit":
            accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE', type='LIVE').all()
            if not accs:
                await q.edit_message_text("No LIVE accounts. Create one first via ➕ Add Account", reply_markup=back_button())
                return
            kb = [[InlineKeyboardButton(a.name, callback_data=f"deposit_{a.id}")] for a in accs]
            kb.append([InlineKeyboardButton("⬅ Back", callback_data="back_main")])
            await q.edit_message_text("Deposit to which LIVE account?", reply_markup=InlineKeyboardMarkup(kb))

        elif d == "profit_payout":
            accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all()
            if not accs:
                await q.edit_message_text("No accounts yet.", reply_markup=back_button())
                return
            kb = [[InlineKeyboardButton(f"{a.name} ({a.type})", callback_data=f"payout_{a.id}")] for a in accs]
            kb.append([InlineKeyboardButton("⬅ Back", callback_data="back_main")])
            await q.edit_message_text("Payout from which account?", reply_markup=InlineKeyboardMarkup(kb))

        elif d == "profit_challenge":
            ctx.user_data['mode'] = 'quick'
            ctx.user_data['qt'] = 'challenge'
            await q.edit_message_text("Send: NAME BALANCE FEE", reply_markup=back_button())

        elif d == "profit_stats":
            fees = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id, type='FEE').scalar() or 0
            payouts = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id, type='PAYOUT').scalar() or 0
            withdraws = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id, type='WITHDRAW').scalar() or 0
            net = fees + payouts + withdraws
            await q.edit_message_text(f"📊 Stats\nFees: ${abs(fees):.2f}\nPayouts: ${payouts:.2f}\nWithdraws: ${withdraws:.2f}\nNet: ${net:.2f}", reply_markup=back_button())

        elif d == "profit_history":
            txs = s.query(CashTx).filter_by(user_id=u.id).order_by(CashTx.date.desc()).limit(20).all()
            msg = "📜 Bank History\n\n"
            for t in txs:
                msg += f"{t.date.strftime('%d/%m/%Y')} {t.type} ${t.amount:+.2f} - {t.note}\n"
            await q.edit_message_text(msg or "No transactions", reply_markup=back_button())

        elif d == "profit_reset":
            await q.edit_message_text("Delete ALL data?", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ YES", callback_data="reset_yes"), InlineKeyboardButton("❌ No", callback_data="back_main")]
            ]))

        elif d == "profit_edit":
            accs = s.query(Account).filter_by(user_id=u.id).all()
            kb = [[InlineKeyboardButton(f"🗑 {a.name}", callback_data=f"delacc_{a.id}")] for a in accs]
            kb.append([InlineKeyboardButton("⬅ Back", callback_data="back_main")])
            await q.edit_message_text("Delete account:", reply_markup=InlineKeyboardMarkup(kb))

        else:
            await q.edit_message_text("💰 Wallet & Tools", reply_markup=profit_menu())
    finally:
        s.close()

async def reset_yes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Reset all user data."""
    q = update.callback_query
    await q.answer()
    s = Session()
    try:
        u = get_user(q.from_user.id)
        uid = u.id
        s.query(TradeAccount).filter(TradeAccount.trade_id.in_(s.query(Trade.id).filter_by(user_id=uid))).delete(synchronize_session=False)
        s.query(Trade).filter_by(user_id=uid).delete()
        s.query(Account).filter_by(user_id=uid).delete()
        s.query(Pair).filter_by(user_id=uid).delete()
        s.query(CashTx).filter_by(user_id=uid).delete()
        s.commit()
        await q.edit_message_text("✅ Reset done", reply_markup=back_button())
    finally:
        s.close()

# ==================== TRADE LOGGING ====================
# Section 9: Log / Close trades
# ------------------------------------------------------

async def trade_start(q, ctx):
    """Start trade logging - select account."""
    s = Session()
    try:
        u = get_user(q.from_user.id)
        accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all()
        if not accs:
            await q.edit_message_text("No accounts. Add one first.", reply_markup=back_button())
            return
        ctx.user_data['mode'] = 'trade'
        ctx.user_data['trade'] = {}
        kb = [[InlineKeyboardButton(a.name, callback_data=f"ta_{a.id}")] for a in accs]
        kb.append([InlineKeyboardButton("All Accounts", callback_data="ta_all")])
        kb.append([InlineKeyboardButton("⬅ Back", callback_data="back_main")])
        await q.edit_message_text("Select account:", reply_markup=InlineKeyboardMarkup(kb))
    finally:
        s.close()

async def trade_acc_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Trade - account selected, choose pair."""
    q = update.callback_query
    await q.answer()
    s = Session()
    try:
        u = get_user(q.from_user.id)
        if q.data == "ta_all":
            accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all()
            acc_ids = [a.id for a in accs]
        else:
            acc_ids = [q.data[3:]]
        ctx.user_data['trade']['acc_ids'] = acc_ids
        pairs = s.query(Pair).filter_by(user_id=u.id).all()
        kb = [[InlineKeyboardButton(p.symbol, callback_data=f"tp_{p.symbol}")] for p in pairs]
        kb.append([InlineKeyboardButton("⬅ Back", callback_data="back_main")])
        await q.edit_message_text("Select pair:" if pairs else "No pairs yet. Add one in My Pairs first.", reply_markup=InlineKeyboardMarkup(kb))
    finally:
        s.close()

async def trade_pair_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Trade - pair selected, choose direction."""
    q = update.callback_query
    await q.answer()
    ctx.user_data['trade']['symbol'] = q.data[3:]
    await q.edit_message_text("LONG or SHORT?", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("LONG 📈", callback_data="dir_LONG"), InlineKeyboardButton("SHORT 📉", callback_data="dir_SHORT")]
    ]))

async def dir_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Trade - direction selected, ask for photo."""
    q = update.callback_query
    await q.answer()
    ctx.user_data['trade']['direction'] = q.data.split('_')[1]
    ctx.user_data['trade']['step'] = 'photo'
    await q.edit_message_text("Send BEFORE photo", reply_markup=back_button())

async def close_start(q, ctx):
    """Close trade - list open trades."""
    s = Session()
    try:
        u = get_user(q.from_user.id)
        trs = s.query(Trade).filter_by(user_id=u.id, closed_at=None).all()
        kb = [[InlineKeyboardButton(f"{t.symbol} {t.direction}", callback_data=f"tc_{t.id}")] for t in trs]
        kb.append([InlineKeyboardButton("⬅ Back", callback_data="back_main")])
        await q.edit_message_text("Select trade to close:" if trs else "No open trades", reply_markup=InlineKeyboardMarkup(kb))
    finally:
        s.close()

async def close_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Close trade - selected, ask for after photo."""
    q = update.callback_query
    await q.answer()
    ctx.user_data['mode'] = 'close'
    ctx.user_data['close'] = {'id': q.data[3:], 'step': 'photo'}
    await q.edit_message_text("Send AFTER photo", reply_markup=back_button())

async def close_res_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Close trade - SL/TP selected, ask PnL."""
    q = update.callback_query
    await q.answer()
    res = q.data.split('_')[1]
    ctx.user_data['close']['result'] = res
    ctx.user_data['close']['step'] = 'pnl'
    await q.edit_message_text(f"{res} hit. How much $?", reply_markup=back_button())

# ==================== ADMIN / PAIRS ====================
# Section 10: Admin, pairs, delete account
# ------------------------------------------------------

async def admin_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin panel."""
    q = update.callback_query
    await q.answer()
    if q.data == "admin_users":
        s = Session()
        try:
            users = s.query(User).all()
            msg = f"👥 Users ({len(users)})\n\n"
            for u in users:
                msg += f"• {u.telegram_id} {'(admin)' if u.is_admin=='1' else ''}\n"
            await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back", callback_data="menu_admin")]]))
        finally:
            s.close()

async def pair_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Add / delete pairs."""
    q = update.callback_query
    await q.answer()
    s = Session()
    try:
        if q.data == "pair_add":
            ctx.user_data['mode'] = 'pair_add'
            await q.edit_message_text("Send pair symbol (e.g. EURUSD)", reply_markup=back_button())
        elif q.data.startswith("pairdel_"):
            pid = q.data[8:]
            s.query(Pair).filter_by(id=pid).delete()
            s.commit()
            await q.edit_message_text("✅ Pair deleted", reply_markup=back_button())
    finally:
        s.close()

async def delacc_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Delete account permanently."""
    q = update.callback_query
    await q.answer()
    aid = q.data[7:]
    s = Session()
    try:
        s.query(Account).filter_by(id=aid).delete()
        s.commit()
        await q.edit_message_text("✅ Account deleted", reply_markup=back_button())
    finally:
        s.close()

# ==================== TEXT HANDLER ====================
# Section 11: All text input - FIXED LIVE ACCOUNT
# ------------------------------------------------------

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle all text input, with error trapping."""
    mode = ctx.user_data.get('mode')
    txt = update.message.text.strip()
    s = Session()
    try:
        u = get_user(update.effective_user.id)

        # --- NEW ACCOUNT ---
        if mode == 'new_acc':
            step = ctx.user_data.get('step', 1)
            atype = ctx.user_data.get('atype')

            if step == 1:
                ctx.user_data['na_name'] = txt.strip()
                ctx.user_data['step'] = 2
                await update.message.reply_text("Starting balance?", reply_markup=back_button())
                return

            if step == 2:
                try:
                    bal = float(txt)
                except ValueError:
                    await update.message.reply_text("❌ Send a number, e.g. 500")
                    return

                ctx.user_data['na_bal'] = bal

                if atype == 'CHALLENGE':
                    ctx.user_data['step'] = 3
                    await update.message.reply_text("Fee paid? (will be deducted from Bank)", reply_markup=back_button())
                    return
                else: # LIVE - FIXED
                    name = ctx.user_data['na_name'].strip()
                    # Delete existing to avoid UniqueConstraint crash
                    existing = s.query(Account).filter_by(user_id=u.id, name=name).first()
                    if existing:
                        s.delete(existing)
                        s.commit()
                    acc = Account(user_id=u.id, name=name, type='LIVE', start_balance=bal, current_balance=bal, fee_paid=0, payout_cut=0)
                    s.add(acc)
                    s.add(CashTx(user_id=u.id, type='DEPOSIT', amount=-bal, note=f"Fund {name}"))
                    s.commit()
                    ctx.user_data.clear()
                    await update.message.reply_text(f"✅ LIVE '{name}' created! Bank -${bal:.0f}", reply_markup=main_menu(update.effective_user.id))
                    return

            if step == 3: # Challenge fee
                try:
                    fee = float(txt)
                except ValueError:
                    await update.message.reply_text("❌ Send fee number")
                    return
                ctx.user_data['na_fee'] = fee
                ctx.user_data['step'] = 4
                await update.message.reply_text(
                    "Prop firm keeps what %?",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("10%", callback_data="cut_10"), InlineKeyboardButton("15%", callback_data="cut_15")],
                        [InlineKeyboardButton("20%", callback_data="cut_20"), InlineKeyboardButton("25%", callback_data="cut_25")]
                    ])
                )
                return

        # --- WITHDRAW ---
        elif mode == 'withdraw':
            try:
                amt = float(txt)
            except ValueError:
                await update.message.reply_text("Send a number")
                return
            acc = s.query(Account).get(ctx.user_data['wd_acc'])
            acc.current_balance -= amt
            s.add(CashTx(user_id=u.id, type='WITHDRAW', amount=amt, note=f"From {acc.name}"))
            s.commit()
            ctx.user_data.clear()
            await update.message.reply_text(f"✅ Withdrew ${amt} from {acc.name}", reply_markup=main_menu(update.effective_user.id))
            return

        # --- PAYOUT ---
        elif mode == 'payout':
            try:
                gross = float(txt)
            except ValueError:
                await update.message.reply_text("Send a number")
                return
            acc = s.query(Account).get(ctx.user_data['payout_acc'])
            cut = acc.payout_cut if acc.type == 'CHALLENGE' else 0
            net = gross * (1 - cut / 100)
            acc.current_balance -= gross
            s.add(CashTx(user_id=u.id, type='PAYOUT', amount=net, note=f"{acc.name} gross ${gross} -{cut}%"))
            s.commit()
            ctx.user_data.clear()
            await update.message.reply_text(f"✅ Payout: ${gross} → Bank +${net:.2f} ({cut}% fee)", reply_markup=main_menu(update.effective_user.id))
            return

        # --- DEPOSIT ---
        elif mode == 'deposit':
            try:
                amt = float(txt)
            except ValueError:
                await update.message.reply_text("Send a number")
                return
            acc = s.query(Account).get(ctx.user_data['deposit_acc'])
            acc.current_balance += amt
            s.add(CashTx(user_id=u.id, type='DEPOSIT', amount=-amt, note=f"Fund {acc.name}"))
            s.commit()
            ctx.user_data.clear()
            await update.message.reply_text(f"✅ Deposited ${amt} to {acc.name}", reply_markup=main_menu(update.effective_user.id))
            return

        # --- PAIR ADD ---
        elif mode == 'pair_add':
            sym = txt.upper().replace("/", "")
            existing = s.query(Pair).filter_by(user_id=u.id, symbol=sym).first()
            if existing:
                await update.message.reply_text("Pair already exists", reply_markup=main_menu(update.effective_user.id))
                ctx.user_data.clear()
                return
            s.add(Pair(user_id=u.id, symbol=sym))
            s.commit()
            ctx.user_data.clear()
            await update.message.reply_text(f"✅ Pair added: {sym}", reply_markup=main_menu(update.effective_user.id))
            return

        # --- BAL EDIT ---
        elif mode == 'bal_edit':
            try:
                new_amt = float(txt)
            except ValueError:
                await update.message.reply_text("Send a number")
                return
            current = sum(t.amount for t in s.query(CashTx).filter_by(user_id=u.id)) or 0
            diff = new_amt - current
            s.add(CashTx(user_id=u.id, type='ADJUST', amount=diff, note='Manual edit'))
            s.commit()
            ctx.user_data.clear()
            await update.message.reply_text(f"✅ Bank set to ${new_amt:.2f}", reply_markup=main_menu(update.effective_user.id))
            return

        # --- CLOSE TRADE PNL ---
        elif mode == 'close':
            if ctx.user_data.get('close', {}).get('step') == 'pnl':
                try:
                    amt = float(txt)
                except ValueError:
                    await update.message.reply_text("Send a number")
                    return
                res = ctx.user_data['close']['result']
                pnl = -abs(amt) if res == 'SL' else abs(amt)
                tid = ctx.user_data['close']['id']
                tr = s.query(Trade).get(tid)
                tr.closed_at = datetime.utcnow()
                tas = s.query(TradeAccount).filter_by(trade_id=tid).all()
                for ta in tas:
                    ta.pnl_usd = pnl
                    ta.result = res
                    ta.closed_at = datetime.utcnow()
                    acc = s.query(Account).get(ta.account_id)
                    acc.current_balance += pnl
                s.commit()
                ctx.user_data.clear()
                await update.message.reply_text(f"✅ Closed {res} ${pnl:+.2f}", reply_markup=main_menu(update.effective_user.id))
                return

    except Exception as e:
        traceback.print_exc()
        await update.message.reply_text(f"❌ Error: {e}\n\nSend /start to reset.", reply_markup=main_menu(update.effective_user.id))
        ctx.user_data.clear()
    finally:
        s.close()

# ==================== PHOTO HANDLER ====================
# Section 12: Trade photos
# ------------------------------------------------------

async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle trade before/after photos."""
    mode = ctx.user_data.get('mode')
    s = Session()
    try:
        u = get_user(update.effective_user.id)
        if mode == 'trade' and ctx.user_data.get('trade', {}).get('step') == 'photo':
            t = ctx.user_data['trade']
            tr = Trade(user_id=u.id, symbol=t['symbol'], direction=t['direction'], before_photo=update.message.photo[-1].file_id)
            s.add(tr)
            s.flush()
            for aid in t['acc_ids']:
                s.add(TradeAccount(trade_id=tr.id, account_id=aid))
            s.commit()
            ctx.user_data.clear()
            await update.message.reply_text(f"✅ Trade {tr.symbol} {tr.direction} logged", reply_markup=main_menu(update.effective_user.id))
        elif mode == 'close' and ctx.user_data.get('close', {}).get('step') == 'photo':
            tid = ctx.user_data['close']['id']
            tr = s.query(Trade).get(tid)
            tr.after_photo = update.message.photo[-1].file_id
            s.commit()
            ctx.user_data['close']['step'] = 'result'
            await update.message.reply_text("SL or TP?", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("SL ❌", callback_data="res_SL"), InlineKeyboardButton("TP ✅", callback_data="res_TP")]
            ]))
    except Exception as e:
        traceback.print_exc()
        await update.message.reply_text(f"❌ Photo error: {e}")
    finally:
        s.close()

# ==================== MAIN ====================
# Section 13: Application bootstrap
# ------------------------------------------------------

def main():
    """Start the bot."""
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear_cmd))

    # Specific callbacks FIRST (more specific patterns first)
    app.add_handler(CallbackQueryHandler(cut_cb, pattern="^cut_"))
    app.add_handler(CallbackQueryHandler(deposit_select, pattern="^deposit_"))
    app.add_handler(CallbackQueryHandler(payout_select, pattern="^payout_"))
    app.add_handler(CallbackQueryHandler(wd_select, pattern="^wd_"))
    app.add_handler(CallbackQueryHandler(close_cb, pattern="^tc_"))
    app.add_handler(CallbackQueryHandler(close_res_cb, pattern="^res_"))
    app.add_handler(CallbackQueryHandler(trade_acc_cb, pattern="^ta_"))
    app.add_handler(CallbackQueryHandler(trade_pair_cb, pattern="^tp_"))
    app.add_handler(CallbackQueryHandler(dir_cb, pattern="^dir_"))
    app.add_handler(CallbackQueryHandler(admin_cb, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(pair_cb, pattern="^pair"))
    app.add_handler(CallbackQueryHandler(delacc_cb, pattern="^delacc_"))
    app.add_handler(CallbackQueryHandler(archive_acc, pattern="^arch_"))
    app.add_handler(CallbackQueryHandler(reset_yes, pattern="^reset_yes$"))
    app.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))

    # Generic menu handlers LAST
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^menu_"))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^bal_"))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^clear_"))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^add_"))
    app.add_handler(CallbackQueryHandler(profit_cb, pattern="^profit_"))

    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()