import os
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from sqlalchemy import create_engine, Column, String, Float, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import uuid

# ==================== DATABASE MODELS ====================
Base = declarative_base()
def uid(): return str(uuid.uuid4())

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

# ==================== SETUP ====================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./edgeflo.db")
ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",")
engine = create_engine(DATABASE_URL, future=True)
Session = sessionmaker(bind=engine)
Base.metadata.create_all(engine)

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

def main_menu(uid=None):
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
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back to Menu", callback_data="back_main")]])

def back_tools():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back to Wallet", callback_data="menu_profit")]])

def profit_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Challenge Buy", callback_data="profit_challenge"), InlineKeyboardButton("💰 Live Deposit", callback_data="profit_deposit")],
        [InlineKeyboardButton("💸 Log Payout", callback_data="profit_payout"), InlineKeyboardButton("💵 Withdraw", callback_data="profit_withdraw")],
        [InlineKeyboardButton("📊 View Stats", callback_data="profit_stats"), InlineKeyboardButton("🗑 Edit/Delete", callback_data="profit_edit")],
        [InlineKeyboardButton("🔄 Reset All", callback_data="profit_reset"), InlineKeyboardButton("📜 Bank History", callback_data="profit_history")],
        [InlineKeyboardButton("🧹 Clean View", callback_data="clear_chat")],
        [InlineKeyboardButton("⬅ Back", callback_data="back_main")]
    ])

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    get_user(update.effective_user.id)
    ctx.user_data.clear()
    await update.message.reply_text("📊 Trading Journal", reply_markup=main_menu(update.effective_user.id))

async def clear_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧹 Tap my name → Clear History to clean chat.")

async def back_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data.clear()
    await q.edit_message_text("📊 Trading Journal", reply_markup=main_menu(q.from_user.id))

async def archive_acc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    aid = q.data[5:]
    s = Session()
    a = s.query(Account).get(aid)
    a.status = 'ARCHIVED'
    s.commit()
    s.close()
    await q.edit_message_text(f"✅ {a.name} archived", reply_markup=back_button())

async def wd_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data['mode'] = 'withdraw'
    ctx.user_data['wd_acc'] = q.data[3:]
    await q.edit_message_text("Amount to withdraw to bank?", reply_markup=back_tools())

async def payout_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data['mode'] = 'payout'
    ctx.user_data['payout_acc'] = q.data[7:]
    await q.edit_message_text("Gross payout amount?", reply_markup=back_tools())

async def deposit_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data['mode'] = 'deposit'
    ctx.user_data['deposit_acc'] = q.data[8:]
    await q.edit_message_text("How much to deposit?", reply_markup=back_tools())

