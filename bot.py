import os
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from sqlalchemy import create_engine, Column, String, Float, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import uuid

Base = declarative_base()
def uid(): return str(uuid.uuid4())

class User(Base):
    __tablename__ = 'users'; id = Column(String, primary_key=True, default=uid); telegram_id = Column(String, unique=True); created_at = Column(DateTime, default=datetime.utcnow); is_admin = Column(String, default='0')
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
ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",")
engine = create_engine(DATABASE_URL, future=True); Session = sessionmaker(bind=engine); Base.metadata.create_all(engine)

def get_user(tid):
    s=Session(); u=s.query(User).filter_by(telegram_id=str(tid)).first()
    if not u:
        is_first = s.query(User).count()==0
        u=User(telegram_id=str(tid), is_admin='1' if (is_first or str(tid) in ADMIN_IDS) else '0'); s.add(u); s.commit()
    s.close(); return u

def is_admin(tid):
    s=Session(); u=s.query(User).filter_by(telegram_id=str(tid)).first(); s.close(); return u and u.is_admin=='1'

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Log Trade", callback_data="menu_log"), InlineKeyboardButton("✅ Close Trade", callback_data="menu_close")],
        [InlineKeyboardButton("💰 Balance", callback_data="menu_balance"), InlineKeyboardButton("⚙️ My Accounts", callback_data="menu_accounts")],
        [InlineKeyboardButton("📊 Analyse", callback_data="menu_analyse"), InlineKeyboardButton("📖 Journal", callback_data="menu_journal")],
        [InlineKeyboardButton("📈 My Pairs", callback_data="menu_pairs"), InlineKeyboardButton("📜 Trade History", callback_data="menu_hist")],
        [InlineKeyboardButton("➕ Add Account", callback_data="menu_add"), InlineKeyboardButton("💸 Profit Tracker", callback_data="menu_profit")],
        [InlineKeyboardButton("👑 ADMIN PANEL", callback_data="menu_admin")]
    ])

def back_button(): return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_main")]])

def profit_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Challenge Buy", callback_data="profit_challenge"), InlineKeyboardButton("💰 Live Deposit", callback_data="profit_deposit")],
        [InlineKeyboardButton("💸 Log Payout", callback_data="profit_payout"), InlineKeyboardButton("💵 Withdraw", callback_data="profit_withdraw")],
        [InlineKeyboardButton("📊 View Stats", callback_data="profit_stats"), InlineKeyboardButton("🗑️ Edit/Delete", callback_data="profit_edit")],
        [InlineKeyboardButton("🔄 Reset All", callback_data="profit_reset")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back_main")]
    ])

def admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 View Users", callback_data="admin_users"), InlineKeyboardButton("➕ Add User", callback_data="admin_add")],
        [InlineKeyboardButton("🗑️ Remove User", callback_data="admin_remove")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back_main")]
    ])

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    get_user(update.effective_user.id); ctx.user_data.clear()
    await update.message.reply_text("📊 Trading Journal", reply_markup=main_menu())

async def archive_acc(update, ctx):
    q=update.callback_query; await q.answer(); aid=q.data[5:]; s=Session(); a=s.query(Account).get(aid); a.status='ARCHIVED'; s.commit(); s.close(); await q.answer("Archived"); await q.edit_message_text("✅ Account archived", reply_markup=back_button())

async def back_main(update, ctx):
    q=update.callback_query; await q.answer(); ctx.user_data.clear()
    await q.edit_message_text("📊 Trading Journal", reply_markup=main_menu())

