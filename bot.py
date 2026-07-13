import os
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from sqlalchemy import create_engine, Column, String, Float, DateTime, ForeignKey, Text, UniqueConstraint, func, extract, text, inspect
from sqlalchemy.orm import declarative_base, sessionmaker
import uuid
import calendar
from datetime import datetime, timedelta

Base = declarative_base()

def uid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = 'users'
    id = Column(String, primary_key=True, default=uid)
    telegram_id = Column(String, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_admin = Column(String, default='0')

class Account(Base):
    __tablename__ = 'accounts'
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey('users.id'))
    name = Column(String)
    type = Column(String)
    start_balance = Column(Float)
    current_balance = Column(Float)
    fee_paid = Column(Float, default=0)
    payout_cut = Column(Float, default=20)
    status = Column(String, default='ACTIVE')
    __table_args__ = (UniqueConstraint('user_id', 'name'),)

class Pair(Base):
    __tablename__ = 'pairs'
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey('users.id'))
    symbol = Column(String)
    __table_args__ = (UniqueConstraint('user_id', 'symbol'),)

class Trade(Base):
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
    close_comment = Column(Text)
    before_comment = Column(Text)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime)

class TradeAccount(Base):
    __tablename__ = 'trade_accounts'
    trade_id = Column(String, ForeignKey('trades.id'), primary_key=True)
    account_id = Column(String, ForeignKey('accounts.id'), primary_key=True)
    pnl_usd = Column(Float)
    result = Column(String)
    closed_at = Column(DateTime)

class CashTx(Base):
    __tablename__ = 'cash_txs'
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey('users.id'))
    type = Column(String)
    amount = Column(Float)
    note = Column(Text)
    date = Column(DateTime, default=datetime.utcnow)

class Rule(Base):
    __tablename__ = 'rules'
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey('users.id'))
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    order_num = Column(Float, default=0)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./edgeflo.db")
ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",")
engine = create_engine(DATABASE_URL, future=True)
Session = sessionmaker(bind=engine)
Base.metadata.create_all(engine)
try:
    cols = [c['name'] for c in inspect(engine).get_columns('trades')]
    if 'before_comment' not in cols:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE trades ADD COLUMN before_comment TEXT"))
            conn.commit()
except:
    pass

def get_user(tid):
    s = Session()
    u = s.query(User).filter_by(telegram_id=str(tid)).first()
    if not u:
        is_first = s.query(User).count() == 0
        u = User(telegram_id=str(tid), is_admin='1' if (is_first or str(tid) in ADMIN_IDS) else '0')
        s.add(u)
        s.commit()
    s.close()
    return u

def is_admin(tid):
    s = Session()
    u = s.query(User).filter_by(telegram_id=str(tid)).first()
    s.close()
    return u and u.is_admin == '1'

# ---------------------------------------------------------------------------
# Reply keyboard helpers
#
# Every screen is rendered as a ReplyKeyboardMarkup. Because reply-keyboard
# buttons only send their visible text (they carry no callback_data), each
# screen also registers a per-screen navigation map in ctx.user_data['nav']
# that maps the button label -> (action, argument). text_handler() resolves a
# tapped button by looking it up in this map.
# ---------------------------------------------------------------------------

def rk(rows):
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def screen(ctx, rows_spec):
    """rows_spec: list of rows; each row is a list of (label, action, arg)."""
    nav = {}
    kb_rows = []
    for row in rows_spec:
        kb_row = []
        for label, action, arg in row:
            nav[label] = (action, arg)
            kb_row.append(KeyboardButton(label))
        kb_rows.append(kb_row)
    ctx.user_data['nav'] = nav
    return rk(kb_rows)

def main_menu(tid=None):
    rows = [
        [KeyboardButton("📝 Log Trade"), KeyboardButton("✅ Close Trade")],
        [KeyboardButton("💰 Balance"), KeyboardButton("⚙ My Accounts")],
        [KeyboardButton("📊 Analyse"), KeyboardButton("📖 Journal")],
        [KeyboardButton("📈 My Pairs"), KeyboardButton("📜 Trade History")],
        [KeyboardButton("🖼 Gallery"), KeyboardButton("➕ Add Account")],
        [KeyboardButton("📏 My Rules"), KeyboardButton("💰 Wallet & Tools")],
        [KeyboardButton("🗓 Calendar")],
    ]
    if tid and is_admin(tid):
        rows.append([KeyboardButton("👑 ADMIN PANEL")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def back_menu(ctx):
    return screen(ctx, [[("⬅ Back to Menu", "main", None)]])

def back_wallet(ctx):
    return screen(ctx, [[("⬅ Back to Wallet", "wallet", None)]])

async def show_main(update, ctx):
    ctx.user_data.clear()
    await update.message.reply_text("💰 My Bank", reply_markup=main_menu(update.effective_user.id))

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    get_user(update.effective_user.id)
    await show_main(update, ctx)

async def clear_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧹 Tap my name → Clear History")

async def cmd_pairs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await txt_pairs(update, ctx)

def fmt_money(v: float) -> str:
    """Format money with the sign in front of the $ sign (-$103.00 not $-103.00)."""
    return f"-${abs(v):.2f}" if v < 0 else f"${v:.2f}"

async def fixfees_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """One-shot repair: flip any legacy positive FEE / DEPOSIT rows to negative.
    FEEs and DEPOSITs are money going OUT of the bank, so they must be stored
    as negative CashTx amounts. Older versions of the bot stored them positive."""
    s = Session()
    u = get_user(update.effective_user.id)
    fixed = 0
    rows = s.query(CashTx).filter(
        CashTx.user_id == u.id,
        CashTx.type.in_(('FEE', 'DEPOSIT')),
        CashTx.amount > 0,
    ).all()
    for r in rows:
        r.amount = -r.amount
        fixed += 1
    s.commit()
    net = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id).scalar() or 0
    s.close()
    await update.message.reply_text(
        f"🔧 Repaired {fixed} legacy FEE/DEPOSIT row(s).\n"
        f"💰 Bank Balance: {fmt_money(net)}",
    )

# ---------------------------------------------------------------------------
# Main menu screens (triggered by the persistent reply keyboard)
# ---------------------------------------------------------------------------

async def txt_log(update, ctx):
    s = Session()
    u = get_user(update.effective_user.id)
    accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all()
    s.close()
    if not accs:
        await update.message.reply_text("⚠ No active accounts. Add one first.", reply_markup=main_menu(update.effective_user.id))
        return
    ctx.user_data['mode'] = 'trade'
    ctx.user_data['trade'] = {}
    rows = [[(a.name, "trade_acc", a.id)] for a in accs]
    rows.append([("All Accounts", "trade_acc", "all")])
    rows.append([("⬅ Back to Menu", "main", None)])
    await update.message.reply_text("Select account:", reply_markup=screen(ctx, rows))

async def txt_close(update, ctx):
    s = Session()
    u = get_user(update.effective_user.id)
    trs = s.query(Trade).filter_by(user_id=u.id, closed_at=None).all()
    s.close()
    if not trs:
        await update.message.reply_text("No open trades", reply_markup=main_menu(update.effective_user.id))
        return
    ctx.user_data.pop('mode', None)
    rows = [[(f"{i+1}. {t.symbol} {t.direction}", "close_trade", t.id)] for i, t in enumerate(trs)]
    rows.append([("⬅ Back to Menu", "main", None)])
    await update.message.reply_text("Select trade to close:", reply_markup=screen(ctx, rows))

async def txt_balance(update, ctx):
    s = Session()
    u = get_user(update.effective_user.id)
    net = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id).scalar() or 0
    s.close()
    ctx.user_data.pop('mode', None)
    rows = [[("✏ Edit", "bal_edit", None), ("🔄 Reset", "bal_reset", None)],
            [("⬅ Back to Menu", "main", None)]]
    await update.message.reply_text(f"💰 Bank Balance: {fmt_money(net)}", reply_markup=screen(ctx, rows))

async def txt_accounts(update, ctx):
    s = Session()
    u = get_user(update.effective_user.id)
    accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all()
    arch = s.query(Account).filter_by(user_id=u.id, status='ARCHIVED').all()
    msg = "⚙ Active Accounts\n\n"
    for a in accs:
        cut = f" -{a.payout_cut}%" if a.type == 'CHALLENGE' else ""
        msg += f"🟢 {a.name} ({a.type}{cut}) - ${a.current_balance:.0f}\n"
    msg += "\n📦 Archived:\n"
    for a in arch:
        msg += f"• {a.name}\n"
    rows = []
    for a in accs:
        row = [(f"📦 Archive {a.name}", "archive", a.id)]
        if a.type == 'CHALLENGE':
            row.append((f"✏ Cut {a.name}", "cut_edit", a.id))
        rows.append(row)
    rows.append([("⬅ Back to Menu", "main", None)])
    s.close()
    ctx.user_data.pop('mode', None)
    await update.message.reply_text(msg, reply_markup=screen(ctx, rows))