async def menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    ctx.user_data.clear()
    s = Session()
    u = get_user(q.from_user.id)

    if d == "menu_log":
        s.close()
        return await trade_start(q, ctx)
    if d == "menu_close":
        s.close()
        return await close_start(q, ctx)
    if d == "menu_balance":
        net = sum(t.amount for t in s.query(CashTx).filter_by(user_id=u.id)) or 0
        s.close()
        kb = [[InlineKeyboardButton("✏ Edit", callback_data="bal_edit"), InlineKeyboardButton("🔄 Reset", callback_data="bal_reset")],
              [InlineKeyboardButton("⬅ Back", callback_data="back_main")]]
        await q.edit_message_text(f"💰 Bank Balance: ${net:.2f}", reply_markup=InlineKeyboardMarkup(kb))
        return
    if d == "bal_edit":
        ctx.user_data['mode'] = 'bal_edit'
        s.close()
        await q.edit_message_text("Enter new bank balance:", reply_markup=back_button())
        return
    if d == "bal_reset":
        s.close()
        await q.edit_message_text("Reset bank to $0?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data="bal_reset_yes"), InlineKeyboardButton("❌ No", callback_data="menu_balance")]]))
        return
    if d == "bal_reset_yes":
        s.query(CashTx).filter_by(user_id=u.id).delete()
        s.commit()
        s.close()
        await q.edit_message_text("✅ Bank reset", reply_markup=back_button())
        return
    if d == "clear_chat":
        s.close()
        await q.edit_message_text("🧹 Tap my name → Clear History.", reply_markup=back_button())
        return
    if d == "menu_accounts":
        accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all()
        arch = s.query(Account).filter_by(user_id=u.id, status='ARCHIVED').all()
        msg = "⚙ Active Accounts\n\n"
        for a in accs:
            cut = f" -{a.payout_cut}%" if a.type == 'CHALLENGE' else ""
            msg += f"🟢 {a.name} ({a.type}{cut}) - ${a.current_balance:.0f}\n"
        msg += "\n📦 Archived:\n"
        for a in arch:
            msg += f"• {a.name}\n"
        kb = [[InlineKeyboardButton(f"📦 Archive {a.name}", callback_data=f"arch_{a.id}")] for a in accs]
        kb.append([InlineKeyboardButton("⬅ Back", callback_data="back_main")])
        s.close()
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
        return
    if d == "menu_add":
        s.close()
        await q.edit_message_text("Choose account type:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💼 Live", callback_data="add_live"), InlineKeyboardButton("🎯 Challenge", callback_data="add_challenge")],
            [InlineKeyboardButton("⬅ Back", callback_data="back_main")]
        ]))
        return
    if d == "add_live":
        ctx.user_data['mode'] = 'new_acc'
        ctx.user_data['atype'] = 'LIVE'
        ctx.user_data['step'] = 1
        s.close()
        await q.edit_message_text("Live account name?", reply_markup=back_button())
        return
    if d == "add_challenge":
        ctx.user_data['mode'] = 'new_acc'
        ctx.user_data['atype'] = 'CHALLENGE'
        ctx.user_data['step'] = 1
        s.close()
        await q.edit_message_text("Challenge name? (e.g. FTMO 100k)", reply_markup=back_button())
        return
    if d == "menu_profit":
        s.close()
        await q.edit_message_text("💰 Wallet & Tools", reply_markup=profit_menu())
        return
    if d == "menu_pairs":
        pairs = s.query(Pair).filter_by(user_id=u.id).all()
        kb = [[InlineKeyboardButton(f"❌ {p.symbol}", callback_data=f"pairdel_{p.id}")] for p in pairs]
        kb.append([InlineKeyboardButton("➕ Add Pair", callback_data="pair_add"), InlineKeyboardButton("⬅ Back", callback_data="back_main")])
        s.close()
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
        s.close()
        await q.edit_message_text(msg, reply_markup=back_button())
        return
    if d == "menu_journal":
        trades = s.query(Trade).filter_by(user_id=u.id).order_by(Trade.opened_at.desc()).limit(5).all()
        msg = "📖 Last Trades\n"
        for t in trades:
            msg += f"{t.opened_at.strftime('%d/%m/%Y')} {t.symbol} {t.direction}\n"
        kb = [[InlineKeyboardButton(f"View {t.symbol}", callback_data=f"view_{t.id}")] for t in trades]
        kb.append([InlineKeyboardButton("⬅ Back", callback_data="back_main")])
        s.close()
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
        s.close()
        await q.edit_message_text(msg or "No history", reply_markup=back_button())
        return
    if d == "menu_admin":
        if not is_admin(q.from_user.id):
            s.close()
            await q.answer("Not admin", show_alert=True)
            return
        s.close()
        await q.edit_message_text("👑 ADMIN PANEL", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 View Users", callback_data="admin_users")],
            [InlineKeyboardButton("⬅ Back", callback_data="back_main")]
        ]))
        return
    s.close()