async def menu_cb(update, ctx):
    q=update.callback_query; await q.answer(); d=q.data; ctx.user_data.clear(); s=Session(); u=get_user(q.from_user.id)
    if d=="menu_log": s.close(); return await trade_start(q, ctx)
    if d=="menu_close": s.close(); return await close_start(q, ctx)
    if d=="menu_balance": net=sum(t.amount for t in s.query(CashTx).filter_by(user_id=u.id)); s.close(); await q.edit_message_text(f"💰 Real Balance:\n${net:.2f}", reply_markup=back_button()); return
    if d=="menu_accounts": accs=s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all(); arch=s.query(Account).filter_by(user_id=u.id, status='ARCHIVED').all(); msg="📊 Active Accounts\n\n"; [msg:=msg+f"{'🟢' if a.current_balance>=a.start_balance else '🔴'} **{a.name}** ({a.type}) - ${a.current_balance:.0f}\n" for a in accs]; msg+="\n📦 Archived:\n"; [msg:=msg+f"• {a.name}\n" for a in arch]; kb=[[InlineKeyboardButton(f"📦 Archive {a.name}",callback_data=f"arch_{a.id}")] for a in accs]; kb.append([InlineKeyboardButton("⬅️ Back",callback_data="back_main")]); s.close(); await q.edit_message_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb)); return
    if d=="menu_add": ctx.user_data['mode']='new_acc'; ctx.user_data['step']=1; s.close(); await q.edit_message_text("Account name?", reply_markup=back_button()); return
    if d=="menu_profit": s.close(); await q.edit_message_text("💸 Profit Tracker", reply_markup=profit_menu()); return
    if d=="menu_pairs": pairs=s.query(Pair).filter_by(user_id=u.id).all(); kb=[[InlineKeyboardButton(f"❌ {p.symbol}", callback_data=f"pairdel_{p.id}")] for p in pairs]; kb.append([InlineKeyboardButton("➕ Add Pair", callback_data="pair_add"), InlineKeyboardButton("⬅️ Back", callback_data="back_main")]); s.close(); await q.edit_message_text("📈 My Pairs - tap to delete:", reply_markup=InlineKeyboardMarkup(kb)); return
    if d=="menu_analyse":
        trades=s.query(Trade).filter_by(user_id=u.id).filter(Trade.closed_at!=None).all(); tas=s.query(TradeAccount).join(Trade).filter(Trade.user_id==u.id).filter(TradeAccount.pnl_usd!=None).all()
        total=len(tas); wins=len([t for t in tas if t.pnl_usd>0]); winrate=(wins/total*100) if total else 0; avg_rr=sum(t.rr for t in trades if t.rr)/len(trades) if trades else 0; total_pnl=sum(t.pnl_usd for t in tas)
        msg=f"📊 **Analyse**\n\nTrades: {total}\nWin Rate: {winrate:.1f}%\nAvg RR: {avg_rr:.2f}\nTotal PnL: ${total_pnl:.2f}"; s.close(); await q.edit_message_text(msg, parse_mode='Markdown', reply_markup=back_button()); return
    if d=="menu_journal": trades=s.query(Trade).filter_by(user_id=u.id).order_by(Trade.opened_at.desc()).limit(5).all(); msg="📖 Last Trades\n\n"; [msg:=msg+f"{t.opened_at.strftime('%d/%m')} {t.symbol} {t.direction}\n" for t in trades]; kb=[[InlineKeyboardButton(f"View {t.symbol}", callback_data=f"view_{t.id}")] for t in trades]; kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back_main")]); s.close(); await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb)); return
    if d=="menu_hist": tas=s.query(TradeAccount).join(Trade).filter(Trade.user_id==u.id).order_by(TradeAccount.closed_at.desc()).limit(15).all(); msg="📜 History\n\n"; [msg:=msg+f"{s.query(Trade).get(ta.trade_id).symbol} {ta.result} ${ta.pnl_usd:+.0f}\n" for ta in tas]; s.close(); await q.edit_message_text(msg, reply_markup=back_button()); return
    if d=="menu_admin":
        if not is_admin(q.from_user.id): s.close(); await q.answer("Not admin", show_alert=True); return
        s.close(); await q.edit_message_text("👑 ADMIN PANEL", reply_markup=admin_menu()); return
    s.close()

async def wd_select(update, ctx):
    q=update.callback_query; await q.answer(); ctx.user_data['mode']='withdraw'; ctx.user_data['wd_acc']=q.data[3:]; await q.edit_message_text("Amount to withdraw to bank?", reply_markup=back_button())