async def txt_analyse(update, ctx):
    ctx.user_data.pop('mode', None)
    rows = [
        [("📅 Today", "analyse", "today"), ("📆 This Week", "analyse", "week")],
        [("🗓 This Month", "analyse", "month"), ("📆 Last Month", "analyse", "lastmonth")],
        [("📈 This Year", "analyse", "year"), ("🌍 All Time", "analyse", "all")],
        [("🗓 Calendar", "calendar", None)],
        [("⬅ Back to Menu", "main", None)],
    ]
    await update.message.reply_text("📊 Analyse - Choose period", reply_markup=screen(ctx, rows))

async def txt_journal(update, ctx):
    s = Session()
    u = get_user(update.effective_user.id)
    trades = s.query(Trade).filter_by(user_id=u.id).order_by(Trade.opened_at.desc()).all()
    s.close()
    months = {}
    for t in trades:
        key = (t.opened_at.year, t.opened_at.month)
        months[key] = months.get(key, 0) + 1
    if not months:
        await update.message.reply_text("📖 No trades yet", reply_markup=back_menu(ctx))
        return
    ctx.user_data.pop('mode', None)
    rows = []
    for (year, month), count in sorted(months.items(), reverse=True):
        month_name = calendar.month_name[month]
        rows.append([(f"{month_name} {year} ({count} trades)", "journal_month", (year, month))])
    rows.append([("⬅ Back to Menu", "main", None)])
    await update.message.reply_text("📖 Journal - Select Month", reply_markup=screen(ctx, rows))

async def txt_pairs(update, ctx):
    s = Session()
    u = get_user(update.effective_user.id)
    pairs = s.query(Pair).filter_by(user_id=u.id).all()
    s.close()
    ctx.user_data.pop('mode', None)
    rows = [[(f"❌ {p.symbol}", "pairdel", p.id)] for p in pairs]
    rows.append([("➕ Add Pair", "pair_add", None)])
    rows.append([("⬅ Back to Menu", "main", None)])
    await update.message.reply_text("📈 My Pairs", reply_markup=screen(ctx, rows))

async def txt_hist(update, ctx):
    s = Session()
    u = get_user(update.effective_user.id)
    tas = s.query(TradeAccount).join(Trade).filter(Trade.user_id == u.id).filter(TradeAccount.closed_at != None).order_by(TradeAccount.closed_at.desc()).limit(20).all()
    msg = "📜 Trade History\n\n"
    for ta in tas:
        tr = s.query(Trade).get(ta.trade_id)
        acc = s.query(Account).get(ta.account_id)
        if tr and ta.pnl_usd is not None:
            msg += f"{tr.opened_at.strftime('%d %b %Y')} {tr.symbol} {ta.result or ''} ${ta.pnl_usd:+.0f} ({acc.name})\n"
    s.close()
    ctx.user_data.pop('mode', None)
    await update.message.reply_text(msg or "No history yet", reply_markup=back_menu(ctx))

async def txt_gallery(update, ctx):
    ctx.user_data.pop('mode', None)
    rows = [
        [("📅 Today", "gallery", "today"), ("📆 This Week", "gallery", "week")],
        [("🗓 This Month", "gallery", "month"), ("📈 This Year", "gallery", "year")],
        [("🌍 All Trades", "gallery", "all")],
        [("⬅ Back to Menu", "main", None)],
    ]
    await update.message.reply_text("🖼 Gallery - Choose period", reply_markup=screen(ctx, rows))

async def txt_add(update, ctx):
    ctx.user_data.pop('mode', None)
    rows = [[("💼 Live", "add_live", None), ("🎯 Challenge", "add_challenge", None)],
            [("⬅ Back to Menu", "main", None)]]
    await update.message.reply_text("Choose type:", reply_markup=screen(ctx, rows))

async def txt_profit(update, ctx):
    await show_wallet(update, ctx)

async def txt_admin(update, ctx):
    ctx.user_data.pop('mode', None)
    rows = [[("👥 Users", "admin_users", None)], [("⬅ Back to Menu", "main", None)]]
    await update.message.reply_text("👑 ADMIN", reply_markup=screen(ctx, rows))

async def txt_rules(update, ctx):
    await show_rules(update, ctx)

# ---------------------------------------------------------------------------
# Wallet & Tools
# ---------------------------------------------------------------------------

async def show_wallet(update, ctx):
    ctx.user_data.pop('mode', None)
    rows = [
        [("📉 Starting Balance", "profit_starting", None)],
        [("💳 Challenge Buy", "profit_challenge", None), ("💰 Live Deposit", "profit_deposit", None)],
        [("💸 Log Payout", "profit_payout", None), ("💵 Withdraw", "profit_withdraw", None)],
        [("📊 View Stats", "profit_stats", None), ("🗑 Edit/Delete", "profit_edit", None)],
        [("🔄 Reset All", "profit_reset", None), ("📜 Bank History", "profit_history", None)],
        [("🧹 Clean View", "clear_chat", None)],
        [("⬅ Back to Menu", "main", None)],
    ]
    await update.message.reply_text("💰 Wallet & Tools", reply_markup=screen(ctx, rows))

async def show_rules(update, ctx):
    s = Session()
    u = get_user(update.effective_user.id)
    rules = s.query(Rule).filter_by(user_id=u.id).order_by(Rule.order_num, Rule.created_at).all()
    s.close()
    if not rules:
        msg = "📏 My Rules\n\nNo rules yet."
    else:
        msg = "📏 My Rules\n\n" + "\n\n".join([f"{i}. {r.text}" for i, r in enumerate(rules, 1)])
    ctx.user_data.pop('mode', None)
    rows = []
    for i, r in enumerate(rules, 1):
        rows.append([(f"✏ {i}", "rule_edit", r.id), (f"🗑 {i}", "rule_del", r.id)])
    rows.append([("➕ Add Rule", "rule_add", None)])
    rows.append([("⬅ Back to Menu", "main", None)])
    await update.message.reply_text(msg, reply_markup=screen(ctx, rows))

# ---------------------------------------------------------------------------
# Trade logging flow
# ---------------------------------------------------------------------------

async def act_trade_acc(update, ctx, arg):
    s = Session()
    u = get_user(update.effective_user.id)
    if arg == "all":
        accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all()
        acc_ids = [a.id for a in accs]
    else:
        acc_ids = [arg]
    ctx.user_data.setdefault('trade', {})
    ctx.user_data['trade']['acc_ids'] = acc_ids
    pairs = s.query(Pair).filter_by(user_id=u.id).all()
    s.close()
    rows = [[(p.symbol, "trade_pair", p.symbol)] for p in pairs]
    rows.append([("⬅ Back to Menu", "main", None)])
    await update.message.reply_text("Select pair:", reply_markup=screen(ctx, rows))

async def act_trade_pair(update, ctx, arg):
    ctx.user_data.setdefault('trade', {})
    ctx.user_data['trade']['symbol'] = arg
    rows = [[("LONG 📈", "dir", "LONG"), ("SHORT 📉", "dir", "SHORT")],
            [("⬅ Back to Menu", "main", None)]]
    await update.message.reply_text("LONG or SHORT?", reply_markup=screen(ctx, rows))

async def act_dir(update, ctx, arg):
    ctx.user_data.setdefault('trade', {})
    ctx.user_data['trade']['direction'] = arg
    ctx.user_data['trade']['step'] = 'photo'
    await update.message.reply_text("Send BEFORE photo", reply_markup=back_menu(ctx))

# ---------------------------------------------------------------------------
# Close trade flow
# ---------------------------------------------------------------------------

async def act_close_trade(update, ctx, arg):
    ctx.user_data['mode'] = 'close'
    ctx.user_data['close'] = {'id': arg, 'step': 'photo'}
    # If this trade already has an AFTER photo (e.g. reopening a partially
    # closed multi-account trade), don't ask for the same image again.
    s = Session()
    tr = s.query(Trade).get(arg)
    has_photo = bool(tr and tr.after_photo)
    s.close()
    if has_photo:
        ctx.user_data['close']['step'] = 'result'
        rows = [[("SL ❌", "close_res", "SL"), ("BE ➖", "close_res", "BE"), ("TP ✅", "close_res", "TP")]]
        await update.message.reply_text("AFTER photo already saved. Close as?", reply_markup=screen(ctx, rows))
    else:
        await update.message.reply_text("Send AFTER photo", reply_markup=back_menu(ctx))


async def act_close_res(update, ctx, arg):
    try:
        res = arg
        if 'close' not in ctx.user_data:
            ctx.user_data['close'] = {}
        ctx.user_data['close']['result'] = res
        if 'id' not in ctx.user_data['close']:
            await update.message.reply_text("⚠ Session expired. Please select Close Trade again.", reply_markup=back_menu(ctx))
            return
        tid = ctx.user_data['close']['id']
        s = Session()
        tas = s.query(TradeAccount).filter_by(trade_id=tid).all()
        s.close()
        if not tas:
            await update.message.reply_text("❌ No accounts linked.", reply_markup=back_menu(ctx))
            return
        ctx.user_data['close']['tas'] = {ta.account_id: ta.pnl_usd for ta in tas}
        await show_close_accounts_menu(update, ctx)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}", reply_markup=back_menu(ctx))

