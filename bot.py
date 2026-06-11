import os
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from sqlalchemy import create_engine, Column, String, Float, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import uuid

Base = declarative_base()
def uid(): return str(uuid.uuid4())

class User(Base):
    __tablename__ = 'users'; id = Column(String, primary_key=True, default=uid); telegram_id = Column(String, unique=True); created_at = Column(DateTime, default=datetime.utcnow)
class Account(Base):
    __tablename__ = 'accounts'; id = Column(String, primary_key=True, default=uid); user_id = Column(String, ForeignKey('users.id')); name = Column(String); type = Column(String); start_balance = Column(Float); current_balance = Column(Float); fee_paid = Column(Float, default=0); status = Column(String, default='ACTIVE'); __table_args__ = (UniqueConstraint('user_id', 'name'),)
class Pair(Base):
    __tablename__ = 'pairs'; id = Column(String, primary_key=True, default=uid); user_id = Column(String, ForeignKey('users.id')); symbol = Column(String); __table_args__ = (UniqueConstraint('user_id', 'symbol'),)
class Trade(Base):
    __tablename__ = 'trades'; id = Column(String, primary_key=True, default=uid); user_id = Column(String, ForeignKey('users.id')); symbol = Column(String); direction = Column(String); entry = Column(Float); sl = Column(Float); tp = Column(Float); rr = Column(Float); before_photo = Column(String); after_photo = Column(String); opened_at = Column(DateTime, default=datetime.utcnow); closed_at = Column(DateTime)
class TradeAccount(Base):
    __tablename__ = 'trade_accounts'; trade_id = Column(String, ForeignKey('trades.id'), primary_key=True); account_id = Column(String, ForeignKey('accounts.id'), primary_key=True); pnl_usd = Column(Float); result = Column(String); closed_at = Column(DateTime)
class CashTx(Base):
    __tablename__ = 'cash_txs'; id = Column(String, primary_key=True, default=uid); user_id = Column(String, ForeignKey('users.id')); type = Column(String); amount = Column(Float); note = Column(Text); date = Column(DateTime, default=datetime.utcnow)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./edgeflo.db")
engine = create_engine(DATABASE_URL, future=True); Session = sessionmaker(bind=engine); Base.metadata.create_all(engine)

def get_user(tid):
    s=Session(); u=s.query(User).filter_by(telegram_id=str(tid)).first()
    if not u: u=User(telegram_id=str(tid)); s.add(u); s.commit()
    s.close(); return u

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Log Trade", callback_data="menu_log"), InlineKeyboardButton("✅ Close Trade", callback_data="menu_close")],
        [InlineKeyboardButton("💰 Balance", callback_data="menu_balance"), InlineKeyboardButton("⚙️ My Accounts", callback_data="menu_accounts")],
        [InlineKeyboardButton("📊 Analyse", callback_data="menu_analyse"), InlineKeyboardButton("📖 Journal", callback_data="menu_journal")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="menu_leader"), InlineKeyboardButton("📜 Trade History", callback_data="menu_hist")],
        [InlineKeyboardButton("➕ Add Account", callback_data="menu_add"), InlineKeyboardButton("💸 Profit Tracker", callback_data="menu_profit")],
    ])

def back_button(): return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_main")]])

def profit_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Challenge Buy", callback_data="profit_challenge"), InlineKeyboardButton("💰 Live Deposit", callback_data="profit_deposit")],
        [InlineKeyboardButton("💸 Log Payout", callback_data="profit_payout"), InlineKeyboardButton("📊 View Stats", callback_data="profit_stats")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back_main")]
    ])

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    get_user(update.effective_user.id); ctx.user_data.clear()
    await update.message.reply_text("📊 Trading Journal", reply_markup=main_menu())

async def back_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); ctx.user_data.clear()
    await q.edit_message_text("📊 Trading Journal", reply_markup=main_menu())

async def menu_cb(update, ctx):
    q=update.callback_query; await q.answer(); d=q.data; ctx.user_data.clear()
    if d=="menu_log": return await trade_start(q, ctx)
    if d=="menu_close": return await close_start(q, ctx)
    if d=="menu_balance": s=Session(); u=get_user(q.from_user.id); net=sum(t.amount for t in s.query(CashTx).filter_by(user_id=u.id)); s.close(); await q.edit_message_text(f"💰 Real Balance: ${net:.2f}", reply_markup=back_button()); return
    if d=="menu_accounts": s=Session(); u=get_user(q.from_user.id); accs=s.query(Account).filter_by(user_id=u.id).all(); msg="📊 My Accounts\n"; [msg:=msg+f"{'🟢' if a.current_balance>=a.start_balance else '🔴'} {a.name}: ${a.current_balance:.2f}\n" for a in accs]; s.close(); await q.edit_message_text(msg or "No accounts", reply_markup=back_button()); return
    if d=="menu_add": ctx.user_data['mode']='new_acc'; ctx.user_data['step']=1; await q.edit_message_text("Account name?", reply_markup=back_button()); return
    if d=="menu_profit": await q.edit_message_text("💸 Profit Tracker", reply_markup=profit_menu()); return
    await q.edit_message_text("Coming soon", reply_markup=back_button())