async def profit_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    s = Session()
    u = get_user(q.from_user.id)
    if d == "profit_withdraw":
        accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all()
        kb = [[InlineKeyboardButton(a.name, callback_data=f"wd_{a.id}")] for a in accs]
        kb.append([InlineKeyboardButton("⬅ Back", callback_data="menu_profit")])
        await q.edit_message_text("Select account to withdraw FROM:", reply_markup=InlineKeyboardMarkup(kb))
    elif d == "profit_challenge":
        ctx.user_data['mode'] = 'quick'
        ctx.user_data['qt'] = 'challenge'
        await q.edit_message_text("Send: NAME BALANCE FEE", reply_markup=back_tools())
    elif d == "profit_deposit":
        accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE', type='LIVE').all()
        kb = [[InlineKeyboardButton(a.name, callback_data=f"deposit_{a.id}")] for a in accs]
        kb.append([InlineKeyboardButton("⬅ Back", callback_data="menu_profit")])
        await q.edit_message_text("Deposit to which LIVE account?", reply_markup=InlineKeyboardMarkup(kb))
    elif d == "profit_payout":
        accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all()
        kb = [[InlineKeyboardButton(f"{a.name} ({a.type})", callback_data=f"payout_{a.id}")] for a in accs]
        kb.append([InlineKeyboardButton("⬅ Back", callback_data="menu_profit")])
        await q.edit_message_text("Payout from which account?", reply_markup=InlineKeyboardMarkup(kb))
    elif d == "profit_stats":
        fees = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id, type='FEE').scalar() or 0
        deposits = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id, type='DEPOSIT').scalar() or 0
        payouts = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id, type='PAYOUT').scalar() or 0
        withdraws = s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id, type='WITHDRAW').scalar() or 0
        net = fees + payouts + withdraws + deposits
        await q.edit_message_text(f"📊 Stats\nFees: ${abs(fees):.2f}\nLive Capital: ${abs(deposits):.2f}\nPayouts: ${payouts:.2f}\nWithdraws: ${abs(withdraws):.2f}\nNet: ${net:.2f}", reply_markup=back_tools())
    elif d == "profit_history":
        txs = s.query(CashTx).filter_by(user_id=u.id).order_by(CashTx.date.desc()).limit(20).all()
        msg = "📜 Bank History\n\n"
        for t in txs:
            msg += f"{t.date.strftime('%d/%m/%Y')} {t.type} ${t.amount:+.2f} - {t.note}\n"
        await q.edit_message_text(msg or "No transactions", reply_markup=back_tools())
    elif d == "profit_reset":
        await q.edit_message_text("Delete ALL data?", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ YES", callback_data="reset_yes"), InlineKeyboardButton("❌ No", callback_data="menu_profit")]
        ]))
    elif d == "profit_edit":
        accs = s.query(Account).filter_by(user_id=u.id).all()
        kb = [[InlineKeyboardButton(f"🗑 {a.name}", callback_data=f"delacc_{a.id}")] for a in accs]
        kb.append([InlineKeyboardButton("⬅ Back", callback_data="menu_profit")])
        await q.edit_message_text("Delete account:", reply_markup=InlineKeyboardMarkup(kb))
    s.close()

    async def reset_yes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    s = Session()
    u = get_user(q.from_user.id)
    uid = u.id
    s.query(TradeAccount).filter(TradeAccount.trade_id.in_(s.query(Trade.id).filter_by(user_id=uid))).delete(synchronize_session=False)
    s.query(Trade).filter_by(user_id=uid).delete()
    s.query(Account).filter_by(user_id=uid).delete()
    s.query(Pair).filter_by(user_id=uid).delete()
    s.query(CashTx).filter_by(user_id=uid).delete()
    s.commit()
    s.close()
    await q.edit_message_text("✅ Reset done", reply_markup=back_button())