async def show_close_accounts_menu(update, ctx):
    res = ctx.user_data['close']['result']
    acc_pnls = ctx.user_data['close']['tas']
    s = Session()
    rows = []
    filled = 0
    total = 0
    for acc_id, pnl in acc_pnls.items():
        acc = s.query(Account).get(acc_id)
        if not acc:
            continue
        total += 1
        if pnl is None:
            rows.append([(f"[ ] {acc.name}", "closeacc", acc_id)])
        else:
            filled += 1
            rows.append([(f"[✅ ${pnl:+.0f}] {acc.name}", "closeacc", acc_id)])
    # Always allow finishing early: close the accounts filled so far,
    # leave the rest open to close later.
    if filled > 0:
        rows.append([("✅ DONE - Add Comment", "closeacc_done", None)])
    rows.append([("⬅ Back to Menu", "main", None)])
    s.close()
    ctx.user_data['mode'] = 'close'
    hint = f"{res} hit. Tap each account to set PnL ({filled}/{total} done).\nTap DONE anytime — unfilled accounts stay open."
    await update.message.reply_text(hint, reply_markup=screen(ctx, rows))


async def act_closeacc(update, ctx, arg):
    acc_id = arg
    ctx.user_data['mode'] = 'close_pnl'
    ctx.user_data['close']['current_acc'] = acc_id
    s = Session()
    acc = s.query(Account).get(acc_id)
    s.close()
    rows = [[("⬅ Back", "closeacc_back", None)]]
    await update.message.reply_text(
        f"Enter PnL for {acc.name} (use -50 or +120):\nCurrent: ${acc.current_balance:.2f}",
        reply_markup=screen(ctx, rows))

async def act_closeacc_back(update, ctx, arg):
    ctx.user_data['mode'] = 'close'
    await show_close_accounts_menu(update, ctx)

async def act_closeacc_done(update, ctx, arg):
    ctx.user_data['mode'] = 'await_comment'
    rows = [[("⏭ Skip", "comment_skip", None)]]
    await update.message.reply_text("✍ Add closing note? (optional)", reply_markup=screen(ctx, rows))

async def act_comment_skip(update, ctx, arg):
    await finalize_trade(update, ctx, None)

async def finalize_trade(update, ctx, comment):
    tid = ctx.user_data['close']['id']
    s = Session()
    tr = s.query(Trade).get(tid)
    result = ctx.user_data['close']['result']
    closed_now = 0
    for acc_id, pnl in ctx.user_data['close']['tas'].items():
        if pnl is None:
            continue  # leave unfilled accounts open
        ta = s.query(TradeAccount).filter_by(trade_id=tid, account_id=acc_id).first()
        if not ta or ta.closed_at is not None:
            continue  # skip already-closed accounts (no double counting)
        ta.pnl_usd = pnl
        ta.result = result
        ta.closed_at = datetime.utcnow()
        acc = s.query(Account).get(acc_id)
        acc.current_balance += pnl
        closed_now += 1
    # Only close the whole trade once every account is closed.
    open_remaining = s.query(TradeAccount).filter_by(trade_id=tid, closed_at=None).count()
    if open_remaining == 0:
        tr.closed_at = datetime.utcnow()
        tr.close_comment = comment
    s.commit()
    s.close()
    user_id = update.effective_user.id
    ctx.user_data.clear()
    if open_remaining == 0:
        txt = "✅ Trade fully closed"
        if comment:
            txt += f"\n💬 {comment}"
    else:
        txt = f"✅ Closed {closed_now} account(s).\n⏳ {open_remaining} still open — pick this trade again in Close Trade to finish."
    await update.message.reply_text(txt, reply_markup=main_menu(user_id))


# ---------------------------------------------------------------------------
# Wallet actions
# ---------------------------------------------------------------------------

async def act_profit_starting(update, ctx, arg):
    s = Session()
    u = get_user(update.effective_user.id)
    init = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id, type='INITIAL').scalar() or 0
    s.close()
    ctx.user_data['mode'] = 'starting_balance'
    await update.message.reply_text(
        f"📉 Current Starting Balance: ${init:+.2f}\n\nSend your REAL P/L before using this bot.\n\nExamples:\n-10000 -> you lost 10k\n0 -> fresh start\n3500 -> you were up 3.5k\n\nJust send the number:",
        reply_markup=back_wallet(ctx))

async def act_profit_challenge(update, ctx, arg):
    ctx.user_data['mode'] = 'quick'
    ctx.user_data['qt'] = 'challenge'
    await update.message.reply_text("Send: NAME BALANCE FEE", reply_markup=back_wallet(ctx))

async def act_profit_deposit(update, ctx, arg):
    s = Session()
    u = get_user(update.effective_user.id)
    accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE', type='LIVE').all()
    s.close()
    rows = [[(a.name, "deposit_pick", a.id)] for a in accs]
    rows.append([("⬅ Back to Wallet", "wallet", None)])
    await update.message.reply_text("Deposit to which LIVE account?", reply_markup=screen(ctx, rows))

async def act_profit_withdraw(update, ctx, arg):
    s = Session()
    u = get_user(update.effective_user.id)
    accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all()
    s.close()
    rows = [[(a.name, "wd_pick", a.id)] for a in accs]
    rows.append([("⬅ Back to Wallet", "wallet", None)])
    await update.message.reply_text("Select account to withdraw FROM:", reply_markup=screen(ctx, rows))

async def act_profit_payout(update, ctx, arg):
    s = Session()
    u = get_user(update.effective_user.id)
    accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all()
    s.close()
    rows = [[(f"{a.name} ({a.type})", "payout_pick", a.id)] for a in accs]
    rows.append([("⬅ Back to Wallet", "wallet", None)])
    await update.message.reply_text("Payout from which account?", reply_markup=screen(ctx, rows))

async def act_profit_stats(update, ctx, arg):
    s = Session()
    u = get_user(update.effective_user.id)
    fees = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id, type='FEE').scalar() or 0
    deposits = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id, type='DEPOSIT').scalar() or 0
    payouts = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id, type='PAYOUT').scalar() or 0
    withdraws = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id, type='WITHDRAW').scalar() or 0
    initial = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id, type='INITIAL').scalar() or 0
    net = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id).scalar() or 0
    s.close()
    await update.message.reply_text(
        f"📊 Stats\nStarting (Old): ${initial:+.2f}\nFees: ${abs(fees):.2f}\nLive Capital: ${abs(deposits):.2f}\nPayouts: ${payouts:.2f}\nWithdraws: ${abs(withdraws):.2f}\n-----------------\nNet Real: ${net:.2f}",
        reply_markup=back_wallet(ctx))

async def act_profit_history(update, ctx, arg):
    s = Session()
    u = get_user(update.effective_user.id)
    txs = s.query(CashTx).filter_by(user_id=u.id).order_by(CashTx.date.desc()).limit(20).all()
    if not txs:
        s.close()
        await update.message.reply_text("No transactions", reply_markup=back_wallet(ctx))
        return
    lines = ["📜 Bank History", ""]
    for t in txs:
        lines.append(f"{t.date.strftime('%d/%m %H:%M')}  {t.type:<8} {t.amount:+.2f}  {t.note or ''}")
    s.close()
    rows = [
        [("✏ Edit Entry", "tx_pick", None)],
        [("⬅ Back to Wallet", "wallet", None)],
    ]
    await update.message.reply_text("\n".join(lines), reply_markup=screen(ctx, rows))

async def act_tx_pick(update, ctx, arg):
    s = Session()
    u = get_user(update.effective_user.id)
    txs = s.query(CashTx).filter_by(user_id=u.id).order_by(CashTx.date.desc()).limit(20).all()
    rows = []
    for t in txs:
        label = f"{t.date.strftime('%d/%m')} {t.type} {t.amount:+.2f}"
        rows.append([(label, "tx_view", t.id)])
    rows.append([("⬅ Back to History", "profit_history", None)])
    s.close()
    await update.message.reply_text("Pick a transaction to edit:", reply_markup=screen(ctx, rows))

async def act_tx_view(update, ctx, arg):
    s = Session()
    tx = s.query(CashTx).get(int(arg))
    if not tx:
        s.close()
        await update.message.reply_text("Not found", reply_markup=back_wallet(ctx))
        return
    info = (f"📝 Edit Transaction\n"
            f"Date: {tx.date.strftime('%d/%m/%Y %H:%M')}\n"
            f"Type: {tx.type}\n"
            f"Amount: {tx.amount:+.2f}\n"
            f"Note: {tx.note}")
    s.close()
    rows = [
        [("✏ Edit Amount", "tx_edit_amt", str(arg)), ("✏ Edit Note", "tx_edit_note", str(arg))],
        [("🔄 Flip Sign (+/-)", "tx_flip", str(arg)), ("🗑 Delete", "tx_del", str(arg))],
        [("⬅ Back to History", "profit_history", None)],
    ]
    await update.message.reply_text(info, reply_markup=screen(ctx, rows))