async def profit_cb(update, ctx):
    q=update.callback_query; await q.answer(); d=q.data; ctx.user_data.clear()
    if d=="profit_challenge": ctx.user_data['mode']='quick'; ctx.user_data['qt']='challenge'; await q.edit_message_text("Send: NAME BALANCE FEE\nExample: FTMO 100000 100", reply_markup=back_button()); return
    if d=="profit_deposit": ctx.user_data['mode']='quick'; ctx.user_data['qt']='deposit'; await q.edit_message_text("Send: NAME AMOUNT", reply_markup=back_button()); return
    if d=="profit_payout": ctx.user_data['mode']='quick'; ctx.user_data['qt']='payout'; await q.edit_message_text("Send: AMOUNT FEE%\nExample: 3000 20", reply_markup=back_button()); return
    if d=="profit_stats": s=Session(); u=get_user(q.from_user.id); net=sum(t.amount for t in s.query(CashTx).filter_by(user_id=u.id)); s.close(); await q.edit_message_text(f"📊 Stats: ${net:.2f}", reply_markup=back_button())

async def trade_start(q, ctx):
    s=Session(); u=get_user(q.from_user.id); accs=s.query(Account).filter_by(user_id=u.id).all(); s.close()
    if not accs: await q.edit_message_text("Add account first", reply_markup=back_button()); return
    ctx.user_data['mode']='trade'; ctx.user_data['trade']={'acc_ids':[]}
    kb=[[InlineKeyboardButton(a.name, callback_data=f"ta_{a.id}")] for a in accs]; kb.append([InlineKeyboardButton("Done ✅", callback_data="ta_done"), InlineKeyboardButton("⬅️ Back", callback_data="back_main")])
    await q.edit_message_text("Select accounts (tap to toggle):", reply_markup=InlineKeyboardMarkup(kb))

async def trade_acc_cb(update, ctx):
    q=update.callback_query; await q.answer(); t=ctx.user_data.get('trade',{}); 
    if q.data=="ta_done":
        s=Session(); u=get_user(q.from_user.id); pairs=s.query(Pair).filter_by(user_id=u.id).all(); s.close()
        kb=[[InlineKeyboardButton(p.symbol, callback_data=f"tp_{p.symbol}")] for p in pairs] if pairs else []
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back_main")])
        await q.edit_message_text("Select pair or type new:", reply_markup=InlineKeyboardMarkup(kb) if kb else None); t['step']='pair'; return
    aid=q.data[3:]; t['acc_ids'].remove(aid) if aid in t['acc_ids'] else t['acc_ids'].append(aid); await q.answer(f"Selected {len(t['acc_ids'])}")

async def trade_pair_cb(update, ctx):
    q=update.callback_query; await q.answer(); ctx.user_data['trade']['symbol']=q.data[3:]; ctx.user_data['trade']['step']='dir'; await q.edit_message_text("LONG or SHORT?", reply_markup=back_button())

async def close_start(q, ctx):
    s=Session(); u=get_user(q.from_user.id); trs=s.query(Trade).filter_by(user_id=u.id, closed_at=None).all(); s.close()
    if not trs: await q.edit_message_text("No open trades", reply_markup=back_button()); return
    kb=[[InlineKeyboardButton(f"{t.symbol} {t.direction}", callback_data=f"tc_{t.id}")] for t in trs]; kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back_main")])
    await q.edit_message_text("Select trade to close:", reply_markup=InlineKeyboardMarkup(kb)); ctx.user_data['mode']='close'

async def close_cb(update, ctx):
    q=update.callback_query; await q.answer(); ctx.user_data['close']={'id':q.data[3:],'step':'photo'}; await q.edit_message_text("Send AFTER photo", reply_markup=back_button())