async def profit_cb(update, ctx):
    q=update.callback_query; await q.answer(); d=q.data; ctx.user_data.clear()
    if d=="profit_challenge": ctx.user_data['mode']='quick'; ctx.user_data['qt']='challenge'; await q.edit_message_text("Send: NAME BALANCE FEE", reply_markup=back_button())
    elif d=="profit_deposit": ctx.user_data['mode']='quick'; ctx.user_data['qt']='deposit'; await q.edit_message_text("Send: NAME AMOUNT", reply_markup=back_button())
    elif d=="profit_payout": ctx.user_data['mode']='quick'; ctx.user_data['qt']='payout'; await q.edit_message_text("Send: AMOUNT FEE%", reply_markup=back_button())
    elif d=="profit_withdraw": accs=s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all(); s.close(); kb=[[InlineKeyboardButton(a.name,callback_data=f"wd_{a.id}")] for a in accs]; kb.append([InlineKeyboardButton("⬅️ Back",callback_data="back_main")]); await q.edit_message_text("Select account to withdraw FROM:", reply_markup=InlineKeyboardMarkup(kb)); return
    elif d=="profit_stats": s=Session(); u=get_user(q.from_user.id); fees=s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id, type='FEE').scalar() or 0; payouts=s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id, type='PAYOUT').scalar() or 0; withdraws=s.query(func.sum(CashTx.amount)).filter_by(user_id=u.id, type='WITHDRAW').scalar() or 0; net=fees+payouts+withdraws; s.close(); await q.edit_message_text(f"📊 Stats\nFees: ${abs(fees):.2f}\nPayouts: ${payouts:.2f}\nWithdraws: ${abs(withdraws):.2f}\nNet: ${net:.2f}", reply_markup=back_button())
    elif d=="profit_edit": s=Session(); u=get_user(q.from_user.id); accs=s.query(Account).filter_by(user_id=u.id).all(); kb=[[InlineKeyboardButton(f"🗑️ {a.name}", callback_data=f"delacc_{a.id}")] for a in accs]; kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back_main")]); s.close(); await q.edit_message_text("Delete account:", reply_markup=InlineKeyboardMarkup(kb))
    elif d=="profit_reset": kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ YES DELETE ALL", callback_data="reset_yes"), InlineKeyboardButton("❌ Cancel", callback_data="back_main")]]); await q.edit_message_text("⚠️ This will DELETE all accounts, trades, pairs, and bank history. Are you sure?", reply_markup=kb)

async def reset_yes(update, ctx):
    q=update.callback_query; await q.answer(); s=Session(); u=get_user(q.from_user.id); uid=u.id
    s.query(TradeAccount).filter(TradeAccount.trade_id.in_(s.query(Trade.id).filter_by(user_id=uid))).delete(synchronize_session=False)
    s.query(Trade).filter_by(user_id=uid).delete(); s.query(Account).filter_by(user_id=uid).delete(); s.query(Pair).filter_by(user_id=uid).delete(); s.query(CashTx).filter_by(user_id=uid).delete(); s.commit(); s.close()
    await q.edit_message_text("✅ Everything reset!", reply_markup=back_button())

async def admin_cb(update, ctx):
    q=update.callback_query; await q.answer(); d=q.data; s=Session()
    if d=="admin_users": users=s.query(User).all(); msg="👥 Users:\n"; [msg:=msg+f"{u.telegram_id} {'(admin)' if u.is_admin=='1' else ''}\n" for u in users]; await q.edit_message_text(msg, reply_markup=admin_menu())
    elif d=="admin_add": ctx.user_data['mode']='admin_add'; await q.edit_message_text("Send Telegram ID to add:", reply_markup=back_button())
    elif d=="admin_remove": users=s.query(User).all(); kb=[[InlineKeyboardButton(f"🗑️ {u.telegram_id}", callback_data=f"admindel_{u.id}")] for u in users]; kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back_main")]); await q.edit_message_text("Remove user:", reply_markup=InlineKeyboardMarkup(kb))
    s.close()

async def admindel(update, ctx):
    q=update.callback_query; await q.answer(); uid=q.data[9:]; s=Session(); u=s.query(User).get(uid); tid=u.telegram_id; s.query(Trade).filter_by(user_id=uid).delete(); s.query(Account).filter_by(user_id=uid).delete(); s.delete(u); s.commit(); s.close(); await q.edit_message_text(f"✅ Removed {tid}", reply_markup=admin_menu())

# pairs
async def pair_add(update, ctx):
    q=update.callback_query; await q.answer(); ctx.user_data['mode']='pair_add'; await q.edit_message_text("Send pair symbol (e.g. EURUSD):", reply_markup=back_button())

async def pair_del(update, ctx):
    q=update.callback_query; await q.answer(); pid=q.data[8:]; s=Session(); s.query(Pair).filter_by(id=pid).delete(); s.commit(); s.close(); await q.answer("Deleted"); await menu_cb(update, ctx)

# trade flows (simplified from before)
async def trade_start(q, ctx):
    s=Session(); u=get_user(q.from_user.id); accs=s.query(Account).filter_by(user_id=u.id, status='ACTIVE').all(); s.close()
    ctx.user_data['mode']='trade'; ctx.user_data['trade']={'acc_ids':[]}
    kb=[[InlineKeyboardButton(a.name, callback_data=f"ta_{a.id}")] for a in accs]; kb.append([InlineKeyboardButton("Done", callback_data="ta_done"), InlineKeyboardButton("⬅️ Back", callback_data="back_main")])
    await q.edit_message_text("Select accounts:", reply_markup=InlineKeyboardMarkup(kb))

