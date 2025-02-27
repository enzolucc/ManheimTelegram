import os
import logging
import requests
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, 
    filters, CallbackQueryHandler, ConversationHandler
)

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Manheim API configuration
MANHEIM_CLIENT_ID = os.getenv("MANHEIM_CLIENT_ID")
MANHEIM_CLIENT_SECRET = os.getenv("MANHEIM_CLIENT_SECRET")

# Use UAT (test) environment if specified, otherwise use production
USE_UAT = os.getenv("USE_MANHEIM_UAT", "False").lower() in ("true", "1", "t")

if USE_UAT:
    MANHEIM_BASE_URL = "https://uat.api.manheim.com"
    MANHEIM_TOKEN_URL = "https://uat.api.manheim.com/oauth2/token"
else:
    MANHEIM_BASE_URL = "https://api.manheim.com"
    MANHEIM_TOKEN_URL = "https://api.manheim.com/oauth2/token"

MANHEIM_VALUATIONS_URL = f"{MANHEIM_BASE_URL}/valuations/vin/{{vin}}"
MANHEIM_YMM_URL = f"{MANHEIM_BASE_URL}/valuations/years/{{year}}/makes/{{make}}/models/{{model}}"

# Token storage
token_data = {
    "access_token": None,
    "expires_at": None
}

