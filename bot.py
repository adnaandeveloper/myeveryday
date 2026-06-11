import os
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from sqlalchemy import create_engine, Column, String, Float, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import uuid

Base = declarative_base()
def uid(): return str(uuid.uuid4())

class User(Base):
    __tablename__ = 'users'
    id = Column(String, primary_key=True, default=uid)
    telegram_id = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Account(Base):
    __tablename__ = 'accounts'
    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey('users.id'))
    name = Column(String)
    type = Column(String)
    start_balance = Column(Float)
    current_balance = Column(Float)
    fee_paid = Column(Float, default=0)
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
    entry = Column(Float)
    sl = Column(Float)
    tp = Column(Float)
    rr = Column(Float)
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

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./edgeflo.db")
engine = create_engine(DATABASE_URL, echo=False, future=True)
Session = sessionmaker(bind=engine)
Base.metadata.create_all(engine)

def get_user(telegram_id: str):
    s = Session()
    u = s.query(User).filter_by(telegram_id=str(telegram_id)).first()
    if not u:
        u = User(telegram_id=str(telegram_id))
        s.add(u); s.commit()
    s.close()
    return u

def main_menu():
    kb = [
        [InlineKeyboardButton("📝 Log Trade", callback_data="menu_log"), InlineKeyboardButton("✅ Close Trade", callback_data="menu_close")],
        [InlineKeyboardButton("💰 Balance", callback_data="menu_balance"), InlineKeyboardButton("⚙️ My Accounts", callback_data="menu_accounts")],
        [InlineKeyboardButton("📊 Analyse", callback_data="menu_analyse"), InlineKeyboardButton("📖 Journal", callback_data="menu_journal")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="menu_leader"), InlineKeyboardButton("📜 Trade History", callback_data="menu_hist")],
        [InlineKeyboardButton("➕ Add Account", callback_data="menu_add"), InlineKeyboardButton("💸 Profit Tracker", callback_data="menu_profit")],
        [InlineKeyboardButton("👑 ADMIN PANEL", callback_data="menu_admin")]
    ]
    return InlineKeyboardMarkup(kb)

def profit_menu():
    kb = [
        [InlineKeyboardButton("💳 Challenge Buy", callback_data="profit_challenge"), InlineKeyboardButton("💰 Live Deposit", callback_data="profit_deposit")],
        [InlineKeyboardButton("💸 Log Payout", callback_data="profit_payout"), InlineKeyboardButton("📊 View Stats", callback_data="profit_stats")],
        [InlineKeyboardButton("📝 Edit/Delete", callback_data="profit_edit")],
        [InlineKeyboardButton("⬅️ Back", callback_data="profit_back")]
    ]
    return InlineKeyboardMarkup(kb)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    get_user(update.effective_user.id)
    await update.message.reply_text("📊 Trading Journal", reply_markup=main_menu())

async def menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); data = q.data
    if data == "menu_log": return await trade_start(q, ctx)
    if data == "menu_close": return await close_start(q, ctx)
    if data == "menu_balance": return await show_bank(q, ctx)
    if data == "menu_accounts": return await show_accounts(q, ctx)
    if data == "menu_add": await q.message.reply_text("Account name?"); ctx.user_data['state']='new_name'; return
    if data == "menu_profit": await q.edit_message_text("💸 Profit Tracker\nLog your trading expenses and income:", reply_markup=profit_menu()); return
    await q.edit_message_text(f"{data} - coming soon", reply_markup=main_menu())

async def profit_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); d = q.data
    if d == "profit_back": await q.edit_message_text("📊 Trading Journal", reply_markup=main_menu()); return
    if d == "profit_challenge": ctx.user_data['quick']='challenge'; await q.edit_message_text("Send: NAME BALANCE FEE\nExample: FTMO 100000 100"); return
    if d == "profit_deposit": ctx.user_data['quick']='deposit'; await q.edit_message_text("Send: NAME AMOUNT\nExample: Live 500"); return
    if d == "profit_payout": ctx.user_data['quick']='payout'; await q.edit_message_text("Send: AMOUNT FEE%\nExample: 3000 20"); return
    if d == "profit_stats": return await show_bank(q, ctx)