async def trade_acc_cb(update, ctx): q=update.callback_query; await q.answer(); t=ctx.user_data['trade']; 
    if q.data=="ta_done": s=Session(); u=get_user(q.from_user.id); pairs=s.query(Pair).filter_by(user_id=u.id).all(); s.close(); kb=[[InlineKeyboardButton(p.symbol, callback_data=f"tp_{p.symbol}")] for p in pairs]; kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back_main")]); await q.edit_message_text("Select pair:", reply_markup=InlineKeyboardMarkup(kb)); t['step']='pair'; return
    aid=q.data[3:]; t['acc_ids'].append(aid) if aid not in t['acc_ids'] else t['acc_ids'].remove(aid)

async def trade_pair_cb(update, ctx): q=update.callback_query; await q.answer(); ctx.user_data['trade']['symbol']=q.data[3:]; ctx.user_data['trade']['step']='dir'; await q.edit_message_text("LONG or SHORT?", reply_markup=back_button())

async def close_start(q, ctx): s=Session(); u=get_user(q.from_user.id); trs=s.query(Trade).filter_by(user_id=u.id, closed_at=None).all(); s.close(); kb=[[InlineKeyboardButton(f"{t.symbol}", callback_data=f"tc_{t.id}")] for t in trs]; kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back_main")]); await q.edit_message_text("Select trade:", reply_markup=InlineKeyboardMarkup(kb)); ctx.user_data['mode']='close'
async def close_cb(update, ctx): q=update.callback_query; await q.answer(); ctx.user_data['close']={'id':q.data[3:],'step':'photo'}; await q.edit_message_text("Send AFTER photo", reply_markup=back_button())

async def text_handler(update, ctx):
    mode=ctx.user_data.get('mode'); txt=update.message.text.strip()
    s=Session(); u=get_user(update.effective_user.id)
    if mode=='new_acc':
        step=ctx.user_data.get('step',1)
        if step==1: ctx.user_data['na_name']=txt; ctx.user_data['step']=2; await update.message.reply_text("Type?"); return
        if step==2: ctx.user_data['na_type']=txt.upper(); ctx.user_data['step']=3; await update.message.reply_text("Balance?"); return
        if step==3: ctx.user_data['na_bal']=float(txt); ctx.user_data['step']=4; await update.message.reply_text("Fee?"); return
        if step==4: acc=Account(user_id=u.id, name=ctx.user_data['na_name'], type=ctx.user_data['na_type'], start_balance=ctx.user_data['na_bal'], current_balance=ctx.user_data['na_bal'], fee_paid=float(txt)); s.add(acc); 
        if float(txt)>0: s.add(CashTx(user_id=u.id, type='FEE', amount=-float(txt), note=f"Buy {acc.name}")); s.commit(); ctx.user_data.clear(); await update.message.reply_text("✅ Created", reply_markup=main_menu())
    elif mode=='withdraw':
        amt=float(txt); acc=s.query(Account).get(ctx.user_data['wd_acc']); acc.current_balance-=amt; s.add(CashTx(user_id=u.id, type='WITHDRAW', amount=amt, note=f"From {acc.name}")); s.commit(); ctx.user_data.clear(); await update.message.reply_text(f"✅ Withdrew ${amt} from {acc.name} to bank", reply_markup=main_menu()); s.close(); return
    elif mode=='quick':
        qt=ctx.user_data['qt']
        if qt=='challenge': n,b,f=txt.split(); acc=Account(user_id=u.id, name=n, type='CHALLENGE', start_balance=float(b), current_balance=float(b), fee_paid=float(f)); s.add(acc); s.add(CashTx(user_id=u.id, type='FEE', amount=-float(f), note=f"Buy {n}")); s.commit(); await update.message.reply_text("✅ Added", reply_markup=main_menu())
        elif qt=='deposit': n,a=txt.split(); acc=s.query(Account).filter_by(user_id=u.id, name=n).first(); acc.current_balance+=float(a); s.add(CashTx(user_id=u.id, type='FEE', amount=-float(a), note=f"Fund {n}")); s.commit(); await update.message.reply_text("✅ Funded", reply_markup=main_menu())
        elif qt=='payout': p=txt.split(); g=float(p[0]); c=float(p[1]) if len(p)>1 else 20; net=g*(1-c/100); s.add(CashTx(user_id=u.id, type='PAYOUT', amount=net, note=f"gross {g}")); s.commit(); await update.message.reply_text(f"✅ ${net:.2f}", reply_markup=main_menu())
        elif qt=='withdraw': amt=float(txt); s.add(CashTx(user_id=u.id, type='WITHDRAW', amount=-amt, note="Withdraw")); s.commit(); await update.message.reply_text(f"✅ Withdrawn ${amt}", reply_markup=main_menu())
        ctx.user_data.clear()
    elif mode=='pair_add': s.merge(Pair(user_id=u.id, symbol=txt.upper())); s.commit(); ctx.user_data.clear(); await update.message.reply_text(f"✅ Pair {txt.upper()} added", reply_markup=main_menu())
    elif mode=='admin_add': new=User(telegram_id=txt, is_admin='0'); s.add(new); s.commit(); ctx.user_data.clear(); await update.message.reply_text(f"✅ User {txt} added", reply_markup=admin_menu())
    elif mode=='trade':
        t=ctx.user_data['trade']; step=t.get('step')
        if step=='dir': t['direction']=txt.upper(); t['step']='entry'; await update.message.reply_text("Entry?")
        elif step=='entry': t['entry']=float(txt); t['step']='sl'; await update.message.reply_text("SL?")
        elif step=='sl': t['sl']=float(txt); t['step']='tp'; await update.message.reply_text("TP?")
        elif step=='tp': t['tp']=float(txt); t['rr']=abs((t['tp']-t['entry'])/(t['entry']-t['sl'])) if t['entry']!=t['sl'] else 0; t['step']='photo'; await update.message.reply_text(f"RR {t['rr']:.2f} send photo")
    elif mode=='close' and ctx.user_data.get('close',{}).get('step')=='pnl':
        c=ctx.user_data['close']; val=float(txt); aid,name=c['accs'][c['i']]; ta=s.query(TradeAccount).filter_by(trade_id=c['id'], account_id=aid).first(); ta.pnl_usd=val; acc=s.query(Account).get(aid); acc.current_balance+=val; s.commit(); c['i']+=1
        if c['i']>=len(c['accs']): tr=s.query(Trade).get(c['id']); tr.closed_at=datetime.utcnow(); s.commit(); ctx.user_data.clear(); await update.message.reply_text("✅ Closed", reply_markup=main_menu())
        else: await update.message.reply_text(f"PnL for {c['accs'][c['i']][1]}?")
    s.close()