async def trade_start(q, ctx):
    s = Session()
    u = get_user(q.from_user.id)
    accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all()
    s.close()
    ctx.user_data['mode'] = 'trade'
    ctx.user_data['trade'] = {}
    kb = [[InlineKeyboardButton(a.name, callback_data=f"ta_{a.id}")] for a in accs]
    kb.append([InlineKeyboardButton("All Accounts", callback_data="ta_all")])
    kb.append([InlineKeyboardButton("⬅ Back", callback_data="back_main")])
    await q.edit_message_text("Select account:", reply_markup=InlineKeyboardMarkup(kb))

async def trade_acc_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    s = Session()
    u = get_user(q.from_user.id)
    if q.data == "ta_all":
        accs = s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all()
        acc_ids = [a.id for a in accs]
    else:
        acc_ids = [q.data[3:]]
    ctx.user_data['trade']['acc_ids'] = acc_ids
    pairs = s.query(Pair).filter_by(user_id=u.id).all()
    s.close()
    kb = [[InlineKeyboardButton(p.symbol, callback_data=f"tp_{p.symbol}")] for p in pairs]
    kb.append([InlineKeyboardButton("⬅ Back", callback_data="back_main")])
    await q.edit_message_text("Select pair:", reply_markup=InlineKeyboardMarkup(kb))

async def trade_pair_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data['trade']['symbol'] = q.data[3:]
    await q.edit_message_text("LONG or SHORT?", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("LONG 📈", callback_data="dir_LONG"), InlineKeyboardButton("SHORT 📉", callback_data="dir_SHORT")]
    ]))

async def dir_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data['trade']['direction'] = q.data.split('_')[1]
    ctx.user_data['trade']['step'] = 'photo'
    await q.edit_message_text("Send BEFORE photo", reply_markup=back_button())

async def cut_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cut = float(q.data.split('_')[1])
    s = Session()
    u = get_user(q.from_user.id)
    bal = ctx.user_data['na_bal']
    fee = ctx.user_data['na_fee']
    name = ctx.user_data['na_name']
    acc = Account(user_id=u.id, name=name, type='CHALLENGE', start_balance=bal, current_balance=bal, fee_paid=fee, payout_cut=cut)
    s.add(acc)
    s.add(CashTx(user_id=u.id, type='FEE', amount=-fee, note=f"Buy {name}"))
    s.commit()
    s.close()
    ctx.user_data.clear()
    await q.edit_message_text(f"✅ {name} CHALLENGE created\nFee: ${fee} | Prop cut: {cut}%", reply_markup=main_menu(q.from_user.id))

async def close_start(q, ctx):
    s = Session()
    u = get_user(q.from_user.id)
    trs = s.query(Trade).filter_by(user_id=u.id, closed_at=None).all()
    s.close()
    kb = [[InlineKeyboardButton(f"{t.symbol} {t.direction}", callback_data=f"tc_{t.id}")] for t in trs]
    kb.append([InlineKeyboardButton("⬅ Back", callback_data="back_main")])
    await q.edit_message_text("Select trade to close:", reply_markup=InlineKeyboardMarkup(kb))

async def close_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data['mode'] = 'close'
    ctx.user_data['close'] = {'id': q.data[3:], 'step': 'photo'}
    await q.edit_message_text("Send AFTER photo", reply_markup=back_button())

async def close_res_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    res = q.data.split('_')[1]
    ctx.user_data['close']['result'] = res
    tid = ctx.user_data['close']['id']
    s = Session()
    tas = s.query(TradeAccount).filter_by(trade_id=tid).all()
    s.close()
    if not tas:
        await q.edit_message_text("No accounts linked to this trade", reply_markup=back_button())
        return
    ctx.user_data['close']['tas'] = {ta.account_id: ta.pnl_usd for ta in tas}
    await show_close_accounts_menu(q, ctx)