async def act_tx_edit_amt(update, ctx, arg):
    ctx.user_data['mode'] = 'tx_edit_amt'
    ctx.user_data['tx_id'] = int(arg)
    await update.message.reply_text("Send new amount (use - for money going OUT, e.g. -103 for a fee):", reply_markup=back_wallet(ctx))

async def act_tx_edit_note(update, ctx, arg):
    ctx.user_data['mode'] = 'tx_edit_note'
    ctx.user_data['tx_id'] = int(arg)
    await update.message.reply_text("Send new note text:", reply_markup=back_wallet(ctx))

async def act_tx_flip(update, ctx, arg):
    s = Session()
    tx = s.query(CashTx).get(int(arg))
    if tx:
        tx.amount = -tx.amount
        s.commit()
        amt = tx.amount
    s.close()
    await update.message.reply_text(f"✅ Sign flipped. New amount: {amt:+.2f}", reply_markup=back_wallet(ctx))

async def act_tx_del(update, ctx, arg):
    rows = [[("✅ YES delete", "tx_del_yes", str(arg)), ("❌ No", "tx_view", str(arg))]]
    await update.message.reply_text("Delete this transaction?", reply_markup=screen(ctx, rows))

async def act_tx_del_yes(update, ctx, arg):
    s = Session()
    tx = s.query(CashTx).get(int(arg))
    if tx:
        s.delete(tx)
        s.commit()
    s.close()
    await update.message.reply_text("🗑 Deleted", reply_markup=back_wallet(ctx))
    await act_profit_history(update, ctx, None)

async def act_profit_reset(update, ctx, arg):
    rows = [[("✅ YES", "reset_yes", None), ("❌ No", "wallet", None)]]
    await update.message.reply_text("Delete ALL data?", reply_markup=screen(ctx, rows))

async def act_profit_edit(update, ctx, arg):
    s = Session()
    u = get_user(update.effective_user.id)
    accs = s.query(Account).filter_by(user_id=u.id).all()
    s.close()
    rows = [[(f"🗑 {a.name}", "delacc", a.id)] for a in accs]
    rows.append([("⬅ Back to Wallet", "wallet", None)])
    await update.message.reply_text("Delete account:", reply_markup=screen(ctx, rows))

async def act_clear_chat(update, ctx, arg):
    await update.message.reply_text("🧹 Tap my name → Clear History.", reply_markup=back_menu(ctx))

async def act_reset_yes(update, ctx, arg):
    s = Session()
    u = get_user(update.effective_user.id)
    uid_ = u.id
    s.query(TradeAccount).filter(TradeAccount.trade_id.in_(s.query(Trade.id).filter_by(user_id=uid_))).delete(synchronize_session=False)
    s.query(Trade).filter_by(user_id=uid_).delete()
    s.query(Account).filter_by(user_id=uid_).delete()
    s.query(Pair).filter_by(user_id=uid_).delete()
    s.query(CashTx).filter_by(user_id=uid_).delete()
    s.query(Rule).filter_by(user_id=uid_).delete()
    s.commit()
    s.close()
    ctx.user_data.clear()
    await update.message.reply_text("✅ Reset done", reply_markup=back_menu(ctx))

async def act_wd_pick(update, ctx, arg):
    ctx.user_data['mode'] = 'withdraw'
    ctx.user_data['wd_acc'] = arg
    await update.message.reply_text("Amount to withdraw to bank?", reply_markup=back_wallet(ctx))

async def act_payout_pick(update, ctx, arg):
    ctx.user_data['mode'] = 'payout'
    ctx.user_data['payout_acc'] = arg
    await update.message.reply_text("Gross payout amount?", reply_markup=back_wallet(ctx))

async def act_deposit_pick(update, ctx, arg):
    ctx.user_data['mode'] = 'deposit'
    ctx.user_data['deposit_acc'] = arg
    await update.message.reply_text("How much to deposit?", reply_markup=back_wallet(ctx))

# ---------------------------------------------------------------------------
# Balance actions
# ---------------------------------------------------------------------------

async def act_bal_edit(update, ctx, arg):
    ctx.user_data['mode'] = 'bal_edit'
    await update.message.reply_text("Enter new bank balance:", reply_markup=back_menu(ctx))

async def act_bal_reset(update, ctx, arg):
    rows = [[("✅ Yes", "bal_reset_yes", None), ("❌ No", "balance_menu", None)]]
    await update.message.reply_text("Reset bank to $0?", reply_markup=screen(ctx, rows))

async def act_bal_reset_yes(update, ctx, arg):
    s = Session()
    u = get_user(update.effective_user.id)
    s.query(CashTx).filter_by(user_id=u.id).delete()
    s.commit()
    s.close()
    await update.message.reply_text("✅ Bank reset", reply_markup=back_menu(ctx))

async def act_balance_menu(update, ctx, arg):
    await txt_balance(update, ctx)

# ---------------------------------------------------------------------------
# Account create / archive / delete / pairs
# ---------------------------------------------------------------------------

async def act_add_live(update, ctx, arg):
    ctx.user_data['mode'] = 'new_acc'
    ctx.user_data['atype'] = 'LIVE'
    ctx.user_data['step'] = 1
    await update.message.reply_text("Live account name?", reply_markup=back_menu(ctx))

async def act_add_challenge(update, ctx, arg):
    ctx.user_data['mode'] = 'new_acc'
    ctx.user_data['atype'] = 'CHALLENGE'
    ctx.user_data['step'] = 1
    await update.message.reply_text("Challenge name? (e.g. FTMO 100k)", reply_markup=back_menu(ctx))

async def act_cut(update, ctx, arg):
    cut = float(arg)
    s = Session()
    u = get_user(update.effective_user.id)
    bal = ctx.user_data['na_bal']
    fee = ctx.user_data['na_fee']
    name = ctx.user_data['na_name']
    acc = Account(user_id=u.id, name=name, type='CHALLENGE', start_balance=bal, current_balance=bal, fee_paid=fee, payout_cut=cut)
    s.add(acc)
    s.add(CashTx(user_id=u.id, type='FEE', amount=-fee, note=f"Buy {name}"))
    s.commit()
    net = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id).scalar() or 0
    s.close()
    ctx.user_data.clear()
    await update.message.reply_text(
        f"✅ {name} CHALLENGE created\n"
        f"Fee paid: -${fee:.2f}   |   Prop cut: {cut:.0f}%\n"
        f"💰 Bank Balance: {fmt_money(net)}",
        reply_markup=main_menu(update.effective_user.id),
    )


async def act_cut_edit(update, ctx, arg):
    """Change payout_cut % on an existing CHALLENGE account."""
    s = Session()
    a = s.query(Account).get(arg)
    if not a:
        s.close()
        await update.message.reply_text("Account not found.", reply_markup=main_menu(update.effective_user.id))
        return
    name, cur = a.name, a.payout_cut
    s.close()
    ctx.user_data['edit_cut_acc'] = arg
    rows = [
        [("10%", "cut_set", "10"), ("15%", "cut_set", "15"), ("20%", "cut_set", "20")],
        [("25%", "cut_set", "25"), ("30%", "cut_set", "30")],
        [("✏ Custom %", "cut_custom", None)],
        [("⬅ Back to Menu", "main", None)],
    ]
    await update.message.reply_text(
        f"Change prop cut for {name}\nCurrent: {cur:.0f}%\nPick a preset or Custom:",
        reply_markup=screen(ctx, rows),
    )


async def act_cut_set(update, ctx, arg):
    aid = ctx.user_data.get('edit_cut_acc')
    if not aid:
        await update.message.reply_text("Session expired.", reply_markup=main_menu(update.effective_user.id))
        return
    val = float(arg)
    s = Session()
    a = s.query(Account).get(aid)
    if not a:
        s.close()
        await update.message.reply_text("Account not found.", reply_markup=main_menu(update.effective_user.id))
        return
    a.payout_cut = val
    name = a.name
    s.commit()
    s.close()
    ctx.user_data.clear()
    await update.message.reply_text(f"✅ {name} prop cut set to {val:.0f}%", reply_markup=main_menu(update.effective_user.id))


async def act_cut_custom(update, ctx, arg):
    if not ctx.user_data.get('edit_cut_acc'):
        await update.message.reply_text("Session expired.", reply_markup=main_menu(update.effective_user.id))
        return
    ctx.user_data['mode'] = 'edit_cut'
    await update.message.reply_text("Send new cut % (e.g. 15 or 22.5):", reply_markup=back_menu(ctx))