async def quick_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    qtype = ctx.user_data.get('quick')
    if not qtype: return
    txt = update.message.text; s = Session(); u = get_user(update.effective_user.id)
    try:
        if qtype == 'challenge':
            name, bal, fee = txt.split(); acc = Account(user_id=u.id, name=name, type='CHALLENGE', start_balance=float(bal), current_balance=float(bal), fee_paid=float(fee)); s.add(acc); s.add(CashTx(user_id=u.id, type='FEE', amount=-float(fee), note=f"Buy {name}")); s.commit(); await update.message.reply_text(f"✅ {name} created, -${fee}", reply_markup=main_menu())
        elif qtype == 'deposit':
            name, amt = txt.split(); acc = s.query(Account).filter_by(user_id=u.id, name=name).first(); acc.current_balance+=float(amt); acc.start_balance+=float(amt); s.add(CashTx(user_id=u.id, type='FEE', amount=-float(amt), note=f"Fund {name}")); s.commit(); await update.message.reply_text(f"✅ +${amt} to {name}", reply_markup=main_menu())
        elif qtype == 'payout':
            parts = txt.split(); gross=float(parts[0]); cut=float(parts[1]) if len(parts)>1 else 20; net=gross*(1-cut/100); s.add(CashTx(user_id=u.id, type='PAYOUT', amount=net, note=f"gross {gross}")); s.commit(); await update.message.reply_text(f"✅ Payout +${net:.2f}", reply_markup=main_menu())
    finally: s.close(); ctx.user_data['quick']=None

# Simplified new account flow
async def text_handler(update, ctx):
    state = ctx.user_data.get('state')
    if state == 'new_name': ctx.user_data['na_name']=update.message.text; ctx.user_data['state']='new_type'; return await update.message.reply_text("Type? CHALLENGE or LIVE")
    if state == 'new_type': ctx.user_data['na_type']=update.message.text.upper(); ctx.user_data['state']='new_bal'; return await update.message.reply_text("Starting balance?")
    if state == 'new_bal': ctx.user_data['na_bal']=float(update.message.text); ctx.user_data['state']='new_fee'; return await update.message.reply_text("Fee paid? (0 if none)")
    if state == 'new_fee':
        s=Session(); u=get_user(update.effective_user.id); fee=float(update.message.text)
        acc=Account(user_id=u.id, name=ctx.user_data['na_name'], type=ctx.user_data['na_type'], start_balance=ctx.user_data['na_bal'], current_balance=ctx.user_data['na_bal'], fee_paid=fee)
        s.add(acc)
        if fee>0: s.add(CashTx(user_id=u.id, type='FEE', amount=-fee, note=f"Buy {acc.name}"))
        s.commit(); s.close(); ctx.user_data['state']=None; return await update.message.reply_text(f"✅ {acc.name} added", reply_markup=main_menu())

async def show_accounts(q, ctx):
    s=Session(); u=get_user(q.from_user.id); accs=s.query(Account).filter_by(user_id=u.id).all(); msg="📊 My Accounts\n"
    for a in accs: pnl=a.current_balance-a.start_balance; msg+=f"{'🟢' if pnl>=0 else '🔴'} {a.name}: ${a.current_balance:.2f}\n"
    s.close(); await q.edit_message_text(msg, reply_markup=main_menu())

async def show_bank(q, ctx):
    s=Session(); u=get_user(q.from_user.id); txs=s.query(CashTx).filter_by(user_id=u.id).all(); net=sum(t.amount for t in txs); s.close()
    await q.edit_message_text(f"💰 Real Balance: ${net:.2f}", reply_markup=main_menu())

async def trade_start(q, ctx):
    s=Session(); u=get_user(q.from_user.id); accs=s.query(Account).filter_by(user_id=u.id).all(); s.close()
    ctx.user_data['trade']={'acc_ids':[]}
    kb=[[InlineKeyboardButton(a.name, callback_data=f"ta_{a.id}")] for a in accs]; kb.append([InlineKeyboardButton("Done ✅", callback_data="ta_done")])
    await q.edit_message_text("Select accounts", reply_markup=InlineKeyboardMarkup(kb))

async def trade_acc_cb(update, ctx):
    q=update.callback_query; await q.answer(); t=ctx.user_data['trade']
    if q.data=="ta_done":
        s=Session(); u=get_user(q.from_user.id); pairs=s.query(Pair).filter_by(user_id=u.id).all(); s.close()
        if pairs: kb=[[InlineKeyboardButton(p.symbol, callback_data=f"tp_{p.symbol}")] for p in pairs]; await q.edit_message_text("Select pair", reply_markup=InlineKeyboardMarkup(kb))
        else: await q.edit_message_text("Type pair (e.g. EURUSD)"); t['step']='pair'; return
        t['step']='pair'; return
    aid=q.data[3:]; t['acc_ids'].remove(aid) if aid in t['acc_ids'] else t['acc_ids'].append(aid)

async def trade_pair_cb(update, ctx):
    q=update.callback_query; await q.answer(); ctx.user_data['trade']['symbol']=q.data[3:]; ctx.user_data['trade']['step']='dir'; await q.edit_message_text("LONG or SHORT?")

