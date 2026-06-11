import os
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from sqlalchemy import create_engine, Column, String, Float, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from datetime import datetime
import uuid

# ===== DATABASE MODELS (all in one file) =====
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

# ===== DB SETUP =====
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

# ===== BOT HANDLERS =====
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    get_user(update.effective_user.id)
    await update.message.reply_text("EdgeFlo ready\n/newaccount\n/fund\n/pairs\n/trade\n/close\n/accounts\n/bank")

NEW_NAME, NEW_TYPE, NEW_BAL, NEW_FEE = range(4)
async def newaccount(update, ctx):
    await update.message.reply_text("Account name?"); return NEW_NAME
async def na_name(update, ctx):
    ctx.user_data['na_name'] = update.message.text
    await update.message.reply_text("Type? CHALLENGE or LIVE"); return NEW_TYPE
async def na_type(update, ctx):
    ctx.user_data['na_type'] = update.message.text.upper()
    await update.message.reply_text("Starting balance?"); return NEW_BAL
async def na_bal(update, ctx):
    ctx.user_data['na_bal'] = float(update.message.text)
    await update.message.reply_text("Fee paid? (0 if none)"); return NEW_FEE
async def na_fee(update, ctx):
    s = Session(); u = get_user(update.effective_user.id); fee = float(update.message.text)
    acc = Account(user_id=u.id, name=ctx.user_data['na_name'], type=ctx.user_data['na_type'],
                  start_balance=ctx.user_data['na_bal'], current_balance=ctx.user_data['na_bal'], fee_paid=fee)
    s.add(acc)
    if fee>0: s.add(CashTx(user_id=u.id, type='FEE', amount=-fee, note=f"Buy {acc.name}"))
    s.commit(); s.close()
    await update.message.reply_text(f"✅ {acc.name} created"); return ConversationHandler.END

async def fund(update, ctx):
    if len(ctx.args)<2: return await update.message.reply_text("Usage: /fund NAME AMOUNT")
    name, amt = ctx.args[0], float(ctx.args[1])
    s = Session(); u = get_user(update.effective_user.id)
    acc = s.query(Account).filter_by(user_id=u.id, name=name).first()
    if not acc: s.close(); return await update.message.reply_text("Account not found")
    acc.current_balance += amt; acc.start_balance += amt
    s.add(CashTx(user_id=u.id, type='FEE', amount=-amt, note=f"Fund {name}"))
    s.commit(); s.close()
    await update.message.reply_text(f"✅ Funded {name} +${amt}")

async def addpair(update, ctx):
    if not ctx.args: return await update.message.reply_text("Usage /addpair EURUSD")
    sym = ctx.args[0].upper(); s = Session(); u = get_user(update.effective_user.id)
    s.merge(Pair(user_id=u.id, symbol=sym)); s.commit(); s.close()
    await update.message.reply_text(f"✅ {sym}")

async def pairs(update, ctx):
    s = Session(); u = get_user(update.effective_user.id)
    ps = s.query(Pair).filter_by(user_id=u.id).all(); s.close()
    await update.message.reply_text("Pairs: " + ", ".join(p.symbol for p in ps) if ps else "none")

async def accounts(update, ctx):
    s = Session(); u = get_user(update.effective_user.id)
    accs = s.query(Account).filter_by(user_id=u.id).all(); msg="📊 ACCOUNTS\n"
    for a in accs:
        pnl = a.current_balance - a.start_balance
        msg += f"{'🟢' if pnl>=0 else '🔴'} {a.name}: ${a.current_balance:.2f} ({pnl:+.2f})\n"
    s.close(); await update.message.reply_text(msg)

async def bank(update, ctx):
    s = Session(); u = get_user(update.effective_user.id)
    txs = s.query(CashTx).filter_by(user_id=u.id).all(); net = sum(t.amount for t in txs)
    s.close(); await update.message.reply_text(f"💰 Bank: ${net:.2f}")

async def payout(update, ctx):
    if not ctx.args: return await update.message.reply_text("Usage /payout 3000 20")
    gross=float(ctx.args[0]); cut=float(ctx.args[1]) if len(ctx.args)>1 else 20; net=gross*(1-cut/100)
    s=Session(); u=get_user(update.effective_user.id)
    s.add(CashTx(user_id=u.id, type='PAYOUT', amount=net, note=f"gross {gross}"))
    s.commit(); s.close(); await update.message.reply_text(f"✅ +${net:.2f}")

async def trade(update, ctx):
    s=Session(); u=get_user(update.effective_user.id); accs=s.query(Account).filter_by(user_id=u.id).all(); s.close()
    if not accs: return await update.message.reply_text("Add account first")
    ctx.user_data['trade']={'acc_ids':[]}
    kb=[[InlineKeyboardButton(a.name, callback_data=f"ta_{a.id}")] for a in accs]
    kb.append([InlineKeyboardButton("Done ✅", callback_data="ta_done")])
    await update.message.reply_text("Tap accounts", reply_markup=InlineKeyboardMarkup(kb))

async def trade_acc_cb(update, ctx):
    q=update.callback_query; await q.answer(); t=ctx.user_data['trade']
    if q.data=="ta_done":
        s=Session(); u=get_user(update.effective_user.id); pairs=s.query(Pair).filter_by(user_id=u.id).all(); s.close()
        if pairs: kb=[[InlineKeyboardButton(p.symbol, callback_data=f"tp_{p.symbol}")] for p in pairs]; await q.edit_message_text("Pick pair", reply_markup=InlineKeyboardMarkup(kb))
        else: await q.edit_message_text("Type pair")
        t['step']='pair'; return
    aid=q.data[3:]; t['acc_ids'].remove(aid) if aid in t['acc_ids'] else t['acc_ids'].append(aid)