async def act_archive(update, ctx, arg):
    s = Session()
    a = s.query(Account).get(arg)
    a.status = 'ARCHIVED'
    name = a.name
    s.commit()
    s.close()
    await update.message.reply_text(f"✅ {name} archived", reply_markup=back_menu(ctx))

async def act_delacc(update, ctx, arg):
    s = Session()
    s.query(Account).filter_by(id=arg).delete()
    s.commit()
    s.close()
    await update.message.reply_text("✅ Account deleted", reply_markup=back_menu(ctx))

async def act_pair_add(update, ctx, arg):
    ctx.user_data['mode'] = 'pair_add'
    await update.message.reply_text("Send pair symbol (e.g. EURUSD)", reply_markup=back_menu(ctx))

async def act_pairdel(update, ctx, arg):
    s = Session()
    s.query(Pair).filter_by(id=arg).delete()
    s.commit()
    s.close()
    await update.message.reply_text("✅ Pair deleted", reply_markup=back_menu(ctx))

# ---------------------------------------------------------------------------
# Rules actions
# ---------------------------------------------------------------------------

async def act_rule_add(update, ctx, arg):
    ctx.user_data['mode'] = 'rule_add'
    await update.message.reply_text("✍ Send your new trading rule:", reply_markup=back_menu(ctx))

async def act_rule_edit(update, ctx, arg):
    s = Session()
    u = get_user(update.effective_user.id)
    rule = s.query(Rule).get(arg)
    if rule and rule.user_id == u.id:
        ctx.user_data['mode'] = 'rule_edit'
        ctx.user_data['rule_id'] = arg
        await update.message.reply_text(f"Current:\n{rule.text}\n\nSend new version:", reply_markup=back_menu(ctx))
    s.close()

async def act_rule_del(update, ctx, arg):
    s = Session()
    u = get_user(update.effective_user.id)
    s.query(Rule).filter_by(id=arg, user_id=u.id).delete()
    s.commit()
    s.close()
    await show_rules(update, ctx)

# ---------------------------------------------------------------------------
# Journal / view / analyse / gallery / admin
# ---------------------------------------------------------------------------

async def act_journal_month(update, ctx, arg):
    year, month = arg
    s = Session()
    u = get_user(update.effective_user.id)
    trades = s.query(Trade).filter_by(user_id=u.id).filter(extract('year', Trade.opened_at) == year).filter(extract('month', Trade.opened_at) == month).order_by(Trade.opened_at.desc()).all()
    rows = []
    for i, t in enumerate(trades):
        date_str = t.opened_at.strftime('%d %b')
        if not t.closed_at:
            status = "🟢"
        else:
            tas = s.query(TradeAccount).filter_by(trade_id=t.id).all()
            total_pnl = sum(ta.pnl_usd or 0 for ta in tas)
            status = "✅" if total_pnl > 0 else "❌" if total_pnl < 0 else "➖"
        rows.append([(f"{i+1}. {date_str} {t.symbol} {t.direction} {status}", "view_trade", t.id)])
    rows.append([("⬅ Back to Months", "journal_back", None)])
    s.close()
    month_name = calendar.month_name[month]
    await update.message.reply_text(f"📖 {month_name} {year} - {len(trades)} trades", reply_markup=screen(ctx, rows))

async def act_journal_back(update, ctx, arg):
    await txt_journal(update, ctx)

async def act_view_trade(update, ctx, arg):
    tid = arg
    s = Session()
    tr = s.query(Trade).get(tid)
    if not tr:
        s.close()
        await update.message.reply_text("Trade not found", reply_markup=back_menu(ctx))
        return
    msg = f"📊 {tr.symbol} {tr.direction}\n📅 Opened: {tr.opened_at.strftime('%d %b %Y %H:%M')}\n"
    if tr.closed_at:
        msg += f"🔒 Closed: {tr.closed_at.strftime('%d %b %Y %H:%M')}\n"
    if tr.before_comment:
        msg += f"💬 Before: {tr.before_comment}\n"
    if tr.close_comment:
        msg += f"💬 After: {tr.close_comment}\n"
    tas = s.query(TradeAccount).filter_by(trade_id=tid).all()
    if tas:
        total_pnl = sum(ta.pnl_usd or 0 for ta in tas)
        msg += f"\n💰 Total PnL: ${total_pnl:+.2f}\n\nPer Account:\n"
        for ta in tas:
            acc = s.query(Account).get(ta.account_id)
            if ta.pnl_usd is not None:
                icon = "✅" if ta.pnl_usd > 0 else "❌" if ta.pnl_usd < 0 else "➖"
                msg += f"{icon} {acc.name}: ${ta.pnl_usd:+.2f} ({ta.result})\n"
            else:
                msg += f"🟢 {acc.name}: Open\n"
    year = tr.opened_at.year
    month = tr.opened_at.month
    rows = [[("⬅ Back to Month", "journal_month", (year, month))]]
    await update.message.reply_text(msg, reply_markup=screen(ctx, rows))
    if tr.before_photo:
        await update.message.reply_photo(tr.before_photo, caption="📸 BEFORE")
    if tr.after_photo:
        await update.message.reply_photo(tr.after_photo, caption="📸 AFTER")
    s.close()

async def act_analyse(update, ctx, arg):
    period = arg
    s = Session()
    u = get_user(update.effective_user.id)
    now = datetime.utcnow()
    if period == 'today':
        start = now.replace(hour=0, minute=0, second=0, microsecond=0); end = now; label = "TODAY"
    elif period == 'week':
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0); end = now; label = "THIS WEEK"
    elif period == 'month':
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0); end = now; label = "THIS MONTH"
    elif period == 'lastmonth':
        first_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = first_this - timedelta(seconds=1)
        start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0); label = "LAST MONTH"
    elif period == 'year':
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0); end = now; label = "THIS YEAR"
    else:
        start = None; end = None; label = "ALL TIME"
    query = s.query(Trade).filter_by(user_id=u.id).filter(Trade.closed_at != None)
    if start:
        query = query.filter(Trade.closed_at >= start)
    if end and period != 'all':
        query = query.filter(Trade.closed_at <= end)
    trades = query.all()
    trade_ids = [t.id for t in trades]
    tas = s.query(TradeAccount).filter(TradeAccount.trade_id.in_(trade_ids)).filter(TradeAccount.pnl_usd != None).all() if trade_ids else []
    # Aggregate per-Trade (not per-account) so one trade taken across multiple
    # accounts counts as a single win/loss.
    per_trade = {}  # trade_id -> {'pnl': float, 'results': [..], 'symbol': str}
    for tr in trades:
        per_trade[tr.id] = {'pnl': 0.0, 'results': [], 'symbol': tr.symbol}
    for ta in tas:
        if ta.trade_id in per_trade:
            per_trade[ta.trade_id]['pnl'] += (ta.pnl_usd or 0)
            if ta.result:
                per_trade[ta.trade_id]['results'].append(ta.result)
    total_trades = len(trades)
    wins = sum(1 for v in per_trade.values() if v['pnl'] > 0)
    losses = sum(1 for v in per_trade.values() if v['pnl'] < 0)
    decided = wins + losses
    winrate = (wins / decided * 100) if decided else 0
    total_pnl = sum(v['pnl'] for v in per_trade.values())
    avg_win = (sum(v['pnl'] for v in per_trade.values() if v['pnl'] > 0) / wins) if wins else 0
    avg_loss = (sum(v['pnl'] for v in per_trade.values() if v['pnl'] < 0) / losses) if losses else 0
    def _trade_result(v):
        # Pick the most common result across accounts; ties fall back to pnl sign.
        if v['results']:
            from collections import Counter
            return Counter(v['results']).most_common(1)[0][0]
        if v['pnl'] > 0: return 'TP'
        if v['pnl'] < 0: return 'SL'
        return 'BE'
    tp = sum(1 for v in per_trade.values() if _trade_result(v) == 'TP')
    sl = sum(1 for v in per_trade.values() if _trade_result(v) == 'SL')
    be = sum(1 for v in per_trade.values() if _trade_result(v) == 'BE')
    pair_pnl = {}
    for v in per_trade.values():
        pair_pnl[v['symbol']] = pair_pnl.get(v['symbol'], 0) + v['pnl']
    best = max(pair_pnl.items(), key=lambda x: x[1]) if pair_pnl else ("-", 0)
    worst = min(pair_pnl.items(), key=lambda x: x[1]) if pair_pnl else ("-", 0)
    s.close()
    date_str = f"{start.strftime('%d %b')} - {end.strftime('%d %b')}" if start and period != 'all' else ""
    msg = f"📊 {label} {date_str}\n\nTrades: {total_trades}\nWin Rate: {winrate:.1f}% ({wins}W/{losses}L)\nTotal PnL: ${total_pnl:+.2f}\n"
    if wins or losses:
        msg += f"Avg Win: ${avg_win:.0f} | Avg Loss: ${avg_loss:.0f}\n"
    msg += f"\nBest: {best[0]} (${best[1]:+.0f})\nWorst: {worst[0]} (${worst[1]:+.0f})\n\n✅ TP:{tp} ❌ SL:{sl} ➖ BE:{be}"
    rows = [[("⬅ Back", "analyse_back", None)]]
    await update.message.reply_text(msg, reply_markup=screen(ctx, rows))

