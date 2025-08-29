import os
import logging
import sqlite3
import asyncio
import time
import random
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot Configuration
BOT_TOKEN = "8231456687:AAHuLM9GJckxIKcpQ8aEhjQDTN14e96_7-I"
ADMIN_IDS = [7972815378, 8002906283]

# UPI IDs List
UPI_IDS = [
    "rossx1@kiwi",
    "rossx2@kiwi", 
    "rossx3@kiwi",
    "rossx4@kiwi",
    "rossx5@kiwi"
]

DATABASE_FILE = "rossxi.db"
BOT_USERNAME = "your_bot_username"

# User States
USER_STATES = {}

class States:
    NONE = "none"
    AWAITING_DEPOSIT_DETAILS = "awaiting_deposit_details"
    AWAITING_SCREENSHOT = "awaiting_screenshot"
    AWAITING_INVESTMENT_AMOUNT = "awaiting_investment_amount"
    AWAITING_CUSTOM_AMOUNT = "awaiting_custom_amount"

# Investment Plans
PLANS = {
    '45_days': {
        'name': '45 Days Big Opportunity', 
        'rate': 0.50,
        'duration': 45, 
        'min': 199,
        'max': 5000,
        'emoji': '🔥'
    },
    '90_days': {
        'name': '90 Days Big Opportunity', 
        'rate': 1.00,
        'duration': 90, 
        'min': 299,
        'max': 10000,
        'emoji': '💎'
    }
}

# ================== UTILITY FUNCTIONS ==================

def get_random_upi():
    return random.choice(UPI_IDS)

def set_user_state(user_id, state, data=None):
    USER_STATES[user_id] = {'state': state, 'data': data or {}}

def get_user_state(user_id):
    return USER_STATES.get(user_id, {'state': States.NONE, 'data': {}})

def clear_user_state(user_id):
    if user_id in USER_STATES:
        del USER_STATES[user_id]

# ================== DATABASE FUNCTIONS ==================

def init_database():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            phone TEXT,
            name TEXT,
            wallet_balance REAL DEFAULT 0,
            referral_code TEXT UNIQUE,
            referred_by INTEGER,
            total_referrals INTEGER DEFAULT 0,
            available_withdrawals INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            has_invested BOOLEAN DEFAULT FALSE,
            investment_amount REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS investments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan_id TEXT,
            amount REAL,
            expected_returns REAL,
            start_date DATE,
            maturity_date DATE,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            utr_number TEXT,
            user_upi_id TEXT,
            admin_upi_id TEXT,
            screenshot_path TEXT,
            status TEXT DEFAULT 'pending',
            admin_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_at TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

def generate_referral_code(user_id):
    return f"RX{str(user_id)[-6:]}{random.randint(10,99)}"

def get_user_data(user_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            'telegram_id': result[0],
            'username': result[1],
            'phone': result[2],
            'name': result[3],
            'wallet_balance': result[4],
            'referral_code': result[5],
            'referred_by': result[6],
            'total_referrals': result[7],
            'available_withdrawals': result[8],
            'is_active': result[9],
            'created_at': result[10]
        }
    return None

def create_user(user_id, username, name=None, phone=None, referred_by=None):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    referral_code = generate_referral_code(user_id)
    
    cursor.execute('''
        INSERT OR IGNORE INTO users (telegram_id, username, name, phone, referral_code, referred_by)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, username, name, phone, referral_code, referred_by))
    
    if referred_by:
        cursor.execute('''
            INSERT INTO referrals (referrer_id, referred_id)
            VALUES (?, ?)
        ''', (referred_by, user_id))
        
        cursor.execute('''
            UPDATE users SET total_referrals = total_referrals + 1
            WHERE telegram_id = ?
        ''', (referred_by,))
    
    conn.commit()
    conn.close()

def update_wallet_balance(user_id, amount, operation='add'):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    if operation == 'add':
        cursor.execute('UPDATE users SET wallet_balance = wallet_balance + ? WHERE telegram_id = ?', (amount, user_id))
    else:
        cursor.execute('UPDATE users SET wallet_balance = wallet_balance - ? WHERE telegram_id = ?', (amount, user_id))
    
    conn.commit()
    conn.close()

def save_deposit_request(data):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO deposits (user_id, amount, utr_number, user_upi_id, admin_upi_id, screenshot_path)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (data['user_id'], data['amount'], data['utr'], data['user_upi'], data['admin_upi'], data.get('screenshot_path', '')))
    
    deposit_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return deposit_id

def create_investment(user_id, plan_id, amount):
    plan = PLANS[plan_id]
    expected_returns = amount * plan['rate']
    start_date = datetime.now().date()
    maturity_date = start_date + timedelta(days=plan['duration'])
    
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO investments (user_id, plan_id, amount, expected_returns, start_date, maturity_date)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, plan_id, amount, expected_returns, start_date, maturity_date))
    
    investment_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return investment_id

def get_user_investments(user_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, plan_id, amount, expected_returns, start_date, maturity_date, status
        FROM investments WHERE user_id = ? ORDER BY created_at DESC
    ''', (user_id,))
    
    investments = []
    for row in cursor.fetchall():
        investments.append({
            'id': row[0],
            'plan_id': row[1],
            'plan_name': PLANS[row[1]]['name'],
            'amount': row[2],
            'expected_returns': row[3],
            'start_date': datetime.strptime(row[4], '%Y-%m-%d').date(),
            'maturity_date': datetime.strptime(row[5], '%Y-%m-%d').date(),
            'status': row[6],
            'maturity_amount': row[2] + row[3]
        })
    
    conn.close()
    return investments