async def text_handler(update, ctx):
    mode=ctx.user_data.get('mode'); txt=update.message.text.strip()
    if mode=='new_acc':
        step=ctx.user_data.get('step',1)
        if step==1: ctx.user_data['na_name']=txt; ctx.user_data['step']=2; return await update.message.reply_text("Type? CHALLENGE or LIVE", reply_markup=back_button())
        if step==2: ctx.user_data['na_type']=txt.upper(); ctx.user_data['step']=3; return await update.message.reply_text("Starting balance?", reply_markup=back_button())
        if step==3: ctx.user_data['na_bal']=float(txt); ctx.user_data['step']=4; return await update.message.reply_text("Fee paid?", reply_markup=back_button())
        if step==4:
            s=Session(); u=get_user(update.effective_user.id); fee=float(txt); acc=Account(user_id=u.id, name=ctx.user_data['na_name'], type=ctx.user_data['na_type'], start_balance=ctx.user_data['na_bal'], current_balance=ctx.user_data['na_bal'], fee_paid=fee); s.add(acc)
            if fee>0: s.add(CashTx(user_id=u.id, type='FEE', amount=-fee, note=f"Buy {acc.name}"))
            s.commit(); s.close(); ctx.user_data.clear(); return await update.message.reply_text(f"✅ Account '{acc.name}' created!", reply_markup=main_menu())
    if mode=='quick':
        qt=ctx.user_data['qt']; s=Session(); u=get_user(update.effective_user.id)
        if qt=='challenge': name,bal,fee=txt.split(); acc=Account(user_id=u.id, name=name, type='CHALLENGE', start_balance=float(bal), current_balance=float(bal), fee_paid=float(fee)); s.add(acc); s.add(CashTx(user_id=u.id, type='FEE', amount=-float(fee), note=f"Buy {name}")); s.commit(); await update.message.reply_text(f"✅ {name} added, -${fee}", reply_markup=main_menu())
        elif qt=='deposit': name,amt=txt.split(); acc=s.query(Account).filter_by(user_id=u.id, name=name).first(); acc.current_balance+=float(amt); s.add(CashTx(user_id=u.id, type='FEE', amount=-float(amt), note=f"Fund {name}")); s.commit(); await update.message.reply_text(f"✅ Funded", reply_markup=main_menu())
        elif qt=='payout': parts=txt.split(); gross=float(parts[0]); cut=float(parts[1]) if len(parts)>1 else 20; net=gross*(1-cut/100); s.add(CashTx(user_id=u.id, type='PAYOUT', amount=net, note=f"gross {gross}")); s.commit(); await update.message.reply_text(f"✅ Payout ${net:.2f}", reply_markup=main_menu())
        s.close(); ctx.user_data.clear(); return
    if mode=='trade':
        t=ctx.user_data['trade']; step=t.get('step')
        if step=='pair' and 'symbol' not in t: t['symbol']=txt.upper(); t['step']='dir'; return await update.message.reply_text("LONG or SHORT?", reply_markup=back_button())
        if step=='dir': t['direction']=txt.upper(); t['step']='entry'; return await update.message.reply_text("Entry price?", reply_markup=back_button())
        if step=='entry': t['entry']=float(txt); t['step']='sl'; return await update.message.reply_text("SL price?", reply_markup=back_button())
        if step=='sl': t['sl']=float(txt); t['step']='tp'; return await update.message.reply_text("TP price?", reply_markup=back_button())
        if step=='tp': t['tp']=float(txt); t['rr']=abs((t['tp']-t['entry'])/(t['entry']-t['sl'])) if t['entry']!=t['sl'] else 0; t['step']='photo'; return await update.message.reply_text(f"RR {t['rr']:.2f}. Send BEFORE photo", reply_markup=back_button())
    if mode=='close' and ctx.user_data.get('close',{}).get('step')=='pnl':
        c=ctx.user_data['close']; val=float(txt); aid,name=c['accs'][c['i']]; s=Session(); ta=s.query(TradeAccount).filter_by(trade_id=c['id'], account_id=aid).first(); ta.pnl_usd=val; ta.result='TP' if val>0 else 'SL' if val<0 else 'BE'; acc=s.query(Account).get(aid); acc.current_balance+=val; s.commit(); c['i']+=1
        if c['i']>=len(c['accs']): tr=s.query(Trade).get(c['id']); tr.closed_at=datetime.utcnow(); s.commit(); s.close(); ctx.user_data.clear(); return await update.message.reply_text("✅ Trade closed!", reply_markup=main_menu())
        else: s.close(); return await update.message.reply_text(f"PnL for {c['accs'][c['i']][1]}?")

async def photo_handler(update, ctx):
    mode=ctx.user_data.get('mode')
    if mode=='trade' and ctx.user_data['trade'].get('step')=='photo':
        t=ctx.user_data['trade']; fid=update.message.photo[-1].file_id; s=Session(); u=get_user(update.effective_user.id)
        tr=Trade(user_id=u.id, symbol=t['symbol'], direction=t['direction'], entry=t['entry'], sl=t['sl'], tp=t['tp'], rr=t['rr'], before_photo=fid); s.add(tr); s.flush()
        for aid in t['acc_ids']: s.add(TradeAccount(trade_id=tr.id, account_id=aid))
        s.commit(); s.close(); ctx.user_data.clear(); await update.message.reply_text(f"✅ Trade {tr.symbol} logged!", reply_markup=main_menu())
    if mode=='close' and ctx.user_data.get('close',{}).get('step')=='photo':
        c=ctx.user_data['close']; fid=update.message.photo[-1].file_id; s=Session(); tr=s.query(Trade).get(c['id']); tr.after_photo=fid; accs=s.query(TradeAccount).filter_by(trade_id=c['id']).all(); c['accs']=[(a.account_id, s.query(Account).get(a.account_id).name) for a in accs]; c['i']=0; c['step']='pnl'; s.commit(); s.close(); await update.message.reply_text(f"PnL for {c['accs'][0][1]}?")

def main():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^menu_"))
    app.add_handler(CallbackQueryHandler(profit_cb, pattern="^profit_"))
    app.add_handler(CallbackQueryHandler(trade_acc_cb, pattern="^ta_"))
    app.add_handler(CallbackQueryHandler(trade_pair_cb, pattern="^tp_"))
    app.add_handler(CallbackQueryHandler(close_cb, pattern="^tc_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.run_polling()

if __name__ == "__main__": main()