def get_manheim_token():
    """Get a new OAuth token for Manheim API access."""
    global token_data
    
    # Check if we have a valid token
    now = datetime.now()
    if (token_data["access_token"] and token_data["expires_at"] 
            and now < token_data["expires_at"]):
        return token_data["access_token"]
    
    # Request new token
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "client_credentials",
        "client_id": MANHEIM_CLIENT_ID,
        "client_secret": MANHEIM_CLIENT_SECRET
    }
    
    try:
        response = requests.post(MANHEIM_TOKEN_URL, headers=headers, data=data)
        response.raise_for_status()
        
        token_info = response.json()
        token_data["access_token"] = token_info["access_token"]
        # Set expiry time (typically 1 hour, but subtract 5 minutes for safety)
        expires_in_seconds = token_info.get("expires_in", 3600) - 300
        token_data["expires_at"] = now + timedelta(seconds=expires_in_seconds)
        
        return token_data["access_token"]
    
    except Exception as e:
        logger.error(f"Error getting Manheim token: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        "Welcome to Vehicle Auction Bot!\n\n"
        "Use the following commands:\n"
        "/vin [VIN] - Get auction data for a specific VIN\n"
        "/vin [VIN] [Subseries] - Get auction data with subseries specification\n"
        "/vin [VIN] [Subseries] [Transmission] - Get auction data with subseries and transmission\n"
        "/vin [VIN] color=COLOR grade=GRADE odometer=MILES region=REGION - Get auction data with specific parameters\n"
        "/ymm [Year] [Make] [Model] - Get auction data for a Year/Make/Model\n\n"
        "Type /help for more detailed examples"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text(
        "Vehicle Auction Bot commands:\n\n"
        "1️⃣ Basic VIN lookup:\n"
        "/vin 1HGCM82633A123456\n\n"
        
        "2️⃣ VIN lookup with subseries:\n"
        "/vin 1HGCM82633A123456 SE\n\n"
        
        "3️⃣ VIN lookup with subseries and transmission:\n"
        "/vin 1HGCM82633A123456 SE AUTO\n\n"
        
        "4️⃣ VIN lookup with additional parameters:\n"
        "/vin WBA3C1C5XFP853102 color=WHITE grade=3.5 odometer=20000 region=NE\n\n"
        "Available parameters:\n"
        "• color - Vehicle color (e.g., WHITE, BLACK, SILVER)\n"
        "• grade - Vehicle condition grade (e.g., 1.0, 3.5, 4.5) on a 0-5 scale\n"
        "• odometer - Vehicle mileage in miles\n"
        "• region - Geographic region (NE, SE, MW, SW, W)\n\n"
        
        "5️⃣ Year/Make/Model lookup:\n"
        "/ymm 2020 Honda Accord\n\n"
        
        "📊 For testing in the UAT environment, you can use this example VIN:\n"
        "WBA3C1C5XFP853102\n\n"
        
        "After a basic search, you can also use the interactive 'Refine Valuation' button to specify additional parameters without typing."
    )

def get_vin_valuation(vin, subseries=None, transmission=None, **query_params):
    """
    Get valuation data for a specific VIN from Manheim API.
    
    Args:
        vin (str): The Vehicle Identification Number
        subseries (str, optional): Vehicle subseries for more specific valuation
        transmission (str, optional): Transmission type for more specific valuation
                                     (requires subseries to be specified)
        **query_params: Additional query parameters such as:
            - color (str): Vehicle color (e.g., "WHITE", "BLACK")
            - grade (str): Vehicle condition grade (e.g., "31", "40")
            - odometer (int): Vehicle mileage
            - region (str): Geographic region (e.g., "NE", "SE", "MW", "SW", "W")
    
    Returns:
        dict: Valuation data or None if not found/error
    """
    token = get_manheim_token()
    if not token:
        logger.error("Failed to get authentication token")
        return None
    
    # Construct URL based on provided parameters
    if subseries and transmission:
        url = f"{MANHEIM_VALUATIONS_URL.format(vin=vin)}/{subseries}/{transmission}"
    elif subseries:
        url = f"{MANHEIM_VALUATIONS_URL.format(vin=vin)}/{subseries}"
    else:
        url = MANHEIM_VALUATIONS_URL.format(vin=vin)
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    
    # Filter out None values from query parameters
    params = {k: v for k, v in query_params.items() if v is not None}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.warning(f"No data found for VIN: {vin}")
            return None
        logger.error(f"HTTP error fetching VIN data: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching VIN data: {e}")
        return None

# State definitions for conversation
CHOOSING_COLOR, CHOOSING_GRADE, CHOOSING_ODOMETER, CHOOSING_REGION = range(4)

# Data storage for conversation context
user_data_dict = {}

async def vin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get auction data for a specific VIN with optional parameters."""
    if not context.args:
        await update.message.reply_text(
            "Please provide a VIN. Examples:\n"
            "/vin 1HGCM82633A123456\n"
            "/vin 1HGCM82633A123456 SE  (with subseries)\n"
            "/vin 1HGCM82633A123456 SE AUTO  (with subseries and transmission)\n\n"
            "For advanced options, use keyword arguments after the VIN:\n"
            "/vin WBA3C1C5XFP853102 color=WHITE grade=31 odometer=20000 region=NE"
        )
        return

    # Parse arguments
    vin = context.args[0]
    subseries = None
    transmission = None
    query_params = {}
    
    # Check if we have keyword arguments (containing '=')
    has_keyword_args = any('=' in arg for arg in context.args[1:])
    
    if has_keyword_args:
        # Process as keyword arguments
        for arg in context.args[1:]:
            if '=' in arg:
                key, value = arg.split('=', 1)
                # Convert numeric values
                if value.isdigit():
                    value = int(value)
                query_params[key] = value
    else:
        # Process as positional arguments (subseries, transmission)
        if len(context.args) >= 2:
            subseries = context.args[1]
        
        if len(context.args) >= 3:
            transmission = context.args[2]
    
    # Inform user of the search
    search_message = f"Searching for auction data for VIN: {vin}"
    if subseries:
        search_message += f", Subseries: {subseries}"
    if transmission:
        search_message += f", Transmission: {transmission}"
    for key, value in query_params.items():
        search_message += f", {key.capitalize()}: {value}"
    
    await update.message.reply_text(search_message + "...")
    
    try:
        # Get vehicle data from Manheim API
        data = get_vin_valuation(vin, subseries, transmission, **query_params)
        
        if not data:
            await update.message.reply_text(f"No auction data found for VIN: {vin}")
            return
            
        # Format and send the response
        message = format_auction_data(data)
        await update.message.reply_text(message)
        
        # Store data for potential refinement and transaction viewing
        user_id = update.effective_user.id
        user_data_dict[user_id] = {
            'vin': vin,
            'subseries': subseries,
            'transmission': transmission,
            'params': query_params,
            'data': data  # Store full data response
        }
        
        # Create keyboard with appropriate options
        keyboard = []
        
        # Add "View All Transactions" button if there are transactions
        has_transactions = (
            "marketSummary" in data and 
            "transactions" in data["marketSummary"] and 
            data["marketSummary"]["transactions"]
        )
        transaction_count = len(data["marketSummary"]["transactions"]) if has_transactions else 0
        
        if has_transactions and transaction_count > 3:
            keyboard.append([InlineKeyboardButton(
                f"📋 View All {transaction_count} Transactions", 
                callback_data="view_all_transactions"
            )])
        
        # Add refinement option if no color or grade were provided
        if 'color' not in query_params or 'grade' not in query_params:
            keyboard.append([InlineKeyboardButton("🔄 Refine Valuation", callback_data="refine_valuation")])
        
        # Only show keyboard if there are buttons to display
        if keyboard:
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "Additional options:",
                reply_markup=reply_markup
            )
            
    except Exception as e:
        logger.error(f"Error fetching VIN data: {e}")
        await update.message.reply_text(f"Error fetching data for VIN: {vin}. Please try again later.")

async def refine_valuation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the refinement button click."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in user_data_dict:
        await query.edit_message_text("Sorry, your session has expired. Please start a new search with /vin.")
        return ConversationHandler.END
    
    # Start with color selection
    colors = ["BLACK", "WHITE", "SILVER", "GRAY", "RED", "BLUE", "BROWN", "GREEN", "GOLD", "OTHER"]
    keyboard = []
    for color in colors:
        keyboard.append([InlineKeyboardButton(color, callback_data=f"color_{color}")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Please select the vehicle color:", reply_markup=reply_markup)
    return CHOOSING_COLOR

async def color_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the color selection."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in user_data_dict:
        await query.edit_message_text("Sorry, your session has expired. Please start a new search with /vin.")
        return ConversationHandler.END
    
    # Get the color from callback data
    color = query.data.split("_")[1]
    user_data_dict[user_id]['params']['color'] = color
    
    # Now ask for grade (Manheim uses 0-5 scale)
    grades = ["1.0", "1.5", "2.0", "2.5", "3.0", "3.5", "4.0", "4.5", "5.0"]
    keyboard = []
    for grade in grades:
        keyboard.append([InlineKeyboardButton(f"Grade {grade}", callback_data=f"grade_{grade}")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"Selected color: {color}\nPlease select the vehicle condition grade:",
        reply_markup=reply_markup
    )
    return CHOOSING_GRADE

async def grade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the grade selection."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in user_data_dict:
        await query.edit_message_text("Sorry, your session has expired. Please start a new search with /vin.")
        return ConversationHandler.END
    
    # Get the grade from callback data
    grade = query.data.split("_")[1]
    user_data_dict[user_id]['params']['grade'] = float(grade)
    
    # Ask for odometer (mileage)
    keyboard = [
        [
            InlineKeyboardButton("< 10,000", callback_data="odometer_5000"),
            InlineKeyboardButton("10-30k", callback_data="odometer_20000")
        ],
        [
            InlineKeyboardButton("30-60k", callback_data="odometer_45000"),
            InlineKeyboardButton("60-100k", callback_data="odometer_80000")
        ],
        [
            InlineKeyboardButton("100-150k", callback_data="odometer_125000"),
            InlineKeyboardButton("> 150k", callback_data="odometer_175000")
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"Selected color: {user_data_dict[user_id]['params']['color']}\n"
        f"Selected grade: {grade}\n"
        f"Please select approximate mileage:",
        reply_markup=reply_markup
    )
    return CHOOSING_ODOMETER

async def odometer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the odometer selection."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in user_data_dict:
        await query.edit_message_text("Sorry, your session has expired. Please start a new search with /vin.")
        return ConversationHandler.END
    
    # Get the odometer from callback data
    odometer = query.data.split("_")[1]
    user_data_dict[user_id]['params']['odometer'] = int(odometer)
    
    # Ask for region
    keyboard = [
        [
            InlineKeyboardButton("Northeast (NE)", callback_data="region_NE"),
            InlineKeyboardButton("Southeast (SE)", callback_data="region_SE")
        ],
        [
            InlineKeyboardButton("Midwest (MW)", callback_data="region_MW"),
            InlineKeyboardButton("Southwest (SW)", callback_data="region_SW")
        ],
        [
            InlineKeyboardButton("West (W)", callback_data="region_W"),
            InlineKeyboardButton("Skip", callback_data="region_skip")
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"Selected color: {user_data_dict[user_id]['params']['color']}\n"
        f"Selected grade: {user_data_dict[user_id]['params']['grade']}\n"
        f"Selected mileage: {odometer}\n"
        f"Please select region:",
        reply_markup=reply_markup
    )
    return CHOOSING_REGION

async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the region selection and fetch refined valuation."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in user_data_dict:
        await query.edit_message_text("Sorry, your session has expired. Please start a new search with /vin.")
        return ConversationHandler.END
    
    # Get the region from callback data if not skipped
    region_data = query.data.split("_")[1]
    if region_data != "skip":
        user_data_dict[user_id]['params']['region'] = region_data
    
    # Show that we're processing
    await query.edit_message_text("Fetching refined valuation with your parameters...")
    
    # Get the data for the API call
    user_data = user_data_dict[user_id]
    vin = user_data['vin']
    subseries = user_data['subseries']
    transmission = user_data['transmission']
    params = user_data['params']
    
    try:
        # Get vehicle data from Manheim API with the refined parameters
        data = get_vin_valuation(vin, subseries, transmission, **params)
        
        if not data:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"No auction data found for VIN: {vin} with the specified parameters."
            )
        else:
            # Format and send the response
            message = format_auction_data(data)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📊 Refined Valuation Results:\n\n{message}"
            )
            
    except Exception as e:
        logger.error(f"Error fetching refined VIN data: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Error fetching refined data for VIN: {vin}. Please try again later."
        )
    
    # Clear user data to free memory
    if user_id in user_data_dict:
        del user_data_dict[user_id]
    
    return ConversationHandler.END

async def view_all_transactions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display all transactions for a VIN."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in user_data_dict or 'data' not in user_data_dict[user_id]:
        await query.edit_message_text("Sorry, transaction data is no longer available. Please perform a new search with /vin.")
        return
    
    # Get the full data from user storage
    data = user_data_dict[user_id]['data']
    vin = user_data_dict[user_id]['vin']
    
    # Check if transactions exist
    has_transactions = (
        "marketSummary" in data and 
        "transactions" in data["marketSummary"] and 
        data["marketSummary"]["transactions"]
    )
    
    if not has_transactions:
        await query.edit_message_text("No transaction data available for this VIN.")
        return
    
    transactions = data["marketSummary"]["transactions"]
    
    # Create a detailed message with all transactions
    message = f"📋 All Transactions for VIN: {vin}\n\n"
    
    for i, tx in enumerate(transactions, 1):
        message += f"Transaction #{i}:\n"
        
        if "price" in tx:
            message += f"• Price: ${tx.get('price', 0):,.2f}\n"
        
        if "saleDate" in tx:
            sale_date = tx.get('saleDate', '').split('T')[0]  # Format ISO date
            message += f"• Date: {sale_date}\n"
        
        if "odometer" in tx:
            message += f"• Mileage: {tx.get('odometer', 0):,} miles\n"
        
        if "conditionGrade" in tx:
            message += f"• Condition: {tx.get('conditionGrade', 'N/A')}/5.0\n"
        
        if "location" in tx:
            message += f"• Location: {tx.get('location', 'N/A')}\n"
        
        if "lane" in tx:
            message += f"• Lane: {tx.get('lane', 'N/A')}\n"
        
        if "sellerName" in tx:
            message += f"• Seller: {tx.get('sellerName', 'N/A')}\n"
        
        # Add any additional transaction details that might be useful
        for key, value in tx.items():
            if key not in ["price", "saleDate", "odometer", "conditionGrade", "location", "lane", "sellerName"] and value:
                # Format the key with spaces before uppercase letters
                formatted_key = ''.join(' ' + c if c.isupper() else c for c in key).strip().capitalize()
                message += f"• {formatted_key}: {value}\n"
        
        message += "\n"
    
    # Split message if it's too long
    MAX_MESSAGE_LENGTH = 4096  # Telegram's limit
    
    if len(message) <= MAX_MESSAGE_LENGTH:
        await query.edit_message_text(message)
    else:
        # Send initial message
        await query.edit_message_text("Sending transaction details...")
        
        # Split into multiple messages
        for i in range(0, len(message), MAX_MESSAGE_LENGTH):
            chunk = message[i:i + MAX_MESSAGE_LENGTH]
            await context.bot.send_message(chat_id=update.effective_chat.id, text=chunk)

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the refinement process."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id in user_data_dict:
        del user_data_dict[user_id]
    
    await query.edit_message_text("Refinement canceled. You can start a new search with /vin.")
    return ConversationHandler.END

def get_ymm_valuation(year, make, model, trim=None):
    """Get valuation data for Year/Make/Model from Manheim API."""
    token = get_manheim_token()
    if not token:
        logger.error("Failed to get authentication token")
        return None
    
    # URL parameters are part of the path
    url = MANHEIM_YMM_URL.format(year=year, make=make, model=model)
    
    # Query parameters
    params = {}
    if trim:
        params["trim"] = trim
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.warning(f"No data found for {year} {make} {model}")
            return None
        logger.error(f"HTTP error fetching YMM data: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching YMM data: {e}")
        return None

async def ymm_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get auction data for a Year/Make/Model."""
    if len(context.args) < 3:
        await update.message.reply_text("Please provide Year, Make, and Model. Example: /ymm 2020 Honda Accord")
        return

    year = context.args[0]
    make = context.args[1]
    model = " ".join(context.args[2:])
    
    await update.message.reply_text(f"Searching for auction data for {year} {make} {model}...")
    
    try:
        # Get vehicle data from Manheim API
        data = get_ymm_valuation(year, make, model)
        
        if not data:
            await update.message.reply_text(f"No auction data found for {year} {make} {model}")
            return
            
        # Format and send the response
        message = format_auction_data(data)
        await update.message.reply_text(message)
        
    except Exception as e:
        logger.error(f"Error fetching YMM data: {e}")
        await update.message.reply_text(f"Error fetching data for {year} {make} {model}. Please try again later.")

def format_auction_data(data):
    """Format the auction data into a readable message based on Manheim Valuations API structure."""
    if not isinstance(data, dict):
        return f"🚗 Vehicle Auction Data:\n\n{str(data)}"
    
    message = "🚗 Vehicle Auction Data:\n\n"
    
    # Vehicle information
    if "vehicle" in data:
        vehicle = data["vehicle"]
        message += "📋 Vehicle Info:\n"
        if "year" in vehicle and "make" in vehicle and "model" in vehicle:
            message += f"- {vehicle.get('year')} {vehicle.get('make')} {vehicle.get('model')}"
            if "trim" in vehicle:
                message += f" {vehicle.get('trim')}"
            message += "\n"
        if "vin" in vehicle:
            message += f"- VIN: {vehicle.get('vin')}\n"
        if "style" in vehicle:
            message += f"- Style: {vehicle.get('style')}\n"
        if "engineSize" in vehicle:
            message += f"- Engine: {vehicle.get('engineSize')}\n"
        if "transmission" in vehicle:
            message += f"- Transmission: {vehicle.get('transmission')}\n"
        if "drivetrain" in vehicle:
            message += f"- Drivetrain: {vehicle.get('drivetrain')}\n"
        message += "\n"
    
    # Wholesale value ranges
    if "wholesaleAverages" in data:
        message += "💰 Wholesale Values:\n"
        wholesale = data["wholesaleAverages"]
        
        # Aggregate average
        if "aggregateAverage" in wholesale:
            agg = wholesale["aggregateAverage"]
            if "average" in agg:
                message += f"- Aggregate Average: ${agg.get('average', 0):,.2f}\n"
            if "rough" in agg and "clean" in agg:
                message += f"  Range: ${agg.get('rough', 0):,.2f} - ${agg.get('clean', 0):,.2f}\n"
        
        # Adjusted MMR
        if "adjustedMMR" in wholesale:
            adj = wholesale["adjustedMMR"]
            if "average" in adj:
                message += f"- Adjusted MMR: ${adj.get('average', 0):,.2f}\n"
            if "rough" in adj and "clean" in adj:
                message += f"  Range: ${adj.get('rough', 0):,.2f} - ${adj.get('clean', 0):,.2f}\n"
        
        # Base MMR
        if "baseMMR" in wholesale:
            base = wholesale["baseMMR"]
            if "average" in base:
                message += f"- Base MMR: ${base.get('average', 0):,.2f}\n"
        
        message += "\n"
    
    # Recent auction transactions
    if "marketSummary" in data and "transactions" in data["marketSummary"]:
        transactions = data["marketSummary"]["transactions"]
        if transactions:
            # Store transactions for potential detailed view
            data["transaction_count"] = len(transactions)
            
            message += f"🔄 Recent Transactions ({len(transactions)} total):\n"
            count = 0
            for tx in transactions[:3]:  # Show only 3 in the summary view
                count += 1
                message += f"{count}. "
                if "price" in tx:
                    message += f"${tx.get('price', 0):,.2f}"
                if "saleDate" in tx:
                    sale_date = tx.get('saleDate', '').split('T')[0]  # Format ISO date
                    message += f" on {sale_date}"
                message += "\n"
                
                if "odometer" in tx:
                    message += f"   Mileage: {tx.get('odometer', 0):,} miles\n"
                if "conditionGrade" in tx:
                    message += f"   Condition: {tx.get('conditionGrade', 'N/A')}/5.0\n"
                if "location" in tx:
                    message += f"   Location: {tx.get('location', 'N/A')}\n"
                message += "\n"
            
            # Add note about viewing all transactions if there are more than shown
            if len(transactions) > 3:
                message += f"... and {len(transactions) - 3} more transactions. Use the button below to view all.\n\n"
            
    # Market statistics
    if "marketSummary" in data and "statistics" in data["marketSummary"]:
        stats = data["marketSummary"]["statistics"]
        message += "📊 Market Summary:\n"
        
        if "averagePrice" in stats:
            message += f"- Average Price: ${stats.get('averagePrice', 0):,.2f}\n"
        if "averageOdometer" in stats:
            message += f"- Average Mileage: {stats.get('averageOdometer', 0):,} miles\n"
        if "averageConditionGrade" in stats:
            message += f"- Average Condition: {stats.get('averageConditionGrade', 0):.1f}/5.0\n"
        if "transactionCount" in stats:
            message += f"- Total Transactions: {stats.get('transactionCount', 0)}\n"
    
    return message

def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token
    application = ApplicationBuilder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()

    # Add conversation handler for the interactive refinement process
    refinement_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(refine_valuation_callback, pattern="^refine_valuation$")],
        states={
            CHOOSING_COLOR: [CallbackQueryHandler(color_callback, pattern="^color_")],
            CHOOSING_GRADE: [CallbackQueryHandler(grade_callback, pattern="^grade_")],
            CHOOSING_ODOMETER: [CallbackQueryHandler(odometer_callback, pattern="^odometer_")],
            CHOOSING_REGION: [CallbackQueryHandler(region_callback, pattern="^region_")],
        },
        fallbacks=[CallbackQueryHandler(cancel_callback, pattern="^cancel$")],
    )

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("vin", vin_command))
    application.add_handler(CommandHandler("ymm", ymm_command))
    
    # Add callback handlers
    application.add_handler(CallbackQueryHandler(view_all_transactions_callback, pattern="^view_all_transactions$"))
    application.add_handler(refinement_conv_handler)

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()