def get_pending_deposits():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT d.id, d.user_id, u.name, u.username, d.amount, d.utr_number, 
               d.user_upi_id, d.admin_upi_id, d.created_at, d.screenshot_path
        FROM deposits d
        JOIN users u ON d.user_id = u.telegram_id
        WHERE d.status = 'pending'
        ORDER BY d.created_at DESC
    ''')
    
    deposits = []
    for row in cursor.fetchall():
        deposits.append({
            'id': row[0],
            'user_id': row[1],
            'name': row[2],
            'username': row[3],
            'amount': row[4],
            'utr': row[5],
            'user_upi': row[6],
            'admin_upi': row[7],
            'created_at': row[8],
            'screenshot': row[9]
        })
    
    conn.close()
    return deposits

def approve_deposit(deposit_id, admin_notes=''):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT user_id, amount FROM deposits WHERE id = ?', (deposit_id,))
    result = cursor.fetchone()
    
    if result:
        user_id, amount = result
        
        cursor.execute('''
            UPDATE deposits SET status = 'approved', admin_notes = ?, approved_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (admin_notes, deposit_id))
        
        cursor.execute('UPDATE users SET wallet_balance = wallet_balance + ? WHERE telegram_id = ?', (amount, user_id))
        
        conn.commit()
        conn.close()
        return user_id, amount
    
    conn.close()
    return None, None

def can_user_withdraw(user_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT available_withdrawals FROM users WHERE telegram_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] > 0 if result else False