async def show_close_accounts_menu(q_or_update, ctx):
    tid = ctx.user_data['close']['id']
    res = ctx.user_data['close']['result']
    acc_pnls = ctx.user_data['close']['tas']
    s = Session()
    kb = []
    all_done = True
    for acc_id, pnl in acc_pnls.items():
        acc = s.query(Account).get(acc_id)
        if pnl is None:
            kb.append([InlineKeyboardButton(f"[ ] {acc.name}", callback_data=f"closeacc_{tid}_{acc_id}")])
            all_done = False
        else:
            kb.append([InlineKeyboardButton(f"[✅ ${pnl:+.0f}] {acc.name}", callback_data=f"closeacc_{tid}_{acc_id}")])
    if all_done:
        kb.append([InlineKeyboardButton("✅ DONE - Close Trade", callback_data="closeacc_done")])
    else:
        kb.append([InlineKeyboardButton("⬅ Back", callback_data="back_main")])
    s.close()
    text = f"{res} hit. Click each account to enter PnL:"
    if isinstance(q_or_update, Update):
        await q_or_update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await q_or_update.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def close_acc_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data.split('_')
    if data[1] == "done":
        tid = ctx.user_data['close']['id']
        s = Session()
        tr = s.query(Trade).get(tid)
        tr.closed_at = datetime.utcnow()
        for acc_id, pnl in ctx.user_data['close']['tas'].items():
            ta = s.query(TradeAccount).filter_by(trade_id=tid, account_id=acc_id).first()
            ta.pnl_usd = pnl
            ta.result = ctx.user_data['close']['result']
            ta.closed_at = datetime.utcnow()
            acc = s.query(Account).get(acc_id)
            acc.current_balance += pnl
        s.commit()
        s.close()
        ctx.user_data.clear()
        await q.edit_message_text("✅ Trade closed. All accounts updated.", reply_markup=main_menu(q.from_user.id))
        return
    tid, acc_id = data[1], data[2]
    ctx.user_data['mode'] = 'close_pnl'
    ctx.user_data['close']['current_acc'] = acc_id
    s = Session()
    acc = s.query(Account).get(acc_id)
    s.close()
    await q.edit_message_text(
        f"Enter PnL for {acc.name}:\nCurrent balance: ${acc.current_balance:.2f}\n\n"
        f"Send dollar amount. Use - for loss, + for profit.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back to list", callback_data="closeacc_back")]])
    )

async def close_acc_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data['mode'] = 'close'
    await show_close_accounts_menu(q, ctx)

async def admin_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "admin_users":
        s = Session()
        users = s.query(User).all()
        msg = f"👥 Users ({len(users)})\n\n"
        for u in users:
            msg += f"• {u.telegram_id} {'(admin)' if u.is_admin=='1' else ''}\n"
        if len(users) == 1:
            msg += "\nYou are the only user"
        s.close()
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back", callback_data="menu_admin")]]))

async def pair_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    s = Session()
    if q.data == "pair_add":
        ctx.user_data['mode'] = 'pair_add'
        await q.edit_message_text("Send pair symbol (e.g. EURUSD)", reply_markup=back_button())
    elif q.data.startswith("pairdel_"):
        pid = q.data[8:]
        s.query(Pair).filter_by(id=pid).delete()
        s.commit()
        await q.edit_message_text("✅ Pair deleted", reply_markup=back_button())
    s.close()

async def delacc_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    aid = q.data[7:]
    s = Session()
    s.query(Account).filter_by(id=aid).delete()
    s.commit()
    s.close()
    await q.edit_message_text("✅ Account deleted", reply_markup=back_button())