async def act_analyse_back(update, ctx, arg):
    await txt_analyse(update, ctx)

# ---- Calendar ------------------------------------------------------------
def _fmt_pnl_short(v):
    a = abs(v)
    sign = "+" if v >= 0 else "-"
    if a >= 1000:
        return f"{sign}${a/1000:.1f}k"
    return f"{sign}${a:.0f}"

def _month_pnl_by_day(user_id, year, month, account_id=None):
    """Return {day:int -> (pnl:float, trade_count:int)} aggregated per-Trade.
    If account_id is given, only include that account's slice of each trade,
    and only count trades that actually touched that account."""
    from calendar import monthrange
    s = Session()
    last_day = monthrange(year, month)[1]
    start = datetime(year, month, 1)
    end = datetime(year, month, last_day, 23, 59, 59)
    trades = s.query(Trade).filter_by(user_id=user_id).filter(
        Trade.closed_at != None, Trade.closed_at >= start, Trade.closed_at <= end
    ).all()
    tids = [t.id for t in trades]
    q = s.query(TradeAccount).filter(TradeAccount.trade_id.in_(tids)) if tids else None
    if q is not None and account_id is not None:
        q = q.filter(TradeAccount.account_id == account_id)
    tas = q.all() if q is not None else []
    pnl_per_trade = {}
    trades_with_acc = set()
    for ta in tas:
        pnl_per_trade[ta.trade_id] = pnl_per_trade.get(ta.trade_id, 0) + (ta.pnl_usd or 0)
        trades_with_acc.add(ta.trade_id)
    by_day = {}
    for t in trades:
        if account_id is not None and t.id not in trades_with_acc:
            continue
        d = t.closed_at.day
        cur_pnl, cur_ct = by_day.get(d, (0.0, 0))
        by_day[d] = (cur_pnl + pnl_per_trade.get(t.id, 0), cur_ct + 1)
    s.close()
    return by_day

async def txt_calendar(update, ctx):
    ctx.user_data.pop('mode', None)
    await act_calendar(update, ctx, None)

async def act_calendar(update, ctx, arg):
    from calendar import monthrange
    now = datetime.utcnow()
    if arg is None:
        year, month = now.year, now.month
    else:
        year, month = arg
    u = get_user(update.effective_user.id)
    acc_id = ctx.user_data.get('cal_account_id')  # None = All
    by_day = _month_pnl_by_day(u.id, year, month, acc_id)
    last_day = monthrange(year, month)[1]
    first_wd = datetime(year, month, 1).weekday()  # Mon=0

    # Prev / Next month
    pm_y, pm_m = (year, month - 1) if month > 1 else (year - 1, 12)
    nm_y, nm_m = (year, month + 1) if month < 12 else (year + 1, 1)
    header_label = f"{calendar.month_name[month]} {year}"

    rows = [[
        ("◀", "calendar", (pm_y, pm_m)),
        (header_label, "calendar", (year, month)),
        ("▶", "calendar", (nm_y, nm_m)),
    ]]

    # Account filter row(s)
    s = Session()
    accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all()
    s.close()
    all_label = ("✅ 👥 All" if acc_id is None else "👥 All")
    acc_row = [(all_label, "cal_pick_acc", 0)]
    filter_rows = []
    for a in accs:
        mark = "✅ " if acc_id == a.id else ""
        acc_row.append((f"{mark}{a.name}", "cal_pick_acc", a.id))
        if len(acc_row) >= 3:
            filter_rows.append(acc_row)
            acc_row = []
    if acc_row:
        filter_rows.append(acc_row)
    rows.extend(filter_rows)

    # Weekday header row (labels must be unique in nav map)
    rows.append([(wd, "cal_noop", i) for i, wd in enumerate(
        ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    )])

    # Build grid — 6 rows × 7 cols max
    cells = []  # list of (label, action, arg)
    pad_counter = 0
    for _ in range(first_wd):
        pad_counter += 1
        cells.append(("▫" * pad_counter, "cal_noop", None))
    for d in range(1, last_day + 1):
        if d in by_day:
            pnl, ct = by_day[d]
            emoji = "🟢" if pnl > 0 else ("🔴" if pnl < 0 else "🟡")
            label = f"{emoji} {d}\n{_fmt_pnl_short(pnl)}"
        else:
            label = f"⬜ {d}\n—"
        cells.append((label, "cal_day", (year, month, d)))
    while len(cells) % 7 != 0:
        pad_counter += 1
        cells.append(("▫" * pad_counter, "cal_noop", None))

    for i in range(0, len(cells), 7):
        rows.append(cells[i:i + 7])

    # Totals
    total_pnl = sum(v[0] for v in by_day.values())
    total_trades = sum(v[1] for v in by_day.values())
    wins = sum(1 for v in by_day.values() if v[0] > 0)
    losses = sum(1 for v in by_day.values() if v[0] < 0)
    be = sum(1 for v in by_day.values() if v[0] == 0 and v[1] > 0)
    rows.append([("⬅ Back", "analyse_back", None)])

    if acc_id is None:
        scope = "All Accounts"
    else:
        acc_name = next((a.name for a in accs if a.id == acc_id), f"#{acc_id}")
        scope = acc_name

    msg = (
        f"🗓 {header_label}  ·  {scope}\n"
        f"PnL: ${total_pnl:+.2f}  |  🟢{wins}  🔴{losses}  🟡{be}\n"
        f"Trades: {total_trades}\n"
        f"Legend: 🟢 win  🔴 loss  🟡 BE  ⬜ no trade\n"
        f"Tap any day for details."
    )
    await update.message.reply_text(msg, reply_markup=screen(ctx, rows))

async def act_cal_pick_acc(update, ctx, arg):
    # arg = 0 for All, else account_id
    ctx.user_data['cal_account_id'] = None if arg == 0 else arg
    await act_calendar(update, ctx, None)

async def act_cal_noop(update, ctx, arg):
    # Ignore taps on padding / weekday header cells
    return

async def act_cal_day(update, ctx, arg):
    year, month, day = arg
    s = Session()
    u = get_user(update.effective_user.id)
    acc_id = ctx.user_data.get('cal_account_id')
    start = datetime(year, month, day, 0, 0, 0)
    end = datetime(year, month, day, 23, 59, 59)
    trades = s.query(Trade).filter_by(user_id=u.id).filter(
        Trade.closed_at != None, Trade.closed_at >= start, Trade.closed_at <= end
    ).order_by(Trade.closed_at.asc()).all()

    scope = "All Accounts"
    if acc_id is not None:
        acc_row = s.query(Account).get(acc_id)
        scope = acc_row.name if acc_row else f"#{acc_id}"

    header = f"🗓 {day:02d} {calendar.month_name[month]} {year}  ·  {scope}"
    if not trades:
        s.close()
        rows = [[("⬅ Back to Calendar", "calendar", (year, month))]]
        await update.message.reply_text(f"{header}\n\nNo trades on this day.",
                                        reply_markup=screen(ctx, rows))
        return

    lines = [header, ""]
    rows = []
    day_pnl = 0.0
    per_account = {}  # account_id -> [name, pnl, trades_count]
    shown_trades = 0
    for tr in trades:
        tas_all = s.query(TradeAccount).filter_by(trade_id=tr.id).all()
        if acc_id is not None:
            tas = [ta for ta in tas_all if ta.account_id == acc_id]
            if not tas:
                continue
        else:
            tas = tas_all
        shown_trades += 1
        pnl = sum(ta.pnl_usd or 0 for ta in tas)
        day_pnl += pnl
        icon = "🟢" if pnl > 0 else ("🔴" if pnl < 0 else "⚪")
        time_str = tr.closed_at.strftime('%H:%M')
        lines.append(f"{icon} {time_str} {tr.symbol} {tr.direction} {_fmt_pnl_short(pnl)}")
        # Per-account breakdown for this trade
        for ta in tas:
            acc = s.query(Account).get(ta.account_id)
            acc_name = acc.name if acc else ta.account_id
            p = ta.pnl_usd or 0
            sub_icon = "🟢" if p > 0 else ("🔴" if p < 0 else ("⚪" if ta.pnl_usd is not None else "⏳"))
            status = "" if ta.pnl_usd is not None else " (open)"
            lines.append(f"   {sub_icon} {acc_name}: {_fmt_pnl_short(p)}{status}")
            if ta.pnl_usd is not None:
                cur = per_account.get(ta.account_id, [acc_name, 0.0, 0])
                cur[1] += p
                cur[2] += 1
                per_account[ta.account_id] = cur
        if tr.before_comment:
            lines.append(f"   💬 Before: {tr.before_comment}")
        if tr.close_comment:
            lines.append(f"   💬 After: {tr.close_comment}")
        lines.append("")
        btn_label = f"🔎 {time_str} {tr.symbol} {_fmt_pnl_short(pnl)}"
        rows.append([(btn_label, "view_trade", tr.id)])

    # Per-account daily summary
    if per_account and acc_id is None:
        lines.append("— By Account —")
        for _, (name, p, ct) in per_account.items():
            ic = "🟢" if p > 0 else ("🔴" if p < 0 else "⚪")
            lines.append(f"{ic} {name}: {_fmt_pnl_short(p)} ({ct} trade{'s' if ct != 1 else ''})")
        lines.append("")

    lines.insert(2, f"Net Day PnL: ${day_pnl:+.2f}  |  Trades: {shown_trades}")
    lines.insert(3, "")
    rows.append([("⬅ Back to Calendar", "calendar", (year, month))])
    s.close()
    await update.message.reply_text("\n".join(lines), reply_markup=screen(ctx, rows))