async def trade_pair_cb(update, ctx):
    q=update.callback_query; await q.answer(); ctx.user_data['trade']['symbol']=q.data[3:]; ctx.user_data['trade']['step']='dir'
    await q.edit_message_text("LONG or SHORT?")

async def trade_text(update, ctx):
    t=ctx.user_data.get('trade'); 
    if not t: return
    txt=update.message.text.strip().upper()
    if t.get('step')=='pair' and 'symbol' not in t: t['symbol']=txt; t['step']='dir'; return await update.message.reply_text("LONG or SHORT?")
    if t['step']=='dir': t['direction']=txt; t['step']='entry'; return await update.message.reply_text("Entry?")
    if t['step']=='entry': t['entry']=float(txt); t['step']='sl'; return await update.message.reply_text("SL?")
    if t['step']=='sl': t['sl']=float(txt); t['step']='tp'; return await update.message.reply_text("TP?")
    if t['step']=='tp': t['tp']=float(txt); t['rr']=abs((t['tp']-t['entry'])/(t['entry']-t['sl'])) if t['entry']!=t['sl'] else 0; t['step']='photo'; return await update.message.reply_text(f"RR {t['rr']:.2f}. Send BEFORE")

async def trade_photo(update, ctx):
    t=ctx.user_data.get('trade')
    if not t or t.get('step')!='photo': return
    fid=update.message.photo[-1].file_id; s=Session(); u=get_user(update.effective_user.id)
    tr=Trade(user_id=u.id, symbol=t['symbol'], direction=t['direction'], entry=t['entry'], sl=t['sl'], tp=t['tp'], rr=t['rr'], before_photo=fid)
    s.add(tr); s.flush()
    for aid in t['acc_ids']: s.add(TradeAccount(trade_id=tr.id, account_id=aid))
    s.commit(); s.close(); ctx.user_data['trade']=None
    await update.message.reply_text(f"✅ {tr.symbol} logged")

async def close(update, ctx):
    s=Session(); u=get_user(update.effective_user.id); trs=s.query(Trade).filter_by(user_id=u.id, closed_at=None).limit(10).all(); s.close()
    if not trs: return await update.message.reply_text("No open")
    kb=[[InlineKeyboardButton(f"{t.symbol} {t.direction}", callback_data=f"tc_{t.id}")] for t in trs]
    await update.message.reply_text("Pick", reply_markup=InlineKeyboardMarkup(kb))

async def close_cb(update, ctx):
    q=update.callback_query; await q.answer(); ctx.user_data['close']={'id':q.data[3:],'step':'photo'}
    await q.edit_message_text("Send AFTER")

async def close_photo(update, ctx):
    c=ctx.user_data.get('close')
    if not c or c['step']!='photo': return
    fid=update.message.photo[-1].file_id; s=Session()
    tr=s.query(Trade).get(c['id']); tr.after_photo=fid
    accs=s.query(TradeAccount).filter_by(trade_id=c['id']).all()
    c['accs']=[(a.account_id, s.query(Account).get(a.account_id).name) for a in accs]; c['i']=0; c['step']='pnl'
    s.commit(); s.close(); await update.message.reply_text(f"PnL for {c['accs'][0][1]}?")

async def close_pnl(update, ctx):
    c=ctx.user_data.get('close')
    if not c or c['step']!='pnl': return
    try: val=float(update.message.text)
    except: return await update.message.reply_text("Send number")
    aid,name=c['accs'][c['i']]; s=Session()
    ta=s.query(TradeAccount).filter_by(trade_id=c['id'], account_id=aid).first()
    ta.pnl_usd=val; ta.result='TP' if val>0 else 'SL' if val<0 else 'BE'; ta.closed_at=datetime.utcnow()
    acc=s.query(Account).get(aid); acc.current_balance+=val; s.commit()
    c['i']+=1
    if c['i']>=len(c['accs']):
        tr=s.query(Trade).get(c['id']); tr.closed_at=datetime.utcnow(); s.commit(); s.close()
        ctx.user_data['close']=None; await update.message.reply_text("✅ Closed")
    else: s.close(); await update.message.reply_text(f"PnL for {c['accs'][c['i']][1]}?")

def main():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    conv = ConversationHandler(entry_points=[CommandHandler('newaccount', newaccount)],
        states={NEW_NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND, na_name)],
                NEW_TYPE:[MessageHandler(filters.TEXT & ~filters.COMMAND, na_type)],
                NEW_BAL:[MessageHandler(filters.TEXT & ~filters.COMMAND, na_bal)],
                NEW_FEE:[MessageHandler(filters.TEXT & ~filters.COMMAND, na_fee)]}, fallbacks=[])
    app.add_handler(CommandHandler("start", start)); app.add_handler(conv)
    app.add_handler(CommandHandler("fund", fund)); app.add_handler(CommandHandler("addpair", addpair))
    app.add_handler(CommandHandler("pairs", pairs)); app.add_handler(CommandHandler("accounts", accounts))
    app.add_handler(CommandHandler("bank", bank)); app.add_handler(CommandHandler("payout", payout))
    app.add_handler(CommandHandler("trade", trade)); app.add_handler(CallbackQueryHandler(trade_acc_cb, pattern="^ta_"))
    app.add_handler(CallbackQueryHandler(trade_pair_cb, pattern="^tp_")); app.add_handler(CommandHandler("close", close))
    app.add_handler(CallbackQueryHandler(close_cb, pattern="^tc_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, trade_text))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, close_pnl), group=1)
    app.add_handler(MessageHandler(filters.PHOTO, trade_photo), group=2)
    app.add_handler(MessageHandler(filters.PHOTO, close_photo), group=3)
    print("Bot running..."); app.run_polling()

if __name__ == "__main__":
    main()