async def photo_handler(update, ctx):
    mode=ctx.user_data.get('mode')
    s=Session(); u=get_user(update.effective_user.id)
    if mode=='trade': t=ctx.user_data['trade']; tr=Trade(user_id=u.id, symbol=t['symbol'], direction=t['direction'], entry=t['entry'], sl=t['sl'], tp=t['tp'], rr=t['rr'], before_photo=update.message.photo[-1].file_id); s.add(tr); s.flush(); [s.add(TradeAccount(trade_id=tr.id, account_id=aid)) for aid in t['acc_ids']]; s.commit(); ctx.user_data.clear(); await update.message.reply_text("✅ Logged", reply_markup=main_menu())
    if mode=='close': c=ctx.user_data['close']; tr=s.query(Trade).get(c['id']); tr.after_photo=update.message.photo[-1].file_id; accs=s.query(TradeAccount).filter_by(trade_id=c['id']).all(); c['accs']=[(a.account_id, s.query(Account).get(a.account_id).name) for a in accs]; c['i']=0; c['step']='pnl'; s.commit(); await update.message.reply_text(f"PnL for {c['accs'][0][1]}?")
    s.close()

def main():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(archive_acc, pattern="^arch_"))
    app.add_handler(CallbackQueryHandler(wd_select, pattern="^wd_"))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^menu_"))
    app.add_handler(CallbackQueryHandler(profit_cb, pattern="^profit_"))
    app.add_handler(CallbackQueryHandler(reset_yes, pattern="^reset_yes$"))
    app.add_handler(CallbackQueryHandler(admin_cb, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(admindel, pattern="^admindel_"))
    app.add_handler(CallbackQueryHandler(pair_add, pattern="^pair_add$"))
    app.add_handler(CallbackQueryHandler(pair_del, pattern="^pairdel_"))
    app.add_handler(CallbackQueryHandler(trade_acc_cb, pattern="^ta_"))
    app.add_handler(CallbackQueryHandler(trade_pair_cb, pattern="^tp_"))
    app.add_handler(CallbackQueryHandler(close_cb, pattern="^tc_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.run_polling()

if __name__ == "__main__": main()