def get_referral_stats(user_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT COUNT(*) as total,
               COUNT(CASE WHEN has_invested = TRUE THEN 1 END) as invested
        FROM referrals WHERE referrer_id = ?
    ''', (user_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    return {
        'total_referrals': result[0] if result else 0,
        'investing_referrals': result[1] if result else 0
    }

# ================== ANIMATION FUNCTIONS ==================

async def send_animated_message(chat_id, context, frames, final_text, final_keyboard=None):
    message = await context.bot.send_message(chat_id, frames[0])
    
    for frame in frames[1:]:
        await asyncio.sleep(0.5)
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message.message_id,
                text=frame
            )
        except:
            pass
    
    await asyncio.sleep(0.5)
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message.message_id,
        text=final_text,
        parse_mode='Markdown',
        reply_markup=final_keyboard
    )

def create_progress_bar(percentage, length=10):
    filled = int(percentage / 100 * length)
    bar = "🟢" * filled + "⚪" * (length - filled)
    return f"{bar} {percentage:.1f}%"

# ================== BOT HANDLERS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Check for referral
    referred_by = None
    if context.args:
        try:
            referral_code = context.args[0]
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            cursor.execute('SELECT telegram_id FROM users WHERE referral_code = ?', (referral_code,))
            result = cursor.fetchone()
            if result:
                referred_by = result[0]
            conn.close()
        except:
            pass
    
    user_data = get_user_data(user.id)
    
    if not user_data:
        create_user(user.id, user.username, user.first_name, referred_by=referred_by)
        user_data = get_user_data(user.id)
        
        if referred_by:
            try:
                await context.bot.send_message(
                    chat_id=referred_by,
                    text=f"🎉 *New Referral!*\n\n"
                         f"👤 {user.first_name} joined using your link!\n"
                         f"🎯 Get them to invest for withdrawal benefits!",
                    parse_mode='Markdown'
                )
            except:
                pass
    
    welcome_frames = [
        "🌟",
        "🌟✨",
        "🌟✨💫",
        "🚀 Welcome to Ross X! 🚀",
        "💰 BIGGEST OPPORTUNITY EVER! 💰"
    ]
    
    keyboard = [
        [InlineKeyboardButton("🔥 START EARNING NOW! 🔥", callback_data='dashboard')],
        [
            InlineKeyboardButton("📈 Big Opportunities", callback_data='plans'),
            InlineKeyboardButton("👥 Refer & Earn", callback_data='referral')
        ],
        [
            InlineKeyboardButton("💰 Wallet", callback_data='wallet'),
            InlineKeyboardButton("🎯 How it Works?", callback_data='how_it_works')
        ]
    ]
    
    final_text = f"""
🎊 *WELCOME TO ROSS X* 🎊
_{user.first_name}, Your Journey to Wealth Starts HERE!_

🔥 *MASSIVE RETURNS GUARANTEED!*
• 45 Days Plan: *50% PROFIT* 🚀 (₹199)
• 90 Days Plan: *100% PROFIT* 💎 (₹299)

💸 *SPECIAL LAUNCH OFFERS:*
⚡ Minimum Investment: Just ₹199
⚡ Maximum Returns: Up to 100%
⚡ Instant Withdrawals Available*

👥 *REFERRAL BONUS SYSTEM:*
🎯 Refer 3 friends who invest
🔓 Unlock withdrawal permissions
💰 Unlimited earning potential

🏆 *YOUR REFERRAL CODE:*
`{user_data['referral_code']}`

⚠️ *Limited Time Offer - JOIN NOW!*
"""
    
    await send_animated_message(
        update.effective_chat.id,
        context,
        welcome_frames,
        final_text,
        InlineKeyboardMarkup(keyboard)
    )

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    if not user_data:
        await update.callback_query.answer("Please start the bot first with /start")
        return
    
    investments = get_user_investments(user_id)
    active_investments = [inv for inv in investments if inv['status'] == 'active']
    total_invested = sum([inv['amount'] for inv in active_investments])
    total_returns = sum([inv['expected_returns'] for inv in active_investments])
    
    referral_stats = get_referral_stats(user_id)
    
    loading_frames = [
        "⏳ Loading your dashboard...",
        "⌛ Calculating profits...",
        "💰 Preparing your wealth summary...",
        "✨ Almost ready..."
    ]
    
    text = f"""
🏆 *ROSS X DASHBOARD* 🏆
_{user_data['name'] or 'Wealth Builder'}_

💰 *WALLET BALANCE:* ₹{user_data['wallet_balance']:,.2f}
📈 *TOTAL INVESTED:* ₹{total_invested:,.2f}
💎 *EXPECTED RETURNS:* ₹{total_returns:,.2f}
📊 *ACTIVE PLANS:* {len(active_investments)}

👥 *REFERRAL POWER:*
🎯 Total Referrals: {referral_stats['total_referrals']}
💰 Investing Referrals: {referral_stats['investing_referrals']}/3
🔓 Withdrawal Status: {"✅ Available" if can_user_withdraw(user_id) else "❌ Need 3 investing referrals"}

🚀 *ACTIVE INVESTMENTS:*
"""
    
    if active_investments:
        for inv in active_investments[:3]:
            days_passed = (datetime.now().date() - inv['start_date']).days
            total_days = (inv['maturity_date'] - inv['start_date']).days
            progress = min((days_passed / total_days) * 100, 100)
            progress_bar = create_progress_bar(progress)
            
            plan_emoji = PLANS[inv['plan_id']]['emoji']
            
            text += f"""
{plan_emoji} *{inv['plan_name']}*
💰 Investment: ₹{inv['amount']:,}
🎯 Returns: +₹{inv['expected_returns']:,}
📅 Maturity: {inv['maturity_date'].strftime('%d %b')}
{progress_bar}

"""
    else:
        text += "\n🎯 No investments yet - Start earning NOW!\n"
    
    keyboard = [
        [
            InlineKeyboardButton("🔥 INVEST NOW 🔥", callback_data='plans'),
            InlineKeyboardButton("💰 ADD MONEY", callback_data='add_money')
        ],
        [
            InlineKeyboardButton("👥 INVITE FRIENDS", callback_data='referral'),
            InlineKeyboardButton("💸 WITHDRAW", callback_data='withdraw_menu')
        ],
        [
            InlineKeyboardButton("📋 All Investments", callback_data='all_investments'),
            InlineKeyboardButton("🔄 Refresh", callback_data='dashboard')
        ]
    ]
    
    await send_animated_message(
        update.callback_query.message.chat.id,
        context,
        loading_frames,
        text,
        InlineKeyboardMarkup(keyboard)
    )

async def investment_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    frames = [
        "🔥 Loading BIG opportunities...",
        "💎 Preparing MASSIVE returns...",
        "🚀 Ready to make you RICH!"
    ]
    
    text = """
🔥 *BIGGEST OPPORTUNITIES EVER!* 🔥

╔════════════════════════════╗
║ 🚀 *45 DAYS BIG OPPORTUNITY* ║
║ ┌────────────────────────┐ ║
║ │  *50% GUARANTEED*      │ ║
║ │  *RETURNS!*            │ ║
║ └────────────────────────┘ ║
║                            ║
║ 🔥 FAST MONEY MAKER        ║
║ Amount: ₹199 ONLY!         ║
║ 💰 *₹199 → ₹298.50* ✨     ║
╚════════════════════════════╝

╔════════════════════════════╗
║ 💎 *90 DAYS BIG OPPORTUNITY* ║
║ ┌────────────────────────┐ ║
║ │  *100% GUARANTEED*     │ ║
║ │  *DOUBLE MONEY!*       │ ║
║ └────────────────────────┘ ║
║                            ║
║ 💎 WEALTH MULTIPLIER       ║
║ Amount: ₹299 ONLY!         ║
║ 🎯 *₹299 → ₹598* 🚀        ║
╚════════════════════════════╝

⚠️ *LIMITED TIME OFFERS!*
"""
    
    keyboard = [
        [
            InlineKeyboardButton("🔥 45 Days (₹199 → ₹298)", callback_data='invest_45_days'),
            InlineKeyboardButton("💎 90 Days (₹299 → ₹598)", callback_data='invest_90_days')
        ],
        [InlineKeyboardButton("🧮 PROFIT CALCULATOR", callback_data='calculator')],
        [InlineKeyboardButton("← Back to Dashboard", callback_data='dashboard')]
    ]
    
    await send_animated_message(
        update.callback_query.message.chat.id,
        context,
        frames,
        text,
        InlineKeyboardMarkup(keyboard)
    )

async def add_money_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    frames = [
        "💰 Preparing payment gateway...",
        "🏦 Connecting to secure servers...",
        "✅ Ready for deposit!"
    ]
    
    selected_upi = get_random_upi()
    
    text = f"""
💰 *ADD MONEY TO WALLET* 💰

🔥 *STEP 1:* Pay to UPI ID
`{selected_upi}`

🔥 *STEP 2:* Submit payment proof

⚡ *QUICK AMOUNTS:*
💸 Start your wealth journey now!
"""
    
    keyboard = [
        [
            InlineKeyboardButton("₹199 🔥", callback_data=f'deposit_199_{selected_upi}'),
            InlineKeyboardButton("₹299 💰", callback_data=f'deposit_299_{selected_upi}'),
            InlineKeyboardButton("₹500 💎", callback_data=f'deposit_500_{selected_upi}')
        ],
        [
            InlineKeyboardButton("₹1000 🚀", callback_data=f'deposit_1000_{selected_upi}'),
            InlineKeyboardButton("₹2000 👑", callback_data=f'deposit_2000_{selected_upi}')
        ],
        [InlineKeyboardButton("💬 Custom Amount", callback_data=f'deposit_custom_{selected_upi}')],
        [InlineKeyboardButton("📋 Copy UPI ID", callback_data=f'copy_upi_{selected_upi}')],
        [InlineKeyboardButton("← Back to Wallet", callback_data='wallet')]
    ]
    
    await send_animated_message(
        update.callback_query.message.chat.id,
        context,
        frames,
        text,
        InlineKeyboardMarkup(keyboard)
    )

async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    frames = [
        "💰 Opening your wallet...",
        "💸 Counting your money...",
        "✨ Wallet ready!"
    ]
    
    text = f"""
💰 *YOUR WEALTH CENTER* 💰

💎 *CURRENT BALANCE:*
₹{user_data['wallet_balance']:,.2f}

🚀 *WHAT YOU CAN DO:*
• Add money instantly
• View transaction history  
• Invest in big opportunities
• Track your wealth growth

💡 *WEALTH TIPS:*
Start with ₹199 or ₹299 and watch it grow!
"""
    
    keyboard = [
        [InlineKeyboardButton("💰 ADD MONEY NOW!", callback_data='add_money')],
        [InlineKeyboardButton("📊 Transaction History", callback_data='transactions')],
        [InlineKeyboardButton("🔥 INVEST NOW", callback_data='plans')],
        [InlineKeyboardButton("← Back to Dashboard", callback_data='dashboard')]
    ]
    
    await send_animated_message(
        update.callback_query.message.chat.id,
        context,
        frames,
        text,
        InlineKeyboardMarkup(keyboard)
    )

async def how_it_works(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
🎯 *HOW ROSS X WORKS* 🎯

🔥 *STEP 1: JOIN & INVEST*
• Register with Ross X
• Add money to wallet
• Choose investment plan
• Earn guaranteed returns!

💎 *STEP 2: REFER & UNLOCK*
• Share your referral link
• Get 3 friends to invest
• Unlock withdrawal permissions
• Access unlimited withdrawals!

🚀 *STEP 3: WITHDRAW & REPEAT*
• Withdraw your profits
• Cycle resets after withdrawal
• Refer 3 more for next withdrawal
• Build unlimited wealth!

⚡ *RETURNS:*
• 45 Days: 50% profit (₹199 → ₹298)
• 90 Days: 100% profit (₹299 → ₹598)

🎊 *SPECIAL FEATURES:*
• Instant deposits
• Secure investments
• Referral bonuses
• 24/7 support

*START YOUR WEALTH JOURNEY NOW!*
"""
    
    keyboard = [
        [InlineKeyboardButton("🔥 START INVESTING", callback_data='plans')],
        [InlineKeyboardButton("👥 REFER FRIENDS", callback_data='referral')],
        [InlineKeyboardButton("← Back to Menu", callback_data='dashboard')]
    ]
    
    await update.callback_query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def referral_system(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    referral_stats = get_referral_stats(user_id)
    
    referral_link = f"https://t.me/{BOT_USERNAME}?start={user_data['referral_code']}"
    
    frames = [
        "👥 Loading your referral power...",
        "💰 Calculating earning potential...",
        "🚀 Your empire awaits!"
    ]
    
    text = f"""
👥 *REFERRAL EMPIRE BUILDER* 👥

🎯 *YOUR REFERRAL CODE:*
`{user_data['referral_code']}`

🔗 *YOUR REFERRAL LINK:*
`{referral_link}`

📊 *CURRENT STATUS:*
• Total Referrals: {referral_stats['total_referrals']}
• Investing Referrals: {referral_stats['investing_referrals']}/3
• Withdrawal Permissions: {user_data['available_withdrawals']}

🎯 *HOW IT WORKS:*
1️⃣ Share your referral link
2️⃣ Friends join using your link  
3️⃣ When 3 friends invest, you get withdrawal permission
4️⃣ After each withdrawal, cycle resets

💰 *BENEFITS:*
🔓 Unlock withdrawal permissions
🎊 Build passive income stream
👑 Become a Ross X Leader

🚀 *SHARE NOW & GET RICH!*
"""
    
    keyboard = [
        [InlineKeyboardButton("📤 SHARE REFERRAL LINK", switch_inline_query=f"🔥 Join Ross X and earn 50-100% returns! 💰 Use my referral link: {referral_link}")],
        [InlineKeyboardButton("📋 Copy Referral Code", callback_data='copy_referral')],
        [InlineKeyboardButton("👥 My Referrals", callback_data='my_referrals')],
        [InlineKeyboardButton("← Back to Dashboard", callback_data='dashboard')]
    ]
    
    await send_animated_message(
        update.callback_query.message.chat.id,
        context,
        frames,
        text,
        InlineKeyboardMarkup(keyboard)
    )

async def withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    referral_stats = get_referral_stats(user_id)
    
    if not can_user_withdraw(user_id):
        text = f"""
⚠️ *WITHDRAWAL LOCKED* ⚠️

🔒 You need 3 investing referrals to unlock withdrawals!

📊 *CURRENT STATUS:*
• Investing Referrals: {referral_stats['investing_referrals']}/3
• Remaining: {3 - referral_stats['investing_referrals']}

🎯 *TO UNLOCK WITHDRAWALS:*
1️⃣ Share your referral link
2️⃣ Get friends to join
3️⃣ Ensure they make investments
4️⃣ Once 3 friends invest, withdrawals unlock!

💡 *REFERRAL BENEFITS:*
• Unlimited withdrawal access
• Passive income potential
• VIP status in Ross X
"""
        
        keyboard = [
            [InlineKeyboardButton("👥 START REFERRING NOW!", callback_data='referral')],
            [InlineKeyboardButton("← Back to Dashboard", callback_data='dashboard')]
        ]
    else:
        investments = get_user_investments(user_id)
        matured_investments = [inv for inv in investments if inv['status'] == 'active' and inv['maturity_date'] <= datetime.now().date()]
        
        text = f"""
💸 *WITHDRAWAL CENTER* 💸

✅ Withdrawal Permission: *GRANTED*
🎯 Available Withdrawals: {user_data['available_withdrawals']}

💰 *MATURED INVESTMENTS:*
"""
        
        if matured_investments:
            for inv in matured_investments:
                text += f"""
💎 {inv['plan_name']}
Amount: ₹{inv['maturity_amount']:,.2f}
[Withdraw Available]

"""
        else:
            text += "No matured investments yet.\n"
        
        keyboard = [
            [InlineKeyboardButton("💸 Withdraw Matured", callback_data='withdraw_matured')],
            [InlineKeyboardButton("⚠️ Early Withdrawal (50%)", callback_data='withdraw_early')],
            [InlineKeyboardButton("← Back to Dashboard", callback_data='dashboard')]
        ]
    
    await update.callback_query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================== TEXT MESSAGE HANDLERS ==================

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all text messages based on user state"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    user_state_data = get_user_state(user_id)
    current_state = user_state_data['state']
    
    if current_state == States.AWAITING_DEPOSIT_DETAILS:
        await handle_deposit_details_input(update, context, text)
    elif current_state == States.AWAITING_CUSTOM_AMOUNT:
        await handle_custom_amount_input(update, context, text)
    elif current_state == States.AWAITING_INVESTMENT_AMOUNT:
        await handle_investment_amount_input(update, context, text)
    else:
        await handle_unknown_message(update, context)

async def handle_deposit_details_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    user_id = update.effective_user.id
    state_data = get_user_state(user_id)['data']
    
    try:
        lines = text.strip().split('\n')
        upi_line = ""
        utr_line = ""
        
        for line in lines:
            line = line.strip()
            if line.lower().startswith('upi:'):
                upi_line = line.split(':', 1)[1].strip()
            elif line.lower().startswith('utr:'):
                utr_line = line.split(':', 1)[1].strip()
        
        if not upi_line or not utr_line:
            await update.message.reply_text(
                "❌ *Invalid format!*\n\n"
                "Please send in this exact format:\n\n"
                "```\n"
                "UPI: yourname@paytm\n"
                "UTR: 123456789012\n"
                "```",
                parse_mode='Markdown'
            )
            return
        
        if len(utr_line) < 8:
            await update.message.reply_text("❌ UTR should be at least 8 characters long.")
            return
        
        deposit_data = {
            'amount': state_data['amount'],
            'user_upi': upi_line,
            'utr': utr_line,
            'user_id': user_id,
            'admin_upi': state_data['admin_upi']
        }
        
        set_user_state(user_id, States.AWAITING_SCREENSHOT, deposit_data)
        
        frames = [
            "✅ Details received!",
            "🔍 Validating information...",
            "📸 Ready for screenshot!"
        ]
        
        final_text = f"""
✅ *PAYMENT DETAILS RECEIVED!*

💰 Amount: ₹{deposit_data['amount']:,}
🎯 Your UPI: {upi_line}
🔢 UTR: {utr_line}
🏦 Paid to: {deposit_data['admin_upi']}

📸 *NOW SEND PAYMENT SCREENSHOT*
⚡ Final step to complete deposit!
"""
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data='wallet')]
        ])
        
        await send_animated_message(
            update.message.chat.id,
            context,
            frames,
            final_text,
            keyboard
        )
        
    except Exception as e:
        await update.message.reply_text("❌ Error processing details. Please try again!")

async def handle_custom_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    user_id = update.effective_user.id
    state_data = get_user_state(user_id)['data']
    
    try:
        amount = float(text.replace('₹', '').replace(',', '').strip())
        
        if amount < 50 or amount > 50000:
            await update.message.reply_text("❌ Amount should be between ₹50 - ₹50,000")
            return
            
        await handle_deposit_amount_direct(update, context, amount, state_data['admin_upi'])
        
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid amount.\nExample: 1500")

async def handle_deposit_amount_direct(update: Update, context: ContextTypes.DEFAULT_TYPE, amount, upi_id):
    user_id = update.effective_user.id
    set_user_state(user_id, States.AWAITING_DEPOSIT_DETAILS, {'amount': amount, 'admin_upi': upi_id})
    
    text = f"""
💰 *PAYMENT INSTRUCTIONS* 💰

Amount: ₹{amount}
UPI ID: `{upi_id}`

After payment, send details in this format: 
Then send payment screenshot.
"""
    
    await update.message.reply_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data='wallet')]
        ])
    )

async def handle_investment_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    user_id = update.effective_user.id
    state_data = get_user_state(user_id)['data']
    
    try:
        amount = float(text.replace('₹', '').replace(',', '').strip())
        plan = state_data['plan']
        plan_info = PLANS[plan]
        
        if amount != plan_info['min']:
            await update.message.reply_text(
                f"❌ For this plan, investment amount is fixed at ₹{plan_info['min']}"
            )
            return
        
        user_data = get_user_data(user_id)
        if user_data['wallet_balance'] < amount:
            await update.message.reply_text(
                f"❌ *Insufficient Balance!*\n\n"
                f"💰 Your balance: ₹{user_data['wallet_balance']:,}\n"
                f"💸 Required: ₹{amount:,}\n\n"
                f"Add money to start earning!",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💰 ADD MONEY", callback_data='add_money')]
                ])
            )
            return
        
        frames = [
            "🔥 Creating your investment...",
            "💰 Calculating returns...",
            "📈 Setting up profit tracking...",
            "✅ Investment activated!"
        ]
        
        investment_id = create_investment(user_id, plan, amount)
        update_wallet_balance(user_id, amount, 'subtract')
        
        clear_user_state(user_id)
        
        returns = amount * plan_info['rate']
        maturity = amount + returns
        profit_percentage = plan_info['rate'] * 100
        
        final_text = f"""
🎉 *INVESTMENT CREATED SUCCESSFULLY!* 🎉

📄 Investment ID: *#{investment_id}*
{plan_info['emoji']} Plan: *{plan_info['name']}*
💰 Investment: *₹{amount:,.2f}*
🚀 Returns: *₹{returns:,.2f}* ({profit_percentage:.0f}%)
💎 Total Maturity: *₹{maturity:,.2f}*
📅 Duration: *{plan_info['duration']} days*

🔥 *YOUR INVESTMENT IS NOW GROWING!*

💡 *Remember:* 
Share your referral link to unlock withdrawals!
"""
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 DASHBOARD", callback_data='dashboard')],
            [InlineKeyboardButton("👥 REFER FRIENDS", callback_data='referral')]
        ])
        
        await send_animated_message(
            update.message.chat.id,
            context,
            frames,
            final_text,
            keyboard
        )
        
        await notify_admins_new_investment(context, investment_id, user_id, amount, plan_info['name'])
        
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid amount (numbers only).\nExample: 199 or 299")

async def handle_unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🏠 DASHBOARD", callback_data='dashboard')],
        [
            InlineKeyboardButton("🔥 INVEST NOW", callback_data='plans'),
            InlineKeyboardButton("👥 REFER & EARN", callback_data='referral')
        ],
        [
            InlineKeyboardButton("💰 WALLET", callback_data='wallet'),
            InlineKeyboardButton("❓ HOW IT WORKS", callback_data='how_it_works')
        ]
    ]
    
    await update.message.reply_text(
        "🤔 I didn't understand that.\n\n"
        "🎯 Use the menu below to navigate:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================== PHOTO HANDLER ==================

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_state_data = get_user_state(user_id)
    
    if user_state_data['state'] != States.AWAITING_SCREENSHOT:
        await update.message.reply_text(
            "🤔 I wasn't expecting a photo right now.\n"
            "Use /wallet to add money."
        )
        return
    
    try:
        frames = [
            "📸 Uploading screenshot...",
            "🔍 Verifying payment proof...",
            "💾 Saving to secure servers...",
            "✅ Processing complete!"
        ]
        
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        
        deposit_data = user_state_data['data']
        deposit_id = save_deposit_request({
            'user_id': user_id,
            'amount': deposit_data['amount'],
            'user_upi': deposit_data['user_upi'],
            'utr': deposit_data['utr'],
            'admin_upi': deposit_data['admin_upi'],
            'screenshot_path': f"screenshot_{user_id}_{int(time.time())}.jpg"
        })
        
        clear_user_state(user_id)
        
        final_text = f"""
🎉 *DEPOSIT REQUEST SUBMITTED!*

📄 Request ID: *#{deposit_id}*
💰 Amount: *₹{deposit_data['amount']:,}*
🏦 UPI: {deposit_data['admin_upi']}
⏱️ Verification: *0-2 hours*
🔔 You'll be notified instantly!

🚀 *WHAT'S NEXT?*
• Admin will verify your payment
• Money added to wallet automatically
• Start investing immediately!

*Get ready to earn BIG returns!* 💎
"""
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 DASHBOARD", callback_data='dashboard')],
            [InlineKeyboardButton("🔥 VIEW PLANS", callback_data='plans')]
        ])
        
        await send_animated_message(
            update.message.chat.id,
            context,
            frames,
            final_text,
            keyboard
        )
        
        await notify_admins_new_deposit(context, deposit_id, deposit_data, user_id)
        
    except Exception as e:
        await update.message.reply_text("❌ Error uploading screenshot. Please try again.")

# ================== CALLBACK HANDLERS ==================

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    
    await query.answer()
    
    if data == 'dashboard':
        await dashboard(update, context)
    elif data == 'plans':
        await investment_plans(update, context)
    elif data == 'wallet':
        await wallet_menu(update, context)
    elif data == 'referral':
        await referral_system(update, context)
    elif data == 'add_money':
        await add_money_flow(update, context)
    elif data == 'how_it_works':
        await how_it_works(update, context)
    elif data == 'withdraw_menu':
        await withdraw_menu(update, context)
    elif data.startswith('deposit_'):
        parts = data.split('_')
        if len(parts) >= 3 and parts[1] == 'custom':
            upi_id = '_'.join(parts[2:])
            await handle_custom_deposit(update, context, upi_id)
        elif len(parts) >= 3:
            amount = int(parts[1])
            upi_id = '_'.join(parts[2:])
            await handle_deposit_amount(update, context, amount, upi_id)
    elif data.startswith('copy_upi_'):
        upi_id = data.replace('copy_upi_', '')
        await query.answer(f"UPI ID copied: {upi_id}", show_alert=True)
    elif data == 'copy_referral':
        user_data = get_user_data(user_id)
        await query.answer(f"Referral code copied: {user_data['referral_code']}", show_alert=True)
    elif data.startswith('invest_'):
        plan = data.replace('invest_', '')
        await handle_investment_plan_selection(update, context, plan)
    elif data.startswith('confirm_invest_'):
        parts = data.split('_')
        plan = parts[2]
        amount = int(parts[3])
        await handle_quick_invest(update, context, plan, amount)
    elif data.startswith('approve_deposit_'):
        deposit_id = int(data.split('_')[2])
        await approve_deposit_request(update, context, deposit_id)
    elif data.startswith('reject_deposit_'):
        deposit_id = int(data.split('_')[2])
        await reject_deposit_request(update, context, deposit_id)
    elif data == 'admin_panel':
        await admin_panel(update, context)
    elif data == 'pending_deposits':
        await show_pending_deposits(update, context)

async def handle_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE, amount, upi_id):
    user_id = update.effective_user.id
    set_user_state(user_id, States.AWAITING_DEPOSIT_DETAILS, {'amount': amount, 'admin_upi': upi_id})
    
    frames = [
        f"💰 Processing ₹{amount} deposit...",
        "🏦 Preparing payment instructions...",
        "✅ Ready for payment!"
    ]
    
    text = f"""
💰 *PAYMENT INSTRUCTIONS* 💰

🎯 Amount: *₹{amount}*
🏦 UPI ID: `{upi_id}`

🔥 *AFTER PAYMENT, SEND:*
    
📸 *Then send payment screenshot*

⚡ *Processing time: 0-2 hours*
✅ *Money added instantly after approval*
"""
    
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data='wallet')]]
    
    await send_animated_message(
        update.callback_query.message.chat.id,
        context,
        frames,
        text,
        InlineKeyboardMarkup(keyboard)
    )

async def handle_custom_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE, upi_id):
    user_id = update.effective_user.id
    set_user_state(user_id, States.AWAITING_CUSTOM_AMOUNT, {'admin_upi': upi_id})
    
    await update.callback_query.edit_message_text(
        "💰 *Enter custom deposit amount:*\n\n"
        "Minimum: ₹50\n"
        "Maximum: ₹50,000\n\n"
        "Example: 1500",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data='add_money')]
        ])
    )

async def handle_investment_plan_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, plan):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    plan_info = PLANS[plan]
    
    if user_data['wallet_balance'] < plan_info['min']:
        await update.callback_query.edit_message_text(
            f"❌ *Insufficient Balance!*\n\n"
            f"Required: ₹{plan_info['min']}\n"
            f"Your balance: ₹{user_data['wallet_balance']}\n\n"
            f"💰 Add money to start earning!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 ADD MONEY NOW", callback_data='add_money')],
                [InlineKeyboardButton("← Back", callback_data='plans')]
            ])
        )
        return
    
    returns_rate = plan_info['rate'] * 100
    example_amount = plan_info['min']
    example_returns = example_amount * plan_info['rate']
    example_total = example_amount + example_returns
    
    text = f"""
{plan_info['emoji']} *{plan_info['name']}* {plan_info['emoji']}

🔥 *{returns_rate:.0f}% GUARANTEED RETURNS!*
📅 Duration: {plan_info['duration']} days
💰 Investment: ₹{plan_info['min']} ONLY

💡 *EXAMPLE:*
Invest: ₹{example_amount}
Returns: ₹{example_returns}
Total: ₹{example_total} ✨

💰 *Your wallet: ₹{user_data['wallet_balance']:,.2f}*

🎯 *Confirm Investment?*
"""
    
    keyboard = [
        [InlineKeyboardButton(f"💎 INVEST ₹{plan_info['min']} NOW!", callback_data=f'confirm_invest_{plan}_{plan_info["min"]}')],
        [InlineKeyboardButton("❌ Cancel", callback_data='plans')]
    ]
    
    await update.callback_query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_quick_invest(update: Update, context: ContextTypes.DEFAULT_TYPE, plan, amount):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    plan_info = PLANS[plan]
    
    if user_data['wallet_balance'] < amount:
        await update.callback_query.edit_message_text(
            f"❌ *Insufficient Balance!*\n\n"
            f"💰 Your balance: ₹{user_data['wallet_balance']:,}\n"
            f"💸 Required: ₹{amount:,}\n\n"
            f"Add money to start earning!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 ADD MONEY", callback_data='add_money')],
                [InlineKeyboardButton("← Back", callback_data='plans')]
            ])
        )
        return
    
    investment_id = create_investment(user_id, plan, amount)
    update_wallet_balance(user_id, amount, 'subtract')
    
    returns = amount * plan_info['rate']
    maturity = amount + returns
    profit_percentage = plan_info['rate'] * 100
    
    frames = [
        "🔥 Creating your investment...",
        "💰 Calculating returns...",
        "📈 Setting up profit tracking...",
        "✅ Investment activated!"
    ]
    
    final_text = f"""
🎉 *INVESTMENT CREATED SUCCESSFULLY!* 🎉

📄 Investment ID: *#{investment_id}*
{plan_info['emoji']} Plan: *{plan_info['name']}*
💰 Investment: *₹{amount:,.2f}*
🚀 Returns: *₹{returns:,.2f}* ({profit_percentage:.0f}%)
💎 Total Maturity: *₹{maturity:,.2f}*
📅 Duration: *{plan_info['duration']} days*

🔥 *YOUR INVESTMENT IS NOW GROWING!*

💡 *Remember:* 
Share your referral link to unlock withdrawals!
"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 DASHBOARD", callback_data='dashboard')],
        [InlineKeyboardButton("👥 REFER FRIENDS", callback_data='referral')]
    ])
    
    await send_animated_message(
        update.callback_query.message.chat.id,
        context,
        frames,
        final_text,
        keyboard
    )
    
    await notify_admins_new_investment(context, investment_id, user_id, amount, plan_info['name'])

# ================== ADMIN FUNCTIONS ==================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.callback_query.answer("❌ Unauthorized!")
        return
    
    pending_deposits = len(get_pending_deposits())
    
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT SUM(wallet_balance) FROM users')
    total_wallet = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT COUNT(*) FROM investments WHERE status = "active"')
    active_investments = cursor.fetchone()[0]
    
    cursor.execute('SELECT SUM(amount) FROM investments WHERE status = "active"')
    total_invested = cursor.fetchone()[0] or 0
    
    conn.close()
    
    text = f"""
👑 *ROSS X ADMIN PANEL* 👑

📊 *PLATFORM STATS:*
👥 Total Users: {total_users:,}
💰 Total Wallet: ₹{total_wallet:,.2f}
📈 Active Investments: {active_investments:,}
💎 Total Invested: ₹{total_invested:,.2f}

🔔 *PENDING ACTIONS:*
💰 Deposits: {pending_deposits}

⚡ *ADMIN POWERS:*
• Approve/Reject deposits
• Monitor user activity
• View detailed statistics
• Manage system settings
"""
    
    keyboard = [
        [InlineKeyboardButton(f"💰 DEPOSITS ({pending_deposits})", callback_data='pending_deposits')],
        [
            InlineKeyboardButton("👥 USERS", callback_data='admin_users'),
            InlineKeyboardButton("📊 STATS", callback_data='admin_stats')
        ],
        [InlineKeyboardButton("⚙️ SETTINGS", callback_data='admin_settings')]
    ]
    
    await update.callback_query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_pending_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    deposits = get_pending_deposits()
    
    if not deposits:
        await update.callback_query.edit_message_text(
            "✅ *NO PENDING DEPOSITS!*\n\nAll caught up! 🎉",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("← BACK TO ADMIN", callback_data='admin_panel')]
            ])
        )
        return
    
    deposit = deposits[0]
    text = f"""
💰 *DEPOSIT REQUEST #{deposit['id']}*

👤 *USER DETAILS:*
Name: {deposit['name']}
Username: @{deposit['username']}
ID: {deposit['user_id']}

💸 *PAYMENT DETAILS:*
Amount: ₹{deposit['amount']:,.2f}
UTR: `{deposit['utr']}`
User UPI: {deposit['user_upi']}
Admin UPI: {deposit['admin_upi']}
Time: {deposit['created_at']}

🔍 *ACTION REQUIRED:*
Choose to approve or reject this deposit.
"""
    
    keyboard = [
        [
            InlineKeyboardButton("✅ APPROVE", callback_data=f'approve_deposit_{deposit["id"]}'),
            InlineKeyboardButton("❌ REJECT", callback_data=f'reject_deposit_{deposit["id"]}')
        ],
        [InlineKeyboardButton("← BACK TO ADMIN", callback_data='admin_panel')]
    ]
    
    await update.callback_query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def approve_deposit_request(update: Update, context: ContextTypes.DEFAULT_TYPE, deposit_id):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    approved_user_id, amount = approve_deposit(deposit_id)
    
    if approved_user_id:
        frames = [
            "🔍 Payment verified!",
            "✅ Deposit approved!",
            "💰 Adding to wallet...",
            "🎉 Money added successfully!"
        ]
        
        final_text = f"""
🎉 *DEPOSIT APPROVED!* 🎉

💰 Amount: *₹{amount:,.2f}*
✅ Added to your wallet instantly!

🚀 *READY TO INVEST?*
Choose from our BIG OPPORTUNITY plans!

💎 *Quick Actions:*
• 45 Days: 50% returns (₹199)
• 90 Days: 100% returns (₹299)
"""
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 INVEST NOW", callback_data='plans')],
            [InlineKeyboardButton("🏠 DASHBOARD", callback_data='dashboard')]
        ])
        
        try:
            await send_animated_message(
                approved_user_id,
                context,
                frames,
                final_text,
                keyboard
            )
        except:
            pass
        
        await update.callback_query.edit_message_text(
            f"✅ *DEPOSIT APPROVED!*\n\n"
            f"💰 ₹{amount:,.2f} added to user's wallet\n"
            f"👤 User ID: {approved_user_id}\n"
            f"🔔 User notified successfully!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("← BACK TO DEPOSITS", callback_data='pending_deposits')]
            ])
        )
    else:
        await update.callback_query.answer("❌ Error approving deposit!")

async def reject_deposit_request(update: Update, context: ContextTypes.DEFAULT_TYPE, deposit_id):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE deposits SET status = "rejected" WHERE id = ?', (deposit_id,))
    
    cursor.execute('SELECT user_id, amount FROM deposits WHERE id = ?', (deposit_id,))
    result = cursor.fetchone()
    conn.commit()
    conn.close()
    
    if result:
        rejected_user_id, amount = result
        try:
            await context.bot.send_message(
                chat_id=rejected_user_id,
                text=f"❌ *DEPOSIT REJECTED*\n\n"
                     f"💰 Amount: ₹{amount:,.2f}\n"
                     f"🔍 Please check payment details\n\n"
                     f"💡 Contact support if needed\n"
                     f"📞 Try submitting again with correct details",
                parse_mode='Markdown'
            )
        except:
            pass
    
    await update.callback_query.edit_message_text(
        f"❌ *DEPOSIT REJECTED*\n\n"
        f"📄 Request ID: #{deposit_id}\n"
        f"🔔 User notified about rejection",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("← BACK TO DEPOSITS", callback_data='pending_deposits')]
        ])
    )

# ================== NOTIFICATION FUNCTIONS ==================

async def notify_admins_new_deposit(context: ContextTypes.DEFAULT_TYPE, deposit_id, deposit_data, user_id):
    user_data = get_user_data(user_id)
    
    text = f"""
🚨 *NEW DEPOSIT REQUEST* 🚨

📄 ID: *#{deposit_id}*
👤 User: {user_data['name']} (@{user_data['username']})
💰 Amount: *₹{deposit_data['amount']:,}*
🔢 UTR: `{deposit_data['utr']}`
🎯 User UPI: {deposit_data['user_upi']}
🏦 Admin UPI: {deposit_data['admin_upi']}
⏰ Time: {datetime.now().strftime('%d %b %Y, %I:%M %p')}

⚡ *IMMEDIATE ACTION REQUIRED!*
"""
    
    keyboard = [
        [
            InlineKeyboardButton("✅ APPROVE", callback_data=f'approve_deposit_{deposit_id}'),
            InlineKeyboardButton("❌ REJECT", callback_data=f'reject_deposit_{deposit_id}')
        ],
        [InlineKeyboardButton("👑 ADMIN PANEL", callback_data='admin_panel')]
    ]
    
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            logger.info(f"✅ Admin {admin_id} notified about deposit #{deposit_id}")
        except Exception as e:
            logger.error(f"❌ Failed to notify admin {admin_id}: {e}")

async def notify_admins_new_investment(context: ContextTypes.DEFAULT_TYPE, investment_id, user_id, amount, plan_name):
    user_data = get_user_data(user_id)
    
    text = f"""
📈 *NEW INVESTMENT ALERT* 📈

📄 ID: *#{investment_id}*
👤 User: {user_data['name']} (@{user_data['username']})
💰 Amount: *₹{amount:,}*
📊 Plan: {plan_name}
⏰ Time: {datetime.now().strftime('%d %b %Y, %I:%M %p')}

💡 User is growing their wealth! 🚀
"""
    
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode='Markdown'
            )
            logger.info(f"✅ Admin {admin_id} notified about investment #{investment_id}")
        except Exception as e:
            logger.error(f"❌ Failed to notify admin {admin_id}: {e}")

# ================== MAIN FUNCTION ==================

def main():
    """Main function to run the bot"""
    init_database()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Start bot
    logger.info("🚀 Ross X Bot starting...")
    logger.info(f"👑 Admins: @chiefrossx (ID: {ADMIN_IDS[0]}), @angentrossx (ID: {ADMIN_IDS[1]})")
    logger.info(f"💰 UPI IDs: {', '.join(UPI_IDS)}")
    logger.info(f"📈 Plans: 45 Days (₹{PLANS['45_days']['min']}) | 90 Days (₹{PLANS['90_days']['min']})")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