async def act_gallery(update, ctx, arg):
    data = arg
    s = Session()
    u = get_user(update.effective_user.id)
    now = datetime.utcnow()
    if data == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        trades = s.query(Trade).filter_by(user_id=u.id).filter(Trade.before_photo != None, Trade.opened_at >= start).order_by(Trade.opened_at.asc()).all()
        label = "Today"
    elif data == "week":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        trades = s.query(Trade).filter_by(user_id=u.id).filter(Trade.before_photo != None, Trade.opened_at >= start).order_by(Trade.opened_at.asc()).all()
        label = "This Week"
    elif data == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        trades = s.query(Trade).filter_by(user_id=u.id).filter(Trade.before_photo != None, Trade.opened_at >= start).order_by(Trade.opened_at.asc()).all()
        label = "This Month"
    elif data == "year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        trades = s.query(Trade).filter_by(user_id=u.id).filter(Trade.before_photo != None, Trade.opened_at >= start).order_by(Trade.opened_at.asc()).all()
        label = "This Year"
    else:
        trades = s.query(Trade).filter_by(user_id=u.id).filter(Trade.before_photo != None).order_by(Trade.opened_at.asc()).all()
        label = "All Time"
    if not trades:
        s.close()
        await update.message.reply_text(f"🖼 No photos for {label}", reply_markup=screen(ctx, [[("⬅ Back", "gallery_back", None)]]))
        return
    await update.message.reply_text(f"🖼 Gallery - {label} ({len(trades)} trades)", reply_markup=screen(ctx, [[("⬅ Back", "gallery_back", None)]]))
    for tr in trades:
        ta = s.query(TradeAccount).filter_by(trade_id=tr.id).first()
        result = f" • {ta.result}" if ta and ta.result else ""
        base = f"{tr.symbol} {tr.direction} • {tr.opened_at.strftime('%d %b %Y')}{result}"
        before_cap = "BEFORE: " + base
        if tr.before_comment:
            before_cap += f"\n💬 {tr.before_comment}"
        after_cap = "AFTER: " + base
        if tr.close_comment:
            after_cap += f"\n💬 {tr.close_comment}"
        try:
            if tr.before_photo:
                await update.message.reply_photo(tr.before_photo, caption=before_cap)
            if tr.after_photo:
                await update.message.reply_photo(tr.after_photo, caption=after_cap)
        except:
            continue
    s.close()

async def act_gallery_back(update, ctx, arg):
    await txt_gallery(update, ctx)

async def act_admin_users(update, ctx, arg):
    s = Session()
    users = s.query(User).all()
    msg = f"👥 Users ({len(users)})\n\n"
    for u in users:
        msg += f"• {u.telegram_id} {'(admin)' if u.is_admin == '1' else ''}\n"
    s.close()
    await update.message.reply_text(msg, reply_markup=back_menu(ctx))

async def act_wallet(update, ctx, arg):
    await show_wallet(update, ctx)

async def act_main(update, ctx, arg):
    await show_main(update, ctx)

async def act_before_skip(update, ctx, arg):
    ctx.user_data.clear()
    await update.message.reply_text("✅ Trade logged", reply_markup=main_menu(update.effective_user.id))

# ---------------------------------------------------------------------------
# Dispatch table for reply-keyboard button taps
# ---------------------------------------------------------------------------

DISPATCH = {
    "main": act_main,
    "wallet": act_wallet,
    "trade_acc": act_trade_acc,
    "trade_pair": act_trade_pair,
    "dir": act_dir,
    "close_trade": act_close_trade,
    "close_res": act_close_res,
    "closeacc": act_closeacc,
    "closeacc_back": act_closeacc_back,
    "closeacc_done": act_closeacc_done,
    "comment_skip": act_comment_skip,
    "before_skip": act_before_skip,
    "profit_starting": act_profit_starting,
    "profit_challenge": act_profit_challenge,
    "profit_deposit": act_profit_deposit,
    "profit_withdraw": act_profit_withdraw,
    "profit_payout": act_profit_payout,
    "profit_stats": act_profit_stats,
    "profit_history": act_profit_history,
    "tx_pick": act_tx_pick,
    "tx_view": act_tx_view,
    "tx_edit_amt": act_tx_edit_amt,
    "tx_edit_note": act_tx_edit_note,
    "tx_flip": act_tx_flip,
    "tx_del": act_tx_del,
    "tx_del_yes": act_tx_del_yes,
    "profit_reset": act_profit_reset,
    "profit_edit": act_profit_edit,
    "clear_chat": act_clear_chat,
    "reset_yes": act_reset_yes,
    "wd_pick": act_wd_pick,
    "payout_pick": act_payout_pick,
    "deposit_pick": act_deposit_pick,
    "bal_edit": act_bal_edit,
    "bal_reset": act_bal_reset,
    "bal_reset_yes": act_bal_reset_yes,
    "balance_menu": act_balance_menu,
    "add_live": act_add_live,
    "add_challenge": act_add_challenge,
    "cut": act_cut,
    "cut_edit": act_cut_edit,
    "cut_set": act_cut_set,
    "cut_custom": act_cut_custom,
    "archive": act_archive,
    "delacc": act_delacc,
    "pair_add": act_pair_add,
    "pairdel": act_pairdel,
    "rule_add": act_rule_add,
    "rule_edit": act_rule_edit,
    "rule_del": act_rule_del,
    "journal_month": act_journal_month,
    "journal_back": act_journal_back,
    "view_trade": act_view_trade,
    "analyse": act_analyse,
    "analyse_back": act_analyse_back,
    "calendar": act_calendar,
    "cal_day": act_cal_day,
    "cal_noop": act_cal_noop,
    "cal_pick_acc": act_cal_pick_acc,
    "gallery": act_gallery,
    "gallery_back": act_gallery_back,
    "admin_users": act_admin_users,
}