async def trade_text(update, ctx):
    t=ctx.user_data.get('trade')
    if not t: return
    txt=update.message.text.strip().upper()
    if t.get('step')=='pair' and 'symbol' not in t: t['symbol']=txt; t['step']='dir'; return await update.message.reply_text("LONG or SHORT?")
    if t['step']=='dir': t['direction']=txt; t['step']='entry'; return await update.message.reply_text("Entry price?")
    if t['step']=='entry': t['entry']=float(txt); t['step']='sl'; return await update.message.reply_text("SL price?")
    if t['step']=='sl': t['sl']=float(txt); t['step']='tp'; return await update.message.reply_text("TP price?")
    if t['step']=='tp': t['tp']=float(txt); t['rr']=abs((t['tp']-t['entry'])/(t['entry']-t['sl'])) if t['entry']!=t['sl'] else 0; t['step']='photo'; return await update.message.reply_text(f"RR {t['rr']:.2f}. Send BEFORE photo")

async def trade_photo(update, ctx):
    t=ctx.user_data.get('trade')
    if not t or t.get('step')!='photo': return
    fid=update.message.photo[-1].file_id; s=Session(); u=get_user(update.effective_user.id)
    tr=Trade(user_id=u.id, symbol=t['symbol'], direction=t['direction'], entry=t['entry'], sl=t['sl'], tp=t['tp'], rr=t['rr'], before_photo=fid)
    s.add(tr); s.flush()
    for aid in t['acc_ids']: s.add(TradeAccount(trade_id=tr.id, account_id=aid))
    s.commit(); s.close(); ctx.user_data['trade']=None; await update.message.reply_text(f"✅ {tr.symbol} logged", reply_markup=main_menu())

async def close_start(q, ctx):
    s=Session(); u=get_user(q.from_user.id); trs=s.query(Trade).filter_by(user_id=u.id, closed_at=None).limit(10).all(); s.close()
    if not trs: await q.edit_message_text("No open trades", reply_markup=main_menu()); return
    kb=[[InlineKeyboardButton(f"{t.symbol} {t.direction}", callback_data=f"tc_{t.id}")] for t in trs]; await q.edit_message_text("Select trade", reply_markup=InlineKeyboardMarkup(kb))

async def close_cb(update, ctx):
    q=update.callback_query; await q.answer(); ctx.user_data['close']={'id':q.data[3:],'step':'photo'}; await q.edit_message_text("Send AFTER photo")

async def close_photo(update, ctx):
    c=ctx.user_data.get('close')
    if not c or c['step']!='photo': return
    fid=update.message.photo[-1].file_id; s=Session(); tr=s.query(Trade).get(c['id']); tr.after_photo=fid
    accs=s.query(TradeAccount).filter_by(trade_id=c['id']).all(); c['accs']=[(a.account_id, s.query(Account).get(a.account_id).name) for a in accs]; c['i']=0; c['step']='pnl'; s.commit(); s.close()
    await update.message.reply_text(f"PnL for {c['accs'][0][1]}?")

async def close_pnl(update, ctx):
    c=ctx.user_data.get('close')
    if not c or c['step']!='pnl': return
    try: val=float(update.message.text)
    except: return await update.message.reply_text("Send number")
    aid,name=c['accs'][c['i']]; s=Session(); ta=s.query(TradeAccount).filter_by(trade_id=c['id'], account_id=aid).first(); ta.pnl_usd=val; ta.result='TP' if val>0 else 'SL' if val<0 else 'BE'; ta.closed_at=datetime.utcnow(); acc=s.query(Account).get(aid); acc.current_balance+=val; s.commit(); c['i']+=1
    if c['i']>=len(c['accs']): tr=s.query(Trade).get(c['id']); tr.closed_at=datetime.utcnow(); s.commit(); s.close(); ctx.user_data['close']=None; await update.message.reply_text("✅ Closed", reply_markup=main_menu())
    else: s.close(); await update.message.reply_text(f"PnL for {c['accs'][c['i']][1]}?")

def main():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^menu_"))
    app.add_handler(CallbackQueryHandler(profit_cb, pattern="^profit_"))
    app.add_handler(CallbackQueryHandler(trade_acc_cb, pattern="^ta_"))
    app.add_handler(CallbackQueryHandler(trade_pair_cb, pattern="^tp_"))
    app.add_handler(CallbackQueryHandler(close_cb, pattern="^tc_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, quick_text), group=0)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, trade_text), group=2)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, close_pnl), group=3)
    app.add_handler(MessageHandler(filters.PHOTO, trade_photo), group=4)
    app.add_handler(MessageHandler(filters.PHOTO, close_photo), group=5)
    app.run_polling()

if __name__ == "__main__":
    main()