async def view_trade_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tid = q.data[5:]
    s = Session()
    tr = s.query(Trade).get(tid)
    if not tr:
        s.close()
        await q.edit_message_text("Trade not found", reply_markup=back_button())
        return
    msg = f"📖 {tr.symbol} {tr.direction}\nOpened: {tr.opened_at.strftime('%d/%m/%Y %H:%M')}"
    if tr.closed_at:
        msg += f"\nClosed: {tr.closed_at.strftime('%d/%m/%Y %H:%M')}"
    tas = s.query(TradeAccount).filter_by(trade_id=tid).all()
    if tas and any(t.pnl_usd for t in tas):
        pnl = sum(t.pnl_usd or 0 for t in tas)
        msg += f"\nPnL: ${pnl:+.2f}"
    await q.edit_message_text(msg, reply_markup=back_button())
    if tr.before_photo:
        await q.message.reply_photo(tr.before_photo, caption="Before")
    if tr.after_photo:
        await q.message.reply_photo(tr.after_photo, caption="After")
    s.close()

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    mode = ctx.user_data.get('mode')
    txt = update.message.text.strip()
    s = Session()
    u = get_user(update.effective_user.id)

    if mode == 'new_acc':
        step = ctx.user_data.get('step', 1)
        atype = ctx.user_data.get('atype')
        if step == 1:
            ctx.user_data['na_name'] = txt
            ctx.user_data['step'] = 2
            if atype == 'CHALLENGE':
                await update.message.reply_text("Account size? (e.g. 100000)", reply_markup=back_button())
            else:
                await update.message.reply_text("Starting balance?", reply_markup=back_button())
        elif step == 2:
            ctx.user_data['na_bal'] = float(txt)
            if atype == 'CHALLENGE':
                ctx.user_data['step'] = 3
                await update.message.reply_text("Fee paid? (will be deducted from Bank)", reply_markup=back_button())
            else:
                bal = ctx.user_data['na_bal']
                acc = Account(user_id=u.id, name=ctx.user_data['na_name'], type='LIVE', start_balance=bal, current_balance=bal, fee_paid=0)
                s.add(acc)
                s.add(CashTx(user_id=u.id, type='DEPOSIT', amount=-bal, note=f"Fund {ctx.user_data['na_name']}"))
                s.commit()
                ctx.user_data.clear()
                await update.message.reply_text(f"✅ {acc.name} LIVE created (Bank -${bal})", reply_markup=main_menu(update.effective_user.id))
        elif step == 3:
            ctx.user_data['na_fee'] = float(txt)
            ctx.user_data['step'] = 4
            await update.message.reply_text("Prop firm keeps what %?", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("10%", callback_data="cut_10"), InlineKeyboardButton("15%", callback_data="cut_15")],
                [InlineKeyboardButton("20%", callback_data="cut_20"), InlineKeyboardButton("25%", callback_data="cut_25")]
            ]))

    elif mode == 'withdraw':
        amt = float(txt)
        acc = s.query(Account).get(ctx.user_data['wd_acc'])
        acc.current_balance -= amt
        s.add(CashTx(user_id=u.id, type='WITHDRAW', amount=amt, note=f"From {acc.name}"))
        s.commit()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Withdrew ${amt} from {acc.name} to bank", reply_markup=main_menu(update.effective_user.id))

    elif mode == 'payout':
        gross = float(txt)
        acc = s.query(Account).get(ctx.user_data['payout_acc'])
        cut = acc.payout_cut if acc.type == 'CHALLENGE' else 0
        net = gross * (1 - cut / 100)
        acc.current_balance -= gross
        s.add(CashTx(user_id=u.id, type='PAYOUT', amount=net, note=f"{acc.name} gross ${gross} -{cut}%"))
        s.commit()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Payout: ${gross} → Bank +${net:.2f} ({cut}% fee)", reply_markup=main_menu(update.effective_user.id))

    elif mode == 'deposit':
        amt = float(txt)
        acc = s.query(Account).get(ctx.user_data['deposit_acc'])
        acc.current_balance += amt
        s.add(CashTx(user_id=u.id, type='DEPOSIT', amount=-amt, note=f"Fund {acc.name}"))
        s.commit()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Deposited ${amt} to {acc.name} (Bank -${amt})", reply_markup=main_menu(update.effective_user.id))

    elif mode == 'quick':
        qt = ctx.user_data['qt']
        if qt == 'challenge':
            name, bal, fee = txt.split()
            acc = Account(user_id=u.id, name=name, type='CHALLENGE', start_balance=float(bal), current_balance=float(bal), fee_paid=float(fee))
            s.add(acc)
            s.add(CashTx(user_id=u.id, type='FEE', amount=-float(fee), note=f"Buy {name}"))
            s.commit()
            await update.message.reply_text(f"✅ {name} added", reply_markup=main_menu(update.effective_user.id))
        ctx.user_data.clear()

    elif mode == 'pair_add':
        sym = txt.upper().replace("/", "")
        s.add(Pair(user_id=u.id, symbol=sym))
        s.commit()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Pair added: {sym}", reply_markup=main_menu(update.effective_user.id))

    elif mode == 'bal_edit':
        new_amt = float(txt)
        current = sum(t.amount for t in s.query(CashTx).filter_by(user_id=u.id)) or 0
        diff = new_amt - current
        s.add(CashTx(user_id=u.id, type='ADJUST', amount=diff, note='Manual edit'))
        s.commit()
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Bank set to ${new_amt:.2f}", reply_markup=main_menu(update.effective_user.id))

    elif mode == 'close_pnl':
        try:
            pnl = float(txt)
            acc_id = ctx.user_data['close']['current_acc']
            ctx.user_data['close']['tas'][acc_id] = pnl
            ctx.user_data['mode'] = 'close'
            await show_close_accounts_menu(update, ctx)
        except ValueError:
            await update.message.reply_text("Send a valid number like +400 or -150", reply_markup=back_button())

    s.close()

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
        ctx.user_data.clear()
        await update.message.reply_text(f"✅ Trade {tr.symbol} {tr.direction} logged", reply_markup=main_menu(update.effective_user.id))
    elif mode == 'close' and ctx.user_data.get('close', {}).get('step') == 'photo':
        tid = ctx.user_data['close']['id']
        tr = s.query(Trade).get(tid)
        tr.after_photo = update.message.photo[-1].file_id
        s.commit()
        ctx.user_data['close']['step'] = 'result'
        await update.message.reply_text("SL or TP?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("SL ❌", callback_data="res_SL"), InlineKeyboardButton("TP ✅", callback_data="res_TP")]]))
    s.close()

def main():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^menu_"))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^bal_"))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^clear_"))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^add_"))
    app.add_handler(CallbackQueryHandler(profit_cb, pattern="^profit_"))
    app.add_handler(CallbackQueryHandler(archive_acc, pattern="^arch_"))
    app.add_handler(CallbackQueryHandler(wd_select, pattern="^wd_"))
    app.add_handler(CallbackQueryHandler(payout_select, pattern="^payout_"))
    app.add_handler(CallbackQueryHandler(deposit_select, pattern="^deposit_"))
    app.add_handler(CallbackQueryHandler(reset_yes, pattern="^reset_yes$"))
    app.add_handler(CallbackQueryHandler(trade_acc_cb, pattern="^ta_"))
    app.add_handler(CallbackQueryHandler(trade_pair_cb, pattern="^tp_"))
    app.add_handler(CallbackQueryHandler(dir_cb, pattern="^dir_"))
    app.add_handler(CallbackQueryHandler(cut_cb, pattern="^cut_"))
    app.add_handler(CallbackQueryHandler(close_cb, pattern="^tc_"))
    app.add_handler(CallbackQueryHandler(close_res_cb, pattern="^res_"))
    app.add_handler(CallbackQueryHandler(close_acc_select, pattern="^closeacc_"))
    app.add_handler(CallbackQueryHandler(close_acc_back, pattern="^closeacc_back$"))
    app.add_handler(CallbackQueryHandler(admin_cb, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(pair_cb, pattern="^pair"))
    app.add_handler(CallbackQueryHandler(delacc_cb, pattern="^delacc_"))
    app.add_handler(CallbackQueryHandler(view_trade_cb, pattern="^view_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.run_polling()

if __name__ == "__main__":
    main()