# ---------------------------------------------------------------------------
# Central text handler: first resolve reply-keyboard button taps via the
# per-screen nav map, then fall through to free-text input modes.
# ---------------------------------------------------------------------------

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()

    # 1) Reply-keyboard button tap for the current screen
    nav = ctx.user_data.get('nav', {})
    if txt in nav:
        action, arg = nav[txt]
        fn = DISPATCH.get(action)
        if fn:
            return await fn(update, ctx, arg)

    # 2) Free-text input modes
    mode = ctx.user_data.get('mode')
    s = Session()
    u = get_user(update.effective_user.id)
    if mode == 'starting_balance':
        try:
            amt = float(txt.replace(',', '').replace('$', '').replace('+', ''))
        except:
            await update.message.reply_text("❌ Send a number like -10000 or 5000", reply_markup=back_wallet(ctx))
            s.close()
            return
        s.query(CashTx).filter_by(user_id=u.id, type='INITIAL').delete()
        s.add(CashTx(user_id=u.id, type='INITIAL', amount=amt, note='Starting balance (old PnL before bot)'))
        s.commit()
        s.close()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Starting balance set to ${amt:+.2f}\nYour Bank Balance now includes this. Check 💰 Balance", reply_markup=main_menu(update.effective_user.id))
        return
    if mode == 'new_acc':
        step = ctx.user_data.get('step', 1)
        atype = ctx.user_data.get('atype')
        if step == 1:
            ctx.user_data['na_name'] = txt
            ctx.user_data['step'] = 2
            await update.message.reply_text("Account size?" if atype == 'CHALLENGE' else "Starting balance?", reply_markup=back_menu(ctx))
        elif step == 2:
            ctx.user_data['na_bal'] = float(txt)
            if atype == 'CHALLENGE':
                ctx.user_data['step'] = 3
                await update.message.reply_text(
                    "Fee paid? (enter positive amount, e.g. 100 — it will be deducted from Bank Balance)",
                    reply_markup=back_menu(ctx),
                )
            else:
                bal = ctx.user_data['na_bal']
                acc = Account(user_id=u.id, name=ctx.user_data['na_name'], type='LIVE', start_balance=bal, current_balance=bal)
                s.add(acc)
                s.add(CashTx(user_id=u.id, type='DEPOSIT', amount=-bal, note=f"Fund {acc.name}"))
                s.commit()
                ctx.user_data.clear()
                await update.message.reply_text(f"✅ {acc.name} LIVE created", reply_markup=main_menu(update.effective_user.id))
        elif step == 3:
            fee = float(txt)
            if fee < 0:
                await update.message.reply_text(
                    "⚠ Fee must be a positive number (e.g. 100).\n"
                    "The bot will subtract it from your Bank Balance automatically.",
                    reply_markup=back_menu(ctx),
                )
                s.close()
                return
            ctx.user_data['na_fee'] = fee
            rows = [[("10%", "cut", "10"), ("20%", "cut", "20")]]
            await update.message.reply_text("Prop cut %?", reply_markup=screen(ctx, rows))
    elif mode == 'withdraw':
        amt = abs(float(txt))
        acc = s.query(Account).get(ctx.user_data['wd_acc'])
        acc.current_balance -= amt
        # withdraw = money into YOUR pocket → stored POSITIVE (adds to bank balance)
        s.add(CashTx(user_id=u.id, type='WITHDRAW', amount=amt, note=f"From {acc.name}"))
        s.commit()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Withdrew ${amt:.2f}", reply_markup=main_menu(update.effective_user.id))
    elif mode == 'payout':
        gross = float(txt)
        acc = s.query(Account).get(ctx.user_data['payout_acc'])
        cut = acc.payout_cut if acc.type == 'CHALLENGE' else 0
        net = gross * (1 - cut / 100)
        acc.current_balance -= gross
        s.add(CashTx(user_id=u.id, type='PAYOUT', amount=net, note=f"{acc.name}"))
        s.commit()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Payout ${net:.2f}", reply_markup=main_menu(update.effective_user.id))
    elif mode == 'deposit':
        amt = float(txt)
        acc = s.query(Account).get(ctx.user_data['deposit_acc'])
        acc.current_balance += amt
        s.add(CashTx(user_id=u.id, type='DEPOSIT', amount=-amt, note=f"Fund {acc.name}"))
        s.commit()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Deposited ${amt}", reply_markup=main_menu(update.effective_user.id))
    elif mode == 'edit_cut':
        try:
            val = float(txt)
        except ValueError:
            await update.message.reply_text("Please send a number like 15 or 22.5", reply_markup=back_menu(ctx))
            s.close()
            return
        aid = ctx.user_data.get('edit_cut_acc')
        acc = s.query(Account).get(aid) if aid else None
        if not acc:
            s.close()
            ctx.user_data.clear()
            await update.message.reply_text("Session expired.", reply_markup=main_menu(update.effective_user.id))
            return
        acc.payout_cut = val
        name = acc.name
        s.commit()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ {name} prop cut set to {val:.0f}%", reply_markup=main_menu(update.effective_user.id))
    elif mode == 'tx_edit_amt':
        try:
            new_amt = float(txt.replace(',', '').replace('$', '').replace('+', ''))
        except ValueError:
            await update.message.reply_text("❌ Send a number like -103 or 250", reply_markup=back_wallet(ctx))
            s.close()
            return
        tx = s.query(CashTx).get(ctx.user_data.get('tx_id'))
        if tx:
            tx.amount = new_amt
            s.commit()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Amount updated to {new_amt:+.2f}", reply_markup=main_menu(update.effective_user.id))
        s.close()
        return
    elif mode == 'tx_edit_note':
        tx = s.query(CashTx).get(ctx.user_data.get('tx_id'))
        if tx:
            tx.note = txt
            s.commit()
        ctx.user_data.clear()
        await update.message.reply_text("✅ Note updated", reply_markup=main_menu(update.effective_user.id))
        s.close()
        return
    elif mode == 'pair_add':
        sym = txt.upper().replace("/", "")
        s.add(Pair(user_id=u.id, symbol=sym))
        s.commit()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Pair {sym}", reply_markup=main_menu(update.effective_user.id))
    elif mode == 'bal_edit':
        new_amt = float(txt)
        current = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id).scalar() or 0
        s.add(CashTx(user_id=u.id, type='ADJUST', amount=new_amt - current, note='Manual'))
        s.commit()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Bank ${new_amt:.2f}", reply_markup=main_menu(update.effective_user.id))
    elif mode == 'rule_add':
        rule = Rule(user_id=u.id, text=txt, order_num=datetime.utcnow().timestamp())
        s.add(rule)
        s.commit()
        ctx.user_data.clear()
        await update.message.reply_text("✅ Rule added!", reply_markup=main_menu(update.effective_user.id))
        s.close()
        return
    elif mode == 'rule_edit':
        rid = ctx.user_data.get('rule_id')
        rule = s.query(Rule).get(rid)
        if rule and rule.user_id == u.id:
            rule.text = txt
            s.commit()
        ctx.user_data.clear()
        await update.message.reply_text("✅ Rule updated!", reply_markup=main_menu(update.effective_user.id))
        s.close()
        return
    elif mode == 'close_pnl':
        try:
            pnl = float(txt.replace('+', ''))
        except:
            await update.message.reply_text("Send number like -50 or +120")
            s.close()
            return
        acc_id = ctx.user_data['close']['current_acc']
        ctx.user_data['close']['tas'][acc_id] = pnl
        ctx.user_data['mode'] = 'close'
        s.close()
        await show_close_accounts_menu(update, ctx)
        return
    elif mode == 'await_before_comment':
        tid = ctx.user_data.get('before_trade_id')
        tr = s.query(Trade).get(tid)
        if tr:
            tr.before_comment = txt
            s.commit()
        ctx.user_data.clear()
        await update.message.reply_text("✅ Trade logged with note", reply_markup=main_menu(update.effective_user.id))
        s.close()
        return
    elif mode == 'await_comment':
        s.close()
        await finalize_trade(update, ctx, txt)
        return
    s.close()

# ---------------------------------------------------------------------------
# Photo handler
# ---------------------------------------------------------------------------

async def photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    mode = ctx.user_data.get('mode')
    s = Session()
    u = get_user(update.effective_user.id)
    if mode == 'trade' and ctx.user_data.get('trade', {}).get('step') == 'photo':
        t = ctx.user_data['trade']
        tr = Trade(user_id=u.id, symbol=t['symbol'], direction=t['direction'], before_photo=update.message.photo[-1].file_id)
        s.add(tr)
        s.flush()
        for aid in t['acc_ids']:
            s.add(TradeAccount(trade_id=tr.id, account_id=aid))
        s.commit()
        ctx.user_data['mode'] = 'await_before_comment'
        ctx.user_data['before_trade_id'] = tr.id
        rows = [[("⏭ Skip", "before_skip", None)]]
        await update.message.reply_text("✍ Add note for BEFORE photo? (optional)", reply_markup=screen(ctx, rows))
        s.close()
        return
    elif mode == 'close' and ctx.user_data.get('close', {}).get('step') == 'photo':
        tid = ctx.user_data['close']['id']
        tr = s.query(Trade).get(tid)
        tr.after_photo = update.message.photo[-1].file_id
        s.commit()
        ctx.user_data['close']['step'] = 'result'
        rows = [[("SL ❌", "close_res", "SL"), ("BE ➖", "close_res", "BE"), ("TP ✅", "close_res", "TP")]]
        await update.message.reply_text("Close as?", reply_markup=screen(ctx, rows))
    s.close()

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def main():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("fixfees", fixfees_cmd))
    app.add_handler(CommandHandler("pairs", cmd_pairs))
    # Persistent main-menu reply buttons
    app.add_handler(MessageHandler(filters.Regex("^📝 Log Trade$"), txt_log))
    app.add_handler(MessageHandler(filters.Regex("^✅ Close Trade$"), txt_close))
    app.add_handler(MessageHandler(filters.Regex("^💰 Balance$"), txt_balance))
    app.add_handler(MessageHandler(filters.Regex("^⚙ My Accounts$"), txt_accounts))
    app.add_handler(MessageHandler(filters.Regex("^📊 Analyse$"), txt_analyse))
    app.add_handler(MessageHandler(filters.Regex("^📖 Journal$"), txt_journal))
    app.add_handler(MessageHandler(filters.Regex("^📈 My Pairs$"), txt_pairs))
    app.add_handler(MessageHandler(filters.Regex("^📜 Trade History$"), txt_hist))
    app.add_handler(MessageHandler(filters.Regex("^🖼 Gallery$"), txt_gallery))
    app.add_handler(MessageHandler(filters.Regex("^➕ Add Account$"), txt_add))
    app.add_handler(MessageHandler(filters.Regex("^💰 Wallet & Tools$"), txt_profit))
    app.add_handler(MessageHandler(filters.Regex("^👑 ADMIN PANEL$"), txt_admin))
    app.add_handler(MessageHandler(filters.Regex("^📏 My Rules$"), txt_rules))
    app.add_handler(MessageHandler(filters.Regex("^🗓 Calendar$"), txt_calendar))
    # Photos and everything else (sub-menu taps + typed input)
